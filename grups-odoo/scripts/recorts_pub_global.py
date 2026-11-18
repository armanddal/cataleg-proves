#!/usr/bin/env python3
"""Recorts de fotos d'informació que recorts_pub.py no troba (score < 0.45 a la pàgina que li correspon per numeració).
El marc de cada foto és fix (pos de gN.yaml, la plantilla de la pàgina d'informació és la mateixa a tot el grup), però la NUMERACIÓ de pàgines de gN.yaml no sempre
coincideix amb la tarifa publicada (G11: el yaml té ~170 pàgines per a un grup de 72). Aquí, per a cada foto sense entrada:
  1) es prova la pàgina assignada i les veïnes (±4);  2) si no arriba al llindar, es prova TOTES les pàgines del grup (cerca ràpida a 50 ppp) i es verifica la millor a 150 ppp.
Només afegeix entrades noves a dades/recorts-fotos.yaml (mai toca les existents); després cal python scripts/recorts_pub.py --indexa.
Ús (venv numpy/opencv): python scripts/recorts_pub_global.py [--grup N ...] [--llindar 0.6] [--llista]"""
import argparse, hashlib, os, subprocess, sys, tempfile
import cv2, numpy as np, yaml
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import recorts_pub as R
FI = {**R.COVER, 17: 862}


def png(pdf, n, cache, dpi):
    f = os.path.join(cache, f'p{n}-{dpi}.png')
    if not os.path.exists(f):
        subprocess.run(['pdftoppm', '-r', str(dpi), '-f', str(n), '-l', str(n), '-png', '-singlefile', pdf, f[:-4]], check=True)
    return cv2.imread(f, cv2.IMREAD_GRAYSCALE)


def troba_dpi(pag, asset, pos, dpi, pas=1.04, kmax=4.2):
    """Com recorts_pub.troba, a una altra resolució (pxcm) i amb pas d'escala configurable."""
    old = R.PXCM; R.PXCM = dpi / 2.54
    try: return troba_k(pag, asset, pos, pas, kmax)
    finally: R.PXCM = old


def troba_k(pag, asset, pos, pas, kmax):
    H, W = pag.shape; PX = R.PXCM
    x0, y0, x1, y1 = [int(round(v * PX)) for v in (pos['x'], pos['y'], pos['x'] + pos['w'], pos['y'] + pos['h'])]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    tpl = pag[y0:y1, x0:x1]
    if tpl.shape[0] < 12 or tpl.shape[1] < 12 or float(tpl.std()) < 14: return 0, None        # marc buit/pla: la correlació no val res
    im = cv2.imread(asset, cv2.IMREAD_GRAYSCALE)
    if im is None: return 0, None
    ah, aw = im.shape; th, tw = tpl.shape
    s0 = max(tw / aw, th / ah); best = (-1, None); k = 1.0
    while k <= kmax:
        s = s0 * k; nw, nh = int(aw * s), int(ah * s)
        if nw >= tw and nh >= th and nw < 6000:
            big = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_AREA)
            r = cv2.matchTemplate(big, tpl, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
            if mx > best[0]: best = (mx, [loc[0] / nw, loc[1] / nh, (loc[0] + tw) / nw, (loc[1] + th) / nh])
        k *= pas
    return best


def marc_buit(pag, pos, minstd=14):
    """True si el marc de la pàgina publicada no té contingut (blanc o pla): la correlació d'una plantilla plana no val res."""
    H, W = pag.shape; k = R.PXCM
    x0, y0, x1, y1 = [int(round(v * k)) for v in (pos['x'], pos['y'], pos['x'] + pos['w'], pos['y'] + pos['h'])]
    t = pag[max(0, y0):min(H, y1), max(0, x0):min(W, x1)]
    return t.size == 0 or float(t.std()) < minstd


def troba_ok(pag, asset, pos):
    """R.troba (150 ppp) però sense donar per bo un marc buit."""
    if marc_buit(pag, pos): return 0, None
    return R.troba(pag, asset, pos)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--grup', type=int, action='append'); ap.add_argument('--pdf', default=R.PDF)
    ap.add_argument('--llindar', type=float, default=.75); ap.add_argument('--llista', action='store_true'); a = ap.parse_args()
    out_p = os.path.join(ROOT, 'dades', 'recorts-fotos.yaml')
    res = yaml.safe_load(open(out_p, encoding='utf8')) or {}
    cache = tempfile.mkdtemp(prefix='rglobal-')
    for g in (a.grup or range(1, 17)):
        d = R.dades(g)
        isim = [i for i, p in enumerate(d['pagines'], 1) if p['tipus'] == 'simbologia'][0]; off = R.SIM[g] - isim
        pend = []
        for i, pg in enumerate(d['pagines'], 1):
            if pg['tipus'] != 'informacio_general': continue
            for f in pg.get('fotos') or []:
                path = os.path.join(ROOT, f['asset'])
                if not os.path.exists(path): continue
                sha = hashlib.sha1(open(path, 'rb').read()).hexdigest()
                if sha in res: continue
                pend.append((pg['n'], off + i, f, path, sha))
        print(f'G{g}: {len(pend)} fotos sense entrada', flush=True)
        if a.llista or not pend: continue
        lo, hi = R.COVER[g], FI[g + 1] - 1
        n_ok = n_sen = 0; no = []; veines = 0; globals_ = 0
        for pn, pagn, f, path, sha in pend:
            if sha in res: continue
            millor = (-1, None, None)
            cand = [pagn] + [pagn + s * k for k in (1, 2, 3, 4) for s in (1, -1)]
            for n in cand:
                if not lo <= n <= hi: continue
                sc, rect = troba_ok(R.pagina_png(a.pdf, n, cache), path, f['pos'])
                if sc > millor[0]: millor = (sc, rect, n)
                if sc >= .8: break
            via = 'veïna'
            if millor[0] < a.llindar:
                # cerca a tot el grup a 50 ppp, verifica la millor a 150
                punts = []
                for n in range(lo, hi + 1):
                    sc, rect = troba_dpi(png(a.pdf, n, cache, 50), path, f['pos'], 50, pas=1.08, kmax=4.2)
                    punts.append((sc, n))
                punts.sort(reverse=True)
                for sc50, n in punts[:3]:
                    sc, rect = troba_ok(R.pagina_png(a.pdf, n, cache), path, f['pos'])
                    if sc > millor[0]: millor = (sc, rect, n); via = 'global'
            sc, rect, n = millor
            if rect is None or sc < a.llindar: no.append((pn, f['asset'], f'millor correlació {sc:.2f} (pàg. {n})')); continue
            if marc_buit(R.pagina_png(a.pdf, n, cache), f['pos']): no.append((pn, f['asset'], f'el marc és buit a la pàg. {n} de la tarifa publicada (la foto no hi surt)')); continue
            if via == 'global': globals_ += 1
            area = (rect[2] - rect[0]) * (rect[3] - rect[1])
            if area > .965: n_sen += 1; continue
            res[sha] = {'rect': [round(float(v), 4) for v in rect], 'font': f'G{g} p{pn} {os.path.basename(f["asset"])}', 'metode': f'pub-{via}', 'score': round(float(sc), 2), 'pagina_pub': int(n)}
            n_ok += 1
        print(f'G{g}: afegides {n_ok} ({globals_} només amb cerca global), sense retall {n_sen}, no trobades {len(no)}', flush=True)
        for x in no: print('   ', x, flush=True)
        yaml.safe_dump(res, open(out_p, 'w', encoding='utf8'), allow_unicode=True, sort_keys=True)


if __name__ == '__main__': main()
