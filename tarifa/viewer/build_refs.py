#!/usr/bin/env python3
"""Build references.json from cataleg.pdf.

One entry per price-table page: {p: page, g: groupIdx, f: family, c: [codes]}.
Run from the pdf-viewer-demo directory:  python3 scripts/build-refs.py

Done offline (PyMuPDF) because pdf.js splits code tokens inconsistently in the
browser, whereas fitz reads each code whole and reliably. Re-run whenever
cataleg.pdf changes.
"""
import fitz, re, json, os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF  = os.path.join(HERE, 'cataleg.pdf')
OUT  = os.path.join(HERE, 'references.json')
OUT_TEXT = os.path.join(HERE, 'search-text.json')

# First PDF page of each group (must match the GROUPS array in index.html).
GROUP_STARTS = [2, 47, 65, 93, 151, 207, 248, 284, 340, 389, 423, 496, 588, 660, 731, 815]

def group_idx(p):
    g = 0
    for i, s in enumerate(GROUP_STARTS):
        if p >= s: g = i
        else: break
    return g

# A price-table page has a MOD./COD. (or COD.) column header and a € column.
def has_table(t):
    return bool(re.search(r'MOD\./COD\.|(?:^|\s)COD\.(?:\s|$)', t)) and ('€' in t)

# A reference code: 7-8 alphanumeric chars, starts with a digit, >=5 digits.
CODE_RE = re.compile(r'^[0-9][0-9A-Z]{6,7}$')
# WxDxH (o WxD en taules d'accessoris/plaques): números de 3-4 xifres, així
# no confon potències ("2x7,5"), pesos ni preus.
DIMS_RE = re.compile(r'^(\d{3,4})x(\d{3,4})(x\d{3,4})?$', re.I)

# Order codes by their position in the actual price table, not by PDF reading
# order — a code's caption near its product photo is often read by fitz
# BEFORE the table row that repeats it, which scrambled the widget/table order
# relative to what's visually printed.
#
# El criteri per "fila de taula" és que la FILA ACABI EN PREU (cel·la final
# numèrica tipus 450 / 5.910): és l'únic senyal estable a tot el catàleg.
# Els criteris estructurals (columnes alineades amb salts petits) fallaven
# amb les graelles de llegendes sota les fotos (pàg. 298), les taules-matriu
# (pàg. 632) i les files úniques (pàg. 296), i el llindar de dígits del codi
# es pot mantenir baix (>=3, per codis tipus 41RX5ETM) sense colar brossa de
# capçaleres ("450SNACK"), perquè aquella brossa mai té preu a la seva fila.
# Returns [(code, dims)] where dims is the WxDxH cell found on the code's
# table row ('' if none) — powers the dimension search in the viewer.
# Preu: 25 / 450 / 5.910 / 15.355 — també n'hi ha de 2 xifres (accessoris).
PRICE_RE = re.compile(r'^\d{1,3}(\.\d{3})+$|^\d{2,5}$')
# Codi curt: 5-6 xifres soltes (p.ex. rasquetes 96107, cistelles 92462).
# Només s'accepta en fila amb preu i amb >=2 cel·les a la dreta — un preu
# solt mai en té. NO es pot baixar a 4 xifres: les amplades en mm de
# campanes/mesas/estanteries (1000, 1200... 5000) són números de 4 xifres
# solts en files amb preu i inundarien el panell (provat: +250 falsos).
# Limitació coneguda: el codi '9187' (cistella, pàg. 655) queda fora.
SHORT_CODE_RE = re.compile(r'^\d{5,6}$')
def codes(doc, pno):
    d = doc[pno - 1].get_text('dict')
    items = []  # (x, y, code, ndigits, short)
    all_lines = []  # (x, y, text) — for same-row cell lookups
    for b in d['blocks']:
        for ln in b.get('lines', []):
            text = ''.join(sp['text'] for sp in ln['spans'])
            t = text.strip()
            if t:
                all_lines.append((ln['bbox'][0], ln['bbox'][1], t))
            c = t.replace(' ', '').upper()
            if CODE_RE.match(c) and len(re.findall(r'[0-9]', c)) >= 3:
                items.append((ln['bbox'][0], ln['bbox'][1], c,
                              len(re.findall(r'[0-9]', c)), False))
            elif SHORT_CODE_RE.match(c):
                items.append((ln['bbox'][0], ln['bbox'][1], c, len(c), True))
    if not items:
        return []

    def row_cells(x, y):
        return sorted((lx, lt) for lx, ly, lt in all_lines
                      if abs(ly - y) < 4 and lx > x + 5)

    def dims_at(x, y):
        for _, lt in row_cells(x, y):
            if DIMS_RE.match(lt.replace(' ', '')):
                return lt.replace(' ', '').lower()
        return ''

    table_items, caption_items = [], []
    for x, y, c, nd, short in items:
        cells = row_cells(x, y)
        # Fila de taula: alguna cel·la de la fila és un preu. No exigim que
        # sigui l'ÚLTIMA perquè amb dues taules costat a costat les cel·les
        # de la taula veïna queden més a la dreta que el preu propi (p. 243).
        has_price = any(PRICE_RE.match(lt.replace(' ', '')) for _, lt in cells)
        if short:
            # Codi curt: només via fila amb preu i descripció (mai caption) —
            # un número solt de 5 xifres fora d'aquest context no és un codi.
            if len(cells) >= 2 and has_price:
                table_items.append((y, x, c))
        elif cells and has_price:
            table_items.append((y, x, c))
        elif nd >= 5:
            # Fora d'una fila amb preu el llindar torna a 5 dígits: és on
            # viuen els falsos positius de capçalera ("450SNACK").
            caption_items.append((y, x, c))

    # Row-major order — same-row entries (e.g. two model variants side by
    # side) share a y-band and sort left-to-right.
    table_items.sort(key=lambda t: (round(t[0] / 6), t[1]))
    out, seen = [], set()
    for y, x, c in table_items:
        if c not in seen:
            seen.add(c); out.append((c, dims_at(x, y)))
    # Codes seen only in captions (no price row of their own) are appended
    # after, in their natural top-to-bottom order.
    caption_items.sort(key=lambda t: (t[0], t[1]))
    for y, x, c in caption_items:
        if c not in seen:
            seen.add(c); out.append((c, dims_at(x, y)))
    return out

def is_heading(s):
    s = s.strip()
    if len(s) < 5 or len(s) > 70: return False
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 4: return False
    if sum(1 for c in letters if c.isupper()) / len(letters) < 0.9: return False
    U = s.upper()
    if U[:2] in ('E ', 'F ', 'D '): return False
    if any(k in U for k in ('GRUPO','PAG','SIMBOLOG','CARACTER','GENERAL','FEATURES','MOD','COD')):
        return False
    return True

# Family = topmost uppercase heading on the page (by coordinates, not reading order).
def family(doc, pno):
    d = doc[pno - 1].get_text('dict')
    H = doc[pno - 1].rect.height
    lines = {}
    for b in d['blocks']:
        for ln in b.get('lines', []):
            y = ln['bbox'][1]
            if y > H * 0.18: continue
            e = lines.setdefault(round(y / 2), {'y': y, 'p': []})
            for sp in ln['spans']:
                e['p'].append((sp['bbox'][0], sp['text']))
    best = None
    for e in lines.values():
        s = re.sub(r'\s+', ' ', ' '.join(t for _, t in sorted(e['p']))).strip()
        if is_heading(s) and (best is None or e['y'] < best[0]):
            best = (e['y'], s)
    return best[1] if best else ''

def main():
    doc = fitz.open(PDF)
    pages = []        # references (table pages only)
    text_pages = []   # full text of every page, for the fallback search
    for p in range(1, doc.page_count + 1):
        t = doc[p - 1].get_text('text')
        text_pages.append({'p': p, 'g': group_idx(p), 't': t})
        if not has_table(t): continue
        cs = codes(doc, p)
        if not cs: continue
        pages.append({'p': p, 'g': group_idx(p), 'f': family(doc, p),
                      'c': [c for c, _ in cs], 'd': [dm for _, dm in cs]})

    json.dump({'v': 6, 'pages': pages}, open(OUT, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    json.dump({'v': 1, 'pages': text_pages}, open(OUT_TEXT, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    print(f'{len(pages)} table pages, {sum(len(x["c"]) for x in pages)} refs → {OUT} '
          f'({os.path.getsize(OUT)//1024} KB)')
    print(f'{len(text_pages)} text pages → {OUT_TEXT} '
          f'({os.path.getsize(OUT_TEXT)//1024} KB)')

if __name__ == '__main__':
    main()
