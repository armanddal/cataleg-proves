#!/usr/bin/env python3
"""Lector d'una pàgina d'informació del catàleg escrita en un Google Doc (prototip).

Entrada: l'HTML exportat d'un Doc (Drive: exportMimeType text/html). Sortida (`llegeix_doc(html)`):
  {'items': [ {'k': 'fotos', 'fotos': [F, ...]},
              {'k': 'bloc',  'foto': F, 'cols': [{'idioma': 'es'|'en'|'fr', 'titol': str, 'items': [str], 'numerat': bool}]},
              {'k': 'text',  'linies': [{'t': str, 'neg': bool, 'vinyeta': bool}]} ],
   'avisos': [str]}
  F = {'referencia': n}            -> marcador «[FOTO n]»: la foto amb referència n de la pàgina a Odoo
    | {'imatge': 'treball/docs/img/<sha1>.<ext>'}  -> imatge enganxada al Doc (baixada i desada)

Regles del Doc:
  - paràgraf que només té marcadors [FOTO n] (i/o imatges)  -> fila de fotos
  - taula: 1a cel·la = foto/marcador; les següents = idiomes ES, EN, FR (en aquest ordre); a cada cel·la la 1a línia en negreta
    és el títol, i la llista numerada o amb vinyetes (segons el tipus de llista del Doc) són els ítems
  - la resta de paràgrafs (títols en negreta + vinyetes) -> text de la pàgina, pintat sota els blocs
Seguretat: es llegeix només estructura i text (tot s'escapa en pintar-lo); mai s'executa res del Doc (scripts/estils s'ignoren);
de les imatges només s'accepten data: URI i https, de com a màxim 15 MB, que PIL pugui obrir com a imatge.
"""
import base64, hashlib, os, re, sys, urllib.request
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDIOMES = ('es', 'en', 'fr')
MARCADOR = re.compile(r'\[\s*FOTO\s*(\d+)\s*\]', re.I)
BUITS = {'br', 'hr', 'img', 'input', 'meta', 'link', 'col', 'wbr'}
IGNORA = {'script', 'style', 'head', 'title', 'noscript', 'iframe', 'object', 'embed', 'template'}


class N:
    __slots__ = ('tag', 'at', 'ch')
    def __init__(s, tag, at=None): s.tag = tag; s.at = at or {}; s.ch = []      # ch: N o str


class _P(HTMLParser):
    def __init__(s): super().__init__(convert_charrefs=True); s.arrel = N('#'); s.pila = [s.arrel]; s.ign = 0
    def handle_starttag(s, tag, at):
        if tag in IGNORA: s.ign += 1; return
        if s.ign: return
        n = N(tag, dict(at)); s.pila[-1].ch.append(n)
        if tag not in BUITS: s.pila.append(n)
    def handle_startendtag(s, tag, at):
        if tag in IGNORA or s.ign: return
        s.pila[-1].ch.append(N(tag, dict(at)))
    def handle_endtag(s, tag):
        if tag in IGNORA: s.ign = max(0, s.ign - 1); return
        if s.ign or tag in BUITS: return
        for i in range(len(s.pila) - 1, 0, -1):
            if s.pila[i].tag == tag: del s.pila[i:]; return
    def handle_data(s, d):
        if not s.ign: s.pila[-1].ch.append(d)


def arbre(html): p = _P(); p.feed(html); p.close(); return p.arrel


def _neg(n):
    """Estil en negreta d'un node (Google: <span style="font-weight:700">; també b/strong i títols)."""
    if n.tag in ('b', 'strong', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'): return True
    m = re.search(r'font-weight\s*:\s*(\w+)', n.at.get('style', ''))
    return bool(m and (m.group(1) == 'bold' or (m.group(1).isdigit() and int(m.group(1)) >= 600)))


def segments(n, neg=False):
    """Contingut en línia d'un node -> llista de ('t', text, negreta) | ('img', node)."""
    out = []
    for c in n.ch:
        if isinstance(c, str): out.append(('t', c, neg))
        elif c.tag == 'img': out.append(('img', c, neg))
        elif c.tag == 'br': out.append(('t', ' ', neg))
        elif c.tag in ('ul', 'ol', 'table'): continue
        else: out += segments(c, neg or _neg(c))
    return out


def _text(segs): return re.sub(r'[ \t\r\n\xa0]+', ' ', ''.join(s[1] for s in segs if s[0] == 't')).strip()


def _tot_neg(segs):
    ts = [s for s in segs if s[0] == 't' and s[1].strip()]
    return bool(ts) and all(s[2] for s in ts)


def _foto_de_imatge(node, avisos):
    """<img> -> ruta local relativa a ROOT o None. Només data: i https; es valida amb PIL."""
    src = (node.at.get('src') or '').strip()
    try:
        if src.startswith('data:image/'):
            cap, _, dades = src.partition(',')
            if ';base64' not in cap: raise ValueError('data: no base64')
            b = base64.b64decode(dades)
        elif src.startswith('https://'):
            req = urllib.request.Request(src, headers={'User-Agent': 'cataleg-eurast'})
            with urllib.request.urlopen(req, timeout=30) as r: b = r.read(15 * 1024 * 1024 + 1)
        else: raise ValueError('només s\'accepten data: i https')
        if len(b) > 15 * 1024 * 1024: raise ValueError('imatge de més de 15 MB')
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(b)); fmt = (im.format or '').lower(); im.verify()
        ext = {'jpeg': 'jpg', 'png': 'png', 'gif': 'gif', 'webp': 'webp'}.get(fmt)
        if not ext: raise ValueError(f'format {fmt} no admès')
        rel = f'treball/docs/img/{hashlib.sha1(b).hexdigest()}.{ext}'
        os.makedirs(os.path.join(ROOT, 'treball/docs/img'), exist_ok=True)
        with open(os.path.join(ROOT, rel), 'wb') as f: f.write(b)
        return rel
    except Exception as e:
        avisos.append(f"imatge del Doc ignorada ({e})"); return None


def _fotos(segs, avisos):
    """Si els segments són només marcadors [FOTO n] i/o imatges (res més) -> llista de fotos; si no, None."""
    fs = []
    for s in segs:
        if s[0] == 'img':
            r = _foto_de_imatge(s[1], avisos)
            if r: fs.append({'imatge': r})
        else:
            resta = MARCADOR.sub(lambda m: (fs.append({'referencia': int(m.group(1))}) or ' '), s[1])
            if resta.strip(' \t\r\n\xa0'): return None
    return fs or None


def _llista(n):
    return [t for t in (_text(segments(li)) for li in n.ch if not isinstance(li, str) and li.tag == 'li') if t]


def _cel_la_foto(td, avisos):
    f = _fotos([s for p in _blocs_cel(td) for s in segments(p)], avisos)
    return f[0] if f else None


def _blocs_cel(td):
    """Elements de bloc d'una cel·la (p, h*, ul, ol), en ordre."""
    out = []
    for c in td.ch:
        if isinstance(c, str):
            if c.strip(): x = N('p'); x.ch.append(c); out.append(x)
        elif c.tag in ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'div'):
            out.append(c) if c.tag != 'div' else out.extend(_blocs_cel(c))
        else:
            x = N('p'); x.ch.append(c); out.append(x)
    return out


def _columna(td, idioma):
    titol = ''; items = []; numerat = None
    for b in _blocs_cel(td):
        if b.tag in ('ul', 'ol'):
            if numerat is None: numerat = (b.tag == 'ol')
            items += _llista(b)
        else:
            sg = segments(b); t = _text(sg)
            if not t: continue
            if not titol and not items and _tot_neg(sg): titol = t
            else: items.append(t)
    if not titol and not items: return None
    return {'idioma': idioma, 'titol': titol, 'items': items, 'numerat': bool(numerat)}


def _taula(t, avisos):
    files = []
    def cerca(n):
        for c in n.ch:
            if isinstance(c, str): continue
            if c.tag == 'tr': files.append(c)
            elif c.tag != 'table': cerca(c)
    cerca(t)
    out = []
    for tr in files:
        tds = [c for c in tr.ch if not isinstance(c, str) and c.tag in ('td', 'th')]
        if len(tds) < 2: avisos.append('fila de taula amb menys de 2 cel·les: ignorada'); continue
        foto = _cel_la_foto(tds[0], avisos)
        if foto is None: avisos.append('bloc sense foto a la 1a cel·la (cal un [FOTO n] o una imatge)')
        cols = [c for c in (_columna(td, l) for td, l in zip(tds[1:], IDIOMES)) if c]
        if len(tds) - 1 > len(IDIOMES): avisos.append(f'fila amb {len(tds) - 1} idiomes: només es llegeixen els 3 primers (ES, EN, FR)')
        out.append({'k': 'bloc', 'foto': foto, 'cols': cols})
    return out


def llegeix_doc(html):
    avisos = []; items = []; text = []
    cos = arbre(html)
    body = next((c for c in _iter(cos) if c.tag == 'body'), cos)

    def recorre(n):
        for c in n.ch:
            if isinstance(c, str): continue
            if c.tag == 'table': items.extend(_taula(c, avisos))
            elif c.tag in ('ul', 'ol'):
                for t in _llista(c): text.append({'t': t, 'neg': False, 'vinyeta': True})
            elif c.tag in ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                sg = segments(c); fs = _fotos(sg, avisos)
                if fs: items.append({'k': 'fotos', 'fotos': fs})
                elif _text(sg): text.append({'t': _text(sg), 'neg': _tot_neg(sg) or c.tag[0] == 'h', 'vinyeta': False})
            else: recorre(c)
    recorre(body)
    if text: items.append({'k': 'text', 'linies': text})
    return {'items': items, 'avisos': avisos}


def _iter(n):
    yield n
    for c in n.ch:
        if not isinstance(c, str): yield from _iter(c)


def html_del_doc(doc_id):
    """HTML exportat d'un Doc. Prototip: la mostra desada a treball/docs/<docId>.html. (En el núvol: l'exportació de Drive amb el compte de servei.)"""
    if not re.fullmatch(r'[\w-]+', str(doc_id)): raise ValueError('docId no vàlid')
    p = os.path.join(ROOT, 'treball', 'docs', f'{doc_id}.html')
    with open(p, encoding='utf8') as f: return f.read()


def doc_de_pagina(id_pagina):
    """docId de docs-pagines.yaml (`67: <docId>`) per a una pàgina d'Odoo, o None."""
    p = os.path.join(ROOT, 'docs-pagines.yaml')
    if not os.path.exists(p): return None
    import yaml
    d = yaml.safe_load(open(p, encoding='utf8')) or {}
    v = d.get(int(id_pagina)) or d.get(str(id_pagina))
    return str(v) if v else None


if __name__ == '__main__':
    import json
    arg = sys.argv[1]
    h = open(arg, encoding='utf8').read() if os.path.exists(arg) else html_del_doc(arg)
    print(json.dumps(llegeix_doc(h), ensure_ascii=False, indent=1))
