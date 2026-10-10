# Builds MailBrief's own Microsoft sign-in key into the program: every user then just clicks "Connect with Microsoft".
# A Microsoft "public client" has only an Application (client) ID - no secret - so nothing confidential ships.
# Takes the ID saved in MailBrief's settings on this computer (Settings -> Microsoft one-time setup; the installed
# MailBrief or this folder), writes microsoft_client.json (git-ignored, for local builds) and stores it as the
# MICROSOFT_CLIENT_JSON secret of the GitHub repository (for release builds).
#   powershell -ExecutionPolicy Bypass -File set-microsoft-key.ps1
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

$python = if (Test-Path .venv\Scripts\python.exe) { '.venv\Scripts\python.exe' } else { 'python' }
$code = @'
import json, os
from mailbrief import config
from mailbrief.storage import load_json
places = [config.SETTINGS_FILE, os.path.join(config._documents(), 'MailBrief', 'data', 'settings.json')]
found = next((c for c in ((load_json(p, {}).get('microsoft') or {}).get('client_id', '') for p in places) if c), '')
if not found:
    raise SystemExit('No Microsoft key in the settings - first fill the Microsoft one-time setup in MailBrief')
with open('microsoft_client.json', 'w', encoding='utf-8') as f:
    json.dump({'client_id': found}, f)
print('microsoft_client.json written (' + found.split('-')[0] + '-...)')
'@
& $python -c $code
if ($LASTEXITCODE) { exit 1 }

Get-Content microsoft_client.json -Raw | gh secret set MICROSOFT_CLIENT_JSON --repo ayal408/mailbrief
if ($LASTEXITCODE) { Write-Host 'Could not set the GitHub secret (gh auth login?) - local builds will still include the key'; exit 1 }
Write-Host 'Done: the MICROSOFT_CLIENT_JSON secret is set - the next release includes the key.'
