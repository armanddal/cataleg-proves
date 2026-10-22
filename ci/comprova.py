#!/usr/bin/env python3
"""Comprova que sortida/web té el que toca: tots els grups de `ordre` i els fitxers del visor."""
import json
import os
import sys

import yaml

ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ARREL, "sortida", "web")
cfg = yaml.safe_load(open(os.path.join(ARREL, "cataleg-viu", "cataleg.yaml"), encoding="utf-8")) or {}
ordre = [int(x) for x in cfg.get("ordre") or []]
mapa = json.load(open(os.path.join(ARREL, "cataleg-viu", "estat", "mapa.json"), encoding="utf-8"))
muntats = [g["n"] for g in mapa["grups"]]
errors = []
for f in ("index.html", "cataleg.pdf", "references.json", "search-text.json", "relations.json", "logo.png"):
    if not os.path.exists(os.path.join(WEB, f)) or os.path.getsize(os.path.join(WEB, f)) == 0:
        errors.append("falta %s" % f)
if ordre and muntats != ordre:
    errors.append("grups muntats %s != ordre %s (un grup sense productes marcats a Odoo, o sense dades?)" % (muntats, ordre))
if not muntats:
    errors.append("cap grup muntat")
if errors:
    sys.exit("ERROR: " + "; ".join(errors))
print("OK: grups %s, %d pàgines" % (muntats, mapa["pagines"]))
