$ErrorActionPreference = 'Stop'

$parts = @(Get-ChildItem -File -Filter '*.iso.part-*' | Sort-Object Name)
if ($parts.Count -eq 0) {
    throw 'No *.iso.part-* files found in the current directory.'
}

$outputName = $parts[0].Name -replace '\.part-[0-9]+$', ''
Write-Host "Joining $($parts.Count) parts into $outputName ..."

$output = [System.IO.File]::Create((Join-Path (Get-Location) $outputName))
try {
    foreach ($part in $parts) {
        Write-Host "  $($part.Name)"
        $inputStream = [System.IO.File]::OpenRead($part.FullName)
        try {
            $inputStream.CopyTo($output)
        }
        finally {
            $inputStream.Dispose()
        }
    }
}
finally {
    $output.Dispose()
}

if (Test-Path 'SHA256SUMS') {
    $expectedLine = Get-Content 'SHA256SUMS' | Where-Object { $_ -match [regex]::Escape($outputName) } | Select-Object -First 1
    if (-not $expectedLine) {
        throw "No checksum for $outputName was found in SHA256SUMS."
    }
    $expected = ($expectedLine -split '\s+')[0].ToUpperInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 $outputName).Hash.ToUpperInvariant()
    if ($actual -ne $expected) {
        throw "SHA-256 mismatch. Expected $expected, got $actual."
    }
    Write-Host "SHA-256 OK: $actual" -ForegroundColor Green
}
else {
    Write-Warning 'SHA256SUMS is missing; calculate and compare the ISO checksum manually.'
}

Write-Host "Ready: $outputName" -ForegroundColor Green
