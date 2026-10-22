"""Utilitats comunes del catàleg viu (sense dependre de fitz: es pot importar des de qualsevol Python)."""
import hashlib
import json
import os
import re
import sys
import time

import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(AQUI, 'cataleg.yaml')
TREBALL = os.path.join(AQUI, 'treball')
GRUPS_DIR = os.path.join(TREBALL, 'grups')
ESTAT_DIR = os.path.join(AQUI, 'estat')
WEB = os.environ.get('CATALEG_WEB') or os.path.join(AQUI, 'web')   # CI: sortida/web
CLIENTS = os.path.join(AQUI, 'clients')


def _chrome():
    """Chrome/Chromium: variable CHROME_BIN, o el primer que trobi (macOS, Linux/CI)."""
    import shutil
    if os.environ.get('CHROME_BIN'):
        return os.environ['CHROME_BIN']
    mac = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    if os.path.exists(mac):
        return mac
    for n in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
        if shutil.which(n):
            return shutil.which(n)
    return mac


CHROME = _chrome()


def reexec_x86():
    """PyMuPDF d'aquest Mac és x86_64: si no es pot importar per arquitectura, es torna a executar sota Rosetta."""
    try:
        import fitz  # noqa: F401
        return
    except ImportError as e:
        if 'incompatible architecture' in str(e) and os.environ.get('CATALEG_X86') != '1':
            env = dict(os.environ, CATALEG_X86='1')
            os.execvpe('arch', ['arch', '-x86_64', sys.executable] + sys.argv, env)
        raise


def ruta(p, base=AQUI):
    p = os.path.expanduser(str(p))
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))


def carrega_config():
    with open(CONFIG, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def codi_odoo(n):
    return 'G%02d' % n


def num_de_nom_pdf(nom):
    m = re.fullmatch(r'g(\d+)\.pdf', nom)
    return int(m.group(1)) if m else None


def pdf_de_grup(cfg, n):
    """PDF que fa servir el catàleg per al grup n: cataleg.yaml (grups.N.pdf) > treball/grups/gN.pdf > pdf_origen. None si no n'hi ha."""
    g = (cfg.get('grups') or {}).get(n) or {}
    if g.get('pdf'):
        p = ruta(g['pdf'])
        return p if os.path.exists(p) else None
    p = os.path.join(GRUPS_DIR, 'g%d.pdf' % n)
    if os.path.exists(p):
        return p
    for plantilla in cfg.get('pdf_origen') or []:
        p = ruta(plantilla.format(n=n))
        if os.path.exists(p):
            return p
    return None


def grups_disponibles(cfg):
    """Números de grup que entren al catàleg, en ordre. Amb `ordre` al yaml, només aquells (si tenen PDF)."""
    candidats = set()
    for n in (cfg.get('grups') or {}):
        candidats.add(int(n))
    if os.path.isdir(GRUPS_DIR):
        for f in os.listdir(GRUPS_DIR):
            n = num_de_nom_pdf(f)
            if n:
                candidats.add(n)
    for plantilla in cfg.get('pdf_origen') or []:
        d = ruta(os.path.dirname(plantilla))
        if os.path.isdir(d):
            for f in os.listdir(d):
                n = num_de_nom_pdf(f)
                if n:
                    candidats.add(n)
    if cfg.get('ordre'):
        ordre = [int(x) for x in cfg['ordre']]
    else:
        ordre = sorted(candidats)
    return [n for n in ordre if pdf_de_grup(cfg, n)]


def edicio(cfg):
    e = cfg.get('edicio', 'auto')
    return time.strftime('%Y/%m') if e in (None, '', 'auto') else str(e)


# ----------------------------------------------------------------------------- noms dels grups
GROUP_LINE = re.compile(r"^\s*\{\s*id:\s*'G(\d+)'\s*,\s*page:\s*\d+\s*,(.*)\}\s*,?\s*$")


def noms_visor(index_html_path):
    """{n: {'es':..., 'en':..., 'fr':..., ...}} llegits del bloc GROUPS de l'index.html del visor."""
    html = open(index_html_path, encoding='utf-8').read()
    m = re.search(r'^const GROUPS = \[\n(.*?)^\];\n', html, re.S | re.M)
    if not m:
        raise ValueError('no trobo «const GROUPS = [» a ' + index_html_path)
    out = {}
    for l in m.group(1).split('\n'):
        mm = GROUP_LINE.match(l)
        if mm:
            out[int(mm.group(1))] = dict(re.findall(r"(\w+):\s*'((?:[^'\\]|\\.)*)'", mm.group(2)))
    return out


def noms_grup(cfg, n, del_visor):
    """Noms d'un grup en es/en/fr/... : yaml > visor de partida > genèric."""
    base = dict(del_visor.get(n) or {})
    base.update(((cfg.get('grups') or {}).get(n) or {}).get('nom') or {})
    if not base.get('es'):
        base['es'] = 'Grupo %d' % n
    for l in ('en', 'fr'):
        base.setdefault(l, base['es'])
    return base


# ----------------------------------------------------------------------------- signatures i estat
def hash_fitxer(p, bloc=1 << 20):
    h = hashlib.sha1()
    with open(p, 'rb') as f:
        while True:
            b = f.read(bloc)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def signatura_muntatge(cfg, grups):
    """Descriu què entra al catàleg muntat: si no canvia, no cal tornar a muntar. (Mida + mtime; no llegeix els PDF.)"""
    ent = {'edicio': edicio(cfg), 'grups': [],
           'config': hashlib.sha1(open(CONFIG, 'rb').read()).hexdigest(),
           'codi': [os.path.getmtime(os.path.join(AQUI, f)) for f in ('munta_cataleg.py', 'cataleg_lib.py')]}
    for n in grups:
        p = pdf_de_grup(cfg, n)
        st = os.stat(p)
        ent['grups'].append([n, p, st.st_size, round(st.st_mtime, 2)])
    v = cfg.get('visor') or {}
    for k in ('index_html',):
        p = ruta(v[k])
        ent[k] = [p, os.path.getmtime(p)]
    return ent


def llegeix_json(p, defecte=None):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecte


def escriu_json(p, dades):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(dades, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)


def html_a_pdf(html_path, pdf_path):
    import subprocess
    perfil = os.path.join(TREBALL, 'chrome-perfil')
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    cmd = [CHROME, '--headless=new', '--disable-gpu'] + (['--no-sandbox', '--disable-dev-shm-usage'] if os.environ.get('CHROME_NO_SANDBOX') else []) + [ '--no-pdf-header-footer', '--allow-file-access-from-files',
           '--user-data-dir=' + perfil, '--print-to-pdf=' + pdf_path, 'file://' + os.path.abspath(html_path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if not os.path.exists(pdf_path):
        raise RuntimeError('Chrome no ha generat el PDF: ' + r.stderr[-400:])
