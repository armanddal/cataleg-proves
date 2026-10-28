#!/usr/bin/env python3
"""Estructura el camp `cos` (Html traduïble) de les pàgines d'INFORMACIÓ del catàleg a Odoo STAGING, en tots els idiomes (es/en/fr/de).

Problema: el cos d'algunes pàgines/idiomes és un paràgraf pla («FABRICATION En acier... □ ...») i el generador n'endevina els títols per
heurística (renderitza.estructura_text). Aquí s'aplica aquella mateixa heurística UNA VEGADA i es desa el resultat a Odoo, amb el format que
ja té el cos bo: UN sol `<p>` per pàgina i idioma, títols en `<b>`, una frase/vinyeta per línia amb `<br>`, i els «□» (referència de la foto)
on eren:
        <p><b>CONSTRUCCIÓN</b><br>frase.<br>frase □<br><b>OTRO TÍTULO</b><br>frase.</p>
(Un sol <p> i no un per apartat: Odoo tradueix l'Html per blocs, i amb un sol bloc tots els idiomes casen sempre, encara que no tinguin el
mateix nombre d'apartats.) El que ja és estructurat (conté <b>, <br>, <h3> o diversos <p>) no es toca.

Ús:  python3 scripts/estructura_cos_odoo.py              # assaig (per defecte): no escriu res, mostra el canvi proposat
     python3 scripts/estructura_cos_odoo.py --aplica     # escriu a Staging i verifica rellegint
     --detall: mostra abans/després sencers (per defecte, retallats)

Només Staging (assert .dev.odoo.com a odoo_w). Llista blanca d'escriptura: x_cataleg_pagina.write NOMÉS del camp `cos` en en_US i
x_cataleg_pagina.update_field_translations NOMÉS del camp `cos`, NOMÉS d'ids de pàgines tipus 'informacion'. Per lots de 200 pàgines com a màxim.
"""
import argparse, html as H, json, os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import odoo_w as W
import grup_util as U
from renderitza import estructura_text, _TITOL, _MAJ
from carrega_pagines import EscriptorPag

IDIOMES = ('es', 'en', 'fr', 'de')
LANG_ODOO = {'es': 'es_ES', 'en': 'en_US', 'fr': 'fr_FR', 'de': 'de_DE'}
LOT = 200
ZW = ''.join(sorted(U.ZW)) if hasattr(U, 'ZW') else '​‌‍﻿'


def esc(t): return H.escape(t, quote=False)


def es_pla(h):
    """Cos d'un sol paràgraf pla: cap <b>/<br>/<h*>/<span>/<ul>/<li> i com a màxim un <p>."""
    if not h or not h.strip(): return False
    if re.search(r'<(?:b|strong|br|h[1-6]|span|ul|ol|li|div)\b', h, re.I): return False
    return len(re.findall(r'<p\b', h, re.I)) <= 1


def text_pla(h): return H.unescape(re.sub(r'<[^>]+>', ' ', h))


def net_cmp(t):
    """Per comparar el text: sense etiquetes, sense espais ni invisibles."""
    t = H.unescape(re.sub(r'<[^>]+>', ' ', t))
    return re.sub(r'\s+', '', ''.join(c for c in t if c not in ZW))


def estructura_lax(text):
    """Com renderitza.estructura_text però sense el mínim de 250 caràcters: per a cossos curts d'una pàgina on algun altre idioma
    ja és estructurat (ex. pàgina 42: es amb títol, fr/de plans de 150 car.). Mateixa heurística de títols i de frases."""
    t = re.sub(r'\s+', ' ', text).strip()
    if not _TITOL.search(t): return None
    k = [0]

    def ref(m): k[0] += 1; return f' §{k[0]}§ '
    t = re.sub(r'\s*\u25a1\s*', ref, t); tit = list(_TITOL.finditer(t))
    out = []; pos = 0
    for m in tit + [None]:
        cos = t[pos:m.start()] if m else t[pos:]
        for fr in re.split(r'(?<=[.!?§])\s+(?=[' + _MAJ + r'])', cos.strip()):
            fr = fr.strip()
            if fr: out.append(('li', fr))
        if m: out.append(('h', m.group(1))); pos = m.end()
    return out


def estructura(h, lax=False):
    """Cos pla -> (html estructurat, None) o (None, motiu)."""
    t = text_pla(h)
    est = estructura_text(t) or (estructura_lax(t) if lax else None)
    if not est: return None, 'sense títols detectables (text curt o sense majúscules)'
    parts = []                      # línies del <p>, ja en HTML
    for tipus, x in est:
        if tipus == 'h': parts.append(f'<b>{esc(x)}</b>')
        else: parts.append(esc(re.sub(r'\s*§\d+§', ' □', x).strip()))      # el §n§ de la heurística torna a ser el □ original
    nou = uneix_titol('<p>' + '<br>'.join(parts) + '</p>')
    return nou, None


_TITOL_PARTIT = re.compile(r'^<p>([^<]+?)<br><b>([^<]+)</b>')


def uneix_titol(h):
    """Títol llarg que l'heurística ha partit en dos («CONSTRUCCIÓN DE<br><b>LAS PELADORAS</b>»): el fragment de dalt és tot majúscules i no
    acaba en punt ni □. Es torna a unir en un sol títol en negreta. Retorna el html (igual si no cal)."""
    m = _TITOL_PARTIT.match(h)
    if not m: return h
    a = m.group(1).strip()
    if not a or a != a.upper() or re.search(r'[.!?\u25a1:;,]$', a) or len(a) > 70: return h
    return '<p><b>' + a + ('' if a.endswith('-') else ' ') + m.group(2) + '</b>' + h[m.end():]


def terme(h):
    """Terme traduïble d'un cos d'un sol <p>: el seu contingut."""
    return re.sub(r'^\s*<p>|</p>\s*$', '', h)


def llegeix(lect):
    rows = lect('x_cataleg_pagina', 'search_read', domain=[['tipus', '=', 'informacion']], fields=['name', 'grup', 'sequence', 'tipus'],
                context={'lang': 'en_US'})
    ids = [r['id'] for r in rows]
    cos = {i: {} for i in ids}
    for l in IDIOMES:
        for r in lect('x_cataleg_pagina', 'search_read', domain=[['id', 'in', ids]], fields=['cos'], context={'lang': LANG_ODOO[l]}):
            cos[r['id']][l] = r['cos'] or ''
    return rows, cos


def proposa(rows, cos):
    """-> llista de canvis [{id, nom, grup, nous{lang: html}, antics{lang: html}, avisos[]}] i comptadors."""
    canvis = []; sense = []
    for r in sorted(rows, key=lambda r: (r['grup'] or '', r['sequence'], r['id'])):
        c = cos[r['id']]; nous = {}; avisos = []
        for l in IDIOMES:
            h = c.get(l, '')
            if not es_pla(h):
                rep = uneix_titol(h)
                if rep != h and net_cmp(rep) == net_cmp(h): nous[l] = rep      # ja estructurat però amb el títol partit per una execució anterior
                continue
            lax = any(re.search(r'<(?:b|br)\b', c.get(o, ''), re.I) for o in IDIOMES if o != l)       # algun altre idioma ja és estructurat
            nou, motiu = estructura(h, lax)
            if not nou: sense.append((r['id'], r['name'], l, motiu, len(net_cmp(h)))); continue
            if net_cmp(nou) != net_cmp(h):
                avisos.append(f'{l}: el text net canvia (abans {len(net_cmp(h))} car., després {len(net_cmp(nou))}); NO es toca')
                continue
            nous[l] = nou
        if nous or avisos: canvis.append({'id': r['id'], 'nom': r['name'], 'grup': r['grup'], 'nous': nous, 'antics': {l: c[l] for l in nous}, 'avisos': avisos})
    return canvis, sense


def retalla(s, n=150): return s if len(s) <= n else s[:n] + '…'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--aplica', action='store_true', help='escriu a Staging (sense això: assaig)')
    ap.add_argument('--nomes', type=int, nargs='+', help='només aquests ids de pàgina (per provar)')
    ap.add_argument('--detall', action='store_true', help='abans/després sencers')
    a = ap.parse_args()
    assert ".dev.odoo.com" in W.tc.URL, "Només Staging"
    print(f'Entorn: {W.tc.URL} | {"APLICA" if a.aplica else "assaig (no escriu)"}')
    rows, cos = ROWS0, COS0
    print(f"Pàgines tipus 'informacion': {len(rows)}")
    canvis, sense = proposa(rows, cos)
    if a.nomes: canvis = [c for c in canvis if c['id'] in a.nomes]
    n_lang = sum(len(c['nous']) for c in canvis)
    print(f'\nCanvis proposats: {n_lang} cossos (pàgina+idioma) en {len(canvis)} pàgines.')
    per_lang = {l: sum(1 for c in canvis if l in c['nous']) for l in IDIOMES}
    print('Per idioma:', per_lang)
    for c in canvis:
        print(f"\n[{c['id']}] {c['grup']} «{c['nom']}»  idiomes: {','.join(c['nous']) or '-'}")
        for av in c['avisos']: print('   AVÍS', av)
        for l, nou in c['nous'].items():
            ant = c['antics'][l]
            print(f'   {l} ABANS : {ant if a.detall else retalla(ant)}')
            print(f'   {l} DESPRÉS: {nou if a.detall else retalla(nou)}')
    if sense:
        print(f'\nCossos plans que NO s\'han pogut estructurar ({len(sense)}):')
        for i, nom, l, motiu, n in sense: print(f'   [{i}] {nom} {l}: {motiu} ({n} car.)')
    if not a.aplica:
        print('\n(assaig: no s\'ha escrit res; --aplica per escriure)'); return 0
    return aplica(canvis, rows)


def aplica(canvis, rows):
    ruta = os.path.join(U.ROOT, 'treball', f'backup-cos-{time.strftime("%Y%m%d-%H%M%S")}.json')
    json.dump({str(i): v for i, v in COS0.items()}, open(ruta, 'w', encoding='utf8'), ensure_ascii=False)
    print(f'Còpia del cos original (tots els idiomes) a {ruta}')
    permesos = {r['id'] for r in rows if r['tipus'] == 'informacion'}
    E = EscriptorPag([{'model': 'x_cataleg_pagina', 'method': 'write', 'camps': {'cos'}, 'ids': lambda: permesos}],
                     True, W.Escriptor, lambda: permesos)
    errors = []; fets = []
    for k in range(0, len(canvis), LOT):
        for c in canvis[k:k + LOT]:
            rid = c['id']; assert rid in permesos
            try:
                nous = c['nous']
                # estat complet després del canvi (els idiomes no tocats conserven el seu cos)
                full = {}
                for l in IDIOMES: full[l] = nous.get(l) or COS0[rid][l]
                if 'en' in nous:
                    E.crida('x_cataleg_pagina', 'write', ids=[rid], vals={'cos': nous['en']}, context={'lang': 'en_US'})
                    ltr = [l for l in ('es', 'fr', 'de') if full[l]]            # el terme d'origen ha canviat: cal tornar a posar totes les traduccions
                else:
                    ltr = [l for l in ('es', 'fr', 'de') if l in nous]
                if ltr:
                    tr = E.crida('x_cataleg_pagina', 'get_field_translations', ids=[rid], field_name='cos')
                    fonts = list(dict.fromkeys(x['source'] for x in tr[0] if x['lang'] == 'es_ES'))
                    if len(fonts) != 1: raise RuntimeError(f'Odoo té {len(fonts)} termes d\'origen (n\'esperàvem 1): no escric les traduccions')
                    for l in ltr:
                        E.crida('x_cataleg_pagina', 'update_field_translations', ids=[rid], field_name='cos',
                                translations={LANG_ODOO[l]: {fonts[0]: terme(full[l])}})
                fets.append(rid)
            except Exception as e:
                errors.append((rid, f'{type(e).__name__}: {str(e)[:200]}')); print(f'   ERROR pàgina {rid}: {errors[-1][1]}')
        print(f'Lot {k // LOT + 1}: {len(fets)} pàgines escrites, {len(errors)} errors')
    # ---- verificació: rellegeix
    print('\nVerificació (relectura)...')
    rows2, cos2 = llegeix(W.crida_lectura)
    dolents = []; sumes = [0, 0]
    for c in canvis:
        rid = c['id']
        for l in IDIOMES:
            nou = cos2[rid].get(l, ''); abans = COS0[rid][l]
            sumes[0] += len(net_cmp(abans)); sumes[1] += len(net_cmp(nou))
            if not net_cmp(nou) and net_cmp(abans): dolents.append((rid, l, 'BUIT'))
            elif net_cmp(nou) != net_cmp(abans): dolents.append((rid, l, f'text net diferent ({len(net_cmp(abans))} -> {len(net_cmp(nou))})'))
            elif l in c['nous'] and terme(nou).replace('<br/>', '<br>') != terme(c['nous'][l]): dolents.append((rid, l, 'HTML diferent del proposat: ' + retalla(nou, 100)))
    print(f'Pàgines amb canvi: {len(canvis)}; escrites: {len(fets)}; errors d\'escriptura: {len(errors)}')
    print(f'Caràcters de text net (sense espais) abans/després, en les pàgines tocades: {sumes[0]} / {sumes[1]}')
    print(f'Problemes de verificació: {len(dolents)}')
    for d in dolents: print('   ', d)
    return 0 if not errors and not dolents else 1


COS0 = {}; ROWS0 = []

if __name__ == '__main__':
    # COS0: cos original, per a la verificació i per refer les traduccions (es llegeix abans de res)
    _rows, _cos = llegeix(W.crida_lectura)
    COS0.update(_cos); ROWS0.extend(_rows)
    sys.exit(main())
