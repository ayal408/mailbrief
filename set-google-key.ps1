# Builds MailBrief's own Google sign-in key into the program: every user then just clicks "Connect with Google".
# Takes the Client ID + secret already saved in MailBrief's settings on this computer (Settings -> Google one-time setup),
# writes google_client.json (git-ignored, for local builds) and stores it as the GOOGLE_CLIENT_JSON secret of the
# GitHub repository (for release builds). The key is never printed.
#   powershell -ExecutionPolicy Bypass -File set-google-key.ps1
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

$python = if (Test-Path .venv\Scripts\python.exe) { '.venv\Scripts\python.exe' } else { 'python' }
$code = @'
import json
from mailbrief import config
from mailbrief.storage import decrypt, load_json
cfg = load_json(config.SETTINGS_FILE, {}).get('google') or {}
if not cfg.get('client_id') or not cfg.get('client_secret'):
    raise SystemExit('No Google key in the settings - first fill the Google one-time setup in MailBrief')
with open('google_client.json', 'w', encoding='utf-8') as f:
    json.dump({'client_id': cfg['client_id'], 'client_secret': decrypt(cfg['client_secret'])}, f)
print('google_client.json written (' + cfg['client_id'].split('-')[0] + '-...)')
'@
& $python -c $code
if ($LASTEXITCODE) { exit 1 }

Get-Content google_client.json -Raw | gh secret set GOOGLE_CLIENT_JSON --repo ayal408/mailbrief
if ($LASTEXITCODE) { Write-Host 'Could not set the GitHub secret (gh auth login?) - local builds will still include the key'; exit 1 }
Write-Host 'Done: the GOOGLE_CLIENT_JSON secret is set - the next release includes the key.'
