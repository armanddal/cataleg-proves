"""HTML de les portades i contraportades (es passen a PDF amb Chrome). Sense dependències."""
import html as _html

CSS_COMU = """
@page { size: 210mm 297mm; margin: 0 }
* { box-sizing: border-box }
html, body { margin: 0; padding: 0; background: #fff }
body { font-family: 'Franklin Gothic Book', 'Libre Franklin', 'Helvetica Neue', Arial, sans-serif; color: #111;
  -webkit-print-color-adjust: exact; print-color-adjust: exact }
.page { position: relative; width: 210mm; height: 297mm; overflow: hidden; background: #fff }
.barres { position: absolute; right: -20mm; top: -8mm; width: 120mm; height: 60mm }
.barres i { position: absolute; display: block; height: 7mm; width: 150mm; transform: rotate(-35deg); transform-origin: 0 0 }
"""


def escapa(t):
    return _html.escape(str(t), quote=True)


def html_portada(grups, edicio, logo):
    """Portada general com la de tarifa.eurast.com: fons taronja, «CATÁLOGOS 2026», banda fosca i índex dels grups en 2 columnes."""
    y, _, m = edicio.partition('/')
    n = len(grups)
    if not n: return None
    meitat = (n + 1) // 2

    def fila(g):
        return ('<div class="fila"><span class="num">%02d</span><span class="noms"><b>%s</b><i>%s</i></span><span class="pag">%d</span></div>'
                % (g['n'], escapa(g['nom']['es']), escapa(g['nom']['en']), g['start']))
    esq = ''.join(fila(g) for g in grups[:meitat])
    dre = ''.join(fila(g) for g in grups[meitat:])
    return """<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Catálogo Eurast</title><style>%s
.page { background: #e8640a; font-family: 'Montserrat', 'Libre Franklin', 'Franklin Gothic Medium', 'Helvetica Neue', Arial, sans-serif }
.logo { position: absolute; left: 50%%; margin-left: -37mm; top: 12mm; width: 74mm }
.t1 { position: absolute; left: 0; right: 0; top: 56mm; text-align: center; font-size: 66pt; font-weight: 800; color: #151515; line-height: 1; letter-spacing: -.01em }
.t2 { position: absolute; left: 0; right: 0; top: 83mm; text-align: center; font-size: 78pt; font-weight: 800; color: #fff; line-height: 1 }
.groc { position: absolute; left: 50%%; margin-left: -17mm; top: 115mm; width: 34mm; height: 1mm; background: #ffd400 }
.t3 { position: absolute; left: 0; right: 0; top: 120.5mm; text-align: center; font-size: 15pt; font-weight: 800; color: #151515; letter-spacing: .02em }
.idiomes { position: absolute; left: 50%%; margin-left: -30mm; width: 60mm; top: 132mm; border-top: .25mm solid #b3500a; border-bottom: .25mm solid #b3500a; padding: 1.6mm 0; text-align: center; color: #fff; font-weight: 600; font-size: 9.5pt; line-height: 6mm }
.idiomes span { margin: 0 1.3mm }
.pastilla { position: absolute; left: 50%%; margin-left: -14mm; width: 28mm; top: 161mm; height: 7.4mm; border-radius: 4mm; background: #151515; color: #ffd400; font-weight: 800; font-size: 7pt; text-align: center; line-height: 7.4mm; letter-spacing: .04em }
.banda { position: absolute; left: 0; right: 0; top: 177mm; bottom: 0; background: #c4510a }
.blanc { position: absolute; left: 0; right: 0; top: 181.5mm; bottom: 0; background: #fff; clip-path: polygon(0 0, 100%% 5mm, 100%% 100%%, 0 100%%) }
.cap { position: absolute; left: 8mm; right: 8mm; top: 188.5mm; font-size: 5.5pt; font-weight: 600; letter-spacing: .02em; color: #777; border-bottom: .3mm solid #e8640a; padding-bottom: .8mm }
.cols { position: absolute; left: 8mm; right: 8mm; top: 192.5mm; display: flex; gap: 2mm }
.col { flex: 1 }
.fila { display: flex; align-items: center; height: 8.4mm; margin-bottom: .8mm; padding: 0 1.5mm 0 0 }
.fila:nth-child(odd) { background: #f0f0f0 }
.num { width: 8mm; text-align: left; padding-left: 1mm; font-size: 10pt; font-weight: 800; color: #e8640a }
.noms { flex: 1; border-left: .3mm solid #e8640a; padding-left: 2mm; display: flex; flex-direction: column; line-height: 1.25 }
.noms b { font-size: 7pt; font-weight: 700; color: #222; text-transform: uppercase }
.noms i { font-size: 5.5pt; font-style: normal; color: #aaa; text-transform: uppercase; font-weight: 400 }
.pag { font-size: 7pt; font-weight: 700; color: #e8640a }
.peu1 { position: absolute; left: 8mm; right: 8mm; top: 269mm; border-top: .25mm solid #ccc; padding-top: 3mm; font-size: 6.5pt; color: #999; line-height: 4.8mm }
.peu1 b { color: #222; font-weight: 700 }
.segell { position: absolute; right: 8mm; top: 269mm; width: 25mm; height: 25mm; border: .9mm solid #d9120c; border-radius: 50%%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #d9120c; font-weight: 800; font-size: 13pt; line-height: 1.1; background: #fff }
.segell small { font-size: 8pt; font-weight: 700 }
</style></head><body><div class="page">
<img class="logo" src="file://%s">
<div class="t1">CATÁLOGOS</div><div class="t2">%s</div><div class="groc"></div>
<div class="t3">EDICIÓN COMPLETA</div>
<div class="idiomes">CATALOGUE <span>·</span> PRICE LIST<br>CATALOGUE <span>·</span> LISTE DE PRIX<br>KATALOG <span>·</span> PREISLISTE</div>
<div class="pastilla">%d GRUPOS</div>
<div class="banda"></div><div class="blanc"></div>
<div class="cap">ÍNDEX DE GRUPS / INDEX OF GROUPS &nbsp;·&nbsp; PÁG.</div>
<div class="cols"><div class="col">%s</div><div class="col">%s</div></div>
<div class="peu1"><b>EDICIÓN COMPLETA DE TODOS LOS CATÁLOGOS</b><br>COMPLETE EDITION OF ALL CATALOGUES<br>ÉDITION COMPLÈTE DE TOUS LES CATALOGUES<br>VOLLSTÄNDIGE AUSGABE ALLER KATALOGE</div>
<div class="segell"><span>%s</span><small>%s</small></div>
</div></body></html>""" % (CSS_COMU, logo, escapa(y), n, esq, dre, escapa(y), escapa(m))


def html_contraportada(c, logo):
    adr = '<br>'.join(escapa(x) for x in c.get('adreca', []))
    return """<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Contraportada</title><style>%s
.banda { position: absolute; left: 0; right: 0; top: 0; height: 24mm; background: #772f32 }
.centre { position: absolute; left: 25mm; right: 25mm; top: 100mm; text-align: center }
.centre img { display: block; width: 120mm; margin: 0 auto 16mm auto }
.web { font-size: 15pt; font-weight: 800; letter-spacing: .12em; color: #111; margin-bottom: 14mm }
.caixa { border: .4mm solid #772f32; padding: 10mm 8mm; display: inline-block; text-align: left; font-size: 11.5pt; line-height: 1.5; font-weight: 600 }
.caixa .emp { font-size: 12.5pt; font-weight: 800 }
.caixa .w { color: #772f32; font-weight: 700; margin-bottom: 3mm }
.fi { position: absolute; left: 0; right: 0; bottom: 0; height: 9mm; background: #da5f06 }
</style></head><body><div class="page"><div class="banda"></div>
<div class="centre"><img src="file://%s"><div class="web">%s</div>
<div class="caixa"><div class="w">%s</div><div class="emp">%s</div>%s<br>%s<br>%s</div></div>
<div class="fi"></div></div></body></html>""" % (
        CSS_COMU, logo, escapa((c.get('web_marca') or 'WWW.EURAST.COM').upper()), escapa(c.get('web', '')),
        escapa(c.get('empresa', '')), adr, escapa(c.get('email', '')), escapa(c.get('telefon', '')))




def html_portada_client(titol, subtitol, detall, edicio, logo):
    """Portada d'un PDF a mida: títol (p. ex. «Propuesta para X»), subtítol i una llista curta del que conté."""
    y, _, m = edicio.partition('/')
    items = ''.join('<div class="it">%s</div>' % escapa(x) for x in detall)
    return """<!doctype html><html lang="es"><head><meta charset="utf-8"><title>%s</title><style>%s
.logo { position: absolute; left: 16mm; top: 14mm; width: 74mm }
.segell { position: absolute; right: 16mm; top: 16mm; width: 27mm; height: 27mm; border: 2.2mm solid #cc0000; border-radius: 50%%;
  display: flex; flex-direction: column; align-items: center; justify-content: center; color: #cc0000; font-weight: 800;
  font-size: 17pt; line-height: 1.05; background: #fff; z-index: 3 }
.titol { position: absolute; left: 16mm; right: 16mm; top: 100mm }
.titol h1 { margin: 0; font-size: 34pt; color: #772f32; font-weight: 800; line-height: 1.1 }
.titol .sub { margin-top: 5mm; font-size: 13pt; color: #555 }
.titol .linia { margin-top: 8mm; height: 1.4mm; width: 70mm; background: #da5f06 }
.detall { position: absolute; left: 16mm; right: 16mm; top: 165mm }
.detall .cap { font-size: 8pt; letter-spacing: .08em; color: #777; border-bottom: .3mm solid #bbb; padding-bottom: 1.5mm; margin-bottom: 2mm }
.it { font-size: 11pt; padding: 1.6mm 0; border-bottom: .2mm solid #e3e3e3 }
.fi { position: absolute; left: 0; right: 0; bottom: 0; height: 9mm; background: #da5f06 }
</style></head><body><div class="page">
<div class="barres"><i style="top:0;background:#da5f06"></i><i style="top:11mm;background:#ececec"></i><i style="top:22mm;background:#e7e7e7"></i></div>
<img class="logo" src="file://%s"><div class="segell"><div>%s</div><div>%s</div></div>
<div class="titol"><h1>%s</h1><div class="sub">%s</div><div class="linia"></div></div>
<div class="detall"><div class="cap">CONTENIDO / CONTENTS</div>%s</div><div class="fi"></div>
</div></body></html>""" % (escapa(titol), CSS_COMU, logo, escapa(y), escapa(m), escapa(titol), escapa(subtitol), items)
