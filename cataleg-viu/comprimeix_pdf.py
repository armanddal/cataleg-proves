#!/usr/bin/env python3
"""Redueix el pes d'un PDF sense tocar el text ni els vectors: les imatges que tenen més resolució de la que cal
a la mida en què es mostren es tornen a mostrejar a ~DPI ppp i, si són fotos, es desen en JPEG (qualitat QUALITAT).
Les icones, símbols i logos (imatges petites) no es toquen.

    python3 comprimeix_pdf.py entrada.pdf [sortida.pdf]      (sense sortida, substitueix l'entrada)
Variables opcionals: CATALEG_DPI (defecte 150), CATALEG_JPEG_Q (defecte 78).

S'escriu amb PyMuPDF + Pillow (no es fa servir `rewrite_images` de PyMuPDF: peta amb segmentation fault amb alguns d'aquests PDF).
Si alguna imatge no es pot processar es deixa tal com és (mai es perd informació per un error).
"""
import io
import os
import sys

import cataleg_lib as L

L.reexec_x86()      # al Mac, PyMuPDF és x86: es torna a executar sota Rosetta si cal
import fitz  # noqa: E402
from PIL import Image  # noqa: E402

DPI = int(os.environ.get('CATALEG_DPI', '150'))
QUALITAT = int(os.environ.get('CATALEG_JPEG_Q', '78'))
MIN_PIXELS = 300_000        # per sota (≈ 550x550 px) es considera icona/símbol/logo i no es toca
MARGE = 1.3                 # només es redueix si té més d'1,3 vegades la resolució objectiu


def necessitats(doc):
    """{xref: (ample_px_necessari, alt_px_necessari)}: el màxim sobre tots els usos de la imatge."""
    nec = {}
    for pg in doc:
        for inf in pg.get_image_info(xrefs=True):
            x = inf.get('xref')
            if not x:
                continue
            b = fitz.Rect(inf['bbox'])
            w = max(1.0, b.width / 72 * DPI)
            h = max(1.0, b.height / 72 * DPI)
            o = nec.get(x, (0, 0))
            nec[x] = (max(o[0], w), max(o[1], h))
    return nec


def jpeg(im, q):
    bio = io.BytesIO()
    im.save(bio, 'JPEG', quality=q, optimize=True, progressive=False)
    return bio.getvalue()


def processa(doc, xref, need):
    """Retorna True si ha substituït la imatge."""
    info = doc.extract_image(xref)
    if not info:
        return False
    w, h = info['width'], info['height']
    if w * h < MIN_PIXELS:
        return False
    escala = min(need[0] / w, need[1] / h)
    if escala * MARGE >= 1:
        return False
    nw, nh = max(1, round(w * escala)), max(1, round(h * escala))
    im = Image.open(io.BytesIO(info['image']))
    im.load()
    smask = info.get('smask') or 0
    mask = None
    if smask:
        mi = doc.extract_image(smask)
        if mi:
            mask = Image.open(io.BytesIO(mi['image'])).convert('L')
            if mask.size != (w, h):
                mask = mask.resize((w, h), Image.LANCZOS)
    if im.mode in ('RGBA', 'LA', 'P'):
        # transparència dins la pròpia imatge (no hauria de passar als PDF de Chrome): s'aplana sobre blanc
        rgba = im.convert('RGBA')
        fons = Image.new('RGB', rgba.size, 'white')
        fons.paste(rgba, mask=rgba.split()[-1])
        im = fons
    im = im.convert('RGB').resize((nw, nh), Image.LANCZOS)
    plana = im.getcolors(maxcolors=256) is not None      # dibuix pla (poques tintes): es manté sense pèrdua
    if plana:
        dades, filtre = im.tobytes(), None
    else:
        dades, filtre = jpeg(im, QUALITAT), '/DCTDecode'
    if len(dades) >= len(info['image']) * 0.9 and not plana:
        return False
    # Ordre important: update_stream esborra el Filter de l'objecte, així que el Filter es posa DESPRÉS
    doc.update_stream(xref, dades, compress=not filtre)
    doc.xref_set_key(xref, 'Width', str(nw))
    doc.xref_set_key(xref, 'Height', str(nh))
    doc.xref_set_key(xref, 'ColorSpace', '/DeviceRGB')
    doc.xref_set_key(xref, 'BitsPerComponent', '8')
    for k in ('DecodeParms', 'Decode', 'Intent', 'ColorTransform'):
        doc.xref_set_key(xref, k, 'null')
    if filtre:
        doc.xref_set_key(xref, 'Filter', filtre)
    if smask and mask is not None:
        mask = mask.resize((nw, nh), Image.LANCZOS)
        doc.update_stream(smask, mask.tobytes(), compress=True)
        doc.xref_set_key(smask, 'Width', str(nw))
        doc.xref_set_key(smask, 'Height', str(nh))
        doc.xref_set_key(smask, 'ColorSpace', '/DeviceGray')
        doc.xref_set_key(smask, 'BitsPerComponent', '8')
        for k in ('DecodeParms', 'Decode'):
            doc.xref_set_key(smask, k, 'null')
    return True


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ent = sys.argv[1]
    sor = sys.argv[2] if len(sys.argv) > 2 else ent
    doc = fitz.open(ent)
    nec = necessitats(doc)
    fets = errors = 0
    for xref, need in nec.items():
        try:
            if processa(doc, xref, need):
                fets += 1
        except Exception as e:      # una imatge rara es deixa com està
            errors += 1
            print('  avís: imatge %d no processada (%s)' % (xref, e), file=sys.stderr)
    tmp = sor + '.tmp'
    doc.save(tmp, garbage=4, deflate=True)
    doc.close()
    mida0 = os.path.getsize(ent)
    os.replace(tmp, sor)
    print('%s: %.1f MB -> %.1f MB (%d de %d imatges reduïdes, %d errors)' % (
        os.path.basename(ent), mida0 / 1e6, os.path.getsize(sor) / 1e6, fets, len(nec), errors))


if __name__ == '__main__':
    main()
