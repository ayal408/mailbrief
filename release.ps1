# Starts a new release:  .\release.ps1 1.2.0
# Checks locally, sets the version in the code, commits, tags and pushes. GitHub Actions then builds MailBrief.exe,
# publishes the release and sends the update to winget (.github/workflows/release.yml).
param([Parameter(Mandatory = $true)][string]$Version)
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot

function Fail([string]$why) { Write-Host "✗ $why" -ForegroundColor Red; exit 1 }
function Step([string]$what) { if ($LASTEXITCODE -ne 0) { Fail $what } }

if ($Version -notmatch '^\d+\.\d+\.\d+$') { Fail "Version must look like 1.2.0 (got '$Version')" }
$tag = "v$Version"

$branch = git rev-parse --abbrev-ref HEAD
if ($branch -ne 'main') { Fail "Releases are made from main (now on '$branch')" }
if (git status --porcelain) { Fail 'There are unsaved changes - commit them first (git add -A; git commit -m "...")' }
git fetch -q origin; Step 'fetch'
if (git rev-list HEAD..origin/main) { Fail 'GitHub has newer commits - run git pull first' }
git rev-parse -q --verify "refs/tags/$tag" *> $null
if ($LASTEXITCODE -eq 0) { Fail "$tag already exists" }

$init = 'mailbrief\__init__.py'
$current = (Select-String -LiteralPath $init -Pattern "__version__ = '([^']+)'").Matches[0].Groups[1].Value
$newer = [version]$Version -gt [version]$current
if (-not $newer) { Fail "$Version is not newer than the current $current" }

Write-Host "→ Checks (pyflakes + tests)..."
if (-not (Test-Path .venv)) { python -m venv .venv; Step 'python venv' }
.\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt; Step 'install tools'
.\.venv\Scripts\python.exe -m pyflakes main.py mailbrief tests; Step 'pyflakes found problems'
.\.venv\Scripts\python.exe -m unittest discover -s tests 2>&1 | Select-Object -Last 3; Step 'tests failed'

$text = [IO.File]::ReadAllText((Resolve-Path $init), [Text.Encoding]::UTF8) -replace "__version__ = '[^']+'", "__version__ = '$Version'"
[IO.File]::WriteAllText((Resolve-Path $init), $text, (New-Object Text.UTF8Encoding $false))

git add $init
git commit -q -m "Release $Version"; Step 'commit'
git tag -a $tag -m "MailBrief $Version"; Step 'tag'
git push -q origin main $tag; Step 'push'

Write-Host "`n✓ $tag pushed. GitHub is building it now:" -ForegroundColor Green
Write-Host "  https://github.com/ayal408/mailbrief/actions"
Write-Host "  in ~5 minutes: https://github.com/ayal408/mailbrief/releases/tag/$tag"
