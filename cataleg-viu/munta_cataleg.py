#!/usr/bin/env python3
"""Munta el catàleg viu: UN PDF (portada general + PDF de cada grup + contraportada) i el visor web al costat.

    python3 munta_cataleg.py [--sense-visor]

Sortida a web/: cataleg.pdf, index.html (GROUPS generat), references.json, search-text.json, relations.json,
logo.png i favicons. A estat/mapa.json: pàgines de cada grup (ho fa servir pdf_client.py).
Els grups surten de cataleg.yaml + els PDF disponibles (veure README): cap nombre de grups és fix.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import time

import cataleg_lib as L
from portades import html_portada, html_contraportada

L.reexec_x86()
import fitz  # noqa: E402

HERE = L.AQUI
VIEWER_DIRS = [os.path.join(HERE, '..', 'tarifa', 'viewer')]
MARCA_INICI = "// >>> GROUPS-AUTO: bloc generat per cataleg-viu/munta_cataleg.py a partir dels grups disponibles. NO l'editis a mà."
MARCA_FI = '// <<< GROUPS-AUTO'
LANGS = ('es', 'en', 'fr', 'de', 'it', 'pt')


def carrega_script(nom):
    for d in VIEWER_DIRS:
        for f in (nom + '.py', nom.replace('_', '-') + '.py'):
            p = os.path.join(d, f)
            if os.path.exists(p):
                spec = importlib.util.spec_from_file_location('viewer_' + nom, p)
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                return m
    raise FileNotFoundError('no trobo el script del visor ' + nom)


# ----------------------------------------------------------------------------- visor
def bloc_groups(grups):
    linies = []
    for g in grups:
        nom = dict(g['nom'])
        nom.setdefault('de', nom['en'])
        nom.setdefault('it', nom['en'])
        nom.setdefault('pt', nom['es'])
        camps = ', '.join("%s: '%s'" % (l, nom[l].replace('\\', '\\\\').replace("'", "\\'")) for l in LANGS)
        linies.append("  { id: '%s', page: %3d, %s }," % (g['id'], g['start'], camps))
    return MARCA_INICI + '\nconst GROUPS = [\n' + '\n'.join(linies) + '\n];\n' + MARCA_FI + '\n'


# Títol del visor per idioma (el de partida diu «RCR»; el catàleg és d'Eurast) i nom del fitxer de descàrrega.
TITOLS_VISOR = {'Catálogo Tarifa RCR Completa': 'Catálogo Eurast', 'RCR Complete Price List': 'Eurast Catalogue',
                'Catalogue Tarif RCR Complet': 'Catalogue Eurast', 'RCR Vollständiger Preiskatalog': 'Eurast Katalog',
                'Catalogo Prezzi RCR Completo': 'Catalogo Eurast', 'Catálogo Preços RCR Completo': 'Catálogo Eurast'}


def index_html(origen, grups, desti, edicio=None):
    html = open(origen, encoding='utf-8').read()
    for vell, nou in TITOLS_VISOR.items():
        html = html.replace(vell, nou)
    html = html.replace('<title>Catálogo Tarifa — EURAST</title>', '<title>Catálogo Eurast</title>')
    if edicio:
        html = html.replace("a.download = 'Eurast-Cataleg-RCR.pdf';", "a.download = 'Eurast-Catalogo-%s.pdf';" % edicio.replace('/', '-'))
    html = re.sub(r'^' + re.escape(MARCA_INICI) + r'\n', '', html, flags=re.M)
    html = re.sub(r'^' + re.escape(MARCA_FI) + r'\n', '', html, flags=re.M)
    m = re.search(r'^const GROUPS = \[\n.*?^\];\n', html, re.S | re.M)
    if not m:
        raise ValueError('no trobo «const GROUPS = [» a index.html')
    html = html[:m.start()] + bloc_groups(grups) + html[m.end():]
    with open(desti, 'w', encoding='utf-8') as f:
        f.write(html)


def genera_fitxers_visor(grups, cfg, pdf, log):
    br = carrega_script('build_refs')
    brl = carrega_script('build_relations')
    starts = [g['start'] for g in grups]
    br.PDF = pdf
    br.OUT = os.path.join(L.WEB, 'references.json')
    br.OUT_TEXT = os.path.join(L.WEB, 'search-text.json')
    br.GROUP_STARTS = starts
    br.main()
    ns = [int(x) for x in cfg.get('relacions_grups') or []]
    brl.PDF = pdf
    brl.REFS = br.OUT
    brl.OUT = os.path.join(L.WEB, 'relations.json')
    brl.GROUPS_IN_SCOPE = tuple(i for i, g in enumerate(grups) if g['n'] in ns)
    brl.main()
    rel = json.load(open(brl.OUT, encoding='utf-8'))
    rel['items'] = {k: rel['items'][k] for k in sorted(rel['items'])}
    json.dump(rel, open(brl.OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    refs = json.load(open(br.OUT, encoding='utf-8'))
    return refs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sense-visor', action='store_true', help='només el PDF (sense references/search/relations/index)')
    a = ap.parse_args(argv)
    t0 = time.time()
    cfg = L.carrega_config()
    ns = L.grups_disponibles(cfg)
    if not ns:
        sys.exit('No hi ha cap PDF de grup disponible (cap a treball/grups/, ni als pdf_origen de cataleg.yaml).')
    v = cfg.get('visor') or {}
    index_origen = L.ruta(v['index_html'])
    recursos = L.ruta(v.get('recursos', os.path.dirname(index_origen)))
    logo = os.path.join(recursos, 'logo.png')
    del_visor = L.noms_visor(index_origen)
    edicio = L.edicio(cfg)
    os.makedirs(L.WEB, exist_ok=True)
    os.makedirs(L.TREBALL, exist_ok=True)

    # 1) pàgines de cada grup
    grups = []
    for n in ns:
        p = L.pdf_de_grup(cfg, n)
        d = fitz.open(p)
        grups.append({'n': n, 'id': L.codi_odoo(n), 'nom': L.noms_grup(cfg, n, del_visor), 'pdf': p, 'pagines': d.page_count,
                      'mida': os.path.getsize(p), 'doc': d})
    # 2) portada (1 pàgina) i posició de cada grup
    pos = 2
    for g in grups:
        g['start'] = pos
        pos += g['pagines']
        g['end'] = pos - 1
    portada_pdf = os.path.join(L.TREBALL, 'portada.pdf')
    contra_pdf = os.path.join(L.TREBALL, 'contraportada.pdf')
    for nom, doc_html, dest in (('portada', html_portada(grups, edicio, logo), portada_pdf),
                                ('contraportada', html_contraportada(cfg.get('contacte') or {}, logo), contra_pdf)):
        hp = os.path.join(L.TREBALL, nom + '.html')
        open(hp, 'w', encoding='utf-8').write(doc_html)
        L.html_a_pdf(hp, dest)

    # 3) muntatge
    out = fitz.open()
    out.insert_pdf(fitz.open(portada_pdf))
    for g in grups:
        out.insert_pdf(g['doc'], links=True)
        # darrera pàgina del grup = «SOLICITE CATALOGO» (contraportada del grup)? (pdf_client la fa servir)
        ultima = g['doc'][g['pagines'] - 1].get_text('text')
        g['contra'] = g['end'] if 'SOLICITE CATALOGO' in ultima else None
    out.insert_pdf(fitz.open(contra_pdf))
    total = out.page_count
    toc = [[1, 'Portada / Cover', 1]]
    for g in grups:
        toc.append([1, '%s - %s' % (g['id'], g['nom']['es']), g['start']])
    toc.append([1, 'Contraportada / Back cover', total])
    out.set_toc(toc)
    out.set_metadata({'title': 'Catálogo / Tarifa Eurast %s' % edicio, 'author': 'Eurast', 'subject': 'Catálogo / Tarifa'})
    tmp = os.path.join(L.WEB, 'cataleg.pdf.tmp')
    out.save(tmp, garbage=4, deflate=True)
    out.close()
    pdf = os.path.join(L.WEB, 'cataleg.pdf')
    os.replace(tmp, pdf)
    t_pdf = time.time() - t0
    print('PDF: %d pàgines, %.1f MB, %d grups (%s) en %.0f s' % (
        total, os.path.getsize(pdf) / 1e6, len(grups), ', '.join(g['id'] for g in grups), t_pdf))

    # 4) visor
    refs = None
    if not a.sense_visor:
        refs = genera_fitxers_visor(grups, cfg, pdf, print)
        index_html(index_origen, grups, os.path.join(L.WEB, 'index.html'), edicio)
        for f in ('logo.png', 'favicon.ico', 'favicon.svg'):
            if os.path.exists(os.path.join(recursos, f)):
                shutil.copyfile(os.path.join(recursos, f), os.path.join(L.WEB, f))
        # cobertura del cercador: codis trobats per grup
        for i, g in enumerate(grups):
            cs = {c for pg in refs['pages'] if pg['g'] == i for c in pg['c']}
            g['codis'] = len(cs)
            g['pagines_taula'] = sum(1 for pg in refs['pages'] if pg['g'] == i)
        print('Visor: index.html + references/search-text/relations a web/ | codis per grup: ' +
              ', '.join('%s=%d' % (g['id'], g['codis']) for g in grups))

    mapa = {'generat': time.strftime('%Y-%m-%dT%H:%M:%S'), 'edicio': edicio, 'pagines': total, 'pdf': pdf,
            'grups': [{k: g[k] for k in ('n', 'id', 'nom', 'start', 'end', 'pagines', 'pdf', 'contra', 'codis', 'pagines_taula') if k in g}
                      for g in grups]}
    L.escriu_json(os.path.join(L.ESTAT_DIR, 'mapa.json'), mapa)
    L.escriu_json(os.path.join(L.ESTAT_DIR, 'munta.json'),
                  {'signatura': L.signatura_muntatge(cfg, ns), 'muntat': mapa['generat'], 'segons': round(time.time() - t0, 1)})
    print('Catàleg muntat en %.0f s -> %s' % (time.time() - t0, L.WEB))


if __name__ == '__main__':
    main()
