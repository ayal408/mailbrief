"""Writes docs/features.json for the website (ayal408.github.io/mailbrief) from the program's own guide,
so every feature added to MailBrief shows up on the site by itself. Run by .github/workflows/site.yml on every push."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mailbrief import __version__            # noqa: E402
from mailbrief.web.help import GUIDE          # noqa: E402


def data():
    return {'version': __version__,
            'features': [{'title': title, 'text': text} for title, _, text in GUIDE]}


if __name__ == '__main__':
    path = os.path.join(ROOT, 'docs', 'features.json')
    text = json.dumps(data(), ensure_ascii=False, indent=1) + '\n'
    old = open(path, encoding='utf-8').read() if os.path.exists(path) else ''
    if text != old:
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        print('docs/features.json updated')
    else:
        print('docs/features.json already up to date')
