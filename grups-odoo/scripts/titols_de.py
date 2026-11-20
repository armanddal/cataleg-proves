"""Títols de capçalera en alemany (línia «D») de la tarifa publicada: dades/titols-de.yaml, clau = títol ES normalitzat (també l'EN).
Odoo només té ES/EN/FR; la tarifa original duia també el DE (Sergi 20/11: «a tots els títols falta l'alemany»).
Només lectura del PDF. Executar des de grups-odoo/: /tmp/w/venvci/bin/python scripts/titols_de.py [PDF]"""
import sys, re, yaml, fitz, unicodedata
PDF = sys.argv[1] if len(sys.argv) > 1 else '/Users/armanddalmau/dev/tarifa-nova/cataleg_original_web.pdf'


def clau(t):
    t = unicodedata.normalize('NFC', re.sub(r'\s+', ' ', t or '')).strip().upper()
    return re.sub(r'[^\w ]', '', t).strip()


out = {}
doc = fitz.open(PDF)
for pg in doc:
    sc = pg.rect.width / 21
    lin = []
    for b in pg.get_text('dict')['blocks']:
        for l in b.get('lines', []):
            y = l['bbox'][1] / sc; x = l['bbox'][0] / sc
            if y < 2.2 and 3.5 < x < 6:
                lin.append((y, ''.join(s['text'] for s in l['spans']).strip()))
    lin.sort()
    es = next((t for y, t in lin if y < .6 and not re.match(r'^[EFD]\s*\|?\s', t)), None)
    trio = {}
    for y, t in lin:
        m = re.match(r'^([EFD])\s*\|?\s*(.+)$', t)
        if m and y >= .5: trio.setdefault(m.group(1), m.group(2).strip())
    if es and trio.get('D'):
        for k in (clau(es), clau(trio.get('E'))):
            if k and k not in out: out[k] = trio['D']
yaml.safe_dump(dict(sorted(out.items())), open('dades/titols-de.yaml', 'w', encoding='utf8'), allow_unicode=True, width=200)
print(len(out), 'títols DE')
