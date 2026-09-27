"""🧾 Reading scanned receipts: pictures and image-only PDFs, through the text recognition built into Windows
(Windows.Media.Ocr) — on this computer, nothing is sent anywhere, nothing to install. Windows has no Hebrew recognition,
so this reads digits and English: amounts, dates, invoice numbers and English supplier names."""
import json
import os
import subprocess
import tempfile

from mailbrief import config


IMAGES = ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.gif')
BATCH = 40                   # files per run of the recognizer (about half a second each)

SCRIPT = r'''# Windows' built-in text recognition (Windows.Media.Ocr) for pictures and scanned PDFs — on this computer only.
# Input: a JSON file with a list of paths. Output: a JSON file {path: text}. English and digits (Windows has no Hebrew OCR).
param([string]$InFile, [string]$OutFile)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$ext = [System.WindowsRuntimeSystemExtensions].GetMethods()
$asTaskOp = ($ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asTaskAction = ($ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function Await($op, [Type]$type) { $t = $asTaskOp.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
function AwaitAction($action) { $t = $asTaskAction.Invoke($null, @($action)); $t.Wait(-1) | Out-Null }

$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('en-US')) }

function Read-Bitmap($stream) {
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
}
function Read-Text($bitmap) {
    if ($bitmap.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or $bitmap.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) { return '' }
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    ($result.Lines | ForEach-Object { $_.Text }) -join "`n"
}

$paths = Get-Content -LiteralPath $InFile -Raw -Encoding UTF8 | ConvertFrom-Json
$out = @{}
foreach ($path in $paths) {
    try {
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
        if ($path.ToLower().EndsWith('.pdf')) {                 # a scanned PDF: its first pages as pictures
            $doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
            $parts = @()
            for ($i = 0; $i -lt [Math]::Min(3, $doc.PageCount); $i++) {
                $page = $doc.GetPage($i)
                $options = [Windows.Data.Pdf.PdfPageRenderOptions]::new()
                $options.DestinationWidth = 1800                 # sharp enough for small print
                $stream = [Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
                AwaitAction ($page.RenderToStreamAsync($stream, $options))
                $parts += Read-Text (Read-Bitmap $stream)
            }
            $out[$path] = $parts -join "`n"
        } else {
            $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
            $out[$path] = Read-Text (Read-Bitmap $stream)
        }
    } catch {
        $out[$path] = ''
    }
}
$out | ConvertTo-Json -Compress | Out-File -LiteralPath $OutFile -Encoding UTF8
'''


def available():
    return os.name == 'nt'


def ocr_files(paths):
    """{path: text} for pictures and PDFs (the first 3 pages of a PDF). '' for a file that couldn't be read."""
    paths = [p for p in paths if os.path.isfile(p)][:BATCH]
    if not paths or not available():
        return {}
    os.makedirs(config.DATA, exist_ok=True)
    script = os.path.join(config.DATA, 'ocr.ps1')
    if not os.path.exists(script) or open(script, encoding='utf-8-sig').read() != SCRIPT:
        with open(script, 'w', encoding='utf-8-sig') as f:        # with a BOM: Windows PowerShell reads it as UTF-8
            f.write(SCRIPT)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, 'in.json'), os.path.join(tmp, 'out.json')
        with open(src, 'w', encoding='utf-8') as f:
            json.dump(paths, f, ensure_ascii=False)
        try:
            subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script, src, dst],
                           capture_output=True, timeout=30 + 5 * len(paths), creationflags=0x08000000)
            with open(dst, encoding='utf-8-sig') as f:
                found = json.load(f)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return {}
    return {p: (t or '') for p, t in found.items()} if isinstance(found, dict) else {}


def ocr_file(path):
    return ocr_files([path]).get(path, '')
