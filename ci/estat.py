#!/usr/bin/env python3
"""Escriu sortida/web/estat.json: data i hora de l'última generació i el resultat (el consulta el botó d'Odoo)."""
import datetime
import json
import os
import sys
from zoneinfo import ZoneInfo

ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ARREL, "sortida", "web")
resultat = sys.argv[1] if len(sys.argv) > 1 else "ok"
ara = datetime.datetime.now(datetime.timezone.utc)
mapa = {}
try:
    mapa = json.load(open(os.path.join(ARREL, "cataleg-viu", "estat", "mapa.json"), encoding="utf-8"))
except OSError:
    pass
estat = {
    "resultat": resultat,
    "generat_utc": ara.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "generat_local": ara.astimezone(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d %H:%M:%S"),
    # «data» és el camp que llegeix el botó d'Odoo per dir «última publicació».
    "data": ara.astimezone(ZoneInfo("Europe/Madrid")).strftime("%d/%m/%Y %H:%M"),
    "edicio": mapa.get("edicio"),
    "pagines": mapa.get("pagines"),
    "grups": [g["id"] for g in mapa.get("grups", [])],
    "execucio": os.environ.get("GITHUB_RUN_ID"),
    "origen": os.environ.get("GITHUB_EVENT_NAME"),
}
os.makedirs(WEB, exist_ok=True)
with open(os.path.join(WEB, "estat.json"), "w", encoding="utf-8") as f:
    json.dump(estat, f, ensure_ascii=False, indent=1)
print(json.dumps(estat, ensure_ascii=False))
