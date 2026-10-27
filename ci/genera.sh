#!/usr/bin/env bash
# Genera TOT el catàleg des d'Odoo Staging (només lectura) a sortida/web/. Sense estat previ: cada cop es refà de zero.
# Variables obligatòries: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY.  Opcionals: CHROME_BIN, PYTHON.
set -euo pipefail
ARREL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ARREL"
PY="${PYTHON:-python3}"
# Els generadors de grup criden `python3` a seques: que sigui el mateix intèrpret (venv) que aquest
export PATH="$(dirname "$(command -v "$PY")"):$PATH"
T0=$(date +%s)

for v in ODOO_URL ODOO_DB ODOO_USER ODOO_API_KEY; do
  [ -n "${!v:-}" ] || { echo "ERROR: falta la variable $v" >&2; exit 2; }
done
case "$ODOO_URL" in *.dev.odoo.com*) ;; *) echo "ERROR: ODOO_URL ha de ser d'Staging (.dev.odoo.com)" >&2; exit 2;; esac

# Estat net: res de generacions anteriors
rm -rf sortida cataleg-viu/estat cataleg-viu/treball cataleg-viu/web grups-odoo/treball
mkdir -p sortida/web cataleg-viu/treball/grups grups-odoo/treball

export CATALEG_WEB="$ARREL/sortida/web"
echo "== Generant grups i muntant el catàleg (tot, des d'Odoo) =="
"$PY" cataleg-viu/actualitza.py --tot

echo "== Linealitzant el PDF (el visor mostra la primera pàgina abans de baixar-ho tot) =="
qpdf --linearize sortida/web/cataleg.pdf sortida/web/cataleg.lin.pdf
mv sortida/web/cataleg.lin.pdf sortida/web/cataleg.pdf
qpdf --check sortida/web/cataleg.pdf | tail -2
pdfinfo sortida/web/cataleg.pdf | grep -E "Pages|Optimized|File size"

echo "== Comprovant el resultat =="
"$PY" ci/comprova.py

touch sortida/web/.nojekyll
echo "== Fet: $(du -sh sortida/web | cut -f1) a sortida/web, cataleg.pdf $(du -h sortida/web/cataleg.pdf | cut -f1), en $(( $(date +%s) - T0 )) s =="
