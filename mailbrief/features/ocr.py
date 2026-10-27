"""Read scanned receipts with Windows' local OCR APIs, without launching scripts or sending data anywhere."""
import asyncio
import os


IMAGES = ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.gif')
BATCH = 40                   # files per run of the recognizer (about half a second each)


def available():
    if os.name != 'nt':
        return False
    try:
        return _engine() is not None
    except (ImportError, OSError, RuntimeError):
        return False


def _engine():
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine
    return OcrEngine.try_create_from_user_profile_languages() or OcrEngine.try_create_from_language(Language('en-US'))


async def _bitmap(stream):
    from winrt.windows.graphics.imaging import BitmapDecoder
    decoder = await BitmapDecoder.create_async(stream)
    return await decoder.get_software_bitmap_async()


async def _text(engine, bitmap):
    from winrt.windows.media.ocr import OcrEngine
    if bitmap.pixel_width > OcrEngine.max_image_dimension or bitmap.pixel_height > OcrEngine.max_image_dimension:
        return ''
    result = await engine.recognize_async(bitmap)
    return '\n'.join(line.text for line in result.lines)


async def _read_one(engine, path):
    from winrt.windows.data.pdf import PdfDocument, PdfPageRenderOptions
    from winrt.windows.storage import FileAccessMode, StorageFile
    from winrt.windows.storage.streams import InMemoryRandomAccessStream

    source = await StorageFile.get_file_from_path_async(os.path.abspath(path))
    if path.lower().endswith('.pdf'):
        document = await PdfDocument.load_from_file_async(source)
        parts = []
        for index in range(min(3, document.page_count)):
            page = document.get_page(index)
            options = PdfPageRenderOptions()
            options.destination_width = 1800                 # sharp enough for small print
            stream = InMemoryRandomAccessStream()
            await page.render_to_stream_async(stream, options)
            stream.seek(0)
            parts.append(await _text(engine, await _bitmap(stream)))
            page.close()
            stream.close()
        return '\n'.join(parts)
    stream = await source.open_async(FileAccessMode.READ)
    try:
        return await _text(engine, await _bitmap(stream))
    finally:
        stream.close()


async def _read_all(paths):
    engine = _engine()
    if not engine:
        return {}
    found = {}
    for path in paths:
        try:
            found[path] = await _read_one(engine, path)
        except (OSError, RuntimeError, ValueError):
            found[path] = ''
    return found


def ocr_files(paths):
    """{path: text} for pictures and PDFs (the first 3 pages of a PDF). '' when a file cannot be read."""
    paths = [p for p in paths if os.path.isfile(p)][:BATCH]
    if not paths or os.name != 'nt':
        return {}
    try:
        return asyncio.run(_read_all(paths))
    except (ImportError, OSError, RuntimeError, ValueError):
        return {}


def ocr_file(path):
    return ocr_files([path]).get(path, '')
