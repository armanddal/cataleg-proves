#!/usr/bin/env python3
"""Renderitzador dels grups del catàleg (qualsevol G01..G16): dades/gN.yaml (disseny i pàgines genèriques) + Odoo Staging (taules, ordre, preus) -> HTML + PDF.

Ús:
  python3 scripts/renderitza.py --grup 3                 # taules, ordre i preus d'Odoo Staging en viu (només lectura) -> sortida/g3.pdf
  python3 scripts/renderitza.py --grup 3 --cache-estat   # l'última lectura d'Odoo (treball/estat_odoo_g3.json), sense xarxa
  python3 scripts/renderitza.py --grup 3 --estat f.json  # un estat d'Odoo simulat (JSON), p. ex. el pla (carrega_grup.py --simula-estat)
  python3 scripts/renderitza.py --grup 3 --preu 30020311=1900   # simula un canvi de preu, en memòria (MAI s'escriu a Odoo)
  python3 scripts/renderitza.py --grup 3 --capcalera icona --llegenda fixa   # estil antic (només icones; simbologia fixa de g3.yaml)
  python3 scripts/renderitza.py --grup 3 --idioma en     # noms de columna a les capçaleres en anglès (es|en|fr)
  python3 scripts/renderitza.py --grup 3 --data 2026/10  # força la data d'edició (defecte: mes de l'última modificació de les dades del grup a Odoo)
"""
import argparse, hashlib, html, json, os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import yaml
import grup_util as U

def _chrome():
    if os.environ.get('CHROME_BIN'):
        return os.environ['CHROME_BIN']
    mac = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    if os.path.exists(mac):
        return mac
    for n in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
        if shutil.which(n):
            return shutil.which(n)
    return mac


CHROME = _chrome()


def CHROME_ARGS():
    return [CHROME, '--headless=new', '--disable-gpu'] + (['--no-sandbox', '--disable-dev-shm-usage'] if os.environ.get('CHROME_NO_SANDBOX') else []) + ['--allow-file-access-from-files']
E = html.escape
SENSE_SLIDES = False     # --sense-slides: no es posa cap diapositiva (pàgina objectiu generada pel codi)
BASE = '../'     # prefix relatiu cap a l'arrel (on és assets/); es recalcula a renderitza()
# Opcions de disseny (CLI): capçalera 'text' (nom + icona opcional; per defecte) | 'icona' (mode antic: només icona);
# idioma del nom a la capçalera (es|en|fr); llegenda 'auto' (generada de les columnes del grup) | 'fixa' (la de gN.yaml)
OPC = {'capcalera': 'text', 'idioma': 'es', 'llegenda': 'auto'}
_STD = {}


# ----------------------------------------------------------------------------- preus
def num(s):
    if s is None: return None
    s = str(s).strip()
    if re.fullmatch(r'\d{1,3}(\.\d{3})+', s): return float(s.replace('.', ''))
    try: return float(s.replace(',', '.'))
    except ValueError: return None


def fmt_preu(v):
    if v is None: return '-'
    if abs(v - round(v)) < 0.005:
        return f'{int(round(v)):,}'.replace(',', '.')
    return f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


# ----------------------------------------------------------------------------- utilitats HTML
def img(src, cls='', alt=''):
    if src and src.endswith('.bin') and os.path.exists(os.path.join(ROOT, src[:-4] + '.png')):
        src = src[:-4] + '.png'          # icones TIFF extretes del .pub: el navegador no les mostra; se'n fa servir la còpia PNG
    if src: src = redueix(src)
    return f'<img class="{cls}" src="{BASE}{E(src)}" alt="{E(alt)}">' if src else ''


def retalla(src):
    """Foto de producte sense els marges blancs (les d'Odoo en porten molts i el producte quedava petit i lluny de l'etiqueta):
    en fa una còpia retallada a treball/img-retallades/ i en torna el camí relatiu. Si no cal o no es pot, torna l'original."""
    try:
        from PIL import Image, ImageChops
        orig = os.path.join(ROOT, src)
        dest_rel = os.path.join('treball', 'img-retallades', hashlib.md5(f'{src}:{os.path.getmtime(orig)}:v2'.encode()).hexdigest() + '.jpg')
        dest = os.path.join(ROOT, dest_rel)
        if os.path.exists(dest): return dest_rel
        im = Image.open(orig)
        rgba = im.convert('RGBA')
        fons = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        pla = Image.alpha_composite(fons, rgba).convert('RGB')
        dif = ImageChops.difference(pla, Image.new('RGB', pla.size, (255, 255, 255))).convert('L').point(lambda v: 255 if v > 14 else 0)
        bb = dif.getbbox()
        if not bb: return redueix(src)
        w, h = pla.size
        pad = int(max(bb[2] - bb[0], bb[3] - bb[1]) * .02) + 1
        bb = (max(0, bb[0] - pad), max(0, bb[1] - pad), min(w, bb[2] + pad), min(h, bb[3] + pad))
        if (bb[2] - bb[0]) * (bb[3] - bb[1]) > .92 * w * h: return redueix(src)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        talla = pla.crop(bb)
        talla.thumbnail((MAX_PX, MAX_PX))
        talla.save(dest, 'JPEG', quality=84, optimize=True)
        return dest_rel
    except Exception:
        return src


MAX_PX = 1500        # costat llarg màxim d'una foto al PDF (~225 ppp a 17 cm): més resolució només engreixa el PDF


def redueix(src):
    """Còpia reduïda (MAX_PX, JPEG 84) d'una foto gran; si ja és petita o no es pot, torna l'original. Les amb transparència es queden com estan."""
    try:
        from PIL import Image
        orig = os.path.join(ROOT, src)
        if not src.lower().endswith(('.jpg', '.jpeg', '.png')) or os.path.getsize(orig) < 150_000: return src
        dest_rel = os.path.join('treball', 'img-reduides', hashlib.md5(f'{src}:{os.path.getmtime(orig)}:v1'.encode()).hexdigest() + '.jpg')
        dest = os.path.join(ROOT, dest_rel)
        if os.path.exists(dest): return dest_rel
        im = Image.open(orig)
        if im.mode in ('RGBA', 'LA') or 'transparency' in im.info: return src
        im = im.convert('RGB')
        if max(im.size) <= MAX_PX and os.path.getsize(orig) < 400_000: return src
        im.thumbnail((MAX_PX, MAX_PX))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        im.save(dest, 'JPEG', quality=84, optimize=True)
        return dest_rel
    except Exception:
        return src


def lang_lines(d, cls='ml'):
    """{'es':..,'en':..,'fr':..} -> línies amb quadret E/F/D (l'ES va sol, sense lletra)."""
    out = []
    for l in ('es', 'en', 'fr', 'de'):
        if l in d and d[l]:
            t = E(U.repara_faltes_es(str(d[l]))) if l == 'es' else E(str(d[l]))
            if l == 'es': out.append(f'<div class="l-es">{t}</div>')
            else: out.append(f'<div class="l-x"><span class="lt">{l[0].upper()}</span>{t}</div>')
    return f'<div class="{cls}">' + ''.join(out) + '</div>'


def codi_html(codi, trossos=None, destacats=None):
    if trossos:
        return ''.join(f'<b>{E(t)}</b>' if i in (destacats or []) else E(t) for i, t in enumerate(trossos))
    if len(codi) == 8: return f'<b>{E(codi[:4])}</b>{E(codi[4:])}'      # els codis de 5 xifres (96108) surten sense destacar
    return E(codi)


class Ctx:
    def __init__(self, dades, preus):
        self.d = dades; self.preus = preus
        self.pagines = dades['pagines']
        self.num_de = {}
        for i, p in enumerate(self.pagines): self.num_de.setdefault(p['n'], i + 1)   # n original -> número de pàgina renderitzat
        self.avisos = []
        self.data = dades['grup']['data_edicio']
        self.grup = dades['grup']['numero']
        self.colors = dades['plantilla']['colors']

    def pag(self, n): return self.num_de.get(n, n)

    def enllac_pags(self, ns): return '/'.join('%02d' % self.num_de[n] for n in ns if n in self.num_de)   # una pàgina que ja no hi és (grup sense productes marcats) no s'enllaça


# ----------------------------------------------------------------------------- peu i capçalera
def peu(ctx, p, num_pag):
    if p['tipus'] in ('portada_grup', 'contraportada'): return ''
    logo = ctx.d['plantilla']['peu']['logo']
    enll = ''
    pe = p.get('peu_enllac')
    if pe and ctx.enllac_pags(pe['pagines']):
        pgs = ctx.enllac_pags(pe['pagines'])
        t = U.trio_titol(pe['text'])
        ull = next((i for i in pe.get('icones', []) if 'icona-ull' in i), 'assets/peu-icona-ull.png')
        q = pe.get('pos') or {}
        est = f' style="left:{q["x"]}cm;width:{q["w"]}cm"' if q.get('w') else ''
        enll = (f'<div class="peu-enllac"{est}><span class="ull">{img(ull)}</span>'
                f'<div><span class="pg">G{ctx.grup} P.{pgs}</span> <span class="nm">{E(t.get("es", ""))}</span>'
                f'<div class="idi"><span class="lt">E</span>{E(t.get("en", ""))} <span class="lt">F</span>{E(t.get("fr", ""))}</div></div></div>')
    return (f'<div class="peu"><span class="data">Grupo {ctx.grup} - {E(ctx.data)}</span>{img(logo, "logo")}'
            f'<span class="num">{num_pag}</span>{enll}</div>')


def capcalera(ctx, p):
    c = p.get('capcalera', {})
    chip = ''
    if c.get('serie'):
        chip = f'<div class="chip">{img(c.get("logo_serie"))}<div>{E(c["serie"])}</div></div>'
    tit = U.trio_titol(c.get('titol', {})) if c.get('titol') else {}
    if c.get('titol') and not c['titol'].get('en') and tit['en'] == tit['es']: tit.pop('en')       # sense traducció (no es repeteix l'ES)
    if c.get('titol') and not c['titol'].get('fr') and tit['fr'] == tit['es']: tit.pop('fr')
    h = '<div class="cap">' + chip + '<div class="cap-tit">'
    if tit.get('es'): h += f'<div class="t-es">{E(U.repara_faltes_es(tit["es"]))}</div>'
    for l in ('en', 'fr'):
        if tit.get(l): h += f'<div class="t-x"><span class="lt lt-w">{l[0].upper()}</span>{E(tit[l])}</div>'
    h += '</div></div>'
    return h


# ----------------------------------------------------------------------------- taules
def lang_inline(d, cls='ml-i'):
    """ES + [E] EN + [F] FR en línia (com les taules d'accessoris del .pub)."""
    h = ''
    for l in ('es', 'en', 'fr', 'de'):
        if l in d and d[l]:
            h += (f'<span class="l-es">{E(U.repara_faltes_es(str(d[l])))}</span> ' if l == 'es' else f'<span class="lt">{l[0].upper()}</span>{E(str(d[l]))} ')
    return f'<div class="{cls}">{h.strip()}</div>'


def cella_valor(v, inline=False):
    if isinstance(v, dict): return lang_inline(v, 'ml-cell') if inline else lang_lines(v, 'ml-cell')
    return E(str(v)) if v is not None else ''


def nom_capcalera(c):
    """Nom de la columna en l'idioma triat (cau a l'ES), sense els sufixos tècnics «(2)», «(texto)»."""
    nm = c.get('nom_capcalera') or {}
    return U.nom_net(nm.get(OPC['idioma']) or nm.get('es') or '')


def icona_std(ctx, c):
    if 'est' not in _STD: _STD['est'] = U.carrega_estandard()
    return U.icona_estandard(_STD['est'], ctx.grup, c['columna'])


def th_text(ctx, c, nom=None):
    """Capçalera «text primer»: nom sempre; icona estàndard petita damunt, només si la columna en té."""
    ic = icona_std(ctx, c)
    nom = nom if nom is not None else nom_capcalera(c)
    return ('<th class="hc">' + (img(ic, 'hci') if ic else '') + f'<div class="hcn" lang="{OPC["idioma"]}">{E(nom)}</div></th>')


def taula_html(ctx, t, inline=False):
    cols = t['columnes']
    tot = sum(c['ample_cm'] for c in cols) or 1
    h = f'<table class="tau{" hct" if OPC["capcalera"] == "text" else ""}"><colgroup>' + ''.join(f'<col style="width:{c["ample_cm"] / tot * 100:.2f}%">' for c in cols) + '</colgroup>'
    h += '<thead>'
    if t.get('banner'):
        h += f'<tr><th class="ban" colspan="{len(cols)}">{lang_lines(t["banner"], "ml-tit")}</th></tr>'
    if t.get('titol'):
        tt = t['titol']
        if inline and tt.get('en'):
            h += (f'<tr><th class="tit" colspan="{len(cols)}"><div class="ml-tit"><div class="l-es">{E(U.repara_faltes_es(tt["es"]))}</div>'
                  f'<div class="l-x"><span class="lt">E</span>{E(tt["en"])} <span class="lt">F</span>{E(tt.get("fr", ""))}</div></div></th></tr>')
        else: h += f'<tr><th class="tit" colspan="{len(cols)}">{lang_lines(tt, "ml-tit")}</th></tr>'
    h += '<tr class="hdr">'
    # dues columnes de la mateixa taula amb el mateix nom visible («Fuegos gas» x2: dues zones de fogons): se les numera al visible (Odoo no canvia)
    noms_vis = [nom_capcalera(c) if c.get('columna') and c.get('nom_capcalera') else None for c in cols]
    kv = [(c.get('bloc') or 1, x.lower()) if x else None for c, x in zip(cols, noms_vis)]      # dins del mateix bloc (les taules dobles repeteixen columnes)
    rep = {k: kv.count(k) for k in kv if k}
    cont = {}
    for i, x in enumerate(noms_vis):
        if x and rep[kv[i]] > 1:
            cont[kv[i]] = cont.get(kv[i], 0) + 1
            noms_vis[i] = f'{x} {cont[kv[i]]}'
    for c, nv in zip(cols, noms_vis):
        base = c.get('base', c['clau'])
        if base == 'preu': h += '<th class="eur">€</th>'
        elif OPC['capcalera'] == 'text' and c.get('columna') and base != 'codi' and c.get('nom_capcalera'):
            h += th_text(ctx, c, nv)
        elif c.get('icones_capcalera'):
            h += '<th>' + ''.join(img(i['asset'], 'hic') for i in c['icones_capcalera']) + '</th>'
        else:
            tx = c.get('text_capcalera') or {}
            h += '<th>' + ((lang_inline(tx, 'ml-h') if inline else lang_lines(tx, 'ml-h')) if isinstance(tx, dict) and tx else '') + '</th>'
    h += '</tr></thead><tbody>'
    for f in t['files']:
        h += '<tr>'
        for c in cols:
            cl = c['clau']; base = c.get('base', cl); suf = '_2' if c.get('bloc') == 2 else ''
            cod = f['cel_les'].get('codi' + suf) or ''
            v = f['cel_les'].get(cl)
            if base == 'codi':
                h += f'<td class="cod">{codi_html(cod) if cod else ""}</td>'
            elif base == 'preu':
                if not cod: h += '<td class="preu"></td>'; continue
                pv = ctx.preus.get(cod)
                if pv is None: ctx.avisos.append(f'{cod}: sense preu a Odoo')
                h += f'<td class="preu" data-codi="{E(cod)}">{fmt_preu(pv)}</td>'
            elif base == 'energia' and v:
                iv = ctx.d['plantilla'].get('icones_valor_energia', {})
                h += '<td class="ico">' + ''.join(img(iv[x], 'cel-ico') for x in str(v).split('+') if x in iv) + '</td>'
            else:
                nw = ' class="nw"' if isinstance(v, str) and 0 < len(v) <= 12 else ''      # valors curts («2 x 3,6»): no es parteixen si la taula s'estreny
                h += f'<td{nw}>{cella_valor(v, inline)}</td>'
        h += '</tr>'
    return h + '</tbody></table>'


# ----------------------------------------------------------------------------- tipus de pàgina
def pagina_portada(ctx, p, n):
    g = p['grup']
    h = '<div class="page portada">'
    h += '<svg class="franges-svg" viewBox="0 0 21 29.7" width="21cm" height="29.7cm"><defs><linearGradient id="gd"><stop offset="0" stop-color="#f7a600"/><stop offset=".5" stop-color="#e81c0c"/><stop offset="1" stop-color="#f7a600"/></linearGradient></defs>'
    for d in p.get('decoracio', []):
        if d['forma'] == 'degradat':
            q = d['pos']
            h += f'<line x1="{q["x"]}" y1="{q["y"] + q["h"]}" x2="{q["x"] + q["w"]}" y2="{q["y"]}" stroke="url(#gd)" stroke-width=".22" gradientUnits="userSpaceOnUse"/>'
    h += '</svg>'
    for im in p['imatges']:
        pos = im['pos']; rol = im.get('rol')
        if rol == 'segell_data':
            a, b = ctx.data.split('/')
            h += (f'<div class="segell" style="left:{pos["x"]}cm;top:{pos["y"]}cm;width:{pos["w"]}cm;height:{pos["h"]}cm">'
                  f'<span>{a}</span><span>{b}</span></div>')
            continue
        h += f'<img class="abs {rol}" style="left:{pos["x"]}cm;top:{pos["y"]}cm;width:{pos["w"]}cm;height:{pos["h"]}cm" src="{BASE}{redueix(im["asset"])}">'
    h += f'<div class="grup-et">{E(g["etiqueta"]["es"])}<span class="grup-num">{g["numero"]}</span></div>'
    series = g.get('serie', [])
    nom = g.get('nom', '')
    for s_ in reversed(series): nom = re.sub(r'\s*' + re.escape(s_) + r'\s*$', '', nom).strip()
    ss = '<span class="fl">⤢</span>'.join(f'<span class="ser">{s_}</span>' for s_ in series)
    if len(series) == 1: ss = '<span class="fl">⤢</span>' + ss        # G3-G5: la fletxa va entre el nom i la sèrie
    llarg = len(nom) + sum(len(s_) + 3 for s_ in series)
    mida = f' style="font-size:{max(16, min(33, 33 * 34 / llarg)):.1f}pt"' if llarg > 34 else ''      # noms llargs (G6: «EQUIPOS GRAN PRODUCCIÓN / ...»): redueix la lletra perquè càpiga
    h += f'<div class="grup-nom"{mida}>{E(nom)} {ss}</div>'
    tc = p['titol_catalog']
    h += '<div class="cat-tit"><div class="e0">' + E(tc['es']) + '</div>' + ''.join(f'<div><span class="lt lt-o">{l[0].upper()}</span>{E(tc[l])}</div>' for l in ('en', 'fr', 'de') if l in tc) + '</div>'
    return h + '</div>'


def pagina_index(ctx, p, n):
    bl = sorted(p.get('banda_logos', []), key=lambda l: l['pos']['y'])
    if bl: dreta = bl[0]['pos']['x'] > 10
    else: dreta = bool(p.get('targetes')) and min(t['pos']['x'] for t in p['targetes']) < 4     # G3-G5: la franja és a l'altra banda de les targetes
    lateral = p.get('banda_lateral', '')
    if not lateral.strip() and not bl:      # G1, G6-G16: l'extracció no porta el text lateral; hi va el nom del grup (part en castellà)
        lateral = re.split(r'\s+/\s+|\s+-\s+', ctx.d['grup'].get('nom', ''))[0].strip()
    toks = lateral.split()
    h = '<div class="page index">'
    h += f'<div class="franja {"dreta" if dreta else "esq"}">'
    if len(bl) == 2 and len(toks) == 3:
        h += f'<div class="vt">{toks[2]} {toks[1]}</div>{img(bl[0]["asset"], "bl")}<div class="vt">{toks[0]}</div>{img(bl[1]["asset"], "bl")}'
    else:
        mida = f' style="font-size:{max(22, min(50, 50 * 13 / len(lateral))):.1f}pt"' if len(lateral) > 13 else ''
        h += f'<div class="vt"{mida}>{E(lateral)}</div>' + ''.join(img(l['asset'], 'bl') for l in bl)
    h += '</div>'
    for t in p['targetes']:
        pos = t['pos']
        pg = ctx.enllac_pags(t['enllac_pagines'])
        et = t.get('etiqueta', {}).get('es')
        pre = re.sub(r'\s*G\d+ PAG.*$', '', et).strip() if et else ''
        h += f'<div class="card-bar" style="left:{pos["x"]}cm;top:{pos["y"]}cm;width:{pos["w"]}cm"><span class="pre">{E(pre)}</span><span>G{ctx.grup} PAG. {pg}</span></div>'
        for f in t['fotos']:
            fp = f['pos']
            aj = ';object-fit:contain' if f.get('ajust') == 'contain' else ''   # fotos d'Odoo (targetes automàtiques)
            h += f'<img class="abs" style="left:{fp["x"]}cm;top:{fp["y"]}cm;width:{fp["w"]}cm;height:{fp["h"]}cm{aj}" src="{BASE}{redueix(f["asset"])}">'
    return h + peu(ctx, p, n) + '</div>'


_MAJ = 'A-ZÁÉÍÓÚÀÈÒÇÑÜ'
_TITOL = re.compile(r'(?<![\w])([' + _MAJ + r']{3,}(?: [' + _MAJ + r']{1,}){0,4})(?= [' + _MAJ + r'][a-záéíóúàèòçñü])')


def estructura_text(text):
    """Un paràgraf pla del .pub («CONSTRUCCIÓN En acero... □ PLANCHAS A GAS Con grifos...») es torna a estructurar com l'original:
    títols de secció en vermell, una vinyeta per frase i els □ (que eren els números de referència a les fotos) com a 1, 2, 3...
    Retorna [('h', títol) | ('li', text amb §n§ per a les referències)] o None si no sembla un paràgraf d'aquest tipus."""
    t = re.sub(r'\s+', ' ', text).strip()
    tit = list(_TITOL.finditer(t))
    if len(t) < 250 or not tit: return None
    k = [0]

    def ref(m): k[0] += 1; return f' §{k[0]}§ '
    t = re.sub(r'\s*\u25a1\s*', ref, t); tit = list(_TITOL.finditer(t))
    out = []; pos = 0
    for m in tit + [None]:
        cos = t[pos:m.start()] if m else t[pos:]
        for fr in re.split(r'(?<=[.!?§])\s+(?=[' + _MAJ + r'])', cos.strip()):
            fr = fr.strip()
            if fr: out.append(('li', fr))
        if m: out.append(('h', m.group(1))); pos = m.end()
    return out


def _amb_refs(x):
    return re.sub(r'\s*§(\d+)§', lambda m: f' <i class="ref">{m.group(1)}</i>', E(x)).strip()


def parag_html(ps):
    out = []; lst = False
    for q in ps:
        est = estructura_text(q['text']) if q['role'] != 'titol' else None
        if est:
            for tipus, x in est:
                if tipus == 'h':
                    if lst: out.append('</ul>'); lst = False
                    out.append(f'<h3>{E(x)}</h3>')
                else:
                    if not lst: out.append('<ul>'); lst = True
                    out.append(f'<li>{_amb_refs(x)}</li>')
            continue
        q = dict(q, text=re.sub(r' {2,}', ' ', q['text'].replace('\u25a1', '')).strip())      # □ = número de referència del .pub sense glifo (les refs ja van a q['refs'])
        refs = ''.join(f'<i class="ref">{r}</i>' for r in q.get('refs', []))
        if q['role'] == 'titol':
            if lst: out.append('</ul>'); lst = False
            out.append(f'<h3>{E(q["text"])}</h3>')
        else:
            if not lst: out.append('<ul>'); lst = True
            out.append(f'<li>{E(q["text"])} {refs}</li>')
    if lst: out.append('</ul>')
    return ''.join(out)


def _aspecte(src):
    try:
        from PIL import Image
        w, h = Image.open(os.path.join(ROOT, src)).size
        return w / h
    except Exception:
        return 1.0


def blocs_html(blocs):
    """Pàgina d'informació en mode «blocs» (dades d'Odoo: pagines_odoo.blocs_de): files de fotos amb la seva referència i blocs imatge + text per idioma."""
    W_, GAP = 18.6, 0.5                                          # ample útil (cm) i separació entre fotos
    files = [b for b in blocs if b['k'] == 'fotos']
    asps = [[_aspecte(f['asset']) for f in b['fotos']] for b in files]
    alt = min([6.2] + [(W_ - GAP * 2) / max(sum(a), 3 * 0.9) for a in asps])         # totes les files de fotos tenen la mateixa alçada (la que faci caber la més ampla)
    h = '<div class="bl-cos">'
    for b in blocs:
        if b['k'] == 'fotos':
            fs = b['fotos']; asp = asps[files.index(b)]
            h += f'<div class="bl-fila" style="height:{alt:.2f}cm">'
            for f, a in zip(fs, asp):
                ref = f'<i class="bl-n">{f["referencia"]}</i>' if f.get('referencia') else ''
                h += f'<div class="bl-foto" style="width:{alt * a:.2f}cm"><img src="{BASE}{redueix(f["asset"])}">{ref}</div>'
            h += '</div>'
        elif b['k'] == 'text':           # text de la pàgina del Doc (paràgrafs normals): títols en negreta + vinyetes, sota els blocs
            h += '<div class="bl-text">'
            for l in b['linies']:
                h += (f'<p class="bl-vin">{E(l["t"])}</p>' if l['vinyeta'] else f'<p class="{"bl-tit" if l["neg"] else "bl-par"}">{E(l["t"])}</p>')
            h += '</div>'
        else:
            num = f'<i class="bl-n">{E(b["num"])}</i>' if b.get('num') else ''
            h += f'<div class="bl-bloc">{num}<div class="bl-img"><img src="{BASE}{redueix(b["asset"])}"></div><div class="bl-cols">'
            for c in b['cols']:
                marc = f'<span class="lt">{c["idioma"][0].upper()}</span>' if c['idioma'] != 'es' else ''
                tag = 'ol' if c['numerat'] else 'ul'
                h += (f'<div class="bl-col"><h4>{marc}{E(c["titol"])}</h4><{tag} class="bl-{"num" if c["numerat"] else "vin"}">'
                      + ''.join(f'<li>{E(x)}</li>' for x in c['items']) + f'</{tag}></div>')
            h += '</div></div>'
    return h + '</div>'


def pagina_info(ctx, p, n):
    if p.get('blocs'):
        return '<div class="page info blocs">' + capcalera(ctx, p) + blocs_html(p['blocs']) + peu(ctx, p, n) + '</div>'
    h = '<div class="page info">' + capcalera(ctx, p)
    for c in p['columnes']:
        pos = c['pos']
        mida = None
        for q in c['paragrafs']:
            if q['role'] == 'text' and q.get('estil', {}).get('mida'): mida = q['estil']['mida']; break
        marc = f'<div class="col-lang"><span class="lt">{c["idioma"][0].upper()}</span></div>' if c['idioma'] != 'es' else ''
        h += (f'<div class="info-col" style="left:{pos["x"]}cm;top:{pos["y"]}cm;width:{pos["w"]}cm;font-size:{(mida or 10.5) * 0.93:.1f}pt">'
              f'{marc}{parag_html(c["paragrafs"])}</div>')
    for f in p.get('fotos', []):
        pos = f['pos']
        h += f'<div class="abs foto-ref" style="left:{pos["x"]}cm;top:{pos["y"]}cm;width:{pos["w"]}cm;height:{pos["h"]}cm"><img src="{BASE}{redueix(f["asset"])}">'
        if f.get('referencia'): h += f'<i class="ref big">{f["referencia"]}</i>'
        h += '</div>'
    for i in p.get('insignies', []):
        pos = i['pos']
        h += f'<img class="abs" style="left:{pos["x"]}cm;top:{pos["y"]}cm;width:{pos["w"]}cm" src="{BASE}{redueix(i["asset"])}">'
    return h + peu(ctx, p, n) + '</div>'


def etiqueta_foto(f):
    """Etiqueta d'una foto: un o diversos codis (variants gas/elèctrica, potències...), cada un amb les seves icones i text."""
    codis = f.get('codis') or [{'codi': f['codi']}]
    h = ''.join(img(i['asset'], 'et-ico-f') for i in f.get('icones_foto', []) or [])
    h = f'<span class="et-fotoic">{h}</span>' if h else ''
    if len(codis) > 6:      # foto compartida per moltes files (prestatgeries): primer i últim codi; la resta són a la taula
        codis = [codis[0], codis[-1]]; mes = f'<i class="mes">… {len(f["codis"])} models</i>'
    else: mes = ''
    for k, c in enumerate(codis):
        if k == 1 and mes: h += mes
        ic = ''.join(img(a, 'et-ico') for a in c.get('icones_etiqueta', []) or [])
        tx = f'<em>{E(c["text_etiqueta"])}</em>' if c.get('text_etiqueta') else ''
        h += f'<span class="cx"><span class="cl"><i class="fletxa">&#9650;</i><span class="c">{codi_html(c["codi"])}</span>{ic}</span>{tx}</span>'
    return f'<div class="et">{h}</div>'


def es_titol_pagina(q):
    """Text gran sota la capçalera («HASTA FIN DE EXISTENCIAS»): títol de la pàgina, no llegenda."""
    return 1.0 <= q['pos']['y'] < 4.0 and q['pos']['w'] > 8 and len(U.net(q.get('text'))) > 6 and not re.search(r'\d', q['text'])


def titols_pagina_html(p):
    return ''.join(f'<div class="titol-pag">{E(q["text"].strip())}</div>' for q in (p.get('textos_pagina') or []) if es_titol_pagina(q))


def llegenda_html(p):
    """Llegenda del quadre de comandes electrònic (textos_pagina + imatge «sense classificar»): ES / E / F amb els números en cercle."""
    # G11+: el títol de la pàgina i les etiquetes soltes («700») també són a textos_pagina; no són llegenda
    tx = sorted([q for q in (p.get('textos_pagina') or []) if not (q['pos']['y'] < 1.0 and q['pos']['w'] > 10) and not es_titol_pagina(q) and len(U.net(q.get('text'))) > 6],
                key=lambda q: q['pos']['y'])
    if not tx: return ''
    cos = tx[-1]['text']
    titol = tx[0]['text'] if len(tx) > 1 else ''
    grups = []
    parts = re.split(r'(?:(?<=\s)|^)([1-9])\s+(?=\S)', cos)
    k = 1
    while k < len(parts) - 1:
        n, text = int(parts[k]), parts[k + 1].strip(); k += 2
        if n == 1 or not grups: grups.append([])
        grups[-1].append((n, text))
    if not grups:                       # llegenda sense números («D calor directe / I calor indirecte»): una línia per text, amb la seva icona
        icones = []
        for f in p.get('fotos', []):
            for ic in f.get('icones_foto', []) or []:
                if ic['asset'] not in icones: icones.append(ic['asset'])
        files = ''.join(f'<div class="ll-s">{img(icones[i], "et-ico") if i < len(icones) else ""}{E(q["text"].replace(" / ", " · "))}</div>' for i, q in enumerate(tx))
        return f'<div class="llegenda simple"><div class="ll-body">{files}</div></div>'
    imatge = ''.join(img(s['imatge'], 'll-img') for s in (p.get('sense_classificar') or []) if s.get('imatge'))
    cols = ''
    for idx, g_ in enumerate(grups):
        marca = '' if idx == 0 else f'<span class="lt">{"EF"[idx - 1]}</span>'
        cols += '<div class="ll-col">' + marca + ''.join(f'<div><i class="ref">{n}</i> {E(t)}</div>' for n, t in g_) + '</div>'
    return f'<div class="llegenda">{imatge}<div class="ll-body"><div class="ll-t">{E(titol)}</div><div class="ll-cols">{cols}</div></div></div>'


def nota_linies(t):
    """Text d'una nota (taules sense codis: «ACCESORIOS...», «CHE 883 x 603») -> llista de {'es','en','fr'} (un bloc per línia)."""
    plans = [x for bl in (t.get('text_taula') or []) for x in bl]
    txt = ' '.join(' '.join(str(v) for v in d.values()) for d in plans) if plans else ''
    if not txt: return []
    if ' * ' in txt:                                            # «ACCESORIOS E ACCESSORIES F ACCESSOIRES * Cestos... E * Baskets... F * Paniers...»
        cap, resta = txt.split(' * ', 1)
        parts = [x.strip() for x in re.split(r'\s+[EF]\s+', resta)]
        tr = {'es': '* ' + parts[0], 'en': parts[1] if len(parts) > 1 else '', 'fr': parts[2] if len(parts) > 2 else ''}
        return [U.trio_titol({'es': cap}), tr]
    if plans and plans[0].get('en'): return [U.trio_titol(plans[0])]
    return [U.trio_titol({'es': txt})] if re.search(r'\s[EF]\s', txt) else [{'es': txt}]


def nota_html(t):
    col = t['columnes'][0]
    ample = ' wide' if t.get('pos', {}).get('w', 0) > 10 else ''
    ics = ''.join(img(i['asset']) for i in col.get('icones_capcalera', []))
    return f'<div class="nota-caixa{ample}">{ics}<div>' + ''.join(lang_lines(l, 'ml-n') for l in nota_linies(t)) + '</div></div>'


_HASH = {}


def hash_imatge(src):
    """Contingut de la imatge (no el nom): a Odoo cada variant té la seva còpia de la mateixa foto."""
    if src not in _HASH:
        try: _HASH[src] = hashlib.md5(open(os.path.join(ROOT, src), 'rb').read()).hexdigest()
        except OSError: _HASH[src] = src
    return _HASH[src]


def agrupa_fotos(fotos):
    """Les fotos idèntiques d'una pàgina (60 prestatgeries amb la mateixa foto) es mostren un sol cop, amb tots els codis a l'etiqueta."""
    grups = {}
    for f in fotos:
        k = hash_imatge(f['asset'])
        if k not in grups: grups[k] = dict(f, codis=list(f.get('codis') or ([{'codi': f['codi']}] if f.get('codi') else [])))
        else: grups[k]['codis'] += [c for c in (f.get('codis') or [{'codi': f.get('codi')}]) if c.get('codi')]
    out = list(grups.values())
    for g in out:
        if g['codis']: g['codi'] = g['codis'][0]['codi']
    return out


def columnes_fotos(n, ratios=None, alt_cm=None):
    """Com més fotos, més columnes: amb 2 columnes fixes, 13 fotos quedaven en tires de 2 cm.
    Fins a 6 fotos, si es coneixen les proporcions i l'alçada lliure, tria les columnes que fan les fotos més grans
    (2 fotos apaïsades ocupen més apilades en una columna que una al costat de l'altra)."""
    if n <= 1: return 1
    if n > 6 or not ratios or not alt_cm: return 2 if n <= 6 else 3 if n <= 9 else 4 if n <= 16 else 5
    ample = 16.6
    millor, nc = -1, 2
    for c in range(1, min(n, 3) + 1):
        files = -(-n // c)
        w, h = (ample - .3 * (c - 1)) / c, (alt_cm - .2 * (files - 1)) / files - .9     # .9 cm = etiqueta de sota
        if h < 1.5: continue
        area = sum(min(w, h * r) * min(w / r, h) for r in ratios)
        if area > millor * 1.04: millor, nc = area, c        # 4 % de marge: a igualtat es queda amb la disposició amb menys columnes
    return nc


def ratio_foto(asset):
    try:
        from PIL import Image
        w, h = Image.open(os.path.join(ROOT, retalla(asset))).size
        return w / h
    except Exception:
        return 1.3


# Partició de les taules massa llargues (G14: prestatgeries amb 60-108 files). La pàgina té alçada fixa i el que no hi cap es perdia
# sense avís; ara les files que sobren van a pàgines de continuació amb la mateixa capçalera de pàgina i de taula.
ALT_UTIL_CM, FILA_CM, CAP_TAULA_CM, FOTOS_MIN_CM, LLEGENDA_CM = 25.6, .87, 2.4, 5.5, 2.5


def parteix_pagina(p, k=0):
    taules = [t for t in p.get('taules', []) if t['format'] == 'taula_producte']
    altres = [t for t in p.get('taules', []) if t['format'] != 'taula_producte']
    f = .82 ** k          # k > 0: la mesura real al Chrome ha dit que no hi cabia; es parteix més
    alt_util = ALT_UTIL_CM * f
    lim = (ALT_UTIL_CM - (FOTOS_MIN_CM if p.get('fotos') else 0) - (LLEGENDA_CM if llegenda_html(p) else 0) - 2.0 * len(altres)) * f
    if sum(CAP_TAULA_CM + FILA_CM * len(t['files']) for t in taules) <= lim: return [p]
    pags, resta = [[]], lim
    for t in taules:
        i = 0
        while i < len(t['files']):
            cap = int((resta - CAP_TAULA_CM) // FILA_CM)
            if cap < 3:
                pags.append([]); resta = alt_util; continue
            tros = t['files'][i:i + cap]
            pags[-1].append(dict(t, files=tros)); i += len(tros)
            resta -= CAP_TAULA_CM + FILA_CM * len(tros)
    primera = dict(p, taules=altres + pags[0])
    cont = [dict(p, taules=tt, fotos=[], insignies=[], textos_pagina=[], sense_classificar=[], continuacio=True) for tt in pags[1:] if tt]
    return [primera] + cont


def pagina_producte(ctx, p, n):
    h = '<div class="page producte' + (' cont' if p.get('continuacio') else '') + '">' + capcalera(ctx, p)
    ordre_codis = [r['cel_les'].get('codi') for t in p.get('taules', []) if t['format'] == 'taula_producte' for r in t['files'] if r['cel_les'].get('codi')]
    if not p.get('continuacio'):
        h += titols_pagina_html(p)
        h += '<div class="cos">'
        if p.get('insignies'):
            h += '<div class="insig">' + ''.join(img(i['asset']) for i in p['insignies']) + '</div>'

        def idx(f):
            ii = [ordre_codis.index(c['codi']) for c in (f.get('codis') or [{'codi': f.get('codi')}]) if c['codi'] in ordre_codis]
            return min(ii) if ii else 99
        fotos = agrupa_fotos(sorted(p.get('fotos', []), key=idx))
        files_tau = sum(CAP_TAULA_CM + FILA_CM * len(t['files']) for t in p.get('taules', []) if t['format'] == 'taula_producte')
        alt_fotos = ALT_UTIL_CM - files_tau - (LLEGENDA_CM if llegenda_html(p) else 0) - .6
        nc = columnes_fotos(len(fotos), [ratio_foto(f['asset']) for f in fotos], alt_fotos)
        h += f'<div class="fotos n{len(fotos)} c{nc}" style="grid-template-columns:repeat({nc},1fr)">'
        for k, f in enumerate(fotos):
            # l'última foto d'una fila incompleta s'estira fins al final de la fila (centrada), com abans amb 3, 5, 7...
            sobra = len(fotos) % nc
            est = f' style="grid-column:span {nc - sobra + 1}"' if sobra and k == len(fotos) - 1 else ''
            h += f'<figure{est}>{img(retalla(f["asset"]))}{etiqueta_foto(f) if f.get("codi") else ""}</figure>'
        h += '</div></div>'
        amb_foto = {c['codi'] for f in p.get('fotos', []) for c in (f.get('codis') or [{'codi': f.get('codi')}])}
        sense_foto = sorted(set(ordre_codis) - amb_foto)
        if sense_foto: ctx.avisos.append(f'p{p["n"]}: codis sense foto (només a la taula): {", ".join(sense_foto)}')
        for t in p.get('taules', []):
            if t['format'] == 'nota': h += nota_html(t)
        h += llegenda_html(p)
    for t in p.get('taules', []):
        if t['format'] == 'taula_producte': h += '<div class="tau-box">' + taula_html(ctx, t) + '</div>'
    return h + peu(ctx, p, n) + '</div>'


def parteix_accessoris(p, k=0):
    """Pàgines d'accessoris amb massa taules (G10 p.32: 14 taules, se superposaven): es reparteixen en pàgines que hi càpiguen."""
    taules = list(enumerate([t for t in p['taules'] if t['format'] == 'taula_producte'], 1))     # mateixa numeració que taula_ordre de les fotos
    altres = [t for t in p['taules'] if t['format'] != 'taula_producte']
    if len(taules) <= 1: return [p]

    def alt(kt, t):
        doble = 2 if any(c.get('bloc') == 2 for c in t['columnes']) else 1      # taula doble: ocupa les dues columnes
        return doble * (2.4 + .62 * len(t['files']) + (3.0 if any(f.get('taula_ordre') == kt for f in p.get('fotos', [])) else 0))
    cap = 2 * 23.5 * .82 ** k          # dues columnes de ~24 cm útils; k > 0: la mesura real ha dit que no hi cabia
    if sum(alt(k, t) for k, t in taules) <= cap: return [p]
    grups, acum = [[]], 0
    for kt, t in taules:
        if grups[-1] and acum + alt(kt, t) > cap * .9: grups.append([]); acum = 0
        grups[-1].append((kt, t)); acum += alt(kt, t)
    out = []
    for i, g in enumerate(grups):
        ks = {kt for kt, _ in g}; renum = {kt: j for j, (kt, _) in enumerate(g, 1)}
        out.append(dict(p, taules=(altres if not i else []) + [t for _, t in g], fotos=[dict(f, taula_ordre=renum[f['taula_ordre']]) for f in p.get('fotos', []) if f.get('taula_ordre') in ks],
                        **({'continuacio': True} if i else {})))
    return out


def pagina_accessoris(ctx, p, n):
    h = '<div class="page accessoris">' + capcalera(ctx, p)
    taules = [t for t in p['taules'] if t['format'] == 'taula_producte']
    cols = 1 if len(taules) <= 1 else 2
    h += f'<div class="acc-grid c{cols}">'
    for k, t in enumerate(taules, 1):
        fots = [f for f in p.get('fotos', []) if f.get('taula_ordre') == k]
        ample = ' full' if any(c.get('bloc') == 2 for c in t['columnes']) else ''
        h += f'<div class="acc-card{ample}"><div class="acc-fotos">' + ''.join(img(retalla(f['asset'])) for f in fots) + '</div>' + taula_html(ctx, t, True) + '</div>'
    h += '</div>'
    return h + peu(ctx, p, n) + '</div>'


def columnes_llegenda(ctx):
    """Entrades de la llegenda: les columnes que usa el grup (de les taules ja compostes des d'Odoo), en l'ordre del catàleg de columnes,
    sense repetir noms (fogons/fogons_2/fogons_3 -> «Fuegos gas»). [{codi, noms{es,en,fr}, unitat, icona|None}]"""
    est = U.carrega_estandard()
    cat = ctx.d.get('cataleg_columnes', {})
    usades = {c['columna'] for pg in ctx.pagines for t in pg.get('taules', []) for c in t.get('columnes', []) if c.get('columna')}
    fora = set(est.get('fora_llegenda', []))
    out = []; vistos = {}
    for codi, col in cat.items():
        if codi not in usades or codi in fora: continue
        noms = {l: U.nom_net(col['noms'].get(l) or col['noms'].get('es')) for l in ('es', 'en', 'fr')}
        base = est.get('alies', {}).get(codi) or re.sub(r'_\d+$', '', codi)
        unitat = col.get('unitat') or est.get('unitats', {}).get(codi) or est.get('unitats', {}).get(base) or ''
        ic = U.icona_estandard(est, ctx.grup, codi)
        k = noms['es'].lower()
        if k in vistos:                       # variant del mateix concepte: només completa la icona/unitat si la primera no en tenia
            e = vistos[k]; e['icona'] = e['icona'] or ic; e['unitat'] = e['unitat'] or unitat
            continue
        vistos[k] = e = {'codi': codi, 'noms': noms, 'unitat': unitat, 'icona': ic}
        out.append(e)
    return out


def entrada_llegenda(tile, noms, unitat='', cls=''):
    if max(len(v or '') for v in noms.values()) > 28: cls += ' llarg'       # noms molt llargs: lletra una mica més petita
    t = f'<div class="le-tile">{tile}</div>' if tile else '<div class="le-tile sense"><i></i></div>'
    u = f'<div class="le-un">{E(unitat)}</div>' if unitat else ''
    return f'<div class="le {cls}">{t}<div class="le-t">{lang_lines(noms, "ml-s")}{u}</div></div>'


def pagina_simbologia_auto(ctx, p, n):
    """Llegenda generada: columnes usades pel grup (icona estàndard si en té + nom ES/EN/FR + unitat) + els símbols fixos que no són
    columnes (Largo/Fondo/Alto, gas/elèctric, preu, equivalències), tal com surten de gN.yaml."""
    est = U.carrega_estandard()
    fixos = set(est.get('simbols_fixos', []))
    ent = [entrada_llegenda(img(c['icona']) if c['icona'] else '', c['noms'], c['unitat']) for c in columnes_llegenda(ctx)]
    for s_ in p['simbols']:
        tx = U.trio_titol(s_['text'])
        if s_.get('icona_ref') == 'simbol_euro':
            ent.append(entrada_llegenda('<div class="euro">€</div>', tx))
        elif s_.get('icona') and (s_.get('_odoo') or any(b == f or b.startswith(f + '-e-') for f in fixos for b in [os.path.splitext(os.path.basename(s_['icona']))[0]])):   # `_odoo`: símbols fixos de la pàgina d'Odoo   # G5: «simbol-largo-e-length-f-large»
            ent.append(entrada_llegenda(img(s_['icona']), tx))
    eq = p.get('equivalencies', [])
    if len(eq) == 1: eq = [x for x in re.split(r'\s+(?=1 (?:Kw|Kcal|HP))', eq[0]) if x]
    if eq: ent.append('<div class="le"><div class="equiv-l">' + ''.join(f'<div>{E(x)}</div>' for x in eq) + '</div></div>')
    files = -(-len(ent) // 3)
    pas = min(3.15, 24.6 / max(files, 1)); tile = min(2.0, pas - 0.5)
    h = '<div class="page simbologia auto">' + capcalera(ctx, p)
    h += f'<div class="abs llegenda-auto" style="left:.5cm;top:3.0cm;width:19cm;grid-auto-rows:minmax({pas:.2f}cm,auto);--tile:{tile:.2f}cm">' + ''.join(ent) + '</div>'
    return h + peu(ctx, p, n) + '</div>'


def pagina_simbologia(ctx, p, n):
    """Cada símbol és al seu lloc del .pub (el text és a x, la icona 2 cm a l'esquerra)."""
    if OPC['llegenda'] == 'auto' and ctx.d.get('cataleg_columnes'): return pagina_simbologia_auto(ctx, p, n)
    h = '<div class="page simbologia">' + capcalera(ctx, p)
    for s in p['simbols']:
        q = s['pos']
        if s.get('icona_ref') == 'simbol_euro':
            e = p['simbol_euro']['pos']
            h += f'<div class="abs euro-ic" style="left:{e["x"]}cm;top:{e["y"]}cm;width:{e["w"]}cm;height:{e["h"]}cm">€</div>'
        elif s.get('icona'):
            h += f'<img class="abs" style="left:{q["x"] - 2.0}cm;top:{q["y"]}cm;width:2cm;height:2cm" src="{BASE}{E(s["icona"])}">'
        tx = U.trio_titol(s['text'])
        h += f'<div class="abs sim-t" style="left:{q["x"]}cm;top:{q["y"]}cm;width:{q["w"] - 0.2}cm;height:{q["h"]}cm">{lang_lines(tx, "ml-s")}</div>'
    eq = p.get('equivalencies', [])
    if len(eq) == 1: eq = [x for x in re.split(r'\s+(?=1 (?:Kw|Kcal|HP))', eq[0]) if x]
    if eq and p.get('equivalencies_pos'):
        e = p['equivalencies_pos']
        h += f'<div class="abs equiv" style="left:{e["x"]}cm;top:{e["y"]}cm;width:{e["w"]}cm;height:{e["h"]}cm">' + ''.join(f'<div>{E(x)}</div>' for x in eq) + '</div>'
    return h + peu(ctx, p, n) + '</div>'


def pagina_condicions(ctx, p, n):
    h = '<div class="page condicions">' + capcalera(ctx, p) + '<div class="cond">'
    pas = 'es'
    for s in p['seccions']:
        if 'barra_idiomes' in s:
            b = s['barra_idiomes']
            h += f'<div class="barra-id"><span class="lt lt-w">E</span>{E(b.get("en", ""))}<span class="sp"></span><span class="lt lt-w">F</span>{E(b.get("fr", ""))}</div>'
            pas = 'bi'; continue
        tx = s['textos']
        if pas == 'es':
            h += f'<div class="cs">{img(s.get("icona"), "csi")}<div>' + ''.join(f'<div class="{"cst" if q["role"] == "titol" else "csp"}">{E(q["text"])}</div>' for q in tx.get('es', [])) + '</div></div>'
        else:
            def col(l):
                return ''.join(f'<div class="{"cst" if q["role"] == "titol" else "csp"}">' + (f'<span class="lt">{l[0].upper()}</span>' if k == 0 and q['role'] == 'titol' else '') + f'{E(q["text"])}</div>' for k, q in enumerate(tx.get(l, [])))
            h += f'<div class="cs bi">{img(s.get("icona"), "csi")}<div>{col("en")}</div><div>{col("fr")}</div></div>'
    h += '</div>'
    return h + peu(ctx, p, n) + '</div>'


def pagina_contraportada(ctx, p, n):
    t = p['capcalera_text']
    h = '<div class="page contra">' + img(p['imatges'][0]['asset'], 'full')
    h += '<div class="contra-bar">' + E(t['es']) + ''.join(f' <span class="lt">{l[0].upper()}</span> {E(t[l])}' for l in ('en', 'fr', 'de') if l in t) + '</div></div>'
    return h


def pagina_imatge(ctx, p, n):
    """Pàgina que l'extractor només ha pogut guardar com una imatge a pàgina completa."""
    return '<div class="page contra">' + img(p['imatge_pagina']['asset'], 'full') + '</div>'


TIPUS = {'pagina_imatge': pagina_imatge, 'portada_grup': pagina_portada, 'index_grup': pagina_index, 'informacio_general': pagina_info,
         'producte': pagina_producte, 'accessoris': pagina_accessoris, 'simbologia': pagina_simbologia,
         'condicions_venda': pagina_condicions, 'contraportada': pagina_contraportada}

# ----------------------------------------------------------------------------- document
# Les fonts del .pub (Franklin Gothic...) no són aquí: les columnes de text d'una pàgina d'informació poden sortir més altes; es redueix
# la mida de lletra fins que no passen del peu de pàgina.
AJUST_JS = '''
/* Pàgines d'informació. 1) Mode del .pub (coordenades absolutes): el text es redueix fins que càpiga, però mai per sota de 7 pt.
   2) Si així no hi cap sense trepitjar una foto/una altra columna o sortir del full, o una columna fa menys de 5 cm d'ample,
   la pàgina és «problemàtica» i es passa al mode FLUID (flux normal: fotos en fila a dalt, text en 2 columnes a sota). Vegeu fluid(). */
var MIN_PX = 7 * 4 / 3, FLUID_PGS = [];
document.querySelectorAll('.page.info').forEach(function(pg){
  var CM = 37.795, r0 = pg.getBoundingClientRect(), cols = Array.from(pg.querySelectorAll('.info-col')), fots = Array.from(pg.querySelectorAll('.foto-ref'));
  var base = r0.top + 28.1 * CM, mal = false;
  function marge(c){
    var b = c.getBoundingClientRect(), lim = base;
    fots.forEach(function(f){ var q = f.getBoundingClientRect(); if (q.top > b.top && q.left < b.right && q.right > b.left) lim = Math.min(lim, q.top - 0.2 * CM); });
    cols.forEach(function(o){ if (o === c) return; var q = o.getBoundingClientRect(); if (q.top > b.top + 0.1 * CM && q.left < b.right && q.right > b.left) lim = Math.min(lim, q.top - 0.15 * CM); });
    return lim;
  }
  cols.forEach(function(c){
    var lim = marge(c), fs = parseFloat(getComputedStyle(c).fontSize), n = 0;
    if (c.getBoundingClientRect().width < 5 * CM) { mal = true; pg.dataset.why = (pg.dataset.why||'') + ' ample' + (c.getBoundingClientRect().width/CM).toFixed(1); }
    while (c.getBoundingClientRect().bottom > lim && fs > MIN_PX && n < 120) { fs -= 0.2; c.style.fontSize = fs + 'px'; n++; }
    if (c.getBoundingClientRect().bottom > lim + 1) { mal = true; pg.dataset.why = (pg.dataset.why||'') + ' noCap'; }
    if (n == 0 && fs < 10.5 * 4 / 3) {          // lletra petita de l'original: s'augmenta fins on càpiga (màx. 10,5 pt) perquè no quedi mig full en blanc
      while (fs < 10.5 * 4 / 3 && n < 60) { c.style.fontSize = (fs + 0.3) + 'px'; if (c.getBoundingClientRect().bottom > lim) { c.style.fontSize = fs + 'px'; break; } fs += 0.3; n++; }
    }
  });
  function inter(a, b){ return Math.min(a.right, b.right) - Math.max(a.left, b.left) > 3 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 3; }
  cols.forEach(function(c, i){
    var b = c.getBoundingClientRect();
    fots.forEach(function(f){ if (inter(b, f.getBoundingClientRect())) { mal = true; pg.dataset.why = (pg.dataset.why||'') + ' foto'; } });
    cols.forEach(function(o, j){ if (j > i && inter(b, o.getBoundingClientRect())) { mal = true; pg.dataset.why = (pg.dataset.why||'') + ' cols'; } });
  });
  if (mal) FLUID_PGS.push(pg);
});
function fluid(pg){
  var CM = 37.795, r0 = pg.getBoundingClientRect(), base = r0.top + 28.1 * CM;
  var cols = Array.from(pg.querySelectorAll('.info-col')), fots = Array.from(pg.querySelectorAll('.foto-ref'));
  pg.classList.add('fluid');
  var body = document.createElement('div'), fz = document.createElement('div'), tx = document.createElement('div');
  body.className = 'fl-body'; fz.className = 'fl-fotos'; tx.className = 'fl-text';
  fots.forEach(function(f){ f.removeAttribute('style'); f.classList.remove('abs'); fz.appendChild(f); });
  Array.from(pg.children).forEach(function(e){ if (e.tagName == 'IMG' && e.classList.contains('abs')) { e.removeAttribute('style'); e.classList.remove('abs'); e.classList.add('ins'); fz.appendChild(e); fots.push(e); } });     // tires d'icones del .pub (alineades al text): ara van a la fila de fotos
  var rang = {es: 0, e: 1, f: 2, d: 3}, ant = '';
  cols = cols.map(function(c, i){ var m = c.querySelector('.col-lang .lt'); return {c: c, i: i, l: m ? m.textContent.trim().toLowerCase() : 'es'}; })
            .sort(function(a, b){ return ((rang[a.l] === undefined ? 9 : rang[a.l]) - (rang[b.l] === undefined ? 9 : rang[b.l])) || a.i - b.i; });
  cols.forEach(function(o){          // els idiomes junts (ES, EN, FR, DE); una columna del mateix idioma que l'anterior no repeteix el quadret E/F/D
    var c = o.c; c.removeAttribute('style');
    var m = c.querySelector('.col-lang'); if (m && o.l == ant) m.parentNode.removeChild(m);
    ant = o.l; tx.appendChild(c);
  });
  body.appendChild(fz); body.appendChild(tx);
  pg.insertBefore(body, pg.querySelector('.peu'));
  var asp = fots.map(function(f){ var im = f.tagName == 'IMG' ? f : f.querySelector('img'); return im && im.naturalHeight ? im.naturalWidth / im.naturalHeight : 1; });
  function posa(h){ fots.forEach(function(f, i){ f.style.height = h + 'cm'; f.style.width = Math.min(h * asp[i], 17) + 'cm'; }); }
  function cap(){ return tx.getBoundingClientRect().bottom <= base; }
  if (!fots.length) fz.style.display = 'none';
  var ok = false, sizes = [9.5, 9, 8.5, 8, 7.5, 7];      // lletra preferida: la més gran que càpiga; les fotos baixen fins a 2,4 cm abans de reduir la lletra
  function prova(fs, hmin){ tx.style.fontSize = fs + 'pt'; for (var h = 5.2; h >= hmin - 1e-6; h -= 0.2) { posa(h); if (cap()) return true; } return false; }
  for (var k = 0; k < sizes.length && !ok; k++) ok = prova(sizes[k], 2.4);
  if (!ok) {          // massa text per a 2 columnes a 7 pt: 3 columnes (≥ 5 cm cadascuna)
    tx.style.columnCount = 3;
    for (var k3 = 0; k3 < sizes.length - 2 && !ok; k3++) ok = prova(sizes[k3 + 2], 2.0);
  }
  if (!ok) {          // darrer recurs: 6,5 pt (el mínim absolut), interlineat ajustat i fotos fins a 1,6 cm
    tx.style.fontSize = '6.5pt'; tx.style.lineHeight = '1.08';
    for (var h2 = 2.4; h2 >= 1.6 - 1e-6 && !ok; h2 -= 0.2) { posa(h2); if (cap()) ok = true; }
    if (!ok) posa(1.6);
  }
  if (ok) {          // sobra lloc: es fa créixer la lletra (fins a 10,5 pt) i, si encara sobra, les fotos
    var fsz = parseFloat(tx.style.fontSize);
    while (fsz < 10.5) { tx.style.fontSize = (fsz + 0.25) + 'pt'; if (!cap()) { tx.style.fontSize = fsz + 'pt'; break; } fsz += 0.25; }
    var hh = parseFloat(fots.length ? fots[0].style.height : 0);
    while (fots.length && hh < 7) { posa(hh + 0.2); if (!cap()) { posa(hh); break; } hh += 0.2; }
  }
}
window.addEventListener('load', function(){ FLUID_PGS.forEach(fluid); });

/* Pàgines d'informació en mode «blocs» (.page.blocs): la lletra dels blocs és la més gran que càpiga (6,5-9,5 pt); si ni a 6,5 pt hi cap, les files de fotos s'encongeixen. */
document.querySelectorAll('.page.blocs').forEach(function(pg){
  var cos = pg.querySelector('.bl-cos'), fil = Array.from(pg.querySelectorAll('.bl-fila')), blocs = Array.from(pg.querySelectorAll('.bl-bloc,.bl-text'));
  function cap(){ return cos.scrollHeight <= cos.clientHeight + 1; }
  function fs(pt){ blocs.forEach(function(b){ b.style.fontSize = pt + 'pt'; }); }
  var h0 = fil.map(function(f){ return parseFloat(f.style.height); }), w0 = fil.map(function(f){ return Array.from(f.children).map(function(c){ return parseFloat(c.style.width); }); }), ok = false;
  for (var esc = 1.0; esc >= 0.45 && !ok; esc -= 0.05) {
    fil.forEach(function(f, i){ f.style.height = (h0[i] * esc) + 'cm'; Array.from(f.children).forEach(function(c, k){ c.style.width = (w0[i][k] * esc) + 'cm'; }); });
    for (var pt = 9.5; pt >= 6.5 && !ok; pt -= 0.25) { fs(pt); ok = cap(); }
  }
});
'''
CSS = open(os.path.join(HERE, 'estil.css'), encoding='utf8').read()


def expandeix(p, k):
    if p['tipus'] == 'producte': return parteix_pagina(p, k)
    if p['tipus'] == 'accessoris': return parteix_accessoris(p, k)
    return [p]


def construeix_html(dades, preus, estrenyer=None):
    """estrenyer: {n original: k} pàgines que a la passada anterior es desbordaven (es parteixen més)."""
    estrenyer = estrenyer or {}
    dades = dict(dades, pagines=[q for p in dades['pagines'] for q in expandeix(p, estrenyer.get(p['n'], 0))])
    ctx = Ctx(dades, preus)
    vars_ = ':root{' + ''.join(f'--{k.replace("_", "-")}:{v};' for k, v in ctx.colors.items()) + '}'
    cos = [TIPUS[p['tipus']](ctx, p, i) for i, p in enumerate(dades['pagines'], 1)]
    doc = ('<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Tarifa Eurast - Grupo %s</title><style>%s\n%s</style></head><body>%s<script>%s</script></body></html>'
           % (ctx.grup, vars_, CSS, '\n'.join(cos), AJUST_JS))
    doc = re.sub(r'(TARIFA|PRICE LIST|TARIF) □ ', r'\1 · ', doc)      # portada: separador d'idiomes
    doc = re.sub(r' {2,}', ' ', doc.replace('\u25a1', ''))          # □ = glifo que no existeix (número de referència del .pub): mai ha de sortir al paper
    return doc, ctx


def genera_pdf(html_path, pdf_path):
    perfil = tempfile.mkdtemp(prefix='chrome-', dir=os.path.join(ROOT, 'treball'))       # perfil propi: es poden generar diversos grups alhora
    try:
        cmd = CHROME_ARGS() + ['--no-pdf-header-footer', f'--user-data-dir={perfil}', f'--print-to-pdf={pdf_path}', 'file://' + os.path.abspath(html_path)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    finally:
        shutil.rmtree(perfil, ignore_errors=True)
    if not os.path.exists(pdf_path): raise RuntimeError('Chrome no ha generat el PDF: ' + r.stderr[-500:])


MESURA_JS = r'''<script>window.addEventListener('load', function(){ var CM = 37.795, r = [];
  document.querySelectorAll('.page.producte, .page.accessoris').forEach(function(pg, i){
    var t = pg.getBoundingClientRect().top, lim = t + (29.7 - 1.4) * CM + 2;
    var mal = Array.from(pg.querySelectorAll('.tau tr, .acc-card, .llegenda, .nota-caixa')).some(function(e){ var b = e.getBoundingClientRect(); return b.height > 0 && (b.bottom > lim || b.right > pg.getBoundingClientRect().right + 2); });
    if (mal) r.push(Array.prototype.indexOf.call(document.querySelectorAll('.page'), pg) + 1);
  });
  var pre = document.createElement('pre'); pre.id = 'mesura'; pre.textContent = JSON.stringify(r); document.body.appendChild(pre); });</script>'''


def pagines_desbordades(html_path):
    """Mesura real al Chrome: pàgines (1..N) on alguna fila o targeta passa per sota del peu o fora del full."""
    doc = open(html_path, encoding='utf8').read().replace('</body>', MESURA_JS + '</body>')
    tmp = html_path + '.mesura.html'
    open(tmp, 'w', encoding='utf8').write(doc)
    perfil = tempfile.mkdtemp(prefix='chrome-m-', dir=os.path.join(ROOT, 'treball'))
    try:
        r = subprocess.run(CHROME_ARGS() + [f'--user-data-dir={perfil}', '--window-size=794,1123', '--virtual-time-budget=60000', '--dump-dom',
                                            'file://' + os.path.abspath(tmp)], capture_output=True, text=True, timeout=300)
    finally:
        shutil.rmtree(perfil, ignore_errors=True); os.remove(tmp)
    m = re.search(r'<pre id="mesura">(.*?)</pre>', r.stdout, re.S)
    return json.loads(m.group(1)) if m else []


def renderitza(dades, preus, sortida):
    global BASE
    os.makedirs(os.path.dirname(sortida), exist_ok=True)
    BASE = os.path.relpath(ROOT, os.path.dirname(os.path.abspath(sortida))) + '/'
    estrenyer = {}
    for passada in range(4):
        doc, ctx = construeix_html(dades, preus, estrenyer)
        open(sortida + '.html', 'w', encoding='utf8').write(doc)
        desb = pagines_desbordades(sortida + '.html')
        if not desb: break
        for i in desb:
            n = ctx.pagines[i - 1]['n']
            if ctx.pagines[i - 1]['tipus'] in ('producte', 'accessoris'): estrenyer[n] = estrenyer.get(n, 0) + 1
        if passada == 3 or not any(ctx.pagines[i - 1]['tipus'] in ('producte', 'accessoris') for i in desb):
            ctx.avisos += [f'p{i} (renderitzada): el contingut no hi cap i queda tallat' for i in desb]; break
    if os.path.exists(sortida + '.pdf'): os.remove(sortida + '.pdf')
    genera_pdf(sortida + '.html', sortida + '.pdf')
    posa_pagines_slides(ctx, sortida + '.pdf')
    return ctx


def baixa_slide(sid, ctx, pag):
    """PDF de la diapositiva (export de Google Slides). Funciona sense credencials si la carpeta del Drive és «qualsevol amb l'enllaç
    pot veure»; si no, es fa servir l'última còpia baixada (treball/slides/<id>.pdf) i es deixa un avís."""
    import urllib.request
    dest = os.path.join(ROOT, 'treball', 'slides', f'{sid}.pdf')
    try:
        with urllib.request.urlopen(f'https://docs.google.com/presentation/d/{sid}/export/pdf', timeout=60) as r:
            dades = r.read()
        if dades[:5] == b'%PDF-':
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, 'wb').write(dades)
            return dest
        ctx.avisos.append(f'p{pag}: la diapositiva {sid} no és pública (cal «qualsevol amb l\'enllaç pot veure» a la carpeta); es fa servir la còpia local')
    except Exception as e:
        ctx.avisos.append(f'p{pag}: no s\'ha pogut baixar la diapositiva {sid} ({e}); es fa servir la còpia local')
    return dest if os.path.exists(dest) else None


def posa_pagines_slides(ctx, pdf):
    """Pàgines dissenyades a Google Slides (slides-pagines.yaml: grup -> {pàgina renderitzada: id de la presentació}).
    El PDF de la diapositiva substitueix aquella pàgina tal qual; el peu (data, número de pàgina, enllaç) el posa el generador
    al damunt, perquè quedi bé encara que la pàgina canviï de lloc. Tots els peus d'un grup es fan en UNA sola execució de Chrome."""
    if SENSE_SLIDES: return
    cfg_p = os.path.join(ROOT, 'slides-pagines.yaml')
    if not os.path.exists(cfg_p): return
    mapa = (yaml.safe_load(open(cfg_p, encoding='utf8')) or {}).get(ctx.grup) or {}
    if not mapa: return
    html_p = pdf[:-4] + '.html'
    cap = open(html_p, encoding='utf8').read().split('<body', 1)[0]
    fetes = []
    for pag, sid in sorted(mapa.items(), key=lambda x: -int(x[0])):
        pag = int(pag)
        src = baixa_slide(sid, ctx, pag)
        if not src:
            ctx.avisos.append(f'p{pag}: no hi ha el PDF de la diapositiva {sid}; es deixa la pàgina generada'); continue
        tmp = pdf + '.tmp.pdf'
        parts = ([pdf, f'1-{pag - 1}'] if pag > 1 else []) + [src, '1'] + [pdf, f'{pag + 1}-z']
        r = subprocess.run(['qpdf', '--empty', '--pages'] + parts + ['--', tmp], capture_output=True, text=True)
        if r.returncode not in (0, 3):
            ctx.avisos.append(f'p{pag}: no s\'ha pogut posar la diapositiva ({r.stderr.strip()[:200]})'); continue
        os.replace(tmp, pdf)
        fetes.append(pag)
    if not fetes: return
    fetes.sort()
    peus = ''.join('<div class="page" style="background:transparent !important;page-break-after:always">'
                   '<div style="position:absolute;left:0;bottom:0;width:21cm;height:1.45cm;background:#fff"></div>'
                   + peu(ctx, ctx.pagines[p - 1], p) + '</div>' for p in fetes)
    sob_html = pdf[:-4] + '.peus.html'; sob_pdf = pdf[:-4] + '.peus.pdf'
    open(sob_html, 'w', encoding='utf8').write(cap + '<body><style>html,body{background:transparent !important}</style>' + peus + '</body></html>')
    genera_pdf(sob_html, sob_pdf)
    tmp = pdf + '.tmp.pdf'
    r = subprocess.run(['qpdf', pdf, '--overlay', sob_pdf, '--from=1-' + str(len(fetes)), '--to=' + ','.join(map(str, fetes)), '--', tmp], capture_output=True, text=True)
    if r.returncode in (0, 3): os.replace(tmp, pdf)
    else: ctx.avisos.append(f'no s\'han pogut posar els peus de les diapositives ({r.stderr.strip()[:200]})')
    for f in (sob_html, sob_pdf):
        if os.path.exists(f): os.remove(f)


def prepara(a):
    """Retorna (dades, preus, font, avisos_composicio)."""
    import font_odoo as FO
    grup = a.grup
    dades = U.carrega_dades(grup)
    cfg = FO.carrega_config(grup)
    lect = None
    cache = os.path.join(ROOT, 'treball', f'estat_odoo_g{grup}.json')
    if a.estat:
        estat = json.load(open(a.estat, encoding='utf8')); font = f'estat simulat ({a.estat})'
    elif a.cache_estat:
        estat = json.load(open(cache, encoding='utf8')); font = f'Odoo (cache {estat["llegit"]})'
    else:
        from odoo_w import crida_lectura as lect
        extra = [r['codi'] for lst in cfg['repeticions'].values() for r in lst]
        estat = FO.llegeix_estat(cfg['grup']['codi_odoo'], lect, extra); font = 'Odoo Staging en viu (lectura)'
        import pagines_odoo as PG
        estat['pagines'] = PG.llegeix_pagines(lect, cfg['grup']['codi_odoo'])                 # pàgines genèriques d'Odoo (x_cataleg_pagina), amb les imatges baixades
        estat['n_fotos_odoo'] = PG.imatges_catalog_productes(lect, estat['productes'])         # fotos de catàleg (x_cataleg_imatge) dels productes
        pw = [p['write_date'] for p in estat['pagines'] if p.get('write_date')] + [i['write_date'] for p in estat['pagines'] for i in p['imatges'] if i.get('write_date')]
        if pw: estat['data_edicio_auto'] = max([estat.get('data_edicio_auto') or ''] + [w[:7].replace('-', '/') for w in pw])
        json.dump(estat, open(cache, 'w', encoding='utf8'), indent=1, ensure_ascii=False)
    if not estat['productes'] or not estat['families']:
        return None, None, font, [], estat
    d2, preus, avisos = FO.compon(dades, estat, cfg, grup, lect if not (a.estat or a.cache_estat) else None, a.pagines)
    data, origen = a.data, 'forçada (--data)'
    if not data and estat.get('data_edicio_auto'): data, origen = estat['data_edicio_auto'], "última modificació de les dades del grup a Odoo"
    if not data: data, origen = dades['grup']['data_edicio'], f'la del .pub (gN.yaml): {"estat sense write_date" if (a.estat or a.cache_estat) else "Odoo no en dóna"}'
    d2['grup'] = dict(d2['grup'], data_edicio=data)
    font += f' | data d\'edició {data} ({origen})'
    for o in a.preu:
        k, v = o.split('='); preus[k] = float(v.replace(',', '.')); font += f' + simulat {k}={v}'
    for o in a.sense:       # simula desmarcar un producte (en memòria)
        pass
    return d2, preus, font, avisos, estat


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--grup', type=int, required=True, help='número de grup (G01..G16); cal dades/gN-config.yaml (scripts/genera_config.py) i el grup carregat a Odoo')
    ap.add_argument('--data', default=None, metavar='AAAA/MM', help="força la data d'edició (peus i segell de portada)")
    ap.add_argument('--sortida', default=None, help='ruta sense extensió (defecte: sortida/gN)')
    ap.add_argument('--estat', default=None, help="JSON amb un estat d'Odoo (simulació en memòria, no llegeix Odoo)")
    ap.add_argument('--cache-estat', action='store_true', help="usa l'última lectura d'Odoo (treball/estat_odoo_gN.json)")
    ap.add_argument('--preu', action='append', default=[], help='CODI=VALOR (simula un canvi de preu a Odoo, en memòria)')
    ap.add_argument('--sense', action='append', default=[], help=argparse.SUPPRESS)
    ap.add_argument('--capcalera', choices=['text', 'icona'], default='text',
                    help="text (defecte): nom de la columna + icona estàndard petita opcional; icona: mode antic (només la icona d'Odoo)")
    ap.add_argument('--idioma', choices=['es', 'en', 'fr'], default='es', help='idioma del nom a les capçaleres de columna (defecte es)')
    ap.add_argument('--pagines', choices=['odoo', 'yaml'], default='odoo',
                    help="odoo (defecte): pàgines genèriques i fotos de producte d'Odoo si n'hi ha per al grup; yaml: les de dades/gN.yaml (comportament antic)")
    ap.add_argument('--llegenda', choices=['auto', 'fixa'], default='auto',
                    help='auto (defecte): la pàgina de simbologia es genera de les columnes del grup; fixa: la de gN.yaml')
    ap.add_argument('--sense-slides', action='store_true', help='no posa les diapositives de Google Slides (slides-pagines.yaml): genera la pàgina objectiu del codi')
    a = ap.parse_args(argv)
    global SENSE_SLIDES
    SENSE_SLIDES = a.sense_slides
    OPC.update(capcalera=a.capcalera, idioma=a.idioma, llegenda=a.llegenda)
    sortida = a.sortida or os.path.join(ROOT, 'sortida', f'g{a.grup}')
    if a.data and not re.fullmatch(r'\d{4}/(0[1-9]|1[0-2])', a.data): raise SystemExit('--data ha de ser AAAA/MM (p. ex. 2026/10)')
    dades, preus, font, avisos, estat = prepara(a)
    if dades is None:
        print(f"Grup {a.grup} | {font}\nNo hi ha cap producte marcat al catàleg (x_cataleg) a Odoo per al grup G{a.grup:02d}: no es genera cap PDF.\n"
              f"  Per carregar-lo: python3 scripts/genera_config.py --grup {a.grup}; python3 scripts/carrega_grup.py --grup {a.grup} (dry-run) i després --aplica.")
        return None
    ctx = renderitza(dades, preus, sortida)
    print(f'Grup {a.grup} | {font}\nHTML: {sortida}.html\nPDF:  {sortida}.pdf')
    for av in sorted(set(avisos + ctx.avisos)): print('AVIS:', av)
    return ctx


if __name__ == '__main__':
    main()
