"""🔍 Search inside PDFs on this computer: the receipts MailBrief keeps, the clients' folders and Downloads. The text of
each file is read once (and again only when the file changes) — so a search finds words inside the invoices, not only in
the email around them. Nothing leaves the computer."""
import os
import re

from mailbrief import config
from mailbrief.money.pdftext import pdf_text
from mailbrief.storage import load_json, save_json


MAX_FILES = 3000
MAX_SIZE = 15_000_000
NEW_PER_SEARCH = 150            # files read for the first time per search — the rest on the next ones
INDEX = lambda: os.path.join(config.DATA, 'pdf-index.json')


def folders():
    return [(config.RECEIPTS_DIR, '🧾 קבלות'), (config.CLIENTS_DIR, '👥 לקוחות'), (config.DOWNLOADS_DIR, '📥 הורדות')]


def _pdfs():
    for root, label in folders():
        if not os.path.isdir(root):
            continue
        for base, _, names in os.walk(root):
            for name in names:
                if name.lower().endswith('.pdf'):
                    yield os.path.join(base, name), label


def refresh():
    """Reads new and changed PDFs into the index; drops files that are gone. Returns the index {path: row}."""
    old, new, read = load_json(INDEX(), {}), {}, 0
    for path, label in list(_pdfs())[:MAX_FILES]:
        try:
            st = os.stat(path)
        except OSError:
            continue
        row = old.get(path)
        if row and row['mtime'] == st.st_mtime and row['size'] == st.st_size:
            new[path] = row
            continue
        if read >= NEW_PER_SEARCH or st.st_size > MAX_SIZE:
            if row:
                new[path] = row
            continue
        try:
            with open(path, 'rb') as f:
                text = pdf_text(f.read())
        except Exception:
            text = ''
        new[path] = {'mtime': st.st_mtime, 'size': st.st_size, 'label': label, 'text': re.sub(r'\s+', ' ', text)[:20000]}
        read += 1
    if new != old:
        save_json(INDEX(), new)
    return new


def words(query):
    """The plain words of a search (without Gmail operators such as from: or has:attachment)."""
    query = re.sub(r'\b\w+:\([^)]*\)|\b\w+:\S+|\bOR\b|[()"]', ' ', query or '')
    return [w.lower() for w in query.split() if len(w) >= 2]


def search(query, limit=30):
    terms = words(query)
    if not terms:
        return []
    out = []
    for path, row in refresh().items():
        name = os.path.basename(path)
        hay = (name + ' ' + row.get('text', '')).lower()
        if all(t in hay for t in terms):
            text = row.get('text', '')
            at = text.lower().find(terms[0])
            snippet = text[max(0, at - 50):at + 90].strip() if at >= 0 else ''
            out.append({'path': path, 'name': name, 'label': row.get('label', ''), 'snippet': snippet, 'mtime': row['mtime']})
    return sorted(out, key=lambda r: -r['mtime'])[:limit]


def known(path):
    """True only for a file in the index (the "open" button can't open anything else)."""
    return path in load_json(INDEX(), {}) and os.path.isfile(path)
