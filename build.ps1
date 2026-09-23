# Builds MailBrief.exe: tests and lint first, then a single-file windowed executable with the app icon.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt

.\.venv\Scripts\python.exe -m pyflakes main.py mailbrief tests
if ($LASTEXITCODE) { throw 'pyflakes found problems' }
.\.venv\Scripts\python.exe -m unittest discover -s tests
if ($LASTEXITCODE) { throw 'tests failed' }

.\.venv\Scripts\pyinstaller.exe --onefile --noconsole --name MailBrief --icon assets\mailbrief.ico `
    --paths . --distpath dist --workpath build --specpath build --noconfirm --log-level WARN main.py
Write-Host "Built: $(Resolve-Path dist\MailBrief.exe)"
