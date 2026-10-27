# Passos per a l'Armand (publicar el catàleg «al núvol»)

Tot el que cal fer a mà. Cada bloc és una sola ordre. Repositori de destí: `armanddal/cataleg-proves` (públic).
La carpeta de treball és `~/dev/tarifa-projecte/cataleg-cloud` (no hi ha cap secret a dins).

## (a) Pujar la carpeta al repositori, substituint el contingut actual (force push d'un commit net)

Això **substitueix** el visor estàtic que hi ha ara a `main` (la pàgina continuarà publicada fins que facis el pas b i c i d).

```bash
cd ~/dev/tarifa-projecte/cataleg-cloud
```

La carpeta ja és un repositori git amb el commit fet (no cal `git init` ni `git add`). El remot `origin` ja hi és. Només cal pujar-lo (force: substitueix el visor estàtic actual):

```bash
git push --force origin HEAD:main
```

Mida del repositori: uns 80 MB; cap fitxer passa de 2 MB.

(El `.gitignore` ja deixa fora `sortida/`, `treball/` i `estat/`.)

## (b) Canviar la font de GitHub Pages a «GitHub Actions»

```bash
gh api -X PUT repos/armanddal/cataleg-proves/pages -f build_type=workflow
```

Si diu que Pages no existeix (404), crea'l amb `gh api -X POST repos/armanddal/cataleg-proves/pages -f build_type=workflow`.

## (c) Crear els 4 secrets (la clau la demana per stdin; no l'escriguis a l'ordre)

Valors de Staging actuals (de `odoo/api-test/test_connexio.py`):
- `ODOO_URL` = `https://digital-eurast-digital-eurast-test-eurast-39233943.dev.odoo.com`
- `ODOO_DB` = `test-eurast`
- `ODOO_USER` = `comercial@eurast.com`
- `ODOO_API_KEY` = la clau d'Staging: al fitxer local `odoo/api-test/.clau_staging` (o variable `ODOO_STAGING_API_KEY`).
  Si ha caducat, es crea a Odoo Staging: Preferències > Seguretat > Afegir clau API.

**Atenció**: Odoo.sh canvia l'URL d'Staging a cada rebuild de la branca. Si `ODOO_URL` deixa de respondre, cal tornar a posar els secrets d'URL i clau.

```bash
gh secret set ODOO_URL --repo armanddal/cataleg-proves --body "https://digital-eurast-digital-eurast-test-eurast-39233943.dev.odoo.com"
```

```bash
gh secret set ODOO_DB --repo armanddal/cataleg-proves --body "test-eurast"
```

```bash
gh secret set ODOO_USER --repo armanddal/cataleg-proves --body "comercial@eurast.com"
```

Aquesta no porta el valor a l'ordre: `gh` el demana per stdin; enganxa-hi la clau i prem Intro.

```bash
gh secret set ODOO_API_KEY --repo armanddal/cataleg-proves
```

Comprovació (només mostra els noms, mai els valors):

```bash
gh secret list --repo armanddal/cataleg-proves
```

## (d) Primera execució manual (triga ~15-25 min; el límit del workflow és 90 min)

```bash
gh workflow run actualitza-cataleg.yml --repo armanddal/cataleg-proves
```

Mirar-la en directe (tria l'execució més recent a la llista):

```bash
gh run watch --repo armanddal/cataleg-proves
```

Si falla, el registre:

```bash
gh run view --repo armanddal/cataleg-proves --log-failed
```

## Com es comprova que la pàgina s'ha actualitzat

L'estat de l'última generació (data i hora, resultat, grups, pàgines):

```bash
curl -s https://armanddal.github.io/cataleg-proves/estat.json
```

Ha de dir `"resultat": "ok"` i un `generat_local` de fa uns minuts. Després obre el visor i comprova que hi ha els 16 grups (932 pàgines; cataleg.pdf ~65 MB):

```bash
open https://armanddal.github.io/cataleg-proves/
```

Per saber l'estat de l'execució sense mirar el registre:

```bash
gh run list --repo armanddal/cataleg-proves --workflow actualitza-cataleg.yml --limit 3
```

## Per a l'agent del botó d'Odoo

La crida és un `POST https://api.github.com/repos/armanddal/cataleg-proves/dispatches` amb la capçalera
`Authorization: Bearer <token>` (token amb permís d'Actions: escriptura només en aquest repo) i el cos
`{"event_type": "actualitza-cataleg"}`; torna 204. Per dir «actualitzat a les ...» el botó pot llegir
`https://armanddal.github.io/cataleg-proves/estat.json` (camp `generat_local`) i comparar-lo amb l'hora de la pulsació.
Dues pulsacions seguides no es trepitgen (concurrència: la segona espera la primera).
