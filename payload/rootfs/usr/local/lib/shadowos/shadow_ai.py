#!/usr/bin/env python3
"""Shadow AI: provider-neutral chat with a strictly allow-listed local executor.

The remote model can propose structured actions. It never receives a shell and
cannot bypass local validation, an explicit user confirmation, or polkit.
"""

from __future__ import annotations

import argparse
import getpass
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP = "shadow-ai"
HOME = Path.home()
CONFIG_DIR = HOME / ".config" / APP
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_DIR = HOME / ".local" / "state" / APP
BACKUP_DIR = STATE_DIR / "backups"
HISTORY_FILE = STATE_DIR / "history.jsonl"
MAX_RESPONSE = 256 * 1024

SCHEMES = {
    "auto", "grey", "navy", "mono", "slate", "stone", "steel", "ash", "ink",
    "ocean", "sky", "teal", "mint", "forest", "lime", "gold", "sunset",
    "ember", "rose", "orchid", "violet",
}
DIAGNOSTIC_SCOPES = {"quick", "gpu", "gaming", "network"}
WAYBAR_STYLES = {"flat", "floating", "islands", "island"}
DOCK_POSITIONS = {"bottom", "top", "left", "right"}
PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9@._+:-]{0,127}$")
FLATPAK_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+){2,}$")

SYSTEM_PROMPT = """You are Shadow AI, a Russian-language assistant for ShadowOS.
ShadowOS is a CachyOS-based Hyprland workstation using DarkShadowShell.
Return exactly one JSON object, without Markdown:
{"message":"short explanation in Russian","actions":[...]}

You may only propose these action objects:
{"type":"diagnostics","scope":"quick|gpu|gaming|network"}
{"type":"gaming_mode","enabled":true|false}
{"type":"lite_mode","enabled":true|false}
{"type":"color_scheme","name":"violet"}
{"type":"dock","enabled":true,"hover":true,"position":"bottom","opacity":0.82}
{"type":"waybar","style":"island","autohide":false}
{"type":"install_packages","packages":["package-name"]}
{"type":"install_flatpak","app_id":"reverse.dns.Application"}
{"type":"update_system"}
{"type":"open_settings"}

Never output a shell command, script, file path to modify, package removal, or an
action outside that list. Use an empty actions array for advice or unsupported
requests. Administrative actions are separately confirmed by the user and polkit.
Do not claim an action already happened; you only propose it.
"""


class ShadowAIError(RuntimeError):
    pass


def atomic_json(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, mode)
    temp.replace(path)


def normalize_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Нужен полный URL с http:// или https://")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and parsed.hostname not in local_hosts:
        raise ValueError("Удалённый API разрешён только через HTTPS")
    return value


def setup_provider() -> None:
    print("\nНастройка OpenAI-совместимого API. Ключ хранится локально с правами 0600.")
    current = load_config(required=False)
    default_url = current.get("base_url", "https://api.openai.com/v1")
    base_url = input(f"API URL [{default_url}]: ").strip() or default_url
    base_url = normalize_base_url(base_url)
    default_model = current.get("model", "")
    model = input(f"Модель{f' [{default_model}]' if default_model else ''}: ").strip() or default_model
    if not model:
        raise ShadowAIError("Имя модели обязательно")
    old_key = current.get("api_key", "")
    prompt = "API-ключ (пусто = оставить прежний или без ключа для локального API): "
    api_key = getpass.getpass(prompt)
    if not api_key:
        api_key = old_key
    atomic_json(CONFIG_FILE, {"base_url": base_url, "model": model, "api_key": api_key})
    print(f"Настройки сохранены в {CONFIG_FILE}")


def load_config(required: bool = True) -> dict[str, Any]:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise ShadowAIError("API ещё не настроен. Выполни /setup или shadow-ai --setup")
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ShadowAIError(f"Не удалось прочитать {CONFIG_FILE}: {exc}") from exc
    try:
        data["base_url"] = normalize_base_url(str(data["base_url"]))
    except (KeyError, ValueError) as exc:
        raise ShadowAIError(f"Некорректный API URL: {exc}") from exc
    if not str(data.get("model", "")).strip():
        raise ShadowAIError("В конфигурации не указана модель")
    return data


def run(command: list[str], timeout: int = 20, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=check,
        )
    except FileNotFoundError as exc:
        raise ShadowAIError(f"Команда не установлена: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ShadowAIError(f"Превышено время ожидания: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout or "").strip()
        raise ShadowAIError(output or f"Команда завершилась с кодом {exc.returncode}") from exc


def run_interactive(command: list[str], timeout: int) -> None:
    """Run a confirmed administrative command with visible terminal output."""
    try:
        subprocess.run(command, timeout=timeout, check=True)
    except FileNotFoundError as exc:
        raise ShadowAIError(f"Команда не установлена: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ShadowAIError(f"Превышено время ожидания: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise ShadowAIError(f"Команда завершилась с кодом {exc.returncode}") from exc


def compact_output(command: list[str], timeout: int = 10, limit: int = 4000) -> str:
    try:
        result = run(command, timeout=timeout, check=False).stdout.strip()
    except ShadowAIError:
        return "unavailable"
    return result[-limit:] if result else "(no output)"


def system_context() -> str:
    pretty = "ShadowOS"
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                pretty = line.split("=", 1)[1].strip('"')
                break
    except OSError:
        pass
    parts = {
        "system": pretty,
        "kernel": compact_output(["uname", "-r"]),
        "memory": compact_output(["free", "-h"]),
        "home_disk": compact_output(["df", "-h", str(HOME)]),
        "gpu": compact_output(["sh", "-c", "lspci -k | grep -A3 -Ei 'VGA|3D|Display'"], limit=2500),
    }
    effects = user_tool("rice-effects", required=False)
    colors = user_tool("rice-colors", required=False)
    if effects:
        parts["effects"] = compact_output([str(effects), "state"])
    if colors:
        parts["color_scheme"] = compact_output([str(colors), "get"])
    return json.dumps(parts, ensure_ascii=False)


def endpoint_for(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    return base_url + "/chat/completions"


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise ShadowAIError("Провайдер вернул не JSON")
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ShadowAIError("Провайдер вернул некорректный JSON") from exc
    if not isinstance(value, dict):
        raise ShadowAIError("Ответ провайдера должен быть JSON-объектом")
    return value


def call_provider(prompt: str) -> dict[str, Any]:
    config = load_config()
    payload = {
        "model": config["model"],
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Состояние системы: {system_context()}\n\nЗапрос пользователя: {prompt}",
            },
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.get("api_key"):
        headers["Authorization"] = f"Bearer {config['api_key']}"
    request = urllib.request.Request(endpoint_for(config["base_url"]), body, headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", "replace")
        raise ShadowAIError(f"API вернул HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ShadowAIError(f"Не удалось подключиться к API: {exc}") from exc
    if len(raw) > MAX_RESPONSE:
        raise ShadowAIError("Ответ API слишком большой")
    try:
        envelope = json.loads(raw.decode("utf-8"))
        content = envelope["choices"][0]["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ShadowAIError("Неизвестный формат ответа OpenAI-совместимого API") from exc
    return extract_json(str(content))


def require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} должен быть true или false")
    return value


def validate_action(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("действие должно быть объектом")
    kind = raw.get("type")
    if kind == "diagnostics":
        scope = raw.get("scope", "quick")
        if scope not in DIAGNOSTIC_SCOPES:
            raise ValueError("неизвестный профиль диагностики")
        return {"type": kind, "scope": scope}
    if kind in {"gaming_mode", "lite_mode"}:
        return {"type": kind, "enabled": require_bool(raw.get("enabled"), "enabled")}
    if kind == "color_scheme":
        name = raw.get("name")
        if name not in SCHEMES:
            raise ValueError("неизвестная цветовая схема")
        return {"type": kind, "name": name}
    if kind == "dock":
        action: dict[str, Any] = {"type": kind}
        if "enabled" in raw:
            action["enabled"] = require_bool(raw["enabled"], "enabled")
        if "hover" in raw:
            action["hover"] = require_bool(raw["hover"], "hover")
        if "position" in raw:
            if raw["position"] not in DOCK_POSITIONS:
                raise ValueError("неизвестная позиция Dock")
            action["position"] = raw["position"]
        if "opacity" in raw:
            if type(raw["opacity"]) not in {int, float} or not 0.2 <= float(raw["opacity"]) <= 1.0:
                raise ValueError("прозрачность Dock должна быть от 0.2 до 1.0")
            action["opacity"] = round(float(raw["opacity"]), 2)
        if len(action) == 1:
            raise ValueError("действие Dock не содержит изменений")
        return action
    if kind == "waybar":
        action = {"type": kind}
        if "style" in raw:
            if raw["style"] not in WAYBAR_STYLES:
                raise ValueError("неизвестный стиль Waybar")
            action["style"] = raw["style"]
        if "autohide" in raw:
            action["autohide"] = require_bool(raw["autohide"], "autohide")
        if len(action) == 1:
            raise ValueError("действие Waybar не содержит изменений")
        return action
    if kind == "install_packages":
        packages = raw.get("packages")
        if not isinstance(packages, list) or not 1 <= len(packages) <= 10:
            raise ValueError("нужно от 1 до 10 пакетов")
        clean: list[str] = []
        for package in packages:
            if not isinstance(package, str) or not PACKAGE_RE.fullmatch(package):
                raise ValueError(f"некорректное имя пакета: {package!r}")
            if package not in clean:
                clean.append(package)
        return {"type": kind, "packages": clean}
    if kind == "install_flatpak":
        app_id = raw.get("app_id")
        if not isinstance(app_id, str) or not FLATPAK_RE.fullmatch(app_id):
            raise ValueError("некорректный Flatpak application ID")
        return {"type": kind, "app_id": app_id}
    if kind in {"update_system", "open_settings"}:
        return {"type": kind}
    raise ValueError(f"запрещённый или неизвестный тип действия: {kind!r}")


def validate_response(response: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    message = response.get("message", "")
    if not isinstance(message, str):
        raise ShadowAIError("Поле message должно быть строкой")
    raw_actions = response.get("actions", [])
    if not isinstance(raw_actions, list) or len(raw_actions) > 12:
        raise ShadowAIError("Поле actions должно быть списком не длиннее 12 элементов")
    actions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_actions, 1):
        try:
            actions.append(validate_action(raw))
        except ValueError as exc:
            raise ShadowAIError(f"Действие {index} отклонено: {exc}") from exc
    return message.strip(), actions


def is_admin(action: dict[str, Any]) -> bool:
    return action["type"] in {"install_packages", "install_flatpak", "update_system"}


def is_change(action: dict[str, Any]) -> bool:
    return action["type"] not in {"diagnostics", "open_settings"}


def describe(action: dict[str, Any]) -> str:
    kind = action["type"]
    if kind == "diagnostics":
        return f"Диагностика: {action['scope']}"
    if kind == "gaming_mode":
        return f"Игровой режим: {'включить' if action['enabled'] else 'выключить'}"
    if kind == "lite_mode":
        return f"Облегчённые эффекты: {'включить' if action['enabled'] else 'выключить'}"
    if kind == "color_scheme":
        return f"Цветовая схема: {action['name']}"
    if kind == "dock":
        return "Настроить Dock: " + ", ".join(f"{k}={v}" for k, v in action.items() if k != "type")
    if kind == "waybar":
        return "Настроить Waybar: " + ", ".join(f"{k}={v}" for k, v in action.items() if k != "type")
    if kind == "install_packages":
        return "Установить пакеты: " + ", ".join(action["packages"])
    if kind == "install_flatpak":
        return "Установить Flatpak: " + action["app_id"]
    if kind == "update_system":
        return "Обновить систему через pacman"
    if kind == "open_settings":
        return "Открыть настройки DarkShadowShell"
    return kind


def user_tool(name: str, required: bool = True) -> Path | None:
    local = HOME / ".local" / "bin" / name
    found = local if local.exists() else (Path(shutil.which(name)) if shutil.which(name) else None)
    if required and not found:
        raise ShadowAIError(f"Не найден инструмент {name}")
    return found


def create_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = BACKUP_DIR / f"config-{stamp}.tar.gz"
    candidates = ["hypr", "rice", "waybar", "quickshell", "swaync", "rofi", "kitty"]
    with tarfile.open(target, "w:gz") as archive:
        for name in candidates:
            path = HOME / ".config" / name
            if path.exists():
                archive.add(path, arcname=str(Path(".config") / name), recursive=True)
    backups = sorted(BACKUP_DIR.glob("config-*.tar.gz"), reverse=True)
    for old in backups[15:]:
        old.unlink(missing_ok=True)
    return target


def restore_latest() -> None:
    backups = sorted(BACKUP_DIR.glob("config-*.tar.gz"), reverse=True)
    if not backups:
        raise ShadowAIError("Резервных копий ещё нет")
    source = backups[0]
    answer = input(f"Восстановить {source.name}? [y/N]: ").strip().lower()
    if answer not in {"y", "yes", "д", "да"}:
        print("Отменено.")
        return
    home_resolved = HOME.resolve()
    with tarfile.open(source, "r:gz") as archive:
        for member in archive.getmembers():
            destination = (HOME / member.name).resolve()
            if home_resolved not in {destination, *destination.parents}:
                raise ShadowAIError("Небезопасный путь в резервной копии")
        archive.extractall(HOME, filter="data")
    hyprctl = shutil.which("hyprctl")
    if hyprctl:
        run([hyprctl, "reload"], check=False)
    print(f"Восстановлено из {source}")


def diagnostics(scope: str) -> str:
    commands: dict[str, list[list[str]]] = {
        "quick": [
            ["uname", "-a"],
            ["free", "-h"],
            ["df", "-h", "/", str(HOME)],
            ["systemctl", "--failed", "--no-pager"],
        ],
        "gpu": [
            ["sh", "-c", "lspci -k | grep -A3 -Ei 'VGA|3D|Display'"],
            ["nvidia-smi"],
            ["vulkaninfo", "--summary"],
        ],
        "gaming": [
            ["gamemoded", "-t"],
            ["sh", "-c", "pacman -Q steam wine gamemode mangohud 2>&1"],
            ["sh", "-c", "findmnt -no FSTYPE,OPTIONS /"],
        ],
        "network": [
            ["nmcli", "general", "status"],
            ["nmcli", "device", "status"],
            ["ip", "-brief", "address"],
        ],
    }
    sections: list[str] = []
    for command in commands[scope]:
        sections.append(f"$ {shlex.join(command)}\n{compact_output(command, timeout=45, limit=12000)}")
    return "\n\n".join(sections)


def execute_action(action: dict[str, Any]) -> str:
    kind = action["type"]
    if kind == "diagnostics":
        return diagnostics(action["scope"])
    if kind == "gaming_mode":
        tool = user_tool("rice-effects")
        return run([str(tool), "gaming", "on" if action["enabled"] else "off"]).stdout
    if kind == "lite_mode":
        tool = user_tool("rice-effects")
        return run([str(tool), "lite", "on" if action["enabled"] else "off"]).stdout
    if kind == "color_scheme":
        tool = user_tool("rice-colors")
        return run([str(tool), "mode", action["name"]], timeout=45).stdout
    if kind == "dock":
        tool = user_tool("desktop-set")
        for key in ("enabled", "hover"):
            if key in action:
                run([str(tool), "dock", key, "on" if action[key] else "off"])
        if "position" in action:
            run([str(tool), "dock", "position", action["position"]])
        if "opacity" in action:
            run([str(tool), "dock", "opacity", str(action["opacity"])])
        return "Dock обновлён"
    if kind == "waybar":
        tool = user_tool("waybar-set")
        if "style" in action:
            run([str(tool), "style", action["style"]], timeout=45)
        if "autohide" in action:
            run([str(tool), "autohide", "on" if action["autohide"] else "off"], timeout=45)
        return "Waybar обновлён"
    if kind == "install_packages":
        missing = [p for p in action["packages"] if run(["pacman", "-Si", p], check=False).returncode != 0]
        if missing:
            raise ShadowAIError("Пакеты не найдены: " + ", ".join(missing))
        run_interactive(
            ["pkexec", "pacman", "-S", "--needed", "--noconfirm", *action["packages"]],
            timeout=1800,
        )
        return "Пакеты установлены"
    if kind == "install_flatpak":
        run_interactive(
            [
                "pkexec", "flatpak", "install", "--system", "--noninteractive", "-y",
                "flathub", action["app_id"],
            ],
            timeout=1800,
        )
        return "Flatpak установлен"
    if kind == "update_system":
        run_interactive(["pkexec", "pacman", "-Syu"], timeout=3600)
        return "Обновление завершено"
    if kind == "open_settings":
        tool = user_tool("rice-settings")
        subprocess.Popen([str(tool)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Настройки открыты"
    raise ShadowAIError(f"Внутренняя ошибка: неизвестное действие {kind}")


def append_history(record: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    record = {"time": datetime.now(timezone.utc).isoformat(), **record}
    with HISTORY_FILE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.chmod(HISTORY_FILE, 0o600)


def direct_command(text: str) -> tuple[str, list[dict[str, Any]]] | None:
    try:
        parts = shlex.split(text)
    except ValueError as exc:
        raise ShadowAIError(f"Ошибка команды: {exc}") from exc
    if not parts or not parts[0].startswith("/"):
        return None
    command = parts[0].lower()
    if command in {"/help", "/помощь"}:
        return (HELP, [])
    if command == "/doctor":
        return ("Запускаю быструю диагностику.", [{"type": "diagnostics", "scope": "quick"}])
    if command in {"/gaming", "/lite"} and len(parts) == 2 and parts[1] in {"on", "off"}:
        return (
            "Локальная команда, облачный API не используется.",
            [{"type": "gaming_mode" if command == "/gaming" else "lite_mode", "enabled": parts[1] == "on"}],
        )
    if command == "/theme" and len(parts) == 2:
        try:
            action = validate_action({"type": "color_scheme", "name": parts[1]})
        except ValueError as exc:
            raise ShadowAIError(str(exc)) from exc
        return ("Меняю цветовую схему.", [action])
    if command == "/dock" and len(parts) == 2 and parts[1] in {"on", "off"}:
        return ("Меняю состояние Dock.", [{"type": "dock", "enabled": parts[1] == "on"}])
    if command == "/undo":
        restore_latest()
        return ("Откат завершён.", [])
    if command == "/setup":
        setup_provider()
        return ("API настроен.", [])
    if command in {"/quit", "/exit"}:
        raise EOFError
    raise ShadowAIError("Неизвестная локальная команда. Введи /help")


HELP = """Локальные команды (работают без облака):
  /setup              настроить OpenAI-совместимый API
  /doctor             быстрая диагностика
  /gaming on|off      игровой режим DarkShadowShell
  /lite on|off        облегчённые визуальные эффекты
  /theme NAME         цвет: violet, ocean, mono и другие
  /dock on|off        показать или отключить Dock
  /undo               восстановить последнюю копию конфигурации
  /help               эта справка
  /quit               выход

Обычный текст отправляется выбранному API. Модель может только предложить
действия из белого списка; перед изменениями всегда показывается план.
"""


def handle(text: str) -> None:
    direct = direct_command(text)
    if direct is None:
        response = call_provider(text)
        message, actions = validate_response(response)
    else:
        message, actions = direct
    if message:
        print(f"\nShadow AI: {message}")
    if not actions:
        append_history({"prompt": text, "actions": [], "status": "advice"})
        return

    print("\nПлан:")
    for index, action in enumerate(actions, 1):
        suffix = " [права администратора]" if is_admin(action) else ""
        print(f"  {index}. {describe(action)}{suffix}")

    changes = [action for action in actions if is_change(action)]
    if changes:
        if any(is_admin(action) for action in changes):
            answer = input("\nДля применения введи ПРИМЕНИТЬ: ").strip()
            if answer not in {"ПРИМЕНИТЬ", "APPLY"}:
                print("Отменено.")
                append_history({"prompt": text, "actions": actions, "status": "cancelled"})
                return
        else:
            answer = input("\nПрименить? [y/N]: ").strip().lower()
            if answer not in {"y", "yes", "д", "да"}:
                print("Отменено.")
                append_history({"prompt": text, "actions": actions, "status": "cancelled"})
                return
        backup = create_backup()
        print(f"Резервная копия: {backup}")

    results: list[dict[str, Any]] = []
    for action in actions:
        print(f"\n→ {describe(action)}")
        try:
            output = execute_action(action).strip()
            if output:
                print(output[-12000:])
            results.append({"action": action, "ok": True})
        except ShadowAIError as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            results.append({"action": action, "ok": False, "error": str(exc)})
            append_history({"prompt": text, "actions": actions, "results": results, "status": "failed"})
            return
    append_history({"prompt": text, "actions": actions, "results": results, "status": "done"})


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe hybrid assistant for ShadowOS")
    parser.add_argument("prompt", nargs="*")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--undo", action="store_true")
    args = parser.parse_args()
    try:
        if args.setup:
            setup_provider()
            return 0
        if args.undo:
            restore_latest()
            return 0
        if args.prompt:
            handle(" ".join(args.prompt))
            return 0
        print("Shadow AI — безопасный гибридный помощник ShadowOS")
        print("Super+Space открывает это окно. /help — локальные команды.\n")
        while True:
            try:
                text = input("Ты: ").strip()
                if text:
                    handle(text)
            except (EOFError, KeyboardInterrupt):
                print("\nДо встречи.")
                return 0
            except ShadowAIError as exc:
                print(f"Ошибка: {exc}", file=sys.stderr)
    except ShadowAIError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
