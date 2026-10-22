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
    y, _, m = edicio.partition('/')
    n = len(grups)
    files = []
    for g in grups:
        files.append(
            '<div class="fila"><div class="num">%d</div><div class="noms"><div class="es">%s</div>'
            '<div class="altres">%s &nbsp;/&nbsp; %s</div></div><div class="punts"></div><div class="pag">%d</div></div>'
            % (g['n'], escapa(g['nom']['es']), escapa(g['nom']['en']), escapa(g['nom']['fr']), g['start']))
    return """<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Catálogo Eurast</title><style>%s
.vermell { color: #772f32 }
.logo { position: absolute; left: 16mm; top: 14mm; width: 74mm }
.segell { position: absolute; right: 16mm; top: 16mm; width: 27mm; height: 27mm; border: 2.2mm solid #cc0000; border-radius: 50%%;
  display: flex; flex-direction: column; align-items: center; justify-content: center; color: #cc0000; font-weight: 800;
  font-size: 17pt; line-height: 1.05; background: #fff; z-index: 3 }
.titol { position: absolute; left: 16mm; top: 58mm; right: 16mm }
.titol h1 { margin: 0; font-size: 40pt; letter-spacing: .02em; color: #772f32; font-weight: 800; text-transform: uppercase; line-height: 1 }
.titol .sub { margin-top: 3mm; font-size: 10pt; color: #666; letter-spacing: .03em }
.titol .sub .lt { display: inline-block; border: .25mm solid currentColor; border-radius: .6mm; font-size: 6.5pt; line-height: 1; padding: .3mm .8mm; margin-right: 1.6mm; font-weight: 700; vertical-align: middle }
.titol .sub .sep { display: inline-block; margin: 0 3.5mm; color: #aaa }
.titol .linia { margin-top: 5mm; height: 1.2mm; width: 60mm; background: #da5f06 }
.llista { position: absolute; left: 16mm; right: 16mm; top: 96mm; bottom: 16mm; display: flex; flex-direction: column }
.cap { display: flex; font-size: 8pt; letter-spacing: .08em; color: #777; border-bottom: .3mm solid #bbb; padding-bottom: 1.5mm; margin-bottom: 1mm }
.cap .a { flex: 1 } .cap .b { width: 14mm; text-align: right }
.fila { flex: 1 1 0; max-height: 17mm; display: flex; align-items: center; gap: 4mm; border-bottom: .2mm solid #e3e3e3 }
.num { width: 11mm; height: 9mm; border: .35mm solid #a22b2d; color: #a22b2d; font-weight: 700; font-size: 13pt; display: flex;
  align-items: center; justify-content: center; border-radius: 1mm; flex: none }
.noms { flex: none; max-width: 120mm }
.es { font-size: 12.5pt; font-weight: 700; color: #111 }
.altres { font-size: 8pt; color: #777 }
.punts { flex: 1; border-bottom: .3mm dotted #aaa; height: 1px; margin-top: 3mm }
.pag { width: 14mm; text-align: right; font-weight: 700; font-size: 12pt; color: #772f32 }
.peu { position: absolute; left: 16mm; bottom: 7mm; font-size: 7pt; color: #888 }
</style></head><body><div class="page">
<div class="barres"><i style="top:0;background:#da5f06"></i><i style="top:11mm;background:#ececec"></i><i style="top:22mm;background:#e7e7e7"></i></div>
<img class="logo" src="file://%s">
<div class="segell"><div>%s</div><div>%s</div></div>
<div class="titol"><h1>Catálogo / Tarifa</h1>
<div class="sub"><span class="lt">E</span>CATALOG / PRICE LIST<span class="sep">·</span><span class="lt">F</span>CATALOGUE / LISTE DE PRIX<span class="sep">·</span><span class="lt">D</span>KATALOG / PREISLISTE</div><div class="linia"></div></div>
<div class="llista"><div class="cap"><div class="a">GRUPO / GROUP / GROUPE</div><div class="b">PÁG.</div></div>%s</div>
</div></body></html>""" % (CSS_COMU, logo, escapa(y), escapa(m), '\n'.join(files)) if n else None


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
