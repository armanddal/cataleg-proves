"""Connexió a Odoo STAGING per variables d'entorn, només lectura.

Variables: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY (cap valor viu a cap fitxer).
ODOO_DB es valida però NO s'envia: a Odoo.sh la base de dades la tria el nom del servidor (la capçalera X-Odoo-Database
amb «test-eurast» dóna 404 a Staging).
- La URL ha de contenir `.dev.odoo.com` (només Staging; producció queda exclosa).
- Només es permeten search_read / read / search / search_count / fields_get.
"""
import json
import os
import time
import urllib.error
import urllib.request

LECTURA = {"search_read", "read", "search", "search_count", "fields_get"}


def _env(nom):
    v = os.environ.get(nom, "").strip()
    if not v:
        raise SystemExit("Falta la variable d'entorn %s (ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY)" % nom)
    return v


URL = _env("ODOO_URL").rstrip("/")
DB = _env("ODOO_DB")
USERNAME = _env("ODOO_USER")
_CLAU = _env("ODOO_API_KEY")
assert ".dev.odoo.com" in URL, "Només Staging (la URL ha de contenir .dev.odoo.com)"
assert "prod" not in URL.replace("test-eurast", ""), "La URL sembla de producció"


def _api(model, method, **kw):
    req = urllib.request.Request(
        "%s/json/2/%s/%s" % (URL, model, method),
        data=json.dumps(kw).encode(),
        headers={"Content-Type": "application/json", "Authorization": "bearer " + _CLAU},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise Exception("HTTP %s: %s" % (e.code, e.read().decode()[:300]))


def crida_lectura(model, method, **kw):
    """Única porta d'entrada a Odoo: rebutja qualsevol mètode que no sigui de lectura. Reintenta 429/502-504."""
    assert method in LECTURA, "Mètode no permès (només lectura): %s" % method
    time.sleep(0.3)
    for intent in range(9):
        try:
            return _api(model, method, **kw)
        except Exception as e:
            if any(c in str(e) for c in ("429", "502", "503", "504")) and intent < 8:
                time.sleep(min(60, 5 * (intent + 1)))
                continue
            raise
