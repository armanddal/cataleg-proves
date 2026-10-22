#!/usr/bin/env python3
"""Build relations.json: sobretaula ↔ suport ↔ versió muntada (Grups 4 i 5).

Relació de negoci: molts aparells existeixen en versió de sobretaula
(alçada 280) i en versió muntada "sobre soporte" (alçada 900); la muntada
és la sobretaula + un suport (575/765 de fons, 600 d'alçada) de la mateixa
amplada. Saber-ho evita comprar el que ja es pot muntar amb estoc existent.

Regles de matching (validades contra el catàleg 2026/03):
  - sobretaula ↔ muntada: mateix grup, amplada, fons i EXACTAMENT els
    mateixos atributs de fila (cremadors, KW, acabat...) — només canvia
    l'alçada. 63 parelles a G4+G5, cap ambigüitat, cap creuament de
    prefix de codi.
  - sobretaula/muntada ↔ suport: mateix grup i mateixa amplada (el suport
    és més estret de fons perquè queda a sota: 575 per sèrie 700, 765 per
    sèrie 900).

Run:  arch -x86_64 python3 scripts/build-relations.py   (PyMuPDF és x86_64)
Re-run quan canviï cataleg.pdf (després de build-refs.py).
"""
import fitz, re, json, os
from collections import defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF  = os.path.join(HERE, 'cataleg.pdf')
REFS = os.path.join(HERE, 'references.json')
OUT  = os.path.join(HERE, 'relations.json')

GROUPS_IN_SCOPE = (2, 3, 4)   # G03, G04, G05 (0-indexed)

# Famílies excloses de les relacions: productes d'un ALTRE proveïdor (Casta)
# dins d'un grup que és majoritàriament Tecnoinox — els suports solts del grup
# NO hi encaixen i no es poden muntar/desmuntar (confirmat per Sergi, 2026-07).
# Si es detecten més casos (p.ex. algunes planxes), afegir el prefix aquí.
EXCLUDE_FAMILY_PREFIXES = ('WOK',)

CODE_RE = re.compile(r'^[0-9][0-9A-Z]{6,7}$')
DIMS_RE = re.compile(r'^(\d{3,4})x(\d{3,4})x(\d{3,4})$')

def rows_for_page(doc, pno):
    """Table rows: (code, [cells...]) — cells left-to-right in the code's y-band."""
    d = doc[pno - 1].get_text('dict')
    lines = []
    for b in d['blocks']:
        for ln in b.get('lines', []):
            t = ''.join(sp['text'] for sp in ln['spans']).strip()
            if t: lines.append((ln['bbox'][0], ln['bbox'][1], t))
    codes = [(x, y, t.replace(' ', '').upper()) for x, y, t in lines
             if CODE_RE.match(t.replace(' ', '').upper())
             and len(re.findall(r'[0-9]', t)) >= 5]
    if not codes: return []
    cols = defaultdict(list)
    for x, y, t in codes: cols[round(x / 6)].append((x, y, t))
    # The price-table column: most codes with tight (line-height) y-gaps —
    # same heuristic as build-refs.py to skip the per-photo caption codes.
    def score(v):
        ys = sorted(y for _, y, _ in v)
        gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
        return (len(v) if (gaps and max(gaps) <= 30) else 0, len(v))
    best = max(cols.values(), key=score)
    out = []
    for x, y, code in sorted(best, key=lambda v: v[1]):
        row = sorted([(lx, lt) for lx, ly, lt in lines
                      if abs(ly - y) < 4 and lx > x + 5], key=lambda v: v[0])
        out.append((code, [lt for _, lt in row]))
    return out

def classify(fam, h):
    if fam.startswith('SOPORTES'): return 'support'
    if h <= 450: return 'top'
    # Muntada = alçada de taulell (~900). No exigim "SOPORTE" al nom de
    # família: algunes (p.ex. COCINAS DE INDUCCIÓN) barregen sobretaula i
    # muntada a la mateixa pàgina sense dir-ho. El matching posterior per
    # (grup, amplada, fons, atributs exactes) és qui evita falsos positius.
    if 850 <= h <= 950: return 'mounted'
    return 'other'

def support_variant(attrs):
    # Support attr columns: [obert, portes, calaixos]
    if attrs and attrs[0] not in ('', '-'): return 'open'
    if len(attrs) > 1 and attrs[1] not in ('', '-'): return 'doors'
    return 'drawers'

def main():
    doc = fitz.open(PDF)
    refs = json.load(open(REFS))['pages']

    items = {}
    for pg in refs:
        if pg['g'] not in GROUPS_IN_SCOPE: continue
        if pg['f'].startswith(EXCLUDE_FAMILY_PREFIXES): continue
        for code, cells in rows_for_page(doc, pg['p']):
            dims = di = None
            for i, c in enumerate(cells):
                m = DIMS_RE.match(c.replace(' ', ''))
                if m: dims, di = tuple(map(int, m.groups())), i; break
            if not dims or code in items: continue
            items[code] = dict(
                page=pg['p'], fam=pg['f'], g=pg['g'],
                w=dims[0], d=dims[1], h=dims[2],
                attrs=tuple(cells[di + 1:-1]), price=cells[-1],
            )
    for it in items.values():
        it['type'] = classify(it['fam'], it['h'])

    # sobretaula ↔ muntada per (grup, amplada, fons, atributs exactes)
    key = lambda it: (it['g'], it['w'], it['d'], it['attrs'])
    tops, mounted = defaultdict(list), defaultdict(list)
    for c, it in items.items():
        if it['type'] == 'top': tops[key(it)].append(c)
        elif it['type'] == 'mounted': mounted[key(it)].append(c)

    rel = defaultdict(list)   # code -> [(related_code, kind)]
    ambiguous = []
    for k, tcs in tops.items():
        mcs = mounted.get(k, [])
        if not mcs: continue
        if len(tcs) == 1 and len(mcs) == 1:
            rel[tcs[0]].append((mcs[0], 'mounted'))
            rel[mcs[0]].append((tcs[0], 'top'))
        else:
            ambiguous.append((k, tcs, mcs))   # cap actualment; no s'emeten

    # sobretaula/muntada ↔ suport per (grup, amplada)
    supports = defaultdict(list)
    for c, it in items.items():
        if it['type'] == 'support': supports[(it['g'], it['w'])].append(c)
    for c, it in items.items():
        if it['type'] not in ('top', 'mounted'): continue
        for sc in supports.get((it['g'], it['w']), []):
            rel[c].append((sc, 'support'))
            rel[sc].append((c, 'fits'))

    # Output: only codes involved in some relation.
    involved = set(rel)
    out_items = {}
    for c in involved:
        it = items[c]
        e = dict(t=it['type'], pg=it['page'],
                 d=f"{it['w']}x{it['d']}x{it['h']}", pr=it['price'],
                 rel=[[rc, kind] for rc, kind in rel[c]])
        if it['type'] == 'support':
            e['v'] = support_variant(it['attrs'])
        out_items[c] = e

    json.dump({'v': 2, 'groups': [g + 1 for g in GROUPS_IN_SCOPE],
               'items': out_items},
              open(OUT, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))

    n_pairs = sum(1 for c in rel if any(k == 'mounted' for _, k in rel[c]))
    print(f'{len(out_items)} codes amb relacions → {OUT} '
          f'({os.path.getsize(OUT) // 1024} KB)')
    print(f'  parelles sobretaula↔muntada: {n_pairs}')
    print(f'  suports: {sum(1 for c in out_items if out_items[c]["t"] == "support")}')
    if ambiguous:
        print(f'  ⚠ {len(ambiguous)} matches ambigus NO emesos (revisar manualment):')
        for k, t, m in ambiguous: print('   ', k, t, m)

if __name__ == '__main__':
    main()
