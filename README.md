# Catàleg Eurast «al núvol»

Regenera i publica el catàleg viu d'Eurast (visor web + PDF) a GitHub Pages **sense el Mac**, des de GitHub Actions.
Es llança quan Odoo fa una crida `repository_dispatch` (event_type `actualitza-cataleg`) o a mà (`workflow_dispatch`).

**Només lectura a Odoo Staging.** No escriu res a Odoo ni a Makro. Cap clau ni credencial al repositori: tot surt de secrets.

```
Odoo Staging --(lectura)--> cataleg-viu/actualitza.py --> grups-odoo/scripts/renderitza.py (Chrome headless) --> PDF de cada grup
                                         |
                                         +--> cataleg-viu/munta_cataleg.py --> sortida/web/ (cataleg.pdf, index.html, *.json, estat.json)
                                                                                  |
                                                                       actions/deploy-pages --> GitHub Pages
```

## Què hi ha
| Ruta | Contingut |
|---|---|
| `ci/genera.sh` | Entrada: genera tot (sense estat previ) a `sortida/web/`. Necessita les 4 variables d'entorn. |
| `ci/comprova.py`, `ci/estat.py`, `ci/fonts.conf` | Comprovació del resultat, `estat.json`, àlies de fonts per a Linux. |
| `.github/workflows/actualitza-cataleg.yml` | El workflow (dispatch + manual, concurrència, timeout 90 min). |
| `cataleg-viu/` | `cataleg.yaml` (**`ordre`**: grups del catàleg), `actualitza.py`, `munta_cataleg.py`, `portades.py`, lectura d'Odoo. |
| `grups-odoo/scripts/` | Renderitzador dels grups (`renderitza.py`, `font_odoo.py`, `pagines_odoo.py`...), `odoo_env.py` (connexió). |
| `grups-odoo/dades/` | Configuració de disseny: `gN.yaml`, `gN-config.yaml` (+ `gN-columnes.yaml` si en té), columnes, icones, correccions. |
| `grups-odoo/assets/gN/` | Imatges de disseny que no són a Odoo (icones, símbols, plantilles, fotos de reserva). |
| `tarifa/viewer/` | `build_refs.py`, `build_relations.py` (cercador i relacions del visor). |
| `visor/` | Plantilla del visor (`index.html`), logo i favicons. |

Les fotos de producte (`x_cataleg_imatge`) i les pàgines generals (`x_cataleg_pagina`) es llegeixen d'Odoo a cada execució.

## Variables d'entorn (secrets al workflow)
`ODOO_URL` (ha de contenir `.dev.odoo.com`: només Staging), `ODOO_DB`, `ODOO_USER`, `ODOO_API_KEY`.
`ODOO_DB` es valida però no s'envia (Odoo.sh tria la base per nom de servidor). Només es deixen passar
`search_read`, `read`, `search`, `search_count` i `fields_get` (`grups-odoo/scripts/odoo_env.py`).
Opcionals: `CHROME_BIN` (ruta de Chrome), `CHROME_NO_SANDBOX=1` (el workflow ho posa), `PYTHON`.

## Provar-ho en local
```bash
pip install -r requirements.txt     # al Mac amb PyMuPDF x86 es relança sol sota Rosetta
export ODOO_URL=... ODOO_DB=... ODOO_USER=... ODOO_API_KEY=...   # Staging
bash ci/genera.sh                   # ~15 min -> sortida/web/
cd sortida/web && python3 -m http.server 7793
```

## Afegir un grup
1. Posa'l a `ordre` de `cataleg-viu/cataleg.yaml` (p. ex. `[2, 3, 4]`; buit = tots els que tinguin productes marcats a Odoo).
2. Copia les dades del grup N des de `~/dev/tarifa-projecte/grups-odoo/`: `dades/gN.yaml`, `dades/gN-config.yaml`
   (i `dades/gN-columnes.yaml` si existeix) i la carpeta `assets/gN/`.
3. Compte: el generador només el sap fer si el grup té productes marcats (`x_cataleg`) a Odoo i `gN-config.yaml`.
   `ci/genera.sh` falla (i no publica res) si un grup de `ordre` no queda muntat.

## Notes
- **Fonts**: el disseny fa servir Arial Narrow i Franklin Gothic Book (Mac). A Ubuntu es substitueixen per Liberation Sans Narrow
  i Libre Franklin (`ci/fonts.conf`). Pot haver-hi petites diferències de tipus; si la primera execució es veu diferent, mira-ho abans de donar-ho per bo.
- **Temps**: 16 grups, 932 pàgines: ~15 min en local (3 grups alhora, `CATALEG_PARALEL`), PDF ~65 MB linealitzat (imatges a ~150 ppp).
- **Si falla**: no es publica res; la pàgina anterior es queda tal com estava (i `estat.json` també).
- `estat.json` (a l'arrel de la pàgina publicada): `resultat`, `generat_utc`, `generat_local` (Europa/Madrid), `edicio`, `pagines`, `grups`, `execucio`.
