# Builds an inspectable application folder, a portable ZIP and the Windows installer.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt

.\.venv\Scripts\python.exe -m pyflakes main.py mailbrief tests
if ($LASTEXITCODE) { throw 'pyflakes found problems' }
.\.venv\Scripts\python.exe -m unittest discover -s tests
if ($LASTEXITCODE) { throw 'tests failed' }

function Sign-IfConfigured([string]$Path) {
    if (-not $env:MAILBRIEF_SIGN_CERT) { return }
    if (-not (Test-Path -LiteralPath $env:MAILBRIEF_SIGN_CERT)) { throw 'MAILBRIEF_SIGN_CERT does not exist' }
    $signTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signTool) { throw 'signtool.exe was not found in the Windows SDK' }
    & $signTool.FullName sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f $env:MAILBRIEF_SIGN_CERT /p $env:MAILBRIEF_SIGN_PASSWORD $Path
    if ($LASTEXITCODE) { throw "Signing failed: $Path" }
}

# Inside the application: licenses and provider keys when their local files exist.
$data = @('--add-data', "$((Resolve-Path THIRD-PARTY-NOTICES.txt).Path);.")
if (Test-Path google_client.json) { $data += @('--add-data', "$((Resolve-Path google_client.json).Path);."); Write-Host 'Built-in Google key: yes' }
else { Write-Host 'Built-in Google key: no (each user sets up their own - see RELEASING.md)' }
if (Test-Path microsoft_client.json) { $data += @('--add-data', "$((Resolve-Path microsoft_client.json).Path);."); Write-Host 'Built-in Microsoft key: yes' }
else { Write-Host 'Built-in Microsoft key: no (set-microsoft-key.ps1)' }
.\.venv\Scripts\python.exe -m PyInstaller --onedir --noconsole --noupx --clean --name MailBrief --icon (Resolve-Path assets\mailbrief.ico).Path @data `
    --paths . --distpath dist --workpath build --specpath build --noconfirm --log-level WARN main.py
$appExe = (Resolve-Path dist\MailBrief\MailBrief.exe).Path
Sign-IfConfigured $appExe
$portable = Join-Path $PSScriptRoot 'dist\MailBrief-Portable.zip'
Remove-Item -LiteralPath $portable -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $PSScriptRoot 'dist\MailBrief\*') -DestinationPath $portable -CompressionLevel Optimal
Write-Host "Built: $appExe"
Write-Host "Built: $portable"

# The installer, when Inno Setup is installed (winget install JRSoftware.InnoSetup --source winget).
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    $wv2 = 'installer\MicrosoftEdgeWebview2Setup.exe'
    if (-not (Test-Path $wv2)) { Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $wv2 -UseBasicParsing }
    $version = .\.venv\Scripts\python.exe -c "import mailbrief; print(mailbrief.__version__)"
    & $iscc /Q "/DAppVersion=$version" installer\mailbrief.iss
    if ($LASTEXITCODE) { throw 'Inno Setup failed' }
    $setupExe = (Resolve-Path dist\MailBrief-Setup.exe).Path
    Sign-IfConfigured $setupExe
    Write-Host "Built: $setupExe"
} else { Write-Host 'Inno Setup not found - skipped MailBrief-Setup.exe' }
