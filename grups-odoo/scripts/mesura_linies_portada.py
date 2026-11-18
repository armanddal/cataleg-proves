#!/usr/bin/env python3
"""Mesura les línies degradades (taronja-vermell-taronja) de les portades de la tarifa publicada.
Els .pub no guarden la direcció ni el gruix de les línies (dades/gN.yaml només té la caixa): es detecten al PDF publicat (pixels taronja/vermells saturats dins de cada caixa)
i es desa el segment real a dades/portada-linies.yaml  {grup: [{x1,y1,x2,y2,w}]} en cm. Cal numpy/opencv (venv).
Ús: python scripts/mesura_linies_portada.py [--pdf RUTA]"""
import argparse, os, subprocess, sys, tempfile
import cv2, numpy as np, yaml
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
PDF = os.path.expanduser('~/dev/tarifa-nova/cataleg_original_web.pdf')
COVER = {2: 47, 3: 65, 4: 93, 5: 151, 6: 207, 7: 248, 8: 286, 9: 342, 10: 391, 11: 425, 12: 498, 13: 590, 14: 662, 15: 733, 16: 817}
DPI = 200; R = DPI / 2.54


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--pdf', default=PDF); a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix='linies-'); out = {}
    for g, pg in COVER.items():
        subprocess.run(['pdftoppm', '-r', str(DPI), '-f', str(pg), '-l', str(pg), '-png', '-singlefile', a.pdf, f'{tmp}/o{g}'], check=True)
        im = cv2.imread(f'{tmp}/o{g}.png'); b, gg, r = [im[..., i].astype(int) for i in range(3)]
        strict = (r > 225) & (gg < 225) & (b < 60)
        loose = (r > 200) & (b < 130) & (r - b > 110) & (gg < 235)
        d = yaml.safe_load(open(os.path.join(ROOT, 'dades', f'g{g}.yaml'), encoding='utf8'))
        res = []
        for q in d['pagines'][0].get('decoracio', []):
            if q['forma'] != 'degradat': continue
            p = q['pos']; pad = .5
            x0, y0, x1, y1 = [max(0, int(v * R)) for v in (p['x'] - pad, p['y'] - pad, p['x'] + p['w'] + pad, p['y'] + p['h'] + pad)]
            sub = strict[y0:y1, x0:x1].astype(np.uint8)
            n, lab, st, _ = cv2.connectedComponentsWithStats(sub, 8)
            if n < 2: print(f'G{g}: línia {p} no detectada'); continue
            k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA])); mm = (lab == k).astype(np.uint8)
            ys, xs = np.nonzero(mm); pts = np.column_stack([xs, ys]).astype(np.float32)
            vx, vy, cx, cy = [float(v) for v in cv2.fitLine(pts, cv2.DIST_L2, 0, .01, .01).ravel()]
            t = (xs - cx) * vx + (ys - cy) * vy; ext = t.max() - t.min()
            dil = cv2.dilate(mm, np.ones((7, 7), np.uint8)).astype(bool)
            area = int((loose[y0:y1, x0:x1] & dil).sum()); w = area / ext / R
            cx = (cx + x0) / R; cy = (cy + y0) / R
            bx0, bx1, by0, by1 = p['x'], p['x'] + p['w'], p['y'], p['y'] + p['h']
            if abs(vx) >= abs(vy):        # recorta a la caixa (la línia pot quedar tapada per una foto)
                ta, tb = (bx0 - cx) / vx, (bx1 - cx) / vx
            else:
                ta, tb = (by0 - cy) / vy, (by1 - cy) / vy
            if ta > tb: ta, tb = tb, ta
            cord = (p['w'] if abs(vx) >= abs(vy) else p['h']) / max(abs(vx) if abs(vx) >= abs(vy) else abs(vy), 1e-6)   # llargada de la línia dins la caixa
            davant = bool(ext / R >= .93 * cord)        # visible sencera = dibuixada per sobre de les fotos; si una foto la talla, va per sota
            res.append({'davant': davant, 'x1': round(cx + vx * ta, 2), 'y1': round(cy + vy * ta, 2), 'x2': round(cx + vx * tb, 2), 'y2': round(cy + vy * tb, 2), 'w': round(float(w), 3)})
        out[g] = res; print(g, res)
    f = os.path.join(ROOT, 'dades', 'portada-linies.yaml')
    with open(f, 'w', encoding='utf8') as fh:
        fh.write('# Línies degradades de les portades, mesurades sobre la tarifa publicada (scripts/mesura_linies_portada.py): extrems (x1,y1)-(x2,y2) i gruix w, en cm sobre el full A4.\n')
        yaml.safe_dump(out, fh, sort_keys=True, default_flow_style=None)
    print('->', f)


if __name__ == '__main__': main()
