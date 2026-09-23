"""A tiny .xlsx writer (standard library only)."""
import os
import zipfile
from xml.sax.saxutils import escape as xml_escape


def _col(n):
    name = ''
    n += 1
    while n:
        n, rem = divmod(n - 1, 26)
        name = chr(65 + rem) + name
    return name


def _cell(ref, value, bold=False, plain=False):
    """Style 1 = bold text, style 2 = #,##0.00 number; plain numbers (e.g. exchange rates) keep all their digits."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{"" if plain else " s=\"2\""}><v>{value}</v></c>'
    if isinstance(value, str) and value.startswith('='):
        return f'<c r="{ref}" s="2"><f>{xml_escape(value[1:])}</f></c>'
    style = ' s="1"' if bold else ''
    return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{xml_escape(str(value))}</t></is></c>'


def write_xlsx(path, sheet_name, header, rows, widths, bold_rows=(), plain_cols=()):
    lines = [header] + rows
    data = ''.join(
        f'<row r="{r + 1}">' + ''.join(_cell(f'{_col(c)}{r + 1}', v, r == 0 or r in bold_rows, c in plain_cols)
                                       for c, v in enumerate(line) if v not in (None, '')) + '</row>'
        for r, line in enumerate(lines))
    cols = ''.join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    main = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    parts = {
        '[Content_Types].xml': head + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        '_rels/.rels': head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': head + f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
            f'<sheet name="{xml_escape(sheet_name[:31])}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{rel}/styles" Target="styles.xml"/></Relationships>',
        'xl/styles.xml': head + f'<styleSheet xmlns="{main}">'
            '<fonts count="2"><font><sz val="11"/><name val="Arial"/></font><font><b/><sz val="11"/><name val="Arial"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
            '<xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs></styleSheet>',
        'xl/worksheets/sheet1.xml': head + f'<worksheet xmlns="{main}"><sheetViews><sheetView rightToLeft="1" workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<cols>{cols}</cols><sheetData>{data}</sheetData></worksheet>',
    }
    tmp = path + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, xml in parts.items():
            z.writestr(name, xml)
    os.replace(tmp, path)
