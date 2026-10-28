#!/usr/bin/env python3
"""Comprova si el PDF exportat de cada diapositiva de Google Slides és fidel a la pàgina objectiu generada pel codi.

Ús:
  python3 scripts/compara_slides.py --grup 8                 # totes les pàgines de slides-pagines.yaml del grup
  python3 scripts/compara_slides.py --grup 8 --pagina 5 --pagina 9
  python3 scripts/compara_slides.py --grup 8 --regenera      # torna a generar l'objectiu (renderitza.py --sense-slides)
  python3 scripts/compara_slides.py --grup 8 --objectiu X.pdf  # objectiu ja generat sense diapositives

L'objectiu (pàgina del grup renderitzada pel codi SENSE Slides) es genera amb
  renderitza.py --grup N --cache-estat --sense-slides --sortida /private/tmp/claude-501/obj/gN/gN
i es reutilitza si ja hi és (--regenera el força). No toca Odoo (usa la cache d'estat), ni Drive, ni git.
El PDF de la diapositiva és treball/slides/<id>.pdf (el que ha baixat renderitza.py l'última vegada).

Comprovacions per pàgina:
  TEXT   paraules que falten o sobren (text net, sense majúscules ni puntuació, sense peu)
  ALÇADA alçada de cada columna de text (centre primera -> última línia) vs objectiu, i desplaçament de l'última línia
  MARGE  última línia per sota del límit del peu / tallada pel full
  FOTO   línies de text que trepitgen una foto (i que a l'objectiu no la trepitjaven)
  SOBRE  paraules que se sobreposen amb altres paraules (i que a l'objectiu no)
  VISUAL diferència a 40 ppp en gris per blocs de 8x8; guarda /private/tmp/claude-501/diff/gN-pNN.png (objectiu | Slides | diferències)
Exit code 1 si hi ha cap AVIS.
"""
import argparse, collections, os, re, shutil, subprocess, sys, tempfile, unicodedata
import yaml
from PIL import Image, ImageChops, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLIDES_DIR = os.path.join(ROOT, 'treball', 'slides')
OBJ_BASE = '/private/tmp/claude-501/obj'
DIFF_DIR = '/private/tmp/claude-501/diff'
PY = sys.executable

# ---- llindars (calibrats sobre G8; vegeu l'informe) ----
PEU_Y = 800.0            # pt: per sota d'aquesta y hi va el peu del generador (data, número, logo) -> s'ignora
MARGE_BAIX = 802.0       # pt: l'última línia de text no ha de passar d'aquí (1,4 cm de marge inferior)
T_TEXT_ABS = 2           # paraules que difereixen (falten + sobren) a partir de les quals hi ha AVIS
T_DH_CURT = 35.0         # pt: una columna MÉS CURTA que l'objectiu només és sospitosa si ho és molt (no trepitja res; pot ser text perdut)
T_DH_PT = 6.0            # pt: diferència d'alçada de columna (o desplaçament de la darrera línia) tolerada
T_BLOC = 45.0            # diferència mitjana (0-255) d'un bloc 8x8 perquè es consideri «gran»
T_BLOCS_PCT = 5.0        # % de blocs grans (de l'àrea sense peu) a partir del qual hi ha AVIS visual
T_IOU_FOTO = 0.75        # una foto de Slides ha de solapar-se almenys així (IoU) amb alguna foto de l'objectiu
T_FOTO_LINIES = 1        # línies de text trepitjant foto (de més que a l'objectiu) per avisar
SOBRE_MIN = 0.35         # fracció de l'àrea de la paraula més petita per considerar solapament


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------- lectura de PDF
WORD_RE = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
LINE_RE = re.compile(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', re.S)
PAGE_RE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S)


def un_esc(s):
    return s.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'").replace('&amp;', '&')


def llegeix_pagina(pdf, pag):
    """-> dict(w, h, linies=[(x0,y0,x1,y1,[paraules])], paraules=[(x0,y0,x1,y1,text)])"""
    r = sh(['pdftotext', '-bbox-layout', '-f', str(pag), '-l', str(pag), pdf, '-'])
    m = PAGE_RE.search(r.stdout)
    if not m: return dict(w=595.0, h=842.0, linies=[], paraules=[])
    w, h, cos = float(m.group(1)), float(m.group(2)), m.group(3)
    linies, paraules = [], []
    for lm in LINE_RE.finditer(cos):
        ps = [(float(a), float(b), float(c), float(d), un_esc(t)) for a, b, c, d, t in WORD_RE.findall(lm.group(5))]
        if not ps: continue
        linies.append((float(lm.group(1)), float(lm.group(2)), float(lm.group(3)), float(lm.group(4)), ps))
        paraules += ps
    return dict(w=w, h=h, linies=linies, paraules=paraules)


def imatges_pagina(pdf, pag):
    """Caixes (x0,y0,x1,y1) en pt de les imatges de la pàgina (pdftohtml -xml)."""
    d = tempfile.mkdtemp(prefix='cmpimg-')
    try:
        sh(['pdftohtml', '-xml', '-f', str(pag), '-l', str(pag), '-q', pdf, os.path.join(d, 'x')])
        xml = open(os.path.join(d, 'x.xml'), encoding='utf8', errors='replace').read() if os.path.exists(os.path.join(d, 'x.xml')) else ''
    finally:
        shutil.rmtree(d, ignore_errors=True)
    m = re.search(r'<page [^>]*height="([\d.]+)" width="([\d.]+)"', xml)
    if not m: return []
    esc = float(m.group(2)) / 595.0
    out = []
    for t, l, w, h in re.findall(r'<image top="(-?\d+)" left="(-?\d+)" width="(\d+)" height="(\d+)"', xml):
        t, l, w, h = float(t) / esc, float(l) / esc, float(w) / esc, float(h) / esc
        out.append((l, t, l + w, t + h))
    return out


# ---------------------------------------------------------------- comprovacions
def tokens(paraules, peu_y=PEU_Y):
    out = []
    for x0, y0, x1, y1, t in paraules:
        if (y0 + y1) / 2 > peu_y: continue
        out += re.findall(r'\w+', unicodedata.normalize('NFKC', t).lower())      # NFKC: ① -> 1
    return out


def comprova_text(o, s):
    co, cs = collections.Counter(tokens(o['paraules'])), collections.Counter(tokens(s['paraules']))
    falten, sobren = co - cs, cs - co
    nf, ns = sum(falten.values()), sum(sobren.values())
    msg = []
    if nf + ns >= T_TEXT_ABS:
        if nf: msg.append('falten ' + ', '.join(f'{w}' + (f'x{n}' if n > 1 else '') for w, n in list(falten.items())[:8]) + (' ...' if len(falten) > 8 else ''))
        if ns: msg.append('sobren ' + ', '.join(f'{w}' + (f'x{n}' if n > 1 else '') for w, n in list(sobren.items())[:8]) + (' ...' if len(sobren) > 8 else ''))
    return ('TEXT: ' + '; '.join(msg)) if msg else None, nf, ns


def columnes(linies, ample):
    """Agrupa les línies en columnes per unió d'intervals horitzontals. Retorna [{x0,x1,l:[(cy,y0,y1)]}] ordenades per x.
    Ignora capçalera (y<45) i peu (y>PEU_Y)."""
    cand = [(l[0], l[2], (l[1] + l[3]) / 2, l[1], l[3]) for l in linies if 45 < (l[1] + l[3]) / 2 < PEU_Y]
    cols = []
    for x0, x1, cy, y0, y1 in sorted(cand):
        for c in cols:
            if x0 < c['x1'] - 2 and x1 > c['x0'] + 2:
                c['x0'], c['x1'] = min(c['x0'], x0), max(c['x1'], x1); c['l'].append((cy, y0, y1)); break
        else:
            cols.append(dict(x0=x0, x1=x1, l=[(cy, y0, y1)]))
    # una columna pot haver quedat partida per l'ordre: refon les que se solapen
    canvi = True
    while canvi:
        canvi = False
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                a, b = cols[i], cols[j]
                if a['x0'] < b['x1'] - 2 and a['x1'] > b['x0'] + 2:
                    a['x0'], a['x1'] = min(a['x0'], b['x0']), max(a['x1'], b['x1']); a['l'] += b['l']; del cols[j]; canvi = True; break
            if canvi: break
    for c in cols:
        c['l'].sort(); c['top'] = c['l'][0][0]; c['bot'] = c['l'][-1][0]; c['n'] = len(c['l'])
    return sorted(cols, key=lambda c: c['x0'])


def comprova_alcada(o, s):
    co, cs = columnes(o['linies'], o['w']), columnes(s['linies'], s['w'])
    msgs, dmax = [], 0.0
    usats = set()
    for c in co:
        # columna de Slides que més se solapa horitzontalment
        millor, mo = None, 0
        for k, d in enumerate(cs):
            ov = min(c['x1'], d['x1']) - max(c['x0'], d['x0'])
            if ov > mo: millor, mo = k, ov
        if millor is None or mo < 0.4 * (c['x1'] - c['x0']):
            msgs.append(f'ALÇADA: la columna x={c["x0"]:.0f}-{c["x1"]:.0f} de l\'objectiu no existeix a Slides'); continue
        usats.add(millor); d = cs[millor]
        dh = (d['bot'] - d['top']) - (c['bot'] - c['top'])
        dbot = d['bot'] - c['bot']; dtop = d['top'] - c['top']
        dmax = max(dmax, abs(dh), abs(dbot))
        if dh > T_DH_PT or dbot > T_DH_PT or dh < -T_DH_CURT or dbot < -T_DH_CURT:
            msgs.append(f'ALÇADA: columna x={c["x0"]:.0f}-{c["x1"]:.0f}: dH={dh:+.1f}pt, última línia {dbot:+.1f}pt, primera {dtop:+.1f}pt, línies {c["n"]}->{d["n"]}')
    for k, d in enumerate(cs):
        if k not in usats and not any(min(c['x1'], d['x1']) - max(c['x0'], d['x0']) > 0 for c in co):
            msgs.append(f'ALÇADA: columna extra a Slides x={d["x0"]:.0f}-{d["x1"]:.0f} ({d["n"]} línies)')
    return msgs, dmax


def comprova_marge(s):
    msgs = []
    ys = [l[3] for l in s['linies'] if (l[1] + l[3]) / 2 < PEU_Y + 15]            # yMax de les línies que no són del peu
    cy = [(l[1] + l[3]) / 2 for l in s['linies'] if 45 < (l[1] + l[3]) / 2]
    # línia de text que passa del full
    for l in s['linies']:
        if l[3] > s['h'] + 0.5: msgs.append(f'TALLADA: la línia «{" ".join(p[4] for p in l[4])[:40]}» surt per sota del full (yMax={l[3]:.0f} > {s["h"]:.0f})')
    # text del cos dins la franja del peu
    dins = [l for l in s['linies'] if PEU_Y < (l[1] + l[3]) / 2 and l[3] <= s['h'] + 0.5
            and not re.match(r'Grupo \d+ - ', ' '.join(p[4] for p in l[4]))]
    if dins:
        t = ' '.join(p[4] for l in dins for p in l[4])[:60]
        msgs.append(f'MARGE: hi ha text a la franja del peu (y>{PEU_Y:.0f}): «{t}»')
    return msgs


def inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0]); h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def linies_sobre_fotos(pag, imgs):
    """Línies del cos amb caixa (reduïda en vertical) que se solapa amb alguna foto. Ignora les fotos del peu o minúscules."""
    fots = [i for i in imgs if (i[2] - i[0]) * (i[3] - i[1]) > 1500 and (i[1] + i[3]) / 2 < PEU_Y and i[3] > 60]
    res = []
    for x0, y0, x1, y1, ps in pag['linies']:
        cy = (y0 + y1) / 2
        if not (45 < cy < PEU_Y + 15): continue
        caixa = (x0, cy - 3.5, x1, cy + 3.5)
        for k, f in enumerate(fots):
            fi = (f[0] + 2, f[1] + 2, f[2] - 2, f[3] - 2)
            if inter(caixa, fi) > 0.25 * (caixa[2] - caixa[0]) * (caixa[3] - caixa[1]):
                res.append((' '.join(p[4] for p in ps)[:30], k)); break
    return res


def fotos_grans(imgs):
    return [i for i in imgs if (i[2] - i[0]) * (i[3] - i[1]) > 1500 and (i[1] + i[3]) / 2 < PEU_Y and i[3] > 60]


def iou(a, b):
    i = inter(a, b)
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i) if i else 0.0


def comprova_geom_fotos(io, is_):
    fo, fs = fotos_grans(io), fotos_grans(is_)
    msgs = []
    if len(fo) != len(fs): msgs.append(f'FOTO: {len(fs)} fotos a Slides i {len(fo)} a l\'objectiu')
    for k, f in enumerate(fs):
        m = max([iou(f, g) for g in fo] or [0])
        if m < T_IOU_FOTO:
            msgs.append(f'FOTO: la foto {k + 1} de Slides (x={f[0]:.0f}-{f[2]:.0f}, y={f[1]:.0f}-{f[3]:.0f}, {f[2]-f[0]:.0f}x{f[3]-f[1]:.0f}pt) no coincideix amb cap de l\'objectiu (IoU {m:.2f})')
    return msgs


def comprova_fotos(o, s, io, is_):
    lo, ls = linies_sobre_fotos(o, io), linies_sobre_fotos(s, is_)
    extra = len(ls) - len(lo)
    if extra >= T_FOTO_LINIES:
        return f'FOTO: {len(ls)} línies de text trepitgen foto (objectiu: {len(lo)}), p. ex. «{ls[0][0]}»'
    return None


def comprova_sobre(o, s):
    def n(pag):
        ps = [p for p in pag['paraules'] if 45 < (p[1] + p[3]) / 2 < PEU_Y]
        c = 0
        for i in range(len(ps)):
            a = ps[i]; ca = (a[0], (a[1] + a[3]) / 2 - 3, a[2], (a[1] + a[3]) / 2 + 3)
            for j in range(i + 1, len(ps)):
                b = ps[j]; cb = (b[0], (b[1] + b[3]) / 2 - 3, b[2], (b[1] + b[3]) / 2 + 3)
                m = min((ca[2] - ca[0]) * (ca[3] - ca[1]), (cb[2] - cb[0]) * (cb[3] - cb[1]))
                if m > 0 and inter(ca, cb) / m > SOBRE_MIN: c += 1
        return c
    no, ns = n(o), n(s)
    return f'SOBRE: {ns} paraules se sobreposen amb d\'altres (objectiu: {no})' if ns - no >= 1 else None


# ---------------------------------------------------------------- comparació visual
def renderitza_gris(pdf, pag, dest_pre):
    sh(['pdftoppm', '-gray', '-r', '40', '-png', '-f', str(pag), '-l', str(pag), pdf, dest_pre])
    for f in os.listdir(os.path.dirname(dest_pre)):
        if f.startswith(os.path.basename(dest_pre)) and f.endswith('.png'):
            return Image.open(os.path.join(os.path.dirname(dest_pre), f)).convert('L')
    raise RuntimeError('pdftoppm no ha generat la imatge de ' + pdf)


def comprova_visual(opdf, opag, spdf, g, pag, desa):
    d = tempfile.mkdtemp(prefix='cmpvis-')
    try:
        io = renderitza_gris(opdf, opag, os.path.join(d, 'o'))
        i_s = renderitza_gris(spdf, 1, os.path.join(d, 's')).resize(io.size, Image.BILINEAR)
        W, H = io.size
        hpeu = int(PEU_Y / 841.92 * H)
        io2, is2 = io.crop((0, 0, W, hpeu)), i_s.crop((0, 0, W, hpeu))
        bw, bh = W // 8, hpeu // 8
        # mitjana de cada bloc 8x8 de cada imatge (densitat de tinta) i diferència entre les dues: tolera desplaçaments d'1-2 px del text
        bo, bs = io2.resize((bw, bh), Image.BOX), is2.resize((bw, bh), Image.BOX)
        blocs = ImageChops.difference(bo, bs)
        vals = list(blocs.tobytes())
        grans = [i for i, v in enumerate(vals) if v > T_BLOC]
        pct = 100.0 * len(grans) / len(vals)
        mitja = sum(vals) / len(vals)
        avis = pct > T_BLOCS_PCT
        if avis and desa:
            os.makedirs(DIFF_DIR, exist_ok=True)
            hm = Image.new('RGB', (W, hpeu), 'white')
            px = hm.load(); g_px = io2.load()
            for y in range(hpeu):
                for x in range(W):
                    v = g_px[x, y]; px[x, y] = (v, v, v)
            dr = ImageDraw.Draw(hm, 'RGBA')
            for i in grans:
                bx, by = (i % bw) * 8, (i // bw) * 8
                dr.rectangle([bx, by, bx + 7, by + 7], fill=(255, 0, 0, 110))
            out = Image.new('RGB', (W * 3 + 20, hpeu), 'white')
            out.paste(io2.convert('RGB'), (0, 0)); out.paste(is2.convert('RGB'), (W + 10, 0)); out.paste(hm, (2 * W + 20, 0))
            out.save(os.path.join(DIFF_DIR, f'g{g}-p{pag:02d}.png'))
        return (f'VISUAL: {pct:.1f}% de blocs 8x8 amb diferència gran (mitjana {mitja:.1f}/255)' if avis else None), pct, mitja
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- objectiu
def assegura_objectiu(g, regenera, objectiu):
    if objectiu: return objectiu
    sortida = os.path.join(OBJ_BASE, f'g{g}', f'g{g}')
    pdf = sortida + '.pdf'
    if regenera or not os.path.exists(pdf):
        os.makedirs(os.path.dirname(sortida), exist_ok=True)
        print(f'Generant l\'objectiu de G{g} sense diapositives (renderitza.py --sense-slides)...', file=sys.stderr)
        r = subprocess.run([PY, os.path.join(ROOT, 'scripts', 'renderitza.py'), '--grup', str(g), '--cache-estat', '--sense-slides', '--sortida', sortida],
                           capture_output=True, text=True, cwd=ROOT)
        if not os.path.exists(pdf): raise SystemExit('No s\'ha pogut generar l\'objectiu:\n' + r.stdout[-800:] + r.stderr[-800:])
    return pdf


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--grup', type=int, required=True)
    ap.add_argument('--pagina', type=int, action='append', default=[], help='només aquestes pàgines (defecte: totes les del mapa)')
    ap.add_argument('--regenera', action='store_true', help="torna a generar l'objectiu")
    ap.add_argument('--objectiu', default=None, help="PDF objectiu ja generat sense diapositives")
    ap.add_argument('--detall', action='store_true', help='mostra també les mètriques de les pàgines OK')
    a = ap.parse_args(argv)
    mapa = (yaml.safe_load(open(os.path.join(ROOT, 'slides-pagines.yaml'), encoding='utf8')) or {}).get(a.grup) or {}
    pags = sorted(int(p) for p in mapa if not a.pagina or int(p) in a.pagina)
    if not pags: raise SystemExit(f'Cap pàgina a slides-pagines.yaml per al grup {a.grup}')
    opdf = assegura_objectiu(a.grup, a.regenera, a.objectiu)
    n_avis = 0
    print(f'Grup {a.grup} | objectiu {opdf}\n')
    print(f'{"pàg":>3}  {"estat":<5} detall')
    for p in pags:
        sid = mapa[p] if p in mapa else mapa[str(p)]
        spdf = os.path.join(SLIDES_DIR, f'{sid}.pdf')
        if not os.path.exists(spdf):
            print(f'{p:>3}  AVIS  no hi ha el PDF de la diapositiva {sid}'); n_avis += 1; continue
        o, s = llegeix_pagina(opdf, p), llegeix_pagina(spdf, 1)
        avisos = []
        t, nf, ns = comprova_text(o, s)
        if t: avisos.append(t)
        am, dmax = comprova_alcada(o, s); avisos += am
        avisos += comprova_marge(s)
        io_, is_ = imatges_pagina(opdf, p), imatges_pagina(spdf, 1)
        f = comprova_fotos(o, s, io_, is_)
        if f: avisos.append(f)
        avisos += comprova_geom_fotos(io_, is_)
        sb = comprova_sobre(o, s)
        if sb: avisos.append(sb)
        v, pct, mitja = comprova_visual(opdf, p, spdf, a.grup, p, True)
        if v: avisos.append(v + f' -> {DIFF_DIR}/g{a.grup}-p{p:02d}.png')
        if avisos:
            n_avis += 1
            print(f'{p:>3}  AVIS  ' + avisos[0])
            for x in avisos[1:]: print(f'{"":>10}' + x)
        else:
            extra = f' (text {nf}+{ns}, dH màx {dmax:.1f}pt, blocs grans {pct:.1f}%, dif {mitja:.1f})' if a.detall else ''
            print(f'{p:>3}  OK{extra}')
    print(f'\nResum: {len(pags) - n_avis} OK, {n_avis} AVIS de {len(pags)} pàgines')
    sys.exit(1 if n_avis else 0)


if __name__ == '__main__':
    main()
