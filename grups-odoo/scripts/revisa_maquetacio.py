#!/usr/bin/env python3
"""Repàs automàtic de la maquetació d'un grup ja generat (sortida/gN.html), pàgina a pàgina, amb el Chrome headless.

Busca el que a ull costa de veure en 900 pàgines:
  - contingut tallat: alguna cosa passa per sota del peu o fora del full (la pàgina té overflow:hidden i es perd en silenci)
  - fotos de producte massa petites (< 2,5 cm d'alt o d'ample) o amagades (0 cm)
  - imatges trencades (no carreguen)
  - text que surt pel costat

Ús: python3 scripts/revisa_maquetacio.py 1 4 14     (sense números: tots els sortida/g*.html)
Surt amb codi 1 si troba algun problema.
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from renderitza import CHROME  # noqa: E402

CM = 37.795
JS = r'''
<script>
window.addEventListener('load', function(){
  var CM = %s, res = [];
  document.querySelectorAll('.page').forEach(function(pg, i){
    var r = pg.getBoundingClientRect(), peu = pg.querySelector('.peu'), prob = [];
    var lim = r.top + (peu ? (297/10 - 1.4) : 29.7) * CM + 2;
    pg.querySelectorAll('.tau-box, .llegenda, .nota-caixa, .fotos figure, .acc-card, .info-col, .tau tr').forEach(function(e){
      var b = e.getBoundingClientRect();
      if (b.height > 0 && b.bottom > lim) prob.push('tallat: ' + e.className.split(' ')[0] + (e.tagName == 'TR' ? 'fila' : '') + ' fins a ' + ((b.bottom - r.top)/CM).toFixed(1) + ' cm');
      if (b.width > 0 && b.right > r.right + 2) prob.push('surt pel costat: ' + (e.className || e.tagName));
    });
    var petites = 0, amagades = 0, n = 0;
    pg.querySelectorAll('.fotos figure > img, .acc-fotos > img').forEach(function(im){
      n++;
      var b = im.getBoundingClientRect();
      if (!im.complete || im.naturalWidth == 0) prob.push('imatge trencada: ' + im.getAttribute('src'));
      else if (b.height < 2 || b.width < 2) amagades++;
      else if (b.height < 2.5*CM && b.width < 2.5*CM) petites++;
    });
    if (amagades) prob.push(amagades + ' de ' + n + ' fotos amagades (0 cm)');
    if (petites) prob.push(petites + ' de ' + n + ' fotos petites (< 2,5 cm)');
    if (prob.length) res.push({p: i + 1, prob: Array.from(new Set(prob)).slice(0, 6)});
  });
  var pre = document.createElement('pre'); pre.id = 'revisio'; pre.textContent = JSON.stringify(res);
  document.body.appendChild(pre);
});
</script>''' % CM


def revisa(html):
    doc = open(html, encoding='utf8').read().replace('</body>', JS + '</body>')
    tmp = tempfile.NamedTemporaryFile('w', suffix='.html', dir=os.path.dirname(html), delete=False, encoding='utf8')
    tmp.write(doc); tmp.close()
    perfil = tempfile.mkdtemp(prefix='chrome-rev-')
    try:
        r = subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--allow-file-access-from-files', f'--user-data-dir={perfil}',
                            '--window-size=794,1123', '--virtual-time-budget=60000', '--dump-dom', 'file://' + tmp.name],
                           capture_output=True, text=True, timeout=300)
    finally:
        os.remove(tmp.name)
        subprocess.run(['rm', '-rf', perfil])
    m = re.search(r'<pre id="revisio">(.*?)</pre>', r.stdout, re.S)
    if not m: raise RuntimeError(f'{html}: el Chrome no ha tornat el resultat')
    return json.loads(m.group(1).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"'))


def main():
    ns = sys.argv[1:]
    fitxers = [os.path.join(ROOT, 'sortida', f'g{n}.html') for n in ns] if ns else \
        sorted(glob.glob(os.path.join(ROOT, 'sortida', 'g[0-9]*.html')), key=lambda f: int(re.findall(r'g(\d+)\.html$', f)[0]))
    total = 0
    for f in fitxers:
        res = revisa(f)
        total += len(res)
        print(f'== {os.path.basename(f)}: {len(res)} pàgines amb problemes')
        for x in res: print(f'  p{x["p"]}: ' + ' | '.join(x['prob']))
    print(f'TOTAL: {total} pàgines amb problemes')
    sys.exit(1 if total else 0)


if __name__ == '__main__':
    main()
