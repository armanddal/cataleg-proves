"""Font «Odoo» del catàleg d'un grup qualsevol: compon les pàgines de taules a partir de l'estat d'Odoo (només lectura).

Entrada: dades/gN.yaml (pàgines genèriques + plantilles de pàgina: disseny, no dades de taula)
         + dades/gN-config.yaml (quina plantilla del .pub té cada família: pàgina, taula, files repetides)
         + estat d'Odoo (famílies x_cataleg_familia, productes amb x_cataleg=True, columnes i valors).
Sortida: una còpia de `dades` amb `pagines` recompostes (mateixa estructura que llegeix renderitza.py)
         + el diccionari de preus (list_price d'Odoo) + llista d'avisos.

Què surt d'Odoo: quins productes hi són, a quina família, l'ordre de famílies i de files, el nom ES/EN/FR de la família, les COLUMNES
de cada taula (x_cataleg_familia_columna) i els VALORS de cada cel·la (x_cataleg_valor, més els camps de la fitxa: referència, energia,
pes, mesures i preu). De gN.yaml només disseny: pàgines genèriques, plantilles de pàgina, amplades de columna, fotos.
Es generalitza el motor del pilot del grup 2 amb: taules dobles (dos blocs), fotos amb diversos codis, accessoris amb fotos assignades
per geometria, capacitats de pàgina segons la plantilla, índex amb les targetes del .pub del grup i productes compartits entre famílies
o grups (`repeticions`).
"""
import base64, copy, glob, io, math, os, re, time
import yaml
import grup_util as U

HERE = U.HERE; ROOT = U.ROOT
IMG_ODOO = os.path.join(ROOT, 'treball', 'img-odoo')

CAMPS_PROD = ['default_code', 'list_price', 'x_llarg', 'x_ample', 'x_alt', 'x_energia', 'weight',
              'x_cataleg_familia_id', 'x_cataleg_familia_extra_ids', 'x_cataleg_ordre', 'name', 'write_date']
TIPUS_CONEGUTS = {'portada_grup', 'index_grup', 'informacio_general', 'producte', 'accessoris', 'simbologia', 'condicions_venda', 'contraportada', 'pagina_imatge'}
LANGS = (('es_ES', 'es'), ('en_US', 'en'), ('fr_FR', 'fr'))
CAMPS_COLUMNA = ['codi', 'name', 'icona', 'origen', 'tipus', 'unitat', 'sequence']


def carrega_config(grup):
    """Configuració comuna (capacitats, amples) + la del grup (famílies, repeticions)."""
    comu = yaml.safe_load(open(os.path.join(U.DADES, 'cataleg-config-grups.yaml'), encoding='utf8'))
    fg = os.path.join(U.DADES, f'g{grup}-config.yaml')
    if not os.path.exists(fg):
        raise SystemExit(f'Falta dades/g{grup}-config.yaml: executeu primer  python3 scripts/genera_config.py --grup {grup}'
                         + ('' if grup in U.grups_amb_dades() else f"  (i el grup {grup} encara no té dades: ni dades/g{grup}.yaml ni ../grups/dades/g{grup}.yaml)"))
    g = yaml.safe_load(open(fg, encoding='utf8'))
    comu['families'] = g['families']
    comu['repeticions'] = g.get('repeticions', {})
    comu['grup'] = g['grup']
    return comu


# ----------------------------------------------------------------------------- lectura d'Odoo
def llegeix_estat(grup, lect, extra_codis=()):
    """lect(model, method, **kw): només lectura. `grup` = codi d'Odoo («G03»). Retorna l'estat serialitzable.
    `extra_codis`: productes d'una altra família o grup que el catàleg repeteix (marcats a Odoo); surten amb `extern: True`."""
    fams = {}; wd = []
    for lang, k in LANGS:
        for r in lect('x_cataleg_familia', 'search_read', domain=[['grup', '=', grup]],
                      fields=['name', 'sequence', 'write_date'], context={'lang': lang}):
            f = fams.setdefault(r['id'], {'id': r['id'], 'sequence': r['sequence'], 'noms': {}})
            f['noms'][k] = r['name']; wd.append(r['write_date'])
    prods = []
    if fams:
        # productes de les famílies del grup: principals (x_cataleg_familia_id) + els que hi surten com a «altra família» (x_cataleg_familia_extra_ids);
        # un producte d'un altre grup que només hi surt com a extra és `extern` (no compta com a propi del grup)
        for r in lect('product.template', 'search_read',
                      domain=['&', ['x_cataleg', '=', True], '|', ['x_cataleg_familia_id', 'in', list(fams)], ['x_cataleg_familia_extra_ids', 'in', list(fams)]],
                      fields=CAMPS_PROD):
            prods.append(_prod(r, not (r['x_cataleg_familia_id'] and r['x_cataleg_familia_id'][0] in fams))); wd.append(r['write_date'])
    propis = {p['default_code'] for p in prods}
    extra = sorted(set(extra_codis) - propis)
    for i in range(0, len(extra), 40):
        for r in lect('product.template', 'search_read', domain=[['x_cataleg', '=', True], ['default_code', 'in', extra[i:i + 40]]], fields=CAMPS_PROD):
            prods.append(_prod(r, True)); wd.append(r['write_date'])
    estat = {'llegit': time.strftime('%Y-%m-%dT%H:%M:%S'), 'grup': grup,
             'families': sorted(fams.values(), key=lambda f: (f['sequence'], f['id'])), 'productes': prods}
    llegeix_columnes(estat, lect, wd)
    estat['data_edicio_auto'] = data_de_write_dates(wd)
    return estat


def data_de_write_dates(wd):
    """Mes (AAAA/MM) de l'última modificació: el write_date màxim de les dades de catàleg del grup (productes marcats, famílies, columnes de
    família i valors). None si no n'hi ha cap."""
    wd = [w for w in wd if w]
    return max(wd)[:7].replace('-', '/') if wd else None


def _prod(r, extern):
    fid = r['x_cataleg_familia_id']
    ids_f = ([fid[0]] if fid else []) + list(r.get('x_cataleg_familia_extra_ids') or [])      # principal + altres famílies on també surt a la taula
    return {'id': r['id'], 'default_code': r['default_code'], 'list_price': r['list_price'], 'write_date': r['write_date'], 'familia_ids': ids_f,
            'x_llarg': r['x_llarg'], 'x_ample': r['x_ample'], 'x_alt': r['x_alt'],
            'x_energia': r['x_energia'], 'weight': r['weight'], 'familia_id': fid[0] if fid else None,
            'ordre': r['x_cataleg_ordre'], 'name': r['name'], 'extern': extern}


def _tr3(per_idioma):
    """{'es': x, 'en': y, 'fr': z} -> idem; None si no hi ha cap valor (Odoo torna False)."""
    return per_idioma if any(per_idioma.values()) else None


def llegeix_columnes(estat, lect, wd=None):
    """Afegeix a `estat` (només lectura) les columnes de cada família i els valors de cada producte:
      estat['columnes']              {codi: {id, codi, icona, origen, tipus, unitat, sequence, noms{es,en,fr}}} (actives)
      families[i]['columnes']        [{'columna': codi, 'sequence': n, 'etiqueta': {es,en,fr} | None}] (en ordre)
      productes[j]['valors']         {codi de columna: {es,en,fr}} (només columnes de valor propi)
    """
    fam_ids = [f['id'] for f in estat['families']]
    cols = {}; fcs = {}
    if fam_ids:
        for lang, k in LANGS:
            for r in lect('x_cataleg_familia_columna', 'search_read', domain=[['familia_id', 'in', fam_ids]],
                          fields=['familia_id', 'columna_id', 'sequence', 'etiqueta', 'write_date'], context={'lang': lang}):
                if wd is not None: wd.append(r['write_date'])
                d = fcs.setdefault(r['id'], {'id': r['id'], 'familia_id': r['familia_id'][0], 'columna_id': r['columna_id'][0],
                                             'sequence': r['sequence'], 'etiqueta': {}})
                d['etiqueta'][k] = r['etiqueta'] or ''
        for lang, k in LANGS:
            for r in lect('x_cataleg_columna', 'search_read', domain=[], fields=CAMPS_COLUMNA, context={'lang': lang}):
                c = cols.setdefault(r['id'], {'id': r['id'], 'codi': r['codi'], 'icona': r['icona'] or '', 'origen': r['origen'],
                                              'tipus': r['tipus'], 'unitat': r['unitat'] or '', 'sequence': r['sequence'], 'noms': {}})
                c['noms'][k] = r['name']
    estat['columnes'] = {c['codi']: c for c in sorted(cols.values(), key=lambda c: (c['sequence'], c['id']))}
    codi_de = {c['id']: c['codi'] for c in cols.values()}
    for f in estat['families']:
        mine = sorted((d for d in fcs.values() if d['familia_id'] == f['id'] and d['columna_id'] in codi_de),
                      key=lambda d: (d['sequence'], d['id']))
        f['columnes'] = [{'columna': codi_de[d['columna_id']], 'sequence': d['sequence'], 'etiqueta': _tr3(d['etiqueta'])} for d in mine]
    for p in estat['productes']: p['valors'] = {}
    ids_prod = [p['id'] for p in estat['productes']]
    per_id = {p['id']: p for p in estat['productes']}
    if ids_prod and cols:
        for lang, k in LANGS:
            for i in range(0, len(ids_prod), 150):
                for r in lect('x_cataleg_valor', 'search_read', domain=[['producte_id', 'in', ids_prod[i:i + 150]]],
                              fields=['producte_id', 'columna_id', 'valor', 'write_date'], context={'lang': lang}):
                    if wd is not None: wd.append(r['write_date'])
                    codi = codi_de.get(r['columna_id'][0])
                    if codi: per_id[r['producte_id'][0]]['valors'].setdefault(codi, {})[k] = r['valor'] or ''


def foto_odoo(codi, grup, lect=None, img_cat=None):
    """Foto d'un producte, per ordre: la de catàleg d'Odoo (x_cataleg_imatge, `img_cat[codi]`); assets/g<grup>/foto-<codi>.* (extreta del .pub; si no,
    la d'un altre grup); la imatge del producte d'Odoo (image_1920 reduïda) a treball/img-odoo/. Retorna el camí relatiu a l'arrel, o None."""
    if img_cat and img_cat.get(codi): return img_cat[codi]
    for ext in ('jpg', 'png'):
        r = U.cerca_asset(grup, f'foto-{codi}.{ext}')
        if r: return r
    p = os.path.join(IMG_ODOO, f'{codi}.jpg')
    if os.path.exists(p): return f'treball/img-odoo/{codi}.jpg'
    if lect is None: return None
    r = lect('product.template', 'search_read', domain=[['default_code', '=', codi]], fields=['image_1920'])
    if not r or not r[0]['image_1920']: return None
    from PIL import Image
    im = Image.open(io.BytesIO(base64.b64decode(r[0]['image_1920'])))
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA'); fons = Image.new('RGB', im.size, 'white'); fons.paste(im, mask=im.split()[-1]); im = fons
    im = im.convert('RGB'); im.thumbnail((900, 900))
    os.makedirs(IMG_ODOO, exist_ok=True); im.save(p, 'JPEG', quality=88)
    return f'treball/img-odoo/{codi}.jpg'


# ----------------------------------------------------------------------------- plantilles del .pub
def pagines_publicades(dades):
    return [p for p in dades['pagines'] if not p.get('posterior_a_contraportada') and not p.get('fora_del_pdf_publicat')]


def plantilles(dades, cfg):
    """Famílies tal com són al .pub (segons la configuració del grup), en ordre:
    [{clau, noms, tipus, pagina, taula, k, blocs}]. `dades['pagines']` ha de ser la llista ja filtrada (mateixos objectes)."""
    pags = {p['id']: p for p in dades['pagines']}
    out = []
    for f in cfg['families']:
        p = pags[f['pagina']]
        tprod = [t for t in p['taules'] if t['format'] == 'taula_producte']
        t = next(t for t in tprod if t['id'] == f['taula'])
        out.append({'clau': f['clau'], 'noms': f['noms'], 'tipus': p['tipus'] if p['tipus'] == 'accessoris' else 'producte',
                    'pagina': p, 'taula': t, 'k': tprod.index(t) + 1, 'blocs': f.get('blocs', 1)})
    return out


def claus_families_odoo(families):
    occ = {}; res = {}
    for f in families:                       # ja ordenades per (sequence, id)
        res[f['id']] = U.clau_unica(f['noms']['es'], occ)
    return res


def fotos_per_taula(pagina):
    """Fotos d'una pàgina d'accessoris -> taula: cada foto és a sobre de la seva taula (la taula més propera per sota amb solapament en X);
    si no n'hi ha cap, es fa servir `taula_ordre`."""
    taules = [t for t in pagina['taules'] if t['format'] == 'taula_producte']
    res = {t['id']: [] for t in taules}
    if not taules: return res
    for f in pagina.get('fotos', []):
        q = f['pos']; cx = q['x'] + q['w'] / 2
        cand = [t for t in taules if t['pos']['x'] - 0.5 <= cx <= t['pos']['x'] + t['pos']['w'] + 0.5
                and t['pos']['y'] >= q['y'] + q['h'] * 0.4]
        if cand: t = min(cand, key=lambda t: t['pos']['y'] - q['y'])
        else:
            n = f.get('taula_ordre')
            t = taules[min(max((n or 1) - 1, 0), len(taules) - 1)]
        res[t['id']].append(f)
    return res


# ----------------------------------------------------------------------------- utilitats
def fmt_num(v):
    if v is None: return ''
    return str(int(round(v))) if abs(v - round(v)) < 0.005 else str(round(v, 2)).replace('.', ',')


def trocejar(files, maxim):
    """Reparteix `files` en trossos de mida igual (el més igualat possible) de com a màxim `maxim`."""
    if len(files) <= maxim: return [files]
    n = math.ceil(len(files) / maxim); mida = math.ceil(len(files) / n)
    return [files[i:i + mida] for i in range(0, len(files), mida)]


CLAU_RENDER = {'default_code': 'codi', 'x_energia': 'energia', 'list_price': 'preu', 'weight': 'pes', 'mesures': 'mesures'}


def valor_camp(origen, prod):
    """Valor de la cel·la quan la columna és un camp de la fitxa (cap valor propi); None si l'origen és `valor`."""
    if origen == 'default_code': return prod['default_code']
    if origen == 'list_price': return fmt_num(prod['list_price'])
    if origen == 'weight': return fmt_num(prod['weight']) if (prod['weight'] or 0) > 0 else ''
    if origen == 'mesures':
        return (f"{fmt_num(prod['x_ample'])}x{fmt_num(prod['x_llarg'])}x{fmt_num(prod['x_alt'])}"
                if all((prod[k] or 0) > 0 for k in ('x_ample', 'x_llarg', 'x_alt')) else '')
    if origen == 'x_energia': return {'gas': 'gas', 'electric': 'electric', 'gas_elec': 'gas+electric'}.get(prod['x_energia'] or '', '')
    return None


def _unics(per_idioma):
    """{'es','en','fr'} d'Odoo -> text si els idiomes diuen el mateix, o dict només amb els idiomes que difereixen de l'ES
    (el que fa el catàleg: «GN» o «1 x 10» surten una sola vegada). None/buit -> None."""
    if not per_idioma: return None
    es = per_idioma.get('es') or ''
    en = per_idioma.get('en') or es; fr = per_idioma.get('fr') or es
    if en == es and fr == es: return es or None
    return {'es': es, 'en': en, 'fr': fr}          # si algun idioma difereix, surten els tres (com al .pub)


class Constructor:
    def __init__(self, dades, estat, cfg, grup, lect=None, avisos=None):
        self.grup = grup                                   # número (3, 4, 5)
        self.d = copy.deepcopy(dades)
        self.est = estat; self.cfg = cfg; self.lect = lect
        self.avisos = avisos if avisos is not None else []
        self.d['pagines'] = pagines_publicades(self.d)     # les posteriors a la contraportada no són al catàleg publicat
        for p in self.d['pagines']:
            if p['tipus'] not in TIPUS_CONEGUTS: self.av(f"pàgina {p['id']} de tipus «{p['tipus']}»: l'extractor no l'ha classificada; no surt al catàleg")
        self.d['pagines'] = [p for p in self.d['pagines'] if p['tipus'] in TIPUS_CONEGUTS]
        self.pl = plantilles(self.d, cfg); self.pl_per_clau = {x['clau']: x for x in self.pl}
        self.contador_n = 100000
        self.preus = {}
        self.icones = U.carrega_icones(grup)
        self.catalog = estat.get('columnes', {})         # {codi: columna d'Odoo}
        self.avisats = set()
        self.fotos_acc = {}
        self.img_cat = {p['default_code']: p['img_cataleg'] for p in estat.get('productes', []) if p.get('img_cataleg')}     # x_cataleg_imatge baixada d'Odoo
        for p in self.d['pagines']:
            if p['tipus'] == 'accessoris': self.fotos_acc.update(fotos_per_taula(p))

    def nou_n(self):
        self.contador_n += 1; return self.contador_n

    def av(self, m): self.avisos.append(m)

    def av_un_cop(self, m):
        if m not in self.avisats: self.avisats.add(m); self.av(m)

    # -------------------------------------------------------------- columnes i files (tot d'Odoo)
    def columnes_taula(self, fam, plantilla, tipus):
        """Columnes de la taula d'una família, segons x_cataleg_familia_columna d'Odoo (en el seu ordre).
        Cada una: {'idx', 'ample_cm', 'clau' (el que llegeix el renderitzador), 'columna' (codi d'Odoo), 'origen',
        'icones_capcalera' | 'text_capcalera'}. De la plantilla de pàgina només se'n treu l'amplada."""
        llista = fam.get('columnes') or []
        if not llista:
            self.av(f"família «{fam['noms'].get('es')}» (Odoo id {fam['id']}): sense columnes a Odoo; surten les per defecte "
                    f"({', '.join(self.cfg['columnes_defecte'])}). Afegiu-les a «Columnas del catálogo» / a la família.")
            llista = [{'columna': c, 'sequence': 0, 'etiqueta': None} for c in self.cfg['columnes_defecte']]
        amples = {}
        if plantilla:
            for c in plantilla['taula']['columnes']:
                if c.get('ample_cm'): amples.setdefault(U.codi_columna(self.grup, plantilla['taula']['id'], c['clau'], plantilla['tipus']), c['ample_cm'])
        defecte = self.cfg.get('amples_defecte_cm', {}); gen = self.cfg.get('ample_defecte_cm', 3.0)
        cols = []
        for i, fc in enumerate(llista):
            c = self.catalog.get(fc['columna'])
            if not c:
                self.av_un_cop(f"columna «{fc['columna']}» no existeix o és arxivada a Odoo; no surt"); continue
            clau = CLAU_RENDER.get(c['origen'], c['codi'])
            col = {'idx': i, 'ample_cm': amples.get(c['codi'], defecte.get(clau, gen)), 'clau': clau, 'columna': c['codi'], 'origen': c['origen']}
            asset = self.icones.get(c['icona']) if c['icona'] else None
            if c['icona'] and not asset:
                self.av_un_cop(f"columna «{c['codi']}»: la icona «{c['icona']}» no és a dades/icones-grups.yaml; surt el nom")
            tx = _unics(fc['etiqueta'] or c['noms'])
            nom = tx if isinstance(tx, dict) else {'es': tx or ''}
            col['nom_capcalera'] = nom              # nom (etiqueta de la família o nom de la columna), sempre; el renderitzador tria l'estil
            col['unitat'] = c.get('unitat') or ''
            if asset:
                col['icones_capcalera'] = [{'asset': asset}]
            else:
                col['text_capcalera'] = nom
            cols.append(col)
        return cols

    def cel_les(self, prod, columnes, sufix=''):
        """Cel·les d'un producte d'Odoo: cada cel·la ve de la fitxa (camps) o de x_cataleg_valor. Retorna ({clau+sufix: valor}, [claus buides])."""
        cel = {}; falten = []
        for c in columnes:
            cl = c['clau']; o = c['origen']
            v = valor_camp(o, prod)
            if v is None: v = _unics((prod.get('valors') or {}).get(c['columna'])) or ''
            if v == '' and o not in ('x_energia',): falten.append(cl)
            cel[cl + sufix] = v
        return cel, falten

    def fila(self, prod, columnes):
        """Fila de taula d'un producte d'Odoo (una sola fila, un sol bloc)."""
        codi = prod['default_code']
        cel, falten = self.cel_les(prod, columnes)
        cel['codi'] = codi
        if falten: self.av(f'{codi}: sense valor a Odoo per a les columnes {", ".join(falten)} (en blanc)')
        return {'codi': codi, 'cel_les': cel}

    def files_familia(self, prods, columnes, claus_fam, blocs=1):
        """Files de la taula: productes de la família + els repetits (`repeticions`, marcats a una altra família o grup), per ordre.
        Taula doble (blocs=2): ordre < 1000 = bloc esquerre, >= 1000 = bloc dret; la fila i-èsima uneix l'i-èsim de cada bloc."""
        llista = [(p['ordre'] or 9999, p['default_code'], p) for p in prods]
        for rep in self.cfg.get('repeticions', {}).get(claus_fam, []):
            p = self.prod_per_codi.get(rep['codi'])
            if p is None: self.av(f"{rep['codi']}: fila repetida a «{claus_fam}» però no és marcat a Odoo; no surt"); continue
            if all(x[1] != rep['codi'] for x in llista): llista.append((rep['ordre'], rep['codi'], p))
        llista.sort(key=lambda x: (x[0], x[1]))
        if blocs == 1:
            return [self.fila(p, columnes) for _, _, p in llista]
        esq = [p for o, _, p in llista if o < 1000]; dre = [p for o, _, p in llista if o >= 1000]
        files = []
        for i in range(max(len(esq), len(dre))):
            cel = {}; codi = ''
            if i < len(esq):
                c1, f1 = self.cel_les(esq[i], columnes); cel.update(c1); cel['codi'] = codi = esq[i]['default_code']
                if f1: self.av(f'{codi}: sense valor a Odoo per a les columnes {", ".join(f1)} (en blanc)')
            else:
                cel.update({c['clau']: '' for c in columnes}); cel['codi'] = ''
            if i < len(dre):
                c2, f2 = self.cel_les(dre[i], columnes, '_2'); cel.update(c2); cel['codi_2'] = dre[i]['default_code']
                if f2: self.av(f'{dre[i]["default_code"]}: sense valor a Odoo per a les columnes {", ".join(f2)} (en blanc)')
                if not codi: codi = dre[i]['default_code']
            else:
                cel.update({c['clau'] + '_2': '' for c in columnes}); cel['codi_2'] = ''
            files.append({'codi': codi, 'cel_les': cel})
        return files

    def amplia_bloc2(self, columnes):
        """Columnes d'una taula doble: el bloc 1 i la seva còpia (clau_2, base = la clau original)."""
        out = [dict(c, bloc=1, base=c['clau']) for c in columnes]
        for c in columnes:
            d = copy.deepcopy(dict(c, bloc=2, base=c['clau'])); d['clau'] = c['clau'] + '_2'; d['idx'] = len(out); out.append(d)
        return out

    # -------------------------------------------------------------- fotos
    def fotos_de(self, pagina, codis):
        """Fotos dels codis (en l'ordre de les files): del catàleg si hi són (una foto pot servir diversos codis), si no d'Odoo.
        Cada foto porta `codis`: [{'codi', 'icones_etiqueta', 'text_etiqueta'}] només dels codis presents a les files."""
        per_codi = {}
        for f in (pagina.get('fotos', []) if pagina else []):
            cs = ([f['codi']] if f.get('codi') else []) + [c['codi'] for c in f.get('codis', [])]
            for c in dict.fromkeys(cs): per_codi.setdefault(c, f)
        out = []; vistes = set(); actius = [c for c in codis if c]
        for c in actius:
            f = per_codi.get(c)
            if f is not None:
                if id(f) in vistes: continue
                vistes.add(id(f)); g = copy.deepcopy(f)
                entrades = f.get('codis') or [{'codi': f['codi'], 'icones_etiqueta': f.get('icones_etiqueta', [])}]
                g['codis'] = [e for e in entrades if e['codi'] in actius]
                if len(entrades) == 1 and not entrades[0].get('icones_etiqueta') and f.get('icones_etiqueta'):
                    g['codis'][0]['icones_etiqueta'] = f['icones_etiqueta']
                g['codi'] = g['codis'][0]['codi']
                for e_ in g['codis']:                                    # la foto de catàleg editada a Odoo (del primer codi que en té) mana sobre la del .pub
                    if self.img_cat.get(e_['codi']): g['asset'] = self.img_cat[e_['codi']]; break
                out.append(g); continue
            a = foto_odoo(c, self.grup, self.lect, self.img_cat)
            if a: out.append({'codi': c, 'asset': a, 'pos': {}, 'codis': [{'codi': c}]})
            else: self.av(f'{c}: sense foto (ni al catàleg ni a Odoo); surt només a la taula')
        return out

    # -------------------------------------------------------------- composició
    def construeix(self):
        est = self.est; cfg = self.cfg
        fams = est['families']; claus = claus_families_odoo(fams)
        self.prod_per_codi = {p['default_code']: p for p in est['productes']}
        per_fam = {}
        ids_fam = {f['id'] for f in fams}
        for p in est['productes']:
            for fid_ in (p.get('familia_ids') or ([] if p.get('extern') else [p['familia_id']])):
                if fid_ in ids_fam: per_fam.setdefault(fid_, []).append(p)
        for l in per_fam.values(): l.sort(key=lambda p: ((p['ordre'] or 9999), p['default_code']))
        for f in fams:
            if f['id'] in per_fam and not f['noms'].get('es'): self.av(f"família {f['id']} sense nom ES")
        for p in est['productes']:
            if not p.get('extern') and p['familia_id'] not in ids_fam: self.av(f"{p['default_code']}: família no activa/d'un altre grup; no surt")
        self.preus = {p['default_code']: p['list_price'] for p in est['productes']}

        def activa(f):
            if per_fam.get(f['id']): return True
            return any(r['codi'] in self.prod_per_codi for r in cfg.get('repeticions', {}).get(claus[f['id']], []))
        actives = [f for f in fams if activa(f)]
        claus_actives = [claus[f['id']] for f in actives]

        # ---- ancoratge de pàgines genèriques: davant de la primera família (activa) que les segueix al .pub
        ordre_pub = [x['clau'] for x in self.pl]
        ancora = {}; pos_pub = {}; cnt = 0
        for p in self.d['pagines']:
            if p['tipus'] in ('producte', 'accessoris'):
                cnt += sum(1 for x in self.pl if x['pagina'] is p)
            elif p['tipus'] not in ('portada_grup', 'index_grup'):
                pos_pub[p['id']] = cnt
        for p in self.d['pagines']:
            if p.get('_odoo'):                      # pàgina genèrica d'Odoo: «Antes de la familia» = primera família activa des de la triada (en l'ordre d'Odoo)
                fid = p.get('_ancora_fam_id')
                ordre_odoo = [f['id'] for f in fams]
                if p['tipus'] in ('portada_grup', 'index_grup'): continue
                if fid in ordre_odoo:
                    cand = [claus[i] for i in ordre_odoo[ordre_odoo.index(fid):] if claus[i] in claus_actives]
                    ancora[p['id']] = cand[0] if cand else None
                else: ancora[p['id']] = None
            elif p['id'] in pos_pub:
                cand = [c for c in ordre_pub[pos_pub[p['id']]:] if c in claus_actives]
                ancora[p['id']] = cand[0] if cand else None   # None = final

        # ---- pàgines de família
        ref_prod = [self.pl_per_clau[c]['pagina'] for c in claus_actives if c in self.pl_per_clau and self.pl_per_clau[c]['tipus'] == 'producte']
        ref_defecte = ref_prod[0] if ref_prod else next((p for p in self.d['pagines'] if p['tipus'] == 'producte'), None)
        items = []
        for f in actives:
            clau = claus[f['id']]; pl = self.pl_per_clau.get(clau)
            noms = {k: f['noms'].get(k, '') for k in ('es', 'en', 'fr')}
            items.append({'f': f, 'clau': clau, 'pl': pl, 'prods': per_fam.get(f['id'], []), 'noms': noms})
        if ref_defecte is None:
            for it in [x for x in items if x['pl'] is None]:
                self.av(f"família «{it['noms']['es']}»: sense pàgina de producte de plantilla a les dades del grup; no surt")
            items = [x for x in items if x['pl'] is not None]
        pagines = []; mapa_pagines = {}; anterior = None; i = 0
        while i < len(items):
            it = items[i]; pl = it['pl']
            if pl and pl['tipus'] == 'accessoris':
                src = pl['pagina']; grup = [it]
                while i + 1 < len(items) and items[i + 1]['pl'] and items[i + 1]['pl']['pagina'] is src:
                    grup.append(items[i + 1]); i += 1
                for pg, claus_pg in self.pagines_accessoris(src, grup):
                    pagines.append(pg)
                    for c in claus_pg: mapa_pagines.setdefault(c, []).append(pg['n'])
                anterior = src
            else:
                pgs = self.pagines_producte(it, anterior if (anterior and anterior['tipus'] == 'producte') else None, ref_defecte)
                for pg in pgs: pagines.append(pg)
                mapa_pagines[it['clau']] = [pg['n'] for pg in pgs]
                if pl: anterior = pl['pagina']
                elif pgs: anterior = pgs[0]
            i += 1

        # ---- ordre final de pàgines
        gen = {p['id']: p for p in self.d['pagines']}
        portada = next((p for p in self.d['pagines'] if p['tipus'] == 'portada_grup'), None)
        if portada is None: self.av('les dades del grup no tenen portada; el PDF en surt sense')
        index = self.index_pagines(items, mapa_pagines)
        final = ([portada] if portada else []) + index
        emes = set()

        def treu_ancorades(clau):
            for pid, a in ancora.items():
                if a == clau and pid not in emes:
                    emes.add(pid); final.append(gen[pid])
        seen_keys = []
        for pg in pagines:
            c = pg['_clau']
            if c not in seen_keys:
                seen_keys.append(c); treu_ancorades(c)
            final.append(pg)
        treu_ancorades(None)
        for pid in ancora:
            if pid not in emes: final.append(gen[pid])
        for p in final: p.pop('_clau', None)
        d2 = {k: v for k, v in self.d.items() if k != 'pagines'}
        d2['pagines'] = final
        return d2

    # -------------------------------------------------------------- pàgines de producte
    def pagines_producte(self, it, anterior, ref_defecte):
        pl = it['pl']; clau = it['clau']
        if pl:
            base = pl['pagina']; taula = pl['taula']; blocs = pl['blocs']
            maxim = max(self.cfg['capacitats']['producte_files'], len(taula['files']))
        else:
            base = copy.deepcopy(anterior or ref_defecte)
            base['id'] = f'nova-{it["f"]["id"]}'; base['n'] = None
            base['insignies'] = []; base['fotos'] = []
            for k_ in ('textos_pagina', 'sense_classificar', 'referencies_numeriques', 'icones_soltes'): base.pop(k_, None)
            base['taules'] = [t for t in base['taules'] if t['format'] != 'nota']
            taula = {'format': 'taula_producte', 'columnes': [], 'files': []}; blocs = 1
            maxim = self.cfg['capacitats']['producte_files']
        columnes = self.columnes_taula(it['f'], pl, 'producte')
        if not pl:
            self.av(f"família nova «{it['noms']['es']}» (Odoo id {it['f']['id']}): pàgina nova amb la plantilla de producte; "
                    f"capçalera/peu copiats de la pàgina anterior; columnes: {', '.join(c['clau'] for c in columnes)}")
        files = self.files_familia(it['prods'], columnes, clau, blocs)
        trossos_ = trocejar(files, maxim) if blocs == 1 else [files]
        pgs = []
        for j, ch in enumerate(trossos_):
            pg = copy.deepcopy(base)
            pg['n'] = (base['n'] if (pl and j == 0) else self.nou_n())
            pg['_clau'] = clau
            pg['capcalera']['titol'] = dict(it['noms'])
            t2 = copy.deepcopy(taula); t2['columnes'] = copy.deepcopy(self.amplia_bloc2(columnes) if blocs == 2 else columnes); t2['files'] = ch
            pg['taules'] = [t for t in pg['taules'] if t['format'] == 'nota'] + [t2]
            codis = [r['codi'] for r in ch] + ([r['cel_les'].get('codi_2') for r in ch] if blocs == 2 else [])
            pg['fotos'] = self.fotos_de(base if pl else None, codis)
            if not pl: pg['insignies'] = []
            pgs.append(pg)
        if len(pgs) > 1:
            self.av(f"família «{it['noms']['es']}»: {len(files)} files -> {len(pgs)} pàgines (capçalera repetida)")
        return pgs

    # -------------------------------------------------------------- pàgines d'accessoris
    def pagines_accessoris(self, src, grup):
        cap = self.cfg['capacitats']; cards = []   # (clau, taula, fotos)
        for it in grup:
            pl = it['pl']; t = copy.deepcopy(pl['taula'])
            t['titol'] = dict(it['noms'])
            columnes = self.columnes_taula(it['f'], pl, 'accessoris')
            t['columnes'] = self.amplia_bloc2(columnes) if pl['blocs'] == 2 else columnes
            files = self.files_familia(it['prods'], columnes, it['clau'], pl['blocs'])
            fots_orig = self.fotos_acc.get(pl['taula']['id'], [])
            maxim = max(cap['accessoris_files_per_targeta'], len(pl['taula']['files']))
            trossos_ = trocejar(files, maxim) if pl['blocs'] == 1 else [files]
            for j, ch in enumerate(trossos_):
                t2 = copy.deepcopy(t); t2['files'] = ch
                cards.append((it['clau'], t2, copy.deepcopy(fots_orig) if j == 0 else [], pl['taula']['pos']['y']))
        for tn in src['taules']:                      # rètols de grup (taules «nota» sense codis) -> a la primera targeta que els segueix
            nom = U.corr('banners_manuals', self.grup, tn['id'])
            if not nom: continue
            for k_, c in enumerate(cards):
                if c[3] > tn['pos']['y'] and 'banner' not in c[1]:
                    c[1]['banner'] = dict(nom); break
        out = []; per = max(cap['accessoris_targetes_per_pagina'], len([t for t in src['taules'] if t['format'] == 'taula_producte']))
        for j in range(0, len(cards), per):
            lot = cards[j:j + per]
            pg = copy.deepcopy(src)
            pg['n'] = src['n'] if j == 0 else self.nou_n()
            pg['_clau'] = lot[0][0]
            pg['taules'] = [c[1] for c in lot]
            pg['fotos'] = []
            for k, c in enumerate(lot, 1):
                for f_ in c[2]: f_['taula_ordre'] = k; pg['fotos'].append(f_)
            out.append((pg, [c[0] for c in lot]))
        return out

    # -------------------------------------------------------------- índex
    def index_pagines(self, items, mapa):
        plant_idx = [p for p in self.d['pagines'] if p['tipus'] == 'index_grup']
        cards_pub = [(pi, t) for pi in plant_idx for t in pi['targetes']]
        if not any(not t.get('etiqueta') for pi, t in cards_pub):
            self.av("les dades del grup no tenen pàgina d'índex amb targetes; el PDF en surt sense índex")
            return []
        marcats = {p['default_code'] for p in self.est['productes']}
        pagen = {x['clau']: x['pagina']['n'] for x in self.pl if x['tipus'] == 'producte'}
        gen_n = {p['n'] for p in self.d['pagines'] if p['tipus'] not in ('producte', 'accessoris')}
        cards = []; emesa = set(); acc_bar = None
        tot_codis = {r['codi'] for fm in self.cfg['families'] for r in fm['productes'] + fm['compartits']}

        def retalla_fotos(t2):
            ff = []
            for f in t2['fotos']:
                m = re.search(r'foto-([^./]+)\.', f['asset'])
                if m and m.group(1) not in marcats and m.group(1) in tot_codis: continue   # foto d'un producte desmarcat
                if m and self.img_cat.get(m.group(1)): f = dict(f, asset=self.img_cat[m.group(1)])      # foto de catàleg d'Odoo
                ff.append(f)
            t2['fotos'] = ff
        for it in items:
            pl = it['pl']
            if pl and pl['tipus'] == 'accessoris': continue
            if pl:
                n0 = pl['pagina']['n']
                # totes les targetes del .pub que apunten a aquesta pàgina i encara no s'han emès (G2: tres targetes per a la p07);
                # si diverses famílies són a la mateixa pàgina, les targetes ja emeses no es repeteixen
                for pi, t in [(pi, t) for pi, t in cards_pub if not t.get('etiqueta') and t['enllac_pagines'][0] <= n0 <= t['enllac_pagines'][-1]
                              and id(t) not in emesa]:
                    emesa.add(id(t))
                    a, b = t['enllac_pagines'][0], t['enllac_pagines'][-1]
                    en_card = [i2 for i2 in items if i2['pl'] and i2['pl']['tipus'] == 'producte' and a <= pagen[i2['clau']] <= b]
                    primer = mapa[en_card[0]['clau']][0]
                    ultim = b if b in gen_n else mapa[en_card[-1]['clau']][-1]
                    t2 = copy.deepcopy(t); t2['enllac_pagines'] = list(dict.fromkeys([primer, ultim])); t2['_pi'] = pi
                    retalla_fotos(t2)
                    cards.append(t2)
            else:
                fots = []
                for p in it['prods']:
                    a_ = foto_odoo(p['default_code'], self.grup, self.lect, self.img_cat)
                    if a_: fots.append(a_)
                    if len(fots) == 2: break
                base_t = next(t for pi, t in cards_pub if not t.get('etiqueta'))
                geo = [f['pos'] for f in base_t['fotos'][:2]]
                t2 = {'ordre': 0, 'enllac_pagines': list(dict.fromkeys([mapa[it['clau']][0], mapa[it['clau']][-1]])), 'pos': dict(base_t['pos']),
                      '_pi': cards_pub[0][0], 'fotos': []}
                for a_, g_ in zip(fots, geo): t2['fotos'].append({'asset': a_, 'pos': dict(g_), 'ajust': 'contain'})
                if not fots: self.av(f"família «{it['noms']['es']}»: sense fotos per a la targeta de l'índex")
                cards.append(t2)
        ns_acc = []
        for it in items:
            if it['pl'] and it['pl']['tipus'] == 'accessoris':
                for n in mapa.get(it['clau'], []):
                    if n not in ns_acc: ns_acc.append(n)
        barres = [(pi, t) for pi, t in cards_pub if t.get('etiqueta')]
        if ns_acc and barres:
            pi_b, tb = barres[0]
            acc_bar = copy.deepcopy(tb); acc_bar['enllac_pagines'] = list(dict.fromkeys([ns_acc[0], ns_acc[-1]]))

        # repaginació en ranures: cada pàgina d'índex té tantes targetes com la seva plantilla (la darrera, el que quedi)
        caps = [len([t for t in pi['targetes'] if not t.get('etiqueta')]) for pi in plant_idx]
        ys_pla = [sorted(t['pos']['y'] for t in pi['targetes'] if not t.get('etiqueta')) for pi in plant_idx]
        bar_y = barres[0][1]['pos']['y'] if barres else None
        res = []; k = 0; pos = 0
        while (pos < len(cards) or not res) and k < 20:
            tpl_i = k if k < len(plant_idx) else (k % len(plant_idx))
            plt = plant_idx[tpl_i]
            c_per = caps[k] if k < len(caps) else max(caps)
            ys = list(ys_pla[tpl_i])
            while len(ys) < c_per: ys.append(ys[-1] + (ys[-1] - ys[-2] if len(ys) > 1 else 7.0))
            lot = cards[pos:pos + c_per]; pos += len(lot)
            pg = copy.deepcopy({kk: v for kk, v in plt.items() if kk != 'targetes'})
            pg['n'] = plt['n'] if k < len(plant_idx) else self.nou_n()
            pg['id'] = f'index-{k + 1}'
            bx = min(t['pos']['x'] for t in plt['targetes'])
            tg = []
            for s, c in enumerate(lot):
                c = copy.deepcopy(c); c.pop('_pi', None)
                dx = bx - c['pos']['x']; dy = ys[s] - c['pos']['y']
                c['pos']['x'] += dx; c['pos']['y'] += dy
                for f in c['fotos']:
                    if f['pos']: f['pos']['x'] += dx; f['pos']['y'] += dy
                tg.append(c)
            res.append((pg, tg, bx, c_per)); k += 1
        pgs = []
        for idx, (pg, tg, bx, c_per) in enumerate(res):
            if idx == len(res) - 1 and acc_bar:
                b = copy.deepcopy(acc_bar)
                yb = bar_y if (bar_y is not None and len(tg) <= len(ys_pla[min(idx, len(ys_pla) - 1)])) else None
                if tg and (yb is None or yb < tg[-1]['pos']['y'] + 1): yb = tg[-1]['pos']['y'] + 7.0
                nx, ny = bx, (yb if yb is not None else 27.0)
                dx = nx - b['pos']['x']; dy = ny - b['pos']['y']
                b['pos']['x'] = nx; b['pos']['y'] = ny
                for f in b['fotos']:
                    if f['pos']: f['pos']['x'] += dx; f['pos']['y'] += dy
                tg.append(b)
            pg['targetes'] = tg
            pgs.append(pg)
        usats = set()
        for pg in pgs:
            while pg['n'] in usats: pg['n'] = self.nou_n()
            usats.add(pg['n'])
        return pgs


def compon(dades, estat, cfg, grup, lect=None, pagines='odoo'):
    """Retorna (dades2, preus, avisos). pagines: 'odoo' (defecte) = les pàgines genèriques i les fotos de x_cataleg_pagina / x_cataleg_imatge si Odoo
    en té per al grup (estat['pagines']); si no n'hi ha, o amb 'yaml', les de dades/gN.yaml com abans."""
    avisos = []
    if estat['families'] and not estat.get('columnes'):
        raise SystemExit("L'estat d'Odoo no té columnes del catàleg (x_cataleg_columna): falta executar scripts/carrega_grup.py --aplica.")
    if pagines == 'odoo' and estat.get('pagines'):
        import pagines_odoo as PG
        dades = PG.aplica_odoo(dades, estat['pagines'], grup, avisos)
    if pagines == 'yaml':
        estat = dict(estat, productes=[dict(p, img_cataleg=None) for p in estat['productes']])
    c = Constructor(dades, estat, cfg, grup, lect, avisos)
    d2 = c.construeix()
    d2['cataleg_columnes'] = estat.get('columnes', {})      # per a la llegenda automàtica (noms, unitats, ordre)
    return d2, c.preus, avisos
