"""Pàgines genèriques del catàleg (portada, índex, informació, simbologia, condicions, contraportada, pàgines d'imatge) i fotos de producte
a Odoo: conversió yaml <-> contingut d'Odoo (x_cataleg_pagina, x_cataleg_pagina_imatge, product.template.x_cataleg_imatge).

Principi: Odoo guarda el CONTINGUT (textos en ES/EN/FR/DE, imatges); el DISSENY (posicions, columnes, colors, plantilles) continua a dades/gN.yaml.
  - carrega_pagines.py  : extreu() el contingut d'un tema del yaml i el carrega a Odoo.
  - font_odoo/renderitza: llegeix_pagines() el llegeix d'Odoo i aplica_odoo() el posa sobre les plantilles del yaml.

Tema = el que és UNA pàgina d'Odoo: una pàgina d'informació ES amb les fotos + la pàgina EN|FR que la segueix són el MATEIX tema (el text és el
mateix contingut, traduït). El cos és Html traduïble: es_ES / en_US / fr_FR / de_DE. Odoo tradueix l'Html per TERMES (un per bloc), així que
tots els idiomes d'un tema han de tenir el mateix esquelet: si els blocs ES/EN/FR quadren (mateix nombre i tipus) cada bloc és un <p>/<h3>;
si no quadren (extracció irregular) el tema es desa en «mode línies»: un sol <p> per idioma, amb <br> entre línies i els títols en negreta.
"""
import copy, hashlib, html as H, io, os, re
from lxml import html as LH
import grup_util as U

ROOT = U.ROOT
IDIOMES = ('es', 'en', 'fr', 'de')
LANG_ODOO = {'es': 'es_ES', 'en': 'en_US', 'fr': 'fr_FR', 'de': 'de_DE'}
MARCA_RE = re.compile(r'g(\d+)\.yaml\s+(p\d+(?:\+p\d+)*)')
PLACEHOLDER = '-'                    # unitat sense text en un idioma (p. ex. condicions sense versió anglesa d'una secció)
MAX_PAG = 1600                       # px màxims de les imatges de pàgina
MAX_FOTO = 1200                      # px màxims de la foto de catàleg d'un producte
TIPUS_ODOO = {'portada_grup': 'portada', 'index_grup': 'indice', 'informacio_general': 'informacion', 'simbologia': 'simbologia',
              'condicions_venda': 'condiciones', 'contraportada': 'contraportada', 'pagina_imatge': 'otra'}
RANG = {'portada': 0, 'indice': 1, 'contraportada': 9}


def esc(t): return H.escape(t, quote=False)


# ----------------------------------------------------------------------------- HTML <-> línies
def lin(k, t, refs=None):
    """Una línia de text: k = 'h' (títol) | 'p' (text); refs = números de cercle de referència."""
    return {'k': k, 't': U.net(t), 'r': [int(r) for r in (refs or [])]}


def _inner(l, negreta=False):
    s = esc(l['t']) + ''.join(f' <span class="ref">{r}</span>' for r in l['r'])
    return f'<b>{s}</b>' if negreta else s


def unitat_html(u):
    """Unitat (llista de línies) -> bloc HTML. Una línia: <h3> o <p>; diverses: un <p> amb <br> (els títols en negreta)."""
    if len(u) == 1:
        return f'<h3>{_inner(u[0])}</h3>' if u[0]['k'] == 'h' else f'<p>{_inner(u[0])}</p>'
    return '<p>' + '<br>'.join(_inner(l, l['k'] == 'h') for l in u) + '</p>'


def terme(u):
    """Text del terme traduïble d'una unitat (el contingut del bloc)."""
    h = unitat_html(u)
    return re.sub(r'^<(?:h3|p)>|</(?:h3|p)>$', '', h)


def html_unitats(units): return ''.join(unitat_html(u) for u in units)


def parseja_html(h):
    """HTML d'Odoo -> llista d'unitats (cada una, llista de línies {k,t,r}). Entén h1-h6 (títol), p/li/div (línies separades per <br>; una
    línia tota en negreta és un títol), <span class="ref">n</span> (cercle de referència)."""
    if not h or not U.net(re.sub(r'<[^>]+>', ' ', h)): return []
    arrel = LH.fragment_fromstring('<div>' + h + '</div>')
    units = []

    def linies(el):
        out = []; cur = {'t': '', 'nb': False, 'r': []}

        def tanca():
            t = U.net(cur['t'])
            if t or cur['r']:
                out.append(lin('p' if cur['nb'] else 'h', t, cur['r']))
            cur.update(t='', nb=False, r=[])

        def afegeix(txt, neg):
            if not txt: return
            cur['t'] += txt
            if not neg and txt.strip(): cur['nb'] = True

        def camina(n, neg):
            afegeix(n.text, neg)
            for ch in n:
                tag = ch.tag if isinstance(ch.tag, str) else ''
                if tag == 'br': tanca()
                elif tag == 'span' and 'ref' in (ch.get('class') or '').split():
                    m = re.search(r'\d+', ch.text_content() or '')
                    if m: cur['r'].append(int(m.group()))
                elif tag in ('b', 'strong'): camina(ch, True)
                else: camina(ch, neg)
                afegeix(ch.tail, neg)
        camina(el, False); tanca()
        return out

    def recorre(el):
        for ch in el:
            tag = ch.tag if isinstance(ch.tag, str) else ''
            if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                t = U.net(ch.text_content())
                if t: units.append([lin('h', t)])
            elif tag in ('ul', 'ol', 'section', 'article'): recorre(ch)
            elif tag in ('p', 'li', 'div'):
                if any(isinstance(c.tag, str) and c.tag in ('p', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'div') for c in ch): recorre(ch)
                else:
                    ls = linies(ch)
                    if ls:
                        # una sola línia en negreta dins <p> també és un títol; sense negreta: text. Si hi ha diverses línies es queden com a unitat.
                        units.append(ls)
            elif tag in ('hr', 'br'): continue
            else:
                ls = linies(ch)
                if ls: units.append(ls)
        if arrel.text and U.net(arrel.text) and el is arrel:
            units.insert(0, [lin('p', arrel.text)])
    recorre(arrel)
    return units


def dif_unitats(a, b):
    """True si dues llistes d'unitats difereixen (text, tipus de línia i cercles; sense comptar caràcters invisibles)."""
    n = lambda us: [[(x['k'], U.net(x['t']), tuple(x['r'])) for x in u] for u in us]
    return n(a) != n(b)


def linies_planes(units):
    return [l for u in units for l in u]


# ----------------------------------------------------------------------------- cos traduïble
def construeix_cos(per_idioma):
    """per_idioma: {'es': [línies], 'en': [...], ...} (només idiomes amb text) -> dict amb
         base (idioma del valor d'origen en_US), html_base, unitats {idioma: [unitat]}, mode ('blocs'|'linies'), avisos.
    La resta d'idiomes es carreguen amb update_field_translations (terme del base -> terme de l'idioma)."""
    idiomes = [l for l in IDIOMES if per_idioma.get(l)]
    if not idiomes: return None
    base = 'en' if 'en' in idiomes else idiomes[0]
    ref = per_idioma[base]
    mode = 'blocs'
    if not all(len(per_idioma[l]) == len(ref) and [x['k'] for x in per_idioma[l]] == [x['k'] for x in ref] for l in idiomes): mode = 'linies'
    unitats = {l: ([[x] for x in per_idioma[l]] if mode == 'blocs' else [per_idioma[l]]) for l in idiomes}
    if mode == 'blocs': unitats = desambigua(unitats, base)
    return {'base': base, 'html_base': html_unitats(unitats[base]), 'unitats': unitats, 'mode': mode, 'idiomes': idiomes}


def construeix_cos_unitats(unitats_per_idioma):
    """Com construeix_cos però amb unitats ja fetes (condicions: una unitat per secció, el mateix nombre a tots els idiomes)."""
    idiomes = [l for l in IDIOMES if unitats_per_idioma.get(l)]
    if not idiomes: return None
    base = 'en' if 'en' in idiomes else idiomes[0]
    return {'base': base, 'html_base': html_unitats(unitats_per_idioma[base]), 'unitats': {l: unitats_per_idioma[l] for l in idiomes},
            'mode': 'seccions', 'idiomes': idiomes}


def desambigua(unitats, base):
    """Dos blocs amb el mateix text d'origen però traducció diferent no es poden expressar com a diccionari terme->terme: al bloc repetit
    del idioma base se li afegeix un caràcter d'amplada zero (parseja_html els treu: no es veuen ni surten al catàleg)."""
    altres = [l for l in unitats if l != base]
    res = {l: [list(u) for u in us] for l, us in unitats.items()}
    vist = {}
    for i, ub in enumerate(res[base]):
        trans = tuple(terme(res[l][i]) for l in altres)
        k = 0
        while True:
            u = [dict(x) for x in ub]; u[-1]['t'] = u[-1]['t'] + U.ZW[0] * k
            clau = terme(u)
            if vist.setdefault(clau, trans) == trans: break
            k += 1
        res[base][i] = u
    return res


def traduccions_cos(cos, termes_odoo):
    """Diccionari per update_field_translations: {lang_odoo: {terme d'origen (tal com el dóna Odoo): terme traduït}}.
    termes_odoo: llista ordenada de termes únics d'origen que Odoo ha extret del html_base. Retorna (dict, error|None)."""
    base = cos['base']; ordre = list(dict.fromkeys(terme(u) for u in cos['unitats'][base]))
    if len(ordre) != len(termes_odoo):
        return {}, f'Odoo ha extret {len(termes_odoo)} termes i el contingut en té {len(ordre)}'
    mapa_src = dict(zip(ordre, termes_odoo))
    out = {}
    for l in cos['idiomes']:
        if l == base: continue
        d = {}
        for a, b in zip(cos['unitats'][base], cos['unitats'][l]):
            d[mapa_src[terme(a)]] = terme(b)
        out[LANG_ODOO[l]] = d
    return out, None


def termes_html(h):
    """Termes d'origen (únics, en ordre) d'un html tal com els guardem: el que hi ha dins de cada bloc."""
    return list(dict.fromkeys(terme(u) for u in parseja_html(h)))


# ----------------------------------------------------------------------------- imatges
def prepara_imatge(path, maxim, forca_jpeg=False):
    """Fitxer d'imatge -> (bytes, extensió). Redimensiona a <= maxim px. JPEG qualitat 85 (sobre blanc), o PNG si té transparència real
    (portada i icones sobre fons de color) i no es força JPEG."""
    from PIL import Image
    im = Image.open(path)
    transp = im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info)
    if transp:
        im = im.convert('RGBA'); alfa = im.split()[-1]
        transp = alfa.getextrema()[0] < 250
    im.thumbnail((maxim, maxim), Image.LANCZOS)
    b = io.BytesIO()
    if transp and not forca_jpeg:
        im = im.convert('RGBA') if im.mode != 'RGBA' else im
        im.save(b, 'PNG', optimize=True); return b.getvalue(), 'png'
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA'); fons = Image.new('RGB', im.size, 'white'); fons.paste(im, mask=im.split()[-1]); im = fons
    im.convert('RGB').save(b, 'JPEG', quality=85, optimize=True)
    return b.getvalue(), 'jpg'


def ruta_asset(grup, rel):
    """Camí absolut d'un asset relatiu a l'arrel (assets/gN/x.png); si no hi és, el cerca als altres grups. None si no existeix."""
    if not rel: return None
    p = os.path.join(ROOT, rel)
    if os.path.exists(p): return p
    r = U.cerca_asset(grup, os.path.basename(rel))
    return os.path.join(ROOT, r) if r else None


# ----------------------------------------------------------------------------- temes
def pagina_publicada(p):
    return not p.get('posterior_a_contraportada') and not p.get('fora_del_pdf_publicat')


def idiomes_columnes(p):
    """Idioma de cada columna de text d'una pàgina d'informació. Dues columnes «en» seguides són EN + FR (extracció G5)."""
    ids = [c['idioma'] for c in p.get('columnes', [])]
    if ids == ['en', 'en']: ids = ['en', 'fr']
    return ids


def temes(dades):
    """Pàgines del .pub -> temes (una pàgina d'Odoo cadascun), en ordre. Tema: {tipus, pagines[], ids[], marca}."""
    res = []; obert = None; prev_info = None
    pags = [p for p in dades['pagines'] if pagina_publicada(p) and p['tipus'] in TIPUS_ODOO]
    for p in pags:
        t = p['tipus']
        if t == 'informacio_general':
            amb_es = 'es' in idiomes_columnes(p)
            if obert is not None and prev_info is not None and not amb_es and prev_info is obert:
                obert['pagines'].append(p)
            else:
                obert = {'tipus': 'informacion', 'pagines': [p]}; res.append(obert)
            prev_info = obert
            continue
        prev_info = None
        if t == 'index_grup':
            ex = next((x for x in res if x['tipus'] == 'indice'), None)
            if ex: ex['pagines'].append(p)
            else: res.append({'tipus': 'indice', 'pagines': [p]})
            continue
        res.append({'tipus': TIPUS_ODOO[t], 'pagines': [p]})
    for x in res:
        x['ids'] = [p['id'] for p in x['pagines']]
    return res


def marca_tema(grup, tema):
    return f"g{grup}.yaml " + '+'.join(tema['ids'])


def marca_de_notes(notes):
    m = MARCA_RE.search(notes or '')
    return (int(m.group(1)), m.group(2).split('+')) if m else None


def ancoratges(dades, cfg, FO):
    """Per a cada pàgina genèrica: clau (nominal) de la família que la segueix al .pub (None = al final). Mateixa regla que Constructor.construeix."""
    pags = [p for p in FO.pagines_publicades(dades) if p['tipus'] in FO.TIPUS_CONEGUTS]
    dd = dict(dades, pagines=pags)
    pl = FO.plantilles(dd, cfg); ordre = [x['clau'] for x in pl]
    cnt = 0; pos = {}
    for p in pags:
        if p['tipus'] in ('producte', 'accessoris'): cnt += sum(1 for x in pl if x['pagina'] is p)
        elif p['tipus'] not in ('portada_grup', 'index_grup'): pos[p['id']] = ordre[cnt:]
    return pos


# ----------------------------------------------------------------------------- noms (títols)
def noms_tema(pagines):
    """Títol ES/EN/FR d'un tema a partir de la capçalera de les seves pàgines (la d'informació EN|FR porta «E ... F ...» enganxat)."""
    es = en = fr = ''
    for p in pagines:
        o = (p.get('capcalera') or {}).get('titol') or p.get('capcalera_text') or {}
        if not o: continue
        raw = U.net(o.get('es'))
        m = re.match(r'^E\s+(.+?)\s+F\s+(.+)$', raw)
        if m and not o.get('en'):
            en, fr = en or m.group(1), fr or m.group(2); continue
        t = U.trio_titol(o)
        if t['es'] and not es: es = t['es']
        if t['en'] and t['en'] != t['es']: en = en or t['en']
        if t['fr'] and t['fr'] != t['es']: fr = fr or t['fr']
    base = en or es or fr
    return {'es': es or base, 'en': en or es or base, 'fr': fr or en or es or base}


def _mostra_titol(orig):
    """Quins idiomes mostra ara la capçalera d'aquesta pàgina: {es, en, fr} de bools."""
    o = orig or {}
    raw = U.net(o.get('es'))
    if re.match(r'^E\s+(.+?)\s+F\s+(.+)$', raw) and not o.get('en'):
        return {'es': False, 'en': True, 'fr': True}
    t = U.trio_titol(o) if o else {'es': '', 'en': '', 'fr': ''}
    return {'es': bool(t['es']), 'en': bool(t['en']) and (bool(o.get('en')) or t['en'] != t['es']),
            'fr': bool(t['fr']) and (bool(o.get('fr')) or t['fr'] != t['es'])}


def titol_aplicat(orig, noms):
    m = _mostra_titol(orig)
    d = {'es': noms['es'] if m['es'] else ''}
    if m['en']: d['en'] = noms['en']
    if m['fr']: d['fr'] = noms['fr']
    return d


# ----------------------------------------------------------------------------- extracció (yaml -> contingut per a Odoo)
def _conf_imatge(grup, rel, llegenda=None, codis=''):
    return {'rel': rel, 'llegenda': llegenda, 'codis': codis}


def sim_fix(s, fixos):
    """Símbol fix de la llegenda (no és una columna): icona amb nom base a simbols_fixos."""
    ic = s.get('icona')
    if not ic: return False
    b = os.path.splitext(os.path.basename(ic))[0]
    return any(b == f or b.startswith(f + '-e-') for f in fixos)


def extreu(tema, grup):
    """Contingut d'un tema per a Odoo: {tipus, noms{es,en,fr}, cos (construeix_cos|None), imatges[{rel,llegenda,codis}], avisos}."""
    t = tema['tipus']; ps = tema['pagines']; av = []
    r = {'tipus': t, 'imatges': [], 'cos': None, 'avisos': av}
    est = U.carrega_estandard()
    if t == 'portada':
        p = ps[0]; g = p['grup']
        r['noms'] = {'es': g['nom'], 'en': g['nom'], 'fr': g['nom']}
        tc = p['titol_catalog']
        r['cos'] = construeix_cos({l: [lin('p', tc[l])] for l in IDIOMES if tc.get(l)})
        for im in p['imatges']:
            if im.get('rol') in ('foto_producte', 'logo'): r['imatges'].append(_conf_imatge(grup, im['asset']))
    elif t == 'indice':
        p = ps[0]
        r['noms'] = {'es': 'Índice', 'en': 'Index', 'fr': 'Index'}
        bl = p.get('banda_lateral') or ''
        r['cos'] = construeix_cos({'es': [lin('p', bl)]}) if bl.strip() else None
        vistos = set()
        for pg in ps:
            for lg in sorted(pg.get('banda_logos', []), key=lambda l: l['pos']['y']):
                if lg['asset'] in vistos: continue
                vistos.add(lg['asset']); r['imatges'].append(_conf_imatge(grup, lg['asset']))
    elif t == 'informacion':
        r['noms'] = noms_tema(ps)
        per = {l: [] for l in IDIOMES}
        for p in ps:
            for c, l in zip(p.get('columnes', []), idiomes_columnes(p)):
                for q in c['paragrafs']:
                    if U.net(q['text']): per[l].append(lin('h' if q['role'] == 'titol' else 'p', q['text'], q.get('refs')))
        r['cos'] = construeix_cos(per)
        for p in ps:
            for f in p.get('fotos', []):
                r['imatges'].append(_conf_imatge(grup, f['asset'], None, '' if f.get('referencia') is None else str(f['referencia'])))
            for i in p.get('insignies', []) or []:
                r['imatges'].append(_conf_imatge(grup, i['asset']))
    elif t == 'simbologia':
        p = ps[0]; tt = noms_tema(ps)
        r['noms'] = tt
        eq = p.get('equivalencies', [])
        if len(eq) == 1: eq = [x for x in re.split(r'\s+(?=1 (?:Kw|Kcal|HP))', eq[0]) if x]
        r['cos'] = construeix_cos({'es': [lin('p', x) for x in eq]}) if eq else None
        fixos = set(est.get('simbols_fixos', []))
        for s in p['simbols']:
            if sim_fix(s, fixos):
                r['imatges'].append(_conf_imatge(grup, s['icona'], U.trio_titol(s['text'])))
    elif t == 'condiciones':
        p = ps[0]
        nm = noms_tema(ps)
        barra = next((s['barra_idiomes'] for s in p['seccions'] if 'barra_idiomes' in s), {})
        r['noms'] = {'es': nm['es'], 'en': U.net(barra.get('en')) or nm['en'], 'fr': U.net(barra.get('fr')) or nm['fr']}
        es_secs = [s for s in p['seccions'] if (s.get('textos') or {}).get('es')]
        bi = [s for s in p['seccions'] if s.get('textos') and 'es' not in s['textos']]
        un = {'es': [], 'en': [], 'fr': []}
        for s in es_secs:
            un['es'].append([lin('p', q['text']) for q in s['textos']['es'] if U.net(q['text'])])
            ic = s.get('icona')
            r['imatges'].append(_conf_imatge(grup, ic))
            m = next((b for b in bi if b.get('icona') == ic), None)
            en = fr = ''
            if m:
                tx = m['textos']
                en = U.net(' '.join(q['text'] for q in tx.get('en', [])))
                fr = U.net(' '.join(q['text'] for q in tx.get('fr', [])))
                if en and not fr:
                    mm = re.split(r'\s+F\s+', en, maxsplit=1)
                    if len(mm) == 2: en, fr = U.net(mm[0]), U.net(mm[1])
            k_ = len(un['es'])
            un['en'].append([lin('p', en or PLACEHOLDER * k_)]); un['fr'].append([lin('p', fr or PLACEHOLDER * k_)])
        r['cos'] = construeix_cos_unitats(un)
    elif t == 'contraportada':
        p = ps[0]; ct = p['capcalera_text']
        r['noms'] = {'es': 'Contraportada', 'en': 'Back cover', 'fr': 'Quatrième de couverture'}
        r['cos'] = construeix_cos({l: [lin('p', ct[l])] for l in IDIOMES if ct.get(l)})
        r['imatges'].append(_conf_imatge(grup, p['imatges'][0]['asset']))
    elif t == 'otra':
        p = ps[0]
        r['noms'] = {'es': f'Página de imagen ({p["id"]})', 'en': f'Image page ({p["id"]})', 'fr': f"Page d'image ({p['id']})"}
        r['imatges'].append(_conf_imatge(grup, p['imatge_pagina']['asset']))
    return r


# ----------------------------------------------------------------------------- aplicació (contingut d'Odoo -> pàgines del yaml)
def _text_lang(op, l):
    return op['cos'].get(l) or ''


def _unitats_lang(op, l): return parseja_html(_text_lang(op, l))


def reparteix(linies, n):
    """Reparteix les línies de text en n columnes de longitud semblant (en ordre)."""
    if n <= 1 or not linies: return [linies] + [[] for _ in range(max(n - 1, 0))]
    pes = [len(x['t']) + 25 for x in linies]; total = sum(pes); out = [[]]; acc = 0
    for x, w in zip(linies, pes):
        if len(out) < n and acc + w / 2 > total / n * len(out): out.append([])
        out[-1].append(x); acc += w
    while len(out) < n: out.append([])
    return out


def _paragrafs(linies, estil_mida, comptador=None):
    """comptador: llista d'un element amb l'últim número de referència donat; si es passa, cada «□» del text d'una línia (el marcador que
    escriu qui edita a Odoo) es converteix en el següent número de cercle (1, 2, 3...), com feia estructura_text amb el paràgraf pla."""
    out = []
    for x in linies:
        q = {'role': 'titol' if x['k'] == 'h' else 'text', 'text': x['t']}
        if x['r']: q['refs'] = list(x['r'])
        elif comptador is not None and x['k'] != 'h' and '\u25a1' in x['t']:
            n = x['t'].count('\u25a1')
            q['refs'] = list(range(comptador[0] + 1, comptador[0] + 1 + n)); comptador[0] += n
            q['text'] = U.net(x['t'].replace('\u25a1', ''))
        if estil_mida and q['role'] == 'text': q['estil'] = {'mida': estil_mida}
        out.append(q)
    return out


def _mida_orig(c):
    for q in c.get('paragrafs', []):
        if q['role'] == 'text' and q.get('estil', {}).get('mida'): return q['estil']['mida']
    return None


def _marca(p, op, tema):
    p['_odoo'] = True; p['_odoo_id'] = op['id']; p['_ancora_fam_id'] = op.get('familia_id'); p['_seq'] = op['sequence']
    return p


def _imatge_n(op, j): return op['imatges'][j] if j < len(op['imatges']) else None


def llegenda_bloc(t):
    """Text d'una llegenda de bloc (camp d'UNA línia: «# TÍTOL | ítem | ítem») -> {'titol', 'items', 'numerat'}. Separadors: `|` o salt de línia.
    `#` al començament = llista numerada 1..n (sense: vinyetes)."""
    parts = [x.strip() for x in re.split(r'\s*\|\s*|\r?\n', t or '') if x.strip()]
    if not parts: return None
    tit = parts[0]; num = tit.startswith('#')
    return {'titol': tit.lstrip('#').strip(), 'items': parts[1:], 'numerat': num}


def es_blocs(op):
    """Pàgina d'informació de tipus «blocs»: alguna de les seves imatges té llegenda."""
    return any(any((v or '').strip() for v in (n.get('llegenda') or {}).values()) for n in op['imatges'])


def blocs_de(op):
    """Imatges d'Odoo (en ordre de `sequence`) -> blocs del full: files de fins a 3 fotos (les sense llegenda, amb la referència = `codis`) i,
    per a cada imatge amb llegenda, un bloc a ample complet (imatge + una columna de text per idioma amb text diferent)."""
    out = []; fila = None
    for n in op['imatges']:
        ll = n.get('llegenda') or {}; c = (n.get('codis') or '').strip()
        if any((v or '').strip() for v in ll.values()):
            fila = None; cols = []; vistos = set()
            for l in ('es', 'en', 'fr'):
                t = (ll.get(l) or '').strip()
                if not t or t in vistos: continue
                vistos.add(t); b = llegenda_bloc(t)
                if b: cols.append(dict(b, idioma=l))
            out.append({'k': 'bloc', 'asset': n['path'], 'num': c, 'cols': cols})
        else:
            if fila is None or len(fila['fotos']) >= 3: fila = {'k': 'fotos', 'fotos': []}; out.append(fila)
            fila['fotos'].append({'asset': n['path'], 'referencia': int(c) if c.isdigit() else None})
    return out


def blocs_doc(op, avisos):
    """Blocs de la pàgina a partir del seu Google Doc (scripts/llegeix_doc_pagina.py), o None si la pàgina no en té.
    Cada «[FOTO n]» és la imatge d'Odoo amb `codis` = n; una imatge enganxada al Doc es fa servir tal qual."""
    import llegeix_doc_pagina as LD
    doc = LD.doc_de_pagina(op['id'])
    if not doc: return None
    try: r = LD.llegeix_doc(LD.html_del_doc(doc))
    except Exception as e:
        avisos.append(f"pàgina d'Odoo {op['id']}: no es pot llegir el Doc {doc} ({e}); es fa servir el contingut d'Odoo"); return None
    avisos += [f"Doc {doc}: {a}" for a in r['avisos']]
    per_ref = {}
    for n in op['imatges']:
        c = (n.get('codis') or '').strip()
        if c.isdigit(): per_ref.setdefault(int(c), n['path'])
    usades = set()
    def foto(f):
        if f is None: return None
        if 'imatge' in f: return {'asset': f['imatge'], 'referencia': None}
        a = per_ref.get(f['referencia'])
        if a is None: avisos.append(f"Doc {doc}: [FOTO {f['referencia']}] no existeix a la pàgina d'Odoo {op['id']}"); return None
        usades.add(f['referencia']); return {'asset': a, 'referencia': f['referencia']}
    out = []
    for it in r['items']:
        if it['k'] == 'fotos':
            fs = [x for x in (foto(f) for f in it['fotos']) if x]
            for i in range(0, len(fs), 3): out.append({'k': 'fotos', 'fotos': fs[i:i + 3]})
        elif it['k'] == 'bloc':
            f = foto(it['foto'])
            if f: out.append({'k': 'bloc', 'asset': f['asset'], 'num': str(f['referencia'] or ''), 'cols': it['cols']})
        else: out.append(it)
    sobren = sorted(set(per_ref) - usades)
    if sobren: avisos.append(f"Doc {doc}: les fotos d'Odoo amb referència {sobren} no són al Doc; no surten")
    return out


def aplica_tema(tema, op, grup, avisos):
    """Pàgines del yaml del tema amb el contingut d'Odoo (op) al damunt. Retorna llista de pàgines (còpies)."""
    t = tema['tipus']; ps = copy.deepcopy(tema['pagines']); est = U.carrega_estandard()
    noms = {l: op['noms'].get(l) or op['noms'].get('en') or '' for l in ('es', 'en', 'fr')}
    imgs = op['imatges']; j = 0
    if t == 'portada':
        p = ps[0]
        p['grup']['nom'] = op['noms']['en'] or p['grup']['nom']
        orig = p['titol_catalog']
        nou = {}
        for l in IDIOMES:
            if l in orig:
                u = _unitats_lang(op, l)
                nou[l] = ' '.join(x['t'] for x in linies_planes(u)) or orig[l]
        if nou: p['titol_catalog'] = nou
        k = 0; ims = []
        for im in p['imatges']:
            if im.get('rol') in ('foto_producte', 'logo'):
                n = _imatge_n(op, k); k += 1
                if n is None: continue                      # imatge treta a Odoo
                im['asset'] = n['path']
            ims.append(im)
        p['imatges'] = ims
        if len(imgs) > k: avisos.append(f"portada (Odoo {op['id']}): {len(imgs) - k} imatges de més sense lloc a la plantilla; no surten")
    elif t == 'indice':
        bl = ' '.join(x['t'] for x in linies_planes(_unitats_lang(op, 'es') or _unitats_lang(op, 'en')))
        mapa = {}; k = 0
        for pg in ps:
            for lg in sorted(pg.get('banda_logos', []), key=lambda l: l['pos']['y']):
                if lg['asset'] not in mapa:
                    n = _imatge_n(op, k); k += 1
                    mapa[lg['asset']] = n['path'] if n else None
        for pg in ps:
            if bl: pg['banda_lateral'] = bl
            pg['banda_logos'] = [dict(lg, asset=mapa[lg['asset']]) for lg in pg.get('banda_logos', []) if mapa.get(lg['asset'])]
    elif t == 'informacion':
        bl = blocs_doc(op, avisos)       # pàgina amb Google Doc (docs-pagines.yaml): estructura i text del Doc, fotos d'Odoo per referència
        if bl is None: bl = blocs_de(op) if es_blocs(op) else None
        if bl:       # mode «blocs»: la pàgina del .pub amb les fotos passa a ser la de blocs (sense columnes ni fotos fixes); la resta de pàgines del tema porten el cos
            i = next((k for k, q in enumerate(ps) if q.get('fotos')), 0); pb = ps[i]
            pb['columnes'] = []; pb['fotos'] = []; pb['blocs'] = bl
            for k_ in ('insignies', 'textos_pagina', 'decoracio'): pb.pop(k_, None)
        slots = {l: [] for l in IDIOMES}
        for pi, p in enumerate(ps):
            ids = idiomes_columnes(p)
            for ci, (c, l) in enumerate(zip(p.get('columnes', []), ids)):
                c['idioma'] = l; slots[l].append((p, c))
        for l, sl in slots.items():
            if not sl: continue
            linies_ = linies_planes(_unitats_lang(op, l))
            parts = reparteix(linies_, len(sl)); cmp_ = [0]
            for (p, c), pt in zip(sl, parts):
                c['paragrafs'] = _paragrafs(pt, _mida_orig(c), cmp_)
        for p in ps: p['columnes'] = [c for c in p.get('columnes', []) if c['paragrafs']]      # idioma sense text a Odoo: la columna no surt
        k = 0
        for p in ps:
            fs = []
            for f in p.get('fotos', []):
                n = _imatge_n(op, k); k += 1
                if n is None: continue
                f['asset'] = n['path']
                c = (n.get('codis') or '').strip()
                if c.isdigit(): f['referencia'] = int(c)
                elif c == '' and 'referencia' in f: f['referencia'] = None
                fs.append(f)
            p['fotos'] = fs
            ins = []
            for i in p.get('insignies', []) or []:
                n = _imatge_n(op, k); k += 1
                if n is None: continue
                i['asset'] = n['path']; ins.append(i)
            if 'insignies' in p: p['insignies'] = ins
        if bl: k = len(imgs)
        if len(imgs) > k: avisos.append(f"informació (Odoo {op['id']}, «{noms['es']}»): {len(imgs) - k} imatges de més sense lloc a la plantilla; no surten")
        for p in ps:
            if p.get('capcalera', {}).get('titol') is not None:
                p['capcalera']['titol'] = titol_aplicat(p['capcalera']['titol'], noms)
    elif t == 'simbologia':
        p = ps[0]
        eq = [x['t'] for x in linies_planes(_unitats_lang(op, 'en') or _unitats_lang(op, 'es'))]
        if eq: p['equivalencies'] = eq
        fixos = set(est.get('simbols_fixos', [])); nous = []; k = 0
        for s in p['simbols']:
            if sim_fix(s, fixos):
                n = _imatge_n(op, k); k += 1
                if n is None: continue
                s['icona'] = n['path']; s.pop('icona_components', None)
                ll = n.get('llegenda') or {}
                s['text'] = {l: ll.get(l) or ll.get('en') or ll.get('es') or '' for l in ('es', 'en', 'fr')}
                s['_odoo'] = True
            nous.append(s)
        while k < len(imgs):                                   # símbols afegits a Odoo (no són a la plantilla): sense posició
            n = imgs[k]; k += 1; ll = n.get('llegenda') or {}
            nous.append({'text': {l: ll.get(l) or ll.get('en') or ll.get('es') or '' for l in ('es', 'en', 'fr')}, 'pos': {}, 'icona': n['path'], '_odoo': True})
        p['simbols'] = nous
        if p.get('capcalera', {}).get('titol') is not None: p['capcalera']['titol'] = titol_aplicat(p['capcalera']['titol'], noms)
    elif t == 'condiciones':
        p = ps[0]
        un = {l: _unitats_lang(op, l) for l in ('es', 'en', 'fr')}
        es_ics = [s.get('icona') for s in p['seccions'] if (s.get('textos') or {}).get('es')]
        nova = []; i_es = 0; imatge_de = {}
        for s in p['seccions']:
            tx = s.get('textos') or {}
            if 'barra_idiomes' in s:
                s['barra_idiomes'] = {'en': noms['en'], 'fr': noms['fr']}; nova.append(s); continue
            if tx.get('es'):
                i = i_es; i_es += 1
                if i >= len(un['es']): continue                   # secció treta a Odoo
                n = _imatge_n(op, i)
                if n: s['icona'] = n['path']; imatge_de[es_ics[i]] = n['path']
                s['textos'] = {'es': [{'role': 'text', 'text': x['t']} for x in un['es'][i]]}
                nova.append(s)
            else:
                try: i = es_ics.index(s.get('icona'))
                except ValueError: nova.append(s); continue
                nt = {}
                for l in ('en', 'fr'):
                    if l in tx or (l == 'fr' and 'en' in tx):
                        u = un[l][i] if i < len(un[l]) else []
                        ls = [x['t'] for x in u if not re.fullmatch(r'-+', x['t'])]
                        if ls: nt[l] = [{'role': 'text', 'text': x} for x in ls]
                if not nt: continue
                s['textos'] = nt; nova.append(s)
        for s in nova:                                             # la icona d'una secció EN|FR és la de la seva secció ES
            if s.get('icona') in imatge_de: s['icona'] = imatge_de[s['icona']]
        p['seccions'] = nova
        if p.get('capcalera', {}).get('titol') is not None: p['capcalera']['titol'] = titol_aplicat(p['capcalera']['titol'], noms)
    elif t == 'contraportada':
        p = ps[0]; ct = p['capcalera_text']; nou = {}
        for l in IDIOMES:
            if l in ct:
                nou[l] = ' '.join(x['t'] for x in linies_planes(_unitats_lang(op, l))) or ct[l]
        p['capcalera_text'] = nou
        n = _imatge_n(op, 0)
        if n: p['imatges'][0]['asset'] = n['path']
    elif t == 'otra':
        p = ps[0]; n = _imatge_n(op, 0)
        if n: p['imatge_pagina']['asset'] = n['path']
    return [_marca(p, op, tema) for p in ps]


def pagina_nova(op, dades, avisos, contador):
    """Pàgina creada directament a Odoo (sense plantilla al yaml): informació (text a columnes d'idioma sobre una capçalera de plantilla) o imatges."""
    tipus = op['tipus']; res = []
    if tipus == 'otra' and op['imatges']:
        for n in op['imatges']:
            contador[0] += 1
            res.append(_marca({'id': f"odoo-{op['id']}-{contador[0]}", 'n': 300000 + contador[0], 'tipus': 'pagina_imatge', 'imatge_pagina': {'asset': n['path']}}, op, None))
        return res
    if tipus in ('informacion', 'otra'):
        ref = next((p for p in dades['pagines'] if p['tipus'] == 'informacio_general' and pagina_publicada(p)), None)
        if ref is None:
            avisos.append(f"pàgina d'Odoo {op['id']} «{op['noms'].get('es')}»: el grup no té cap pàgina d'informació de plantilla; no surt"); return []
        p = copy.deepcopy(ref)
        contador[0] += 1
        p['id'] = f"odoo-{op['id']}"; p['n'] = 300000 + contador[0]
        p['fotos'] = []; p.pop('insignies', None); p['decoracio'] = []
        noms = {l: op['noms'].get(l) or op['noms'].get('en') or '' for l in ('es', 'en', 'fr')}
        p['capcalera']['titol'] = {'es': noms['es'], 'en': noms['en'], 'fr': noms['fr']} if noms['en'] != noms['es'] else {'es': noms['es']}
        llengs = [l for l in ('es', 'en', 'fr') if parseja_html(_text_lang(op, l))]
        if tipus == 'informacion' and len(llengs) > 1:        # el contingut base (en_US) quan no hi ha traducció es repeteix igual: només idiomes diferents
            textos = {l: _text_lang(op, l) for l in llengs}
            vistos = []; llengs = [l for l in llengs if not (textos[l] in vistos or vistos.append(textos[l]))]
        cols = []; w = 19.0 / max(len(llengs), 1)
        for k, l in enumerate(llengs):
            cols.append({'idioma': l, 'pos': {'x': 1.0 + k * w, 'y': 3.0, 'w': w - 0.4, 'h': 25.0},
                         'paragrafs': _paragrafs(linies_planes(_unitats_lang(op, l)), 10.5)})
        p['columnes'] = cols
        return [_marca(p, op, None)]
    avisos.append(f"pàgina d'Odoo {op['id']} «{op['noms'].get('es')}» ({tipus}): no té plantilla al yaml del grup; només es poden afegir pàgines d'informació o d'imatge; no surt")
    return []


def aplica_odoo(dades, pagines_odoo, grup, avisos):
    """Substitueix les pàgines genèriques de `dades` per les d'Odoo (contingut d'Odoo + disseny del yaml). Retorna dades2 (còpia)."""
    d = copy.deepcopy(dades)
    tms = temes(d); per_ids = {tuple(t['ids']): t for t in tms}
    base = [p for p in d['pagines'] if p['tipus'] in ('producte', 'accessoris') or not pagina_publicada(p) or p['tipus'] not in TIPUS_ODOO]
    gen = []; usats = set(); contador = [0]
    ordenades = sorted(pagines_odoo, key=lambda o: (RANG.get(o['tipus'], 5), o['sequence'], o['id']))
    for op in ordenades:
        m = marca_de_notes(op.get('notes'))
        tema = per_ids.get(tuple(m[1])) if (m and m[0] == grup) else None
        if tema is not None and tema['tipus'] == op['tipus'] and tuple(tema['ids']) not in usats:
            usats.add(tuple(tema['ids']))
            gen += aplica_tema(tema, op, grup, avisos)
        else:
            gen += pagina_nova(op, d, avisos, contador)
    for ids, t in per_ids.items():
        if ids not in usats: avisos.append(f"pàgina del .pub {'+'.join(ids)} ({t['tipus']}) sense pàgina activa a Odoo: no surt")
    d['pagines'] = base + gen
    return d


# ----------------------------------------------------------------------------- lectura d'Odoo (només lectura)
IMG_PAG = os.path.join(ROOT, 'treball', 'img-pagines')
IMG_CAT = os.path.join(ROOT, 'treball', 'img-cataleg')


def _ext(b):
    if b[:8] == b'\x89PNG\r\n\x1a\n': return 'png'
    if b[:3] == b'\xff\xd8\xff': return 'jpg'
    if b[:4] == b'GIF8': return 'gif'
    if b[:4] == b'RIFF' and b[8:12] == b'WEBP': return 'webp'
    return 'bin'


def _slug(s): return re.sub(r'\W+', '', str(s or ''))


def baixa_binaris(lect, model, ids_wd, camp, carpeta, nom_fitxer, lot=4):
    """Baixa (si no hi és ja) el camp binari de cada registre a `carpeta`. ids_wd: {id: write_date}; nom_fitxer(id, wd) -> nom sense extensió.
    Retorna {id: (camí relatiu a l'arrel, sha1)}. Es reutilitza el fitxer si el write_date no ha canviat."""
    import base64, glob
    os.makedirs(carpeta, exist_ok=True); res = {}; falten = []
    for i, wd in ids_wd.items():
        f = sorted(glob.glob(os.path.join(carpeta, glob.escape(nom_fitxer(i, wd)) + '.*')))
        if f:
            res[i] = (os.path.relpath(f[0], ROOT), hashlib.sha1(open(f[0], 'rb').read()).hexdigest())
        else: falten.append(i)
    for k in range(0, len(falten), lot):
        for r in lect(model, 'read', ids=falten[k:k + lot], fields=[camp]):
            if not r[camp]: continue
            b = base64.b64decode(r[camp])
            f = os.path.join(carpeta, f"{nom_fitxer(r['id'], ids_wd[r['id']])}.{_ext(b)}")
            open(f, 'wb').write(b)
            res[r['id']] = (os.path.relpath(f, ROOT), hashlib.sha1(b).hexdigest())
    return res


def llegeix_pagines(lect, grup_codi, actives=True, inclou_general=True):
    """Pàgines d'Odoo del grup (i les «general»), en ordre (tipus, sequence). Cada pàgina:
       {id, grup, tipus, sequence, familia_id, notes, active, write_date, noms{es,en,fr,de}, cos{es,en,fr,de: html},
        imatges[{id, sequence, path, sha1, codis, llegenda{es,en,fr}, write_date}]}   (imatges baixades a treball/img-pagines/)"""
    dom = [['grup', 'in', [grup_codi, 'general']]] if inclou_general else [['grup', '=', grup_codi]]
    ctx = {'lang': 'en_US'}
    if actives: dom = dom + [['active', '=', True]]
    else: ctx['active_test'] = False
    rows = lect('x_cataleg_pagina', 'search_read', domain=dom, context=ctx,
                fields=['name', 'tipus', 'sequence', 'familia_seguent_id', 'notes', 'grup', 'active', 'write_date'])
    if not rows: return []
    ids = [r['id'] for r in rows]
    pags = {r['id']: {'id': r['id'], 'grup': r['grup'], 'tipus': r['tipus'], 'sequence': r['sequence'],
                      'familia_id': r['familia_seguent_id'][0] if r['familia_seguent_id'] else None, 'notes': r['notes'] or '',
                      'active': r['active'], 'write_date': r['write_date'], 'noms': {}, 'cos': {}, 'imatges': []} for r in rows}
    for l in IDIOMES:
        for r in lect('x_cataleg_pagina', 'search_read', domain=[['id', 'in', ids]], fields=['name', 'cos'],
                      context=dict(ctx, lang=LANG_ODOO[l])):
            pags[r['id']]['noms'][l] = r['name'] or ''; pags[r['id']]['cos'][l] = r['cos'] or ''
    ims = lect('x_cataleg_pagina_imatge', 'search_read', domain=[['pagina_id', 'in', ids]], context=ctx,
               fields=['pagina_id', 'sequence', 'codis', 'write_date'])
    if ims:
        bins = baixa_binaris(lect, 'x_cataleg_pagina_imatge', {r['id']: r['write_date'] for r in ims}, 'imatge', IMG_PAG,
                             lambda i, wd: f"{i}-{_slug(wd)}")
        lleg = {}
        for l in ('es', 'en', 'fr'):
            for r in lect('x_cataleg_pagina_imatge', 'search_read', domain=[['id', 'in', [x['id'] for x in ims]]], fields=['llegenda'],
                          context=dict(ctx, lang=LANG_ODOO[l])):
                lleg.setdefault(r['id'], {})[l] = r['llegenda'] or ''
        for r in sorted(ims, key=lambda r: (r['sequence'], r['id'])):
            if r['id'] not in bins: continue                       # sense binari (no hauria de passar: la imatge és obligatòria)
            path, sha = bins[r['id']]
            pags[r['pagina_id'][0]]['imatges'].append({'id': r['id'], 'sequence': r['sequence'], 'path': path, 'sha1': sha, 'codis': r['codis'] or '',
                                                       'llegenda': lleg.get(r['id'], {}), 'write_date': r['write_date']})
    return sorted(pags.values(), key=lambda p: (RANG.get(p['tipus'], 5), p['sequence'], p['id']))


def imatges_catalog_productes(lect, productes):
    """Afegeix a cada producte (dict amb id, write_date) `img_cataleg` = camí relatiu de la seva x_cataleg_imatge baixada a
    treball/img-cataleg/, si en té. Només cerca ids que tenen la imatge (una cerca) i baixa els que no són ja a disc."""
    ids = [p['id'] for p in productes]
    amb = set()
    for i in range(0, len(ids), 200):
        amb |= set(lect('product.template', 'search', domain=[['id', 'in', ids[i:i + 200]], ['x_cataleg_imatge', '!=', False]]))
    wd = {p['id']: p.get('write_date') or '' for p in productes if p['id'] in amb}
    bins = baixa_binaris(lect, 'product.template', wd, 'x_cataleg_imatge', IMG_CAT, lambda i, w: f"{i}-{_slug(w)}", lot=5) if wd else {}
    for p in productes:
        p['img_cataleg'] = bins[p['id']][0] if p['id'] in bins else None
    return len(bins)
