#!/usr/bin/env python3
"""Actualitza el catàleg viu amb UNA ordre: llegeix d'Odoo Staging (només lectura), regenera els PDF dels grups
que han canviat i torna a muntar el catàleg i el visor.

    python3 actualitza.py                  # un cicle
    python3 actualitza.py --vigila 300     # repeteix cada 300 s (bucle en primer pla; Ctrl-C per parar)
    python3 actualitza.py --prova          # només diu què regeneraria (no toca res)
    python3 actualitza.py --forca 4,5      # regenera aquests grups encara que no hagin canviat  (--tot: tots)

Un grup es considera canviat si l'empremta de les seves dades d'Odoo difereix de la de l'última generació
(estat/actualitza.json): famílies, productes de les famílies (marca x_cataleg inclosa) i els repetits d'altres
grups, columnes de família, columnes i valors (id + write_date de cada registre; el write_date màxim es mostra
per informar). Esborrar l'entrada d'un grup a l'estat el fa regenerar. Idempotent: sense canvis no fa res.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import yaml

import cataleg_lib as L

try:
    import odoo_lectura
except Exception as e:      # sense Odoo es pot seguir amb --forca/--tot? no: cal Odoo per saber els grups
    odoo_lectura = None
    ERR_ODOO = e

ESTAT = os.path.join(L.ESTAT_DIR, 'actualitza.json')


# ----------------------------------------------------------------------------- lectura d'Odoo
def llegeix_odoo(cfg, lect=None):
    """{n: {'empremta', 'max', 'resum', 'marcats'}} dels grups amb productes marcats. Només lectura."""
    lect = lect or odoo_lectura.lectura
    ctx = {'active_test': False}
    fams = lect('x_cataleg_familia', 'search_read', domain=[], fields=['grup', 'write_date', 'active'], context=ctx)
    prods = lect('product.template', 'search_read',
                 domain=['|', ['x_cataleg_familia_id', '!=', False], ['x_cataleg_familia_extra_ids', '!=', False]],
                 fields=['write_date', 'x_cataleg', 'x_cataleg_familia_id', 'x_cataleg_familia_extra_ids',
                         'default_code'])
    # Pàgines generals (text, títol, ordre, imatges): un canvi s'ha de notar igual que un canvi de producte.
    pagines = lect('x_cataleg_pagina', 'search_read', domain=[], fields=['write_date', 'grup', 'active'], context=ctx)
    pag_img = lect('x_cataleg_pagina_imatge', 'search_read', domain=[], fields=['write_date', 'pagina_id'])
    famcol = lect('x_cataleg_familia_columna', 'search_read', domain=[], fields=['write_date', 'familia_id', 'columna_id'])
    cols = {r['id']: r for r in lect('x_cataleg_columna', 'search_read', domain=[], fields=['write_date'], context=ctx)}
    valors = lect('x_cataleg_valor', 'search_read', domain=[], fields=['write_date', 'producte_id'])
    fam_grup = {f['id']: f['grup'] for f in fams}
    per_default_code = {p['default_code']: p for p in prods if p.get('default_code')}

    out = {}
    for codi in sorted({f['grup'] for f in fams if f['grup']}):
        n = int(codi[1:])
        fids = {f['id'] for f in fams if f['grup'] == codi}
        propis = [p for p in prods if p['x_cataleg_familia_id'] and p['x_cataleg_familia_id'][0] in fids]
        marcats = sum(1 for p in propis if p['x_cataleg'])
        # productes d'altres grups que surten aquí com a «família extra»
        propis += [p for p in prods if p not in propis and set(p.get('x_cataleg_familia_extra_ids') or []) & fids]
        pids = {pg['id'] for pg in pagines if pg['grup'] in (codi, 'general')}
        if not marcats:
            continue
        ids = {p['id'] for p in propis}
        # productes que el generador repeteix d'altres famílies/grups (configuració del grup, si n'hi ha)
        for c in codis_repetits(cfg, n):
            p = per_default_code.get(c)
            if p and p['id'] not in ids:
                propis.append(p)
                ids.add(p['id'])
        fc = [r for r in famcol if r['familia_id'] and r['familia_id'][0] in fids]
        colids = {r['columna_id'][0] for r in fc if r['columna_id']}
        vs = [r for r in valors if r['producte_id'] and r['producte_id'][0] in ids]
        taules = {
            'x_cataleg_familia': [(f['id'], f['write_date'], f['active']) for f in fams if f['id'] in fids],
            'product.template': [(p['id'], p['write_date'], bool(p['x_cataleg'])) for p in propis],
            'x_cataleg_familia_columna': [(r['id'], r['write_date']) for r in fc],
            'x_cataleg_columna': [(i, cols[i]['write_date']) for i in colids if i in cols],
            'x_cataleg_valor': [(r['id'], r['write_date']) for r in vs],
            'x_cataleg_pagina': [(pg['id'], pg['write_date'], pg['active']) for pg in pagines if pg['id'] in pids],
            'x_cataleg_pagina_imatge': [(r['id'], r['write_date']) for r in pag_img
                                        if r['pagina_id'] and r['pagina_id'][0] in pids],
        }
        resum, mx = {}, ''
        for t, rows in taules.items():
            m = max((r[1] for r in rows if r[1]), default='')
            resum[t] = {'n': len(rows), 'max': m}
            mx = max(mx, m)
        h = hashlib.sha1(json.dumps({t: sorted(map(list, rows)) for t, rows in taules.items()}, sort_keys=True).encode()).hexdigest()
        out[n] = {'empremta': h, 'max': mx, 'resum': resum, 'marcats': marcats}
    return out


def codis_repetits(cfg, n):
    p = L.ruta((cfg.get('repeticions_config') or '../grups-odoo/dades/g{n}-config.yaml').format(n=n))
    try:
        c = yaml.safe_load(open(p, encoding='utf-8')) or {}
    except OSError:
        return []
    return [r['codi'] for lst in (c.get('repeticions') or {}).values() for r in lst]


# ----------------------------------------------------------------------------- regeneració
def ordre_generador(cfg, n, sortida):
    gen = (cfg.get('generadors') or {})
    g = gen.get(n) or gen.get('per_defecte')
    if not g:
        raise RuntimeError('cataleg.yaml no té generador per al grup %d' % n)
    cmd = [str(x).format(n=n, sortida=sortida) for x in g['ordre']]
    return cmd, L.ruta(g.get('cwd', '.'))


def pagines_pdf(p):
    r = subprocess.run(['pdfinfo', p], capture_output=True, text=True)
    m = re.search(r'Pages:\s+(\d+)', r.stdout)
    return int(m.group(1)) if m else 0


def regenera_grup(cfg, n):
    """Crida el generador del grup (només llegeix d'Odoo) i deixa el PDF a treball/grups/gN.pdf. Retorna (pagines, segons)."""
    t0 = time.time()
    nou = os.path.join(L.GRUPS_DIR, '.nou')
    os.makedirs(nou, exist_ok=True)
    sortida = os.path.join(nou, 'g%d' % n)
    for ext in ('.pdf', '.html'):
        if os.path.exists(sortida + ext):
            os.remove(sortida + ext)
    cmd, cwd = ordre_generador(cfg, n, sortida)
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not os.path.exists(sortida + '.pdf'):
        raise RuntimeError('el generador ha fallat (codi %s): %s' % (r.returncode, (r.stderr or r.stdout)[-600:]))
    pags = pagines_pdf(sortida + '.pdf')
    if pags < 1:
        raise RuntimeError('el PDF generat no té pàgines')
    os.replace(sortida + '.pdf', os.path.join(L.GRUPS_DIR, 'g%d.pdf' % n))
    if os.path.exists(sortida + '.html'):
        os.remove(sortida + '.html')
    return pags, time.time() - t0


def canvis_resum(vell, nou):
    """Text curt amb què ha canviat (per taula: nombre de registres i write_date màxim)."""
    if not vell:
        return 'sense generació anterior'
    out = []
    for t, r in nou['resum'].items():
        v = (vell.get('resum') or {}).get(t) or {}
        if v.get('n') != r['n'] or v.get('max') != r['max']:
            out.append('%s %s->%s regs (últim canvi %s)' % (t, v.get('n', '?'), r['n'], r['max'] or '-'))
    return '; '.join(out) or 'empremta diferent'


def ara():
    return time.strftime('%H:%M:%S')


# ----------------------------------------------------------------------------- un cicle
def cicle(a):
    t0 = time.time()
    cfg = L.carrega_config()
    if odoo_lectura is None:
        raise RuntimeError("no puc llegir d'Odoo: %s" % ERR_ODOO)
    estat = L.llegeix_json(ESTAT, {'grups': {}})
    estat.setdefault('grups', {})
    print('[%s] Llegint Odoo Staging (només lectura)...' % ara())
    odoo = llegeix_odoo(cfg)
    if cfg.get('ordre'):
        # Amb `ordre` al yaml només es regeneren els grups que entren al catàleg (prova amb pocs grups).
        dins = {int(x) for x in cfg['ordre']}
        odoo = {n: o for n, o in odoo.items() if n in dins}
    t_lec = time.time() - t0
    print('    grups amb productes marcats: %s (lectura: %.1f s)' % (
        ', '.join('G%02d (%d prod.)' % (n, o['marcats']) for n, o in sorted(odoo.items())) or 'cap', t_lec))

    forca = set()
    if a.tot:
        forca = set(odoo)
    elif a.forca:
        forca = {int(x) for x in a.forca.split(',')}
    pendents = []
    for n, o in sorted(odoo.items()):
        e = estat['grups'].get(str(n))
        pdf = os.path.join(L.GRUPS_DIR, 'g%d.pdf' % n)
        if n in forca:
            motiu = 'forçat'
        elif not e:
            motiu = 'sense estat (primera generació)'
        elif e['empremta'] != o['empremta']:
            motiu = 'canvis a Odoo: ' + canvis_resum(e, o)
        elif not os.path.exists(pdf):
            motiu = 'falta treball/grups/g%d.pdf' % n
        else:
            continue
        pendents.append((n, motiu))

    dins_ordre = {int(x) for x in cfg['ordre']} if cfg.get('ordre') else None
    retirats = [int(n) for n in estat['grups']
                if int(n) not in odoo and (dins_ordre is None or int(n) in dins_ordre)]
    for n in retirats:
        print('    G%02d: ja no té productes marcats a Odoo -> surt del catàleg' % n)
    if not pendents and not retirats:
        print('    cap grup ha canviat: no cal regenerar res')
    regenerats, errors = [], []
    for n, motiu in pendents:
        print('    G%02d: %s' % (n, motiu))
        if a.prova:
            continue
        try:
            pags, seg = regenera_grup(cfg, n)
        except Exception as e:
            print('    G%02d: ERROR - es manté el PDF anterior. %s' % (n, e))
            errors.append(n)
            continue
        estat['grups'][str(n)] = {'empremta': odoo[n]['empremta'], 'max': odoo[n]['max'], 'resum': odoo[n]['resum'],
                                  'generat': time.strftime('%Y-%m-%dT%H:%M:%S'), 'segons': round(seg, 1), 'pagines': pags}
        L.escriu_json(ESTAT, estat)
        regenerats.append(n)
        print('    G%02d: regenerat (%d pàgines, %.0f s)' % (n, pags, seg))
    if not a.prova:
        for n in retirats:
            p = os.path.join(L.GRUPS_DIR, 'g%d.pdf' % n)
            if os.path.exists(p):
                os.makedirs(os.path.join(L.GRUPS_DIR, 'retirats'), exist_ok=True)
                os.replace(p, os.path.join(L.GRUPS_DIR, 'retirats', 'g%d.pdf' % n))
            estat['grups'].pop(str(n), None)
        if retirats:
            L.escriu_json(ESTAT, estat)

    # muntatge: si ha canviat algun grup o la signatura del que entra al catàleg no coincideix amb l'última munta
    munta = False
    if not a.sense_munta and not a.prova:
        grups_cat = L.grups_disponibles(cfg)
        sig = L.signatura_muntatge(cfg, grups_cat) if grups_cat else None
        ultima = (L.llegeix_json(os.path.join(L.ESTAT_DIR, 'munta.json')) or {}).get('signatura')
        faltes = not os.path.exists(os.path.join(L.WEB, 'cataleg.pdf'))
        if regenerats or retirats or faltes or sig != ultima:
            t1 = time.time()
            print('[%s] Muntant catàleg i visor...' % ara())
            r = subprocess.run([sys.executable, os.path.join(L.AQUI, 'munta_cataleg.py')], cwd=L.AQUI)
            if r.returncode != 0:
                errors.append('munta')
                print('    ERROR muntant el catàleg (codi %d)' % r.returncode)
            else:
                munta = True
                print('    muntatge: %.0f s' % (time.time() - t1))
    total = time.time() - t0
    resum = 'regenerats: %s | muntat: %s | errors: %s' % (
        ', '.join('G%02d' % n for n in regenerats) or 'cap', 'sí' if munta else 'no', errors or 'cap')
    print('[%s] Fet en %.0f s | %s' % (ara(), total, resum))
    return 1 if errors else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--vigila', type=int, metavar='N', help='repeteix el cicle cada N segons (primer pla)')
    ap.add_argument('--prova', action='store_true', help='només mostra què regeneraria')
    ap.add_argument('--forca', metavar='N,M', help='grups a regenerar encara que no hagin canviat')
    ap.add_argument('--tot', action='store_true', help='regenera tots els grups')
    ap.add_argument('--sense-munta', action='store_true', help='no torna a muntar el catàleg')
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)
    os.makedirs(L.GRUPS_DIR, exist_ok=True)
    if not a.vigila:
        return cicle(a)
    print('Vigilant cada %d s (Ctrl-C per parar). Només lectura a Odoo Staging.' % a.vigila)
    try:
        while True:
            try:
                cicle(a)
            except Exception as e:           # Odoo caigut, etc.: es torna a provar al cicle següent
                print('[%s] ERROR en el cicle: %s' % (ara(), e))
            a.forca = None
            a.tot = False
            print('    (proper cicle en %d s)\n' % a.vigila)
            time.sleep(a.vigila)
    except KeyboardInterrupt:
        print('\nAturat.')
        return 0


if __name__ == '__main__':
    sys.exit(main())
