#!/usr/bin/env python3
"""Recorts EXACTS de les fotos de les pàgines d'informació, llegits directament del PDF de la tarifa original (sense template matching).

Cada foto d'una pàgina d'informació del PDF original és un bitmap col·locat amb una matriu (cm) i retallat per un rectangle (`re W n`) al flux de la pàgina.
Aquí s'interpreta el flux (q/Q/cm/re/W n/Do), de cada imatge es treu el rectangle visible en fraccions del bitmap, i s'enllaça amb l'asset de gN.yaml
comparant el bitmap incrustat del PDF amb l'asset (dHash 17x16, exacte per a la mateixa imatge) DINS de les pàgines del grup. Res d'escales ni correlacions.
Sortida: dades/recorts-original.yaml  {sha1 asset: {rect, dh, ar, font, pdf_pag, w_cm, h_cm}}  (w_cm/h_cm = mida del marc visible a l'original, per posar la foto a la mateixa mida).
recorta_pub() (renderitza.py) el consulta primer; si una foto no hi és, cau al comportament anterior (dades/recorts-fotos.yaml).
Ús (venv amb pymupdf, pillow, pyyaml): python scripts/recorts_original.py [--grup N ...] [--llista]
"""
import argparse, hashlib, io, os, re, sys
import fitz, yaml
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
PDF = os.path.expanduser('~/dev/tarifa-nova/cataleg_original_web.pdf')
COVER = {1: 2, 2: 47, 3: 65, 4: 93, 5: 151, 6: 207, 7: 248, 8: 286, 9: 342, 10: 391, 11: 425, 12: 498, 13: 590, 14: 662, 15: 733, 16: 817}
FI = 862
OUT = os.path.join(ROOT, 'dades', 'recorts-original.yaml')
PT_CM = 2.54 / 72


def mm(a, b):   # a·b (matrius PDF [a b c d e f])
    return (a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3], a[2]*b[0]+a[3]*b[2], a[2]*b[1]+a[3]*b[3], a[4]*b[0]+a[5]*b[2]+b[4], a[4]*b[1]+a[5]*b[3]+b[5])


def ap(m, x, y): return (m[0]*x + m[2]*y + m[4], m[1]*x + m[3]*y + m[5])


def imatges_pagina(doc, pg):
    """-> [(xref, matriu, clip (x0,y0,x1,y1) o None)] de les imatges que dibuixa el flux de la pàgina (coordenades PDF, y cap amunt)."""
    noms = {e[7]: e[0] for e in pg.get_images(full=True)}
    c = pg.read_contents().decode('latin1')
    tok = re.findall(r'\[.*?\]|\(.*?\)|<[0-9A-Fa-f]*>|/[^\s/\[\]()<>]+|[^\s/\[\]()<>]+', c, flags=re.S)
    pila, ctm, clip, nums, pend, out = [], (1, 0, 0, 1, 0, 0), None, [], None, []
    for t in tok:
        if re.fullmatch(r'-?\d*\.?\d+', t): nums.append(float(t)); continue
        if t == 'q': pila.append((ctm, clip))
        elif t == 'Q':
            if pila: ctm, clip = pila.pop()
        elif t == 'cm' and len(nums) >= 6: ctm = mm(tuple(nums[-6:]), ctm)
        elif t == 're' and len(nums) >= 4:
            x, y, w, h = nums[-4:]; pts = [ap(ctm, x, y), ap(ctm, x+w, y+h)]
            pend = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        elif t == 'W' or t == 'W*':
            if pend:
                clip = pend if clip is None else (max(clip[0], pend[0]), max(clip[1], pend[1]), min(clip[2], pend[2]), min(clip[3], pend[3]))
        elif t in ('n', 'f', 'S', 's', 'B', 'b', 'f*'): pend = None
        elif t == 'Do' and prev and prev.startswith('/'):
            nm = prev[1:]
            if nm in noms: out.append((noms[nm], ctm, clip))
        if t not in ('Do',) : prev = t
        if not re.fullmatch(r'-?\d*\.?\d+', t) and t not in ('W', 'W*') and not t.startswith('/'): nums = []
    return out


prev = None


def dhash(im):
    im = im.convert('RGBA'); g = Image.alpha_composite(Image.new('RGBA', im.size, (255, 255, 255, 255)), im).convert('L').resize((17, 16))
    px = list(g.get_flattened_data() if hasattr(g, 'get_flattened_data') else g.getdata()); bits = 0
    for r in range(16):
        for c in range(16): bits = (bits << 1) | (px[r * 17 + c] > px[r * 17 + c + 1])
    return f'{bits:064x}'


def bitmap(doc, xref):
    pm = fitz.Pixmap(doc, xref)
    if pm.alpha or pm.colorspace is None or pm.colorspace.n not in (1, 3): pm = fitz.Pixmap(fitz.csRGB, pm)
    return Image.open(io.BytesIO(pm.tobytes('png')))


def rect_visible(ctm, clip):
    """Rectangle visible del bitmap (fraccions, y cap avall) i mida del marc (cm), o None si no hi ha retall coherent."""
    a, b, c, d, e, f = ctm
    if abs(b) > 1e-6 or abs(c) > 1e-6 or a <= 0 or d == 0: return None          # només imatges sense rotació
    x0, x1 = e, e + a; y0, y1 = sorted((f, f + d))
    cx0, cy0, cx1, cy1 = clip if clip else (x0, y0, x1, y1)
    vx0, vx1 = max(x0, cx0), min(x1, cx1); vy0, vy1 = max(y0, cy0), min(y1, cy1)
    if vx1 - vx0 < 2 or vy1 - vy0 < 2: return None
    fx0, fx1 = (vx0 - x0) / a, (vx1 - x0) / a
    ftop, fbot = (y1 - vy1) / (y1 - y0), (y1 - vy0) / (y1 - y0)       # y PDF cap amunt -> fracció des de dalt
    if d < 0: ftop, fbot = 1 - fbot, 1 - ftop
    return [round(v, 4) for v in (fx0, ftop, fx1, fbot)], round((vx1 - vx0) * PT_CM, 2), round((vy1 - vy0) * PT_CM, 2)


def dades(g):
    p = os.path.join(ROOT, 'dades', f'g{g}.yaml')
    if not os.path.exists(p): p = os.path.join(ROOT, '..', 'grups', 'dades', f'g{g}.yaml')
    return yaml.safe_load(open(p, encoding='utf8'))


def assets_info(g):
    """[(ruta absoluta, nom, pag yaml, pos del marc a gN.yaml)] de les fotos de les pàgines d'informació del grup (sense repeticions)."""
    r, vist = [], set()
    for p in dades(g)['pagines']:
        if p.get('tipus') != 'informacio_general': continue
        for f in p.get('fotos', []) or []:
            a = os.path.join(ROOT, f['asset'])
            if os.path.exists(a) and not a.lower().endswith('.emf') and a not in vist:
                vist.add(a); r.append((a, os.path.basename(f['asset']), p.get('n'), f.get('pos')))
    return r


_GC = {}


def gris(im, long):
    import numpy as np
    k0 = (id(im), long)
    if k0 in _GC: return _GC[k0][1]
    _GC[k0] = (im, _gris(im, long)); return _GC[k0][1]      # es guarda l'objecte: si no, id() es reutilitza i torna el gris d'una altra imatge


def _gris(im, long):
    import numpy as np
    im = im.convert('RGBA'); g = Image.alpha_composite(Image.new('RGBA', im.size, (255, 255, 255, 255)), im).convert('L')
    k = long / max(g.size); g = g.resize((max(8, round(g.width * k)), max(8, round(g.height * k))), Image.LANCZOS)
    return np.array(g)


def troba(asset, bm, long=120, refina=False):
    """Posició del bitmap del PDF (que és un retall de la foto) dins l'asset: -> (puntuació, [x0,y0,x1,y1] fraccions de l'asset).
    Les dues imatges són la MATEIXA foto (no hi ha pàgina ni marc pel mig): només cal trobar el retall i la seva escala."""
    import cv2, numpy as np
    A = gris(asset, 200 if refina else long); H, W = A.shape
    T0 = gris(bm, 300 if refina else 120); th0, tw0 = T0.shape
    best = (-1, None)
    f = 0.12
    while f <= 1.0001:
        w = max(8, round(f * W)); h = round(w * th0 / tw0)
        if 8 <= h <= H and w <= W:
            T = cv2.resize(T0, (w, h), interpolation=cv2.INTER_AREA)
            if T.std() > 3:
                r = cv2.matchTemplate(A, T, cv2.TM_CCOEFF_NORMED); _, mx, _, loc = cv2.minMaxLoc(r)
                if mx > best[0]: best = (float(mx), (loc[0], loc[1], w, h))
        f *= 1.07
    if best[1] is None: return -1, None
    if not refina: return best[0], [best[1][0] / W, best[1][1] / H, (best[1][0] + best[1][2]) / W, (best[1][1] + best[1][3]) / H]
    # refinament a més resolució al voltant de la millor escala
    A2 = gris(asset, 700); H2, W2 = A2.shape; k = W2 / W
    x, y, w, h = [v * k for v in best[1]]
    T0 = gris(bm, 300); th0, tw0 = T0.shape
    sc2, rect2 = -1, None
    for e in [0.94 + 0.01 * i for i in range(13)]:
        w2 = round(w * e); h2 = round(w2 * th0 / tw0)
        if w2 > W2 or h2 > H2 or h2 < 8: continue
        T = cv2.resize(T0, (w2, h2), interpolation=cv2.INTER_AREA)
        r = cv2.matchTemplate(A2, T, cv2.TM_CCOEFF_NORMED); _, mx, _, loc = cv2.minMaxLoc(r)
        if mx > sc2: sc2, rect2 = float(mx), (loc[0], loc[1], w2, h2)
    if rect2 is None: return best[0], [best[1][0] / W, best[1][1] / H, (best[1][0] + best[1][2]) / W, (best[1][1] + best[1][3]) / H]
    return sc2, [rect2[0] / W2, rect2[1] / H2, (rect2[0] + rect2[2]) / W2, (rect2[1] + rect2[3]) / H2]


def clau(g, n, ref):
    return f'g{g}:p{n}:{ref}'


def main():
    ap_ = argparse.ArgumentParser(); ap_.add_argument('--grup', type=int, action='append'); ap_.add_argument('--llista', action='store_true')
    ap_.add_argument('--llindar', type=float, default=0.80)
    a = ap_.parse_args()
    doc = fitz.open(PDF); res = {}
    if os.path.exists(OUT) and a.grup: res = yaml.safe_load(open(OUT, encoding='utf8')) or {}
    for g in (a.grup or sorted(COVER)):
        res = {k: v for k, v in res.items() if not k.startswith(f'g{g}:')}
        fi = min((COVER[g + 1] - 1) if g + 1 in COVER else FI, len(doc))
        marcs = []                     # marcs visibles (clip) de les imatges del PDF dins del grup: (pag, xref, x cm, y cm (des de dalt), w cm, h cm, rect visible)
        for n in range(COVER[g] + 1, fi + 1):
            for xref, ctm, clip in imatges_pagina(doc, doc[n - 1]):
                v = rect_visible(ctm, clip)
                if not v: continue
                a_, b_, c_, d_, e_, f_ = ctm
                if not clip: clip = (e_, min(f_, f_ + d_), e_ + a_, max(f_, f_ + d_))
                cx0, cy0, cx1, cy1 = max(clip[0], e_), max(clip[1], min(f_, f_ + d_)), min(clip[2], e_ + a_), min(clip[3], max(f_, f_ + d_))      # marc visible = clip ∩ imatge
                marcs.append((n, xref, round(cx0 * PT_CM, 3), round((842 - cy1) * PT_CM, 3), round((cx1 - cx0) * PT_CM, 3), round((cy1 - cy0) * PT_CM, 3), v[0]))
        ok = 0; sense = []; _GC.clear(); bms = {}; fallback = {}
        for p in dades(g)['pagines']:
            if p.get('tipus') != 'informacio_general': continue
            for i, f in enumerate(p.get('fotos', []) or [], 1):
                path = os.path.join(ROOT, f['asset']); pos = f.get('pos'); ref = f.get('referencia') if f.get('referencia') is not None else i
                if not pos or not os.path.exists(path) or path.lower().endswith('.emf'): continue
                # 1) el marc de la foto a gN.yaml coincideix amb el retall (clip) del PDF original: x, y, w, h (cm)
                cs = [m for m in marcs if abs(m[2] - pos['x']) < .12 and abs(m[3] - pos['y']) < .12 and abs(m[4] - pos['w']) < .12 and abs(m[5] - pos['h']) < .12]
                cs.sort(key=lambda m: (m[0] != p['n'] + COVER[g] - 2 and abs(m[0] - p['n']), abs(m[0] - p['n'])))
                im = Image.open(path); im.load(); millor = (-1, None, None)
                glob_ = not cs
                if not cs and path in fallback:      # la mateixa foto ja s'ha cercat per contingut en aquest grup (els yaml refosos la repeteixen a moltes pàgines)
                    cs = [fallback[path]]
                elif not cs:        # el marc del yaml no existeix al PDF (grups amb pàgines refoses): cerca per CONTINGUT entre totes les fotos del grup, per ordre de proximitat de pàgina
                    cs = sorted(marcs, key=lambda m: abs(m[0] - COVER[g] - p['n']))
                    if len(cs) > 60:  # prefiltre ràpid (64 px) i es verifica el millor
                        pre = []
                        for m in cs:
                            bm = bms.get(m[1]) or bms.setdefault(m[1], bitmap(doc, m[1]))
                            pre.append((troba(im, bm, long=64)[0], m))
                        pre.sort(key=lambda t: -t[0]); cs = [m for _, m in pre[:4]]
                for m in cs:
                    bm = bms.get(m[1]) or bms.setdefault(m[1], bitmap(doc, m[1]))
                    sc, rect = troba(im, bm)
                    if sc > millor[0]: millor = (sc, rect, m)
                    if sc >= .93: break
                sc, rect, m = millor
                if m is not None and not any(abs(x[2] - pos['x']) < .12 and abs(x[3] - pos['y']) < .12 for x in marcs if x[1] == m[1]) and sc >= a.llindar: fallback[path] = m
                if m is None: sense.append((p['n'], ref, 'sense marc al PDF')); continue
                bm = bms[m[1]]
                if rect is not None and sc >= a.llindar: sc, rect = troba(im, bm, refina=True)
                vx0, vy0, vx1, vy1 = m[6]
                e = {'font': f'G{g} p{p["n"]} {os.path.basename(f["asset"])}', 'pdf_pag': m[0], 'w_cm': m[4], 'h_cm': m[5], 'dh': dhash(im), 'ar': round(im.width / im.height, 4), 'score': round(sc, 3)}
                if rect is not None and sc >= a.llindar:
                    X0, Y0, X1, Y1 = rect; w, h = X1 - X0, Y1 - Y0
                    e['rect'] = [round(v, 4) for v in (X0 + vx0 * w, Y0 + vy0 * h, X0 + vx1 * w, Y0 + vy1 * h)]
                elif not (len(cs) == 1 and not glob_ and abs(bm.width / bm.height / (m[4] / m[5]) - 1) < .06):
                    sense.append((p['n'], ref, round(sc, 2), 'descartat')); continue      # sense retall fiable: es deixa el comportament anterior (recorts-fotos.yaml)
                else:                  # l'asset no conté aquest retall (foto canviada?): es guarda el bitmap exacte del PDF com a font de la foto
                    d_rel = os.path.join('assets', 'original-pdf'); os.makedirs(os.path.join(ROOT, d_rel), exist_ok=True)
                    nom = f'g{g}-p{m[0]}-x{m[1]}.png'; bw, bh = bm.size
                    bm.crop((round(vx0 * bw), round(vy0 * bh), round(vx1 * bw), round(vy1 * bh))).convert('RGB').save(os.path.join(ROOT, d_rel, nom))
                    e['bitmap'] = os.path.join(d_rel, nom); sense.append((p['n'], ref, round(sc, 2), 'bitmap'))
                res[clau(g, p['n'], ref)] = e; ok += 1
                if a.llista: print(clau(g, p['n'], ref), e)
        with open(OUT, 'w', encoding='utf8') as fh: yaml.safe_dump(res, fh, allow_unicode=True, sort_keys=True)
        print(f'G{g}: {ok} fotos enllaçades per marc; sense retall a l\'asset: {len([x for x in sense if "bitmap" in x or len(x) == 3])} {sense[:8]}', flush=True)
    with open(OUT, 'w', encoding='utf8') as fh: yaml.safe_dump(res, fh, allow_unicode=True, sort_keys=True)
    print('->', OUT, len(res))


if __name__ == '__main__': main()
