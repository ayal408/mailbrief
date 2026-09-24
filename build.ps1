# Builds MailBrief.exe: tests and lint first, then a single-file windowed executable with the app icon.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt

.\.venv\Scripts\python.exe -m pyflakes main.py mailbrief tests
if ($LASTEXITCODE) { throw 'pyflakes found problems' }
.\.venv\Scripts\python.exe -m unittest discover -s tests
if ($LASTEXITCODE) { throw 'tests failed' }

.\.venv\Scripts\pyinstaller.exe --onefile --noconsole --name MailBrief --icon (Resolve-Path assets\mailbrief.ico).Path `
    --paths . --distpath dist --workpath build --specpath build --noconfirm --log-level WARN main.py
Write-Host "Built: $(Resolve-Path dist\MailBrief.exe)"

# the installer, when Inno Setup is installed (winget install JRSoftware.InnoSetup --source winget)
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    $version = .\.venv\Scripts\python.exe -c "import mailbrief; print(mailbrief.__version__)"
    & $iscc /Q "/DAppVersion=$version" installer\mailbrief.iss
    if ($LASTEXITCODE) { throw 'Inno Setup failed' }
    Write-Host "Built: $(Resolve-Path dist\MailBrief-Setup.exe)"
} else { Write-Host 'Inno Setup not found - skipped MailBrief-Setup.exe' }
