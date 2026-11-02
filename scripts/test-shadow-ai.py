#!/usr/bin/env python3
"""Small dependency-free safety tests for Shadow AI's action validator."""

from __future__ import annotations

import importlib.util
import pathlib
import sys


def must_fail(function, value) -> None:
    try:
        function(value)
    except ValueError:
        return
    raise AssertionError(f"Expected validation failure for {value!r}")


def main() -> None:
    source = pathlib.Path(sys.argv[1]).resolve()
    spec = importlib.util.spec_from_file_location("shadow_ai", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.validate_action({"type": "gaming_mode", "enabled": True})["enabled"] is True
    assert module.validate_action({"type": "color_scheme", "name": "violet"})["name"] == "violet"
    assert module.validate_action({"type": "install_packages", "packages": ["steam", "wine"]})[
        "packages"
    ] == ["steam", "wine"]
    assert module.normalize_base_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"

    must_fail(module.validate_action, {"type": "shell", "command": "rm -rf /"})
    must_fail(module.validate_action, {"type": "install_packages", "packages": ["ok;evil"]})
    must_fail(module.validate_action, {"type": "dock", "opacity": 5})
    try:
        module.normalize_base_url("http://example.com/v1")
    except ValueError:
        pass
    else:
        raise AssertionError("Remote plaintext API URL was accepted")

    print("Shadow AI validator tests passed")


if __name__ == "__main__":
    main()
