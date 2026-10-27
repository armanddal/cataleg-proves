"""Utilitats compartides pel càrregador, el generador de configuració i el renderitzador dels grups del catàleg (qualsevol G01..G16).

- noms ES/EN/FR de les famílies a partir dels títols de pàgina del .pub (que porten els tres idiomes enganxats);
- mapa de columnes (clau del gN.yaml -> codi de columna d'Odoo);
- icones de capçalera per grup.
"""
import glob, os, re, shutil
import yaml

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DADES = os.environ.get('CATALEG_DADES') or os.path.join(ROOT, 'dades')      # CATALEG_DADES: carpeta de dades alternativa (proves aïllades)
GRUPS = os.path.normpath(os.path.join(ROOT, '..', 'grups'))          # projecte de l'extracció (només lectura): dades/gN.yaml, assets/gN/, pdf-posicio/
ZW = '​‌‍﻿'
LANGS = ('es', 'en', 'fr')


def yaml_load(path):
    return yaml.safe_load(open(path, encoding='utf8'))


def ruta_dades(grup):
    """dades/gN.yaml d'aquesta carpeta (còpia congelada: la càrrega a Odoo es va fer amb ella) o, si no n'hi ha, la de ../grups/dades/ (extracció)."""
    for r in (os.path.join(DADES, f'g{grup}.yaml'), os.path.join(GRUPS, 'dades', f'g{grup}.yaml')):
        if os.path.exists(r): return r
    return None


def ruta_posicio(grup):
    """Valors per posició del PDF publicat (gN-columnes.yaml): la còpia local o la de ../grups/pdf-posicio/dades/; None si el grup no en té."""
    for r in (os.path.join(DADES, f'g{grup}-columnes.yaml'), os.path.join(GRUPS, 'pdf-posicio', 'dades', f'g{grup}-columnes.yaml')):
        if os.path.exists(r): return r
    return None


def grups_amb_dades():
    ns = set()
    for d in (DADES, os.path.join(GRUPS, 'dades')):
        for f in glob.glob(os.path.join(d, 'g[0-9]*.yaml')):
            m = re.fullmatch(r'g(\d+)\.yaml', os.path.basename(f))
            if m: ns.add(int(m.group(1)))
    return sorted(ns)


def carrega_dades(grup):
    """Dades del grup (pàgines genèriques, plantilles, fotos). Deixa a assets/gN les imatges que hi falten (còpia des de ../grups/assets/gN)."""
    r = ruta_dades(grup)
    if r is None: raise SystemExit(f'No hi ha dades per al grup {grup}: ni dades/g{grup}.yaml ni ../grups/dades/g{grup}.yaml')
    assegura_assets(grup)
    return yaml_load(r)


def assegura_assets(grup):
    """Copia a assets/gN les imatges de ../grups/assets/gN que encara no hi són (mai en sobreescriu)."""
    src = os.path.join(GRUPS, 'assets', f'g{grup}'); dst = os.path.join(ROOT, 'assets', f'g{grup}')
    if not os.path.isdir(src): return 0
    os.makedirs(dst, exist_ok=True); n = 0
    for f in os.listdir(src):
        if not os.path.exists(os.path.join(dst, f)) and os.path.isfile(os.path.join(src, f)):
            shutil.copy2(os.path.join(src, f), os.path.join(dst, f)); n += 1
    return n


def dirs_assets(grup):
    """Ordre de cerca d'un fitxer d'imatge: assets/gN (el del grup), els altres assets/g* d'aquí i, per últim, els de ../grups/assets/."""
    def num(p): return int(re.sub(r'\D', '', os.path.basename(p)) or 0)
    locals_ = sorted(glob.glob(os.path.join(ROOT, 'assets', 'g[0-9]*')), key=num)
    altres = sorted(glob.glob(os.path.join(GRUPS, 'assets', 'g[0-9]*')), key=num)
    out = [os.path.join(ROOT, 'assets', f'g{grup}')] + [d for d in locals_ if num(d) != grup] + altres
    return [d for d in dict.fromkeys(out) if os.path.isdir(d)]


def cerca_asset(grup, nom, glob_ext=False):
    """Camí relatiu a l'arrel (assets/gX/nom) d'una imatge. Si només és a ../grups/assets/gX, se'n deixa una còpia a assets/gX. None si no existeix."""
    for d in dirs_assets(grup):
        f = sorted(glob.glob(os.path.join(d, glob.escape(nom) + '.*'))) if glob_ext else ([os.path.join(d, nom)] if os.path.exists(os.path.join(d, nom)) else [])
        if not f: continue
        gx = os.path.basename(d); b = os.path.basename(f[0])
        dst = os.path.join(ROOT, 'assets', gx, b)
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True); tmp = os.path.join(os.path.dirname(dst), '.%d-%s' % (os.getpid(), b)); shutil.copy2(f[0], tmp); os.replace(tmp, dst)
        return f'assets/{gx}/{b}'
    return None


def carrega_columnes_def():
    return yaml_load(os.path.join(DADES, 'columnes.yaml'))


# ----------------------------------------------------------------------------- text
def net(s):
    """Treu els espais de zero-width i col·lapsa espais."""
    return re.sub(r'\s+', ' ', ''.join(ch for ch in str(s or '') if ch not in ZW)).strip()


def treu_referencia_final(t):
    """«… RÉVERSIBLE 1», «… GN 1/1 2», «… CHAUFFAGE 3»: el número final és el cercle de referència de la foto, no del títol."""
    return re.sub(r'(?<=[A-Za-zÀ-ÿ/1])\s[1-3]$', '', t)


def trio_titol(t, accessori=False):
    """{'es','en','fr'} (parcial, amb idiomes enganxats al text) -> {'es','en','fr'} nets."""
    es = net(t.get('es')); en = net(t.get('en')); fr = net(t.get('fr'))
    if '□' in es and not en:
        p = [net(x) for x in es.split('□')]; p += [''] * (3 - len(p)); es, en, fr = p[:3]
    else:
        if not en:
            m = re.split(r'\s+E\s+', es, maxsplit=1)
            if len(m) == 2: es, en = net(m[0]), net(m[1])
        if en and not fr:
            m = re.split(r'\s+F\s+', en, maxsplit=1)
            if len(m) == 2: en, fr = net(m[0]), net(m[1])
        elif not fr and es:
            m = re.split(r'\s+F\s+', es, maxsplit=1)
            if len(m) == 2: es, fr = net(m[0]), net(m[1])
    if en and en in es: es = net(re.sub(r'\s+E\s*$', '', es.split(en)[0]))          # l'ES porta els altres idiomes enganxats
    if fr and fr in en: en = net(re.sub(r'\s+F\s*$', '', en.split(fr)[0]))
    if fr and fr in es: es = net(re.sub(r'\s+(?:E|F)\s*$', '', es.split(fr)[0]))
    if accessori: es, en, fr = (treu_referencia_final(x) for x in (es, en, fr))
    return {'es': es, 'en': en or es, 'fr': fr or es}


def clau_unica(noms_es, occ):
    n = re.sub(r'\s+', ' ', noms_es.strip()).casefold()
    occ[n] = occ.get(n, 0) + 1
    return noms_es if occ[n] == 1 else f'{noms_es}#{occ[n]}'


def trio(v):
    """str | {'es','en','fr'} (parcial) -> trio complet (l'idioma que falta diu el mateix que l'ES)."""
    if isinstance(v, dict):
        es = v.get('es') or v.get('en') or v.get('fr') or ''
        return {'es': es, 'en': v.get('en') or es, 'fr': v.get('fr') or es}
    return {'es': str(v), 'en': str(v), 'fr': str(v)}


# ----------------------------------------------------------------------------- columnes
_COLDEF = None


def coldef():
    """columnes.yaml (columnes ja decidides i carregades) + columnes-auto.yaml (les que genera_config proposa per a grups nous; editable).
    En cas de duplicat guanya columnes.yaml."""
    global _COLDEF
    if _COLDEF is None:
        c = carrega_columnes_def()
        auto = os.path.join(DADES, 'columnes-auto.yaml')
        if os.path.exists(auto):
            a = yaml_load(auto) or {}
            for k, v in (a.get('columnes') or {}).items(): c['columnes'].setdefault(k, v)
            for tp, m in (a.get('claus') or {}).items(): c['claus'].setdefault(tp, {}).update({k: v for k, v in m.items() if k not in c['claus'].get(tp, {})})
            for t, m in (a.get('taules') or {}).items(): c.setdefault('taules', {}).setdefault(t, {}).update(m)
        _COLDEF = c
    return _COLDEF


def reinicia_coldef():
    global _COLDEF
    _COLDEF = None


def codi_columna(grup, taula_id, clau, tipus):
    """Codi de columna d'Odoo per a la clau d'una taula del gN.yaml. None si no és enlloc (columna nova: la defineix genera_config)."""
    c = coldef()
    ex = (c.get('taules') or {}).get(f'g{grup}:{taula_id}', {})
    if clau in ex: return ex[clau]
    m = (c['claus'].get(tipus) or {})
    if clau in m: return m[clau]
    return clau if clau in c['columnes'] else None


def blocs_taula(claus):
    """Claus d'una taula (en ordre) -> (bloc 1, bloc 2, extra). Una taula «doble» té `codi_2`: des d'aquí fins a `codi_3` (o el final) és el
    segon bloc; `codi_3`, `codi_4`... (taules de 3-4 blocs) no es suporten: surten a `extra` (el generador els avisa)."""
    if 'codi_2' not in claus: return list(claus), [], []
    i2 = claus.index('codi_2')
    i3 = next((i for i, k in enumerate(claus) if re.fullmatch(r'codi_[3-9]', k)), len(claus))
    return list(claus[:i2]), list(claus[i2:i3]), list(claus[i3:])


# ----------------------------------------------------------------------------- icones
def diccionari_icones():
    """Tots els diccionaris hash -> {nom, clau}: el d'aquí (icones-grups.yaml) i els de ../grups/dades/icones*.yaml (grups nous)."""
    out = {}
    fonts = [os.path.join(DADES, 'icones-grups.yaml')] + sorted(glob.glob(os.path.join(GRUPS, 'dades', 'icones*.yaml')))
    for f in fonts:
        if not os.path.exists(f): continue
        for h, v in (yaml_load(f) or {}).items():
            if isinstance(v, dict) and v.get('nom'): out.setdefault(h + '@' + f, v)
    return out


_CLAUS_IC = None


def claus_icones():
    """Claus d'icona conegudes (les que pot dir x_cataleg_columna.icona)."""
    global _CLAUS_IC
    if _CLAUS_IC is None: _CLAUS_IC = {v['clau'] for v in diccionari_icones().values() if v.get('clau')}
    return _CLAUS_IC


def carrega_icones(grup):
    """clau d'icona -> camí relatiu a l'arrel (assets/gN/<nom>.<ext>); prefereix el fitxer del grup, després el d'un altre."""
    out = {}
    for v in diccionari_icones().values():
        clau = v.get('clau')
        if not clau or clau in out: continue
        f = cerca_asset(grup, v['nom'], glob_ext=True)
        if f: out[clau] = f
    return out


# ----------------------------------------------------------------------------- joc estàndard d'icones (capçalera «text primer»)
def carrega_estandard():
    return yaml_load(os.path.join(DADES, 'icones-estandard.yaml'))


def fitxer_icona(grup, nom):
    """assets/gN/<nom> del grup, o el d'un altre grup si no hi és; None si no existeix enlloc."""
    return cerca_asset(grup, nom)


def icona_estandard(est, grup, codi):
    """Icona estàndard d'una columna (camí relatiu a l'arrel) o None. Variants `_N` i àlies hereten de la base."""
    ic = est.get('icones', {})
    for c in (codi, est.get('alies', {}).get(codi), re.sub(r'_\d+$', '', codi)):
        if c and c in ic: return fitxer_icona(grup, ic[c])
    return None


def nom_net(nom):
    """Treu del nom de columna els sufixos tècnics «(2)», «(3)», «(texto)»: «Fuegos gas (2)» -> «Fuegos gas»."""
    return re.sub(r'\s*\((?:\d+|texto|text)\)\s*$', '', nom or '').strip()


# ----------------------------------------------------------------------------- correccions per grup (dades/correccions.yaml)
_CORR = None


def correccions():
    global _CORR
    if _CORR is None:
        f = os.path.join(DADES, 'correccions.yaml')
        _CORR = (yaml_load(f) if os.path.exists(f) else None) or {}
    return _CORR


def corr(seccio, grup=None, *resta):
    """Valor de correccions.yaml[seccio]; amb grup (i parts) busca la clau «gN:part:part». Sense grup torna tot el diccionari de la secció."""
    d = correccions().get(seccio) or {}
    if grup is None: return d
    return d.get(':'.join([f'g{grup}', *map(str, resta)]))


def repara_faltes_es(t):
    """Corregeix al text castellà les faltes conegudes de les dades originals (correccions.yaml: faltes_text), només paraules senceres."""
    for mal, be in (corr('faltes_text') or {}).items():
        t = re.sub(r'\b' + re.escape(mal) + r'\b', be, t)
    return t


def ordre_carrega():
    """Ordre en què els grups es carreguen a Odoo (un producte és del primer grup que el marca). Defecte: els de cataleg-config-grups.yaml
    (`ordre_carrega`), després la resta per número."""
    f = os.path.join(DADES, 'cataleg-config-grups.yaml')
    base = ((yaml_load(f) or {}).get('ordre_carrega') or []) if os.path.exists(f) else []
    return list(base) + [n for n in range(1, 17) if n not in base]


def es_bloc2(clau, claus_taula):
    """Compatibilitat: la clau és del segon bloc d'una taula doble."""
    return clau in blocs_taula(list(claus_taula))[1]


def titol_pagina(p):
    """Títol ES/EN/FR d'una pàgina de producte: capcalera.titol; si l'extractor no el posa (G11+), el text de la banda de títol de
    `textos_pagina` (el de dalt de tot i ample: y < 1 cm, ample > 10 cm). None si no n'hi ha."""
    t = (p.get('capcalera') or {}).get('titol')
    if t: return trio_titol(t)
    cand = [q for q in (p.get('textos_pagina') or []) if q.get('pos') and q['pos']['y'] < 1.0 and q['pos']['w'] > 10 and net(q.get('text'))]
    if not cand: return None
    txt = net(min(cand, key=lambda q: q['pos']['y'])['text'])
    tr = trio_titol({'es': txt})
    return {l: re.sub(r'\s*/\s*$', '', v).strip() for l, v in tr.items()}
