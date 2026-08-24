# -*- coding: utf-8 -*-
"""
Comprobaciones del monitor de aire.

Escucha el chorro REAL de la emisora unos segundos y comprueba que mide el
nivel. Ojo: mientras escucha cuenta como un oyente.
"""

import sys
import tempfile
import time
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA.parent))

import config

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

pruebas = Path(tempfile.mkdtemp(prefix="radio_aire_"))
config.ARCHIVO_AJUSTES = pruebas / "ajustes.json"
config.ARCHIVO_CLAVES = pruebas / "credenciales.env"
config.CARPETA_DATOS = pruebas / "datos"
config.CARPETA_GRABA = pruebas / "grabaciones"
config._cache = None

import monitor_aire
import procesos
import servidor

ok, fallos = 0, []


def check(nombre, cond, detalle=""):
    global ok
    if cond:
        ok += 1
        print("  OK   %s %s" % (nombre, detalle))
    else:
        fallos.append(nombre)
        print("  FALLA %s %s" % (nombre, detalle))


print("")
print("=== 1. La direccion que se escucha ===")
config.guardar({"host": "cast1.asurahosting.com", "puerto_publico": 8024})
url = monitor_aire.url_publica()
check("se arma bien", url == "http://cast1.asurahosting.com:8024/stream", url)
config.guardar({"host": "http://cast1.asurahosting.com/start/nonefern"})
check("aguanta que peguen la direccion del panel",
      monitor_aire.url_publica() == "http://cast1.asurahosting.com:8024/stream",
      monitor_aire.url_publica())
config.guardar({"host": ""})
check("sin servidor no inventa nada", monitor_aire.url_publica() == "")

print("")
print("=== 2. Sin servidor no arranca ===")
v = monitor_aire.VigilanteAire()
check("avisa en vez de fallar", v.arrancar() is False)
check("queda en caida", v.estado == monitor_aire.CAIDA, v.estado)

print("")
print("=== 3. Escuchando la emisora de verdad ===")
config.guardar({"host": "cast1.asurahosting.com", "puerto_publico": 8024})
est = servidor.estado()
print("      el servidor dice: al aire=%s  titulo=%r"
      % (est["en_linea"], (est["titulo"] or "")[:34]))

avisos = []
v2 = monitor_aire.VigilanteAire(al_cambiar=lambda x: avisos.append(x.estado))
check("arranca", v2.arrancar())
niveles = []
for _ in range(10):
    time.sleep(1)
    niveles.append(v2.nivel)
v2.detener()

if est["en_linea"]:
    check("llega a conectarse",
          v2.estado != monitor_aire.CAIDA or any(n > -60 for n in niveles),
          "estado final=%s" % v2.estado)
    check("mide audio de verdad", any(n > -45 for n in niveles),
          "mejor nivel %.1f dB" % max(niveles))
    check("el nivel varia (no es un numero fijo)",
          len(set(round(n) for n in niveles)) > 1,
          "%d valores distintos" % len(set(round(n) for n in niveles)))
    check("avisa de los cambios de estado", len(avisos) > 0,
          "%d avisos" % len(avisos))
else:
    print("      (la emisora esta apagada: se comprueba solo la deteccion)")
    check("detecta que no hay emision",
          v2.estado in (monitor_aire.CAIDA, monitor_aire.CONECTANDO), v2.estado)

print("")
print("=== 4. Se apaga limpio (deja de gastar oyente) ===")
check("queda apagado", v2.estado == monitor_aire.APAGADO, v2.estado)
check("el nivel vuelve al minimo", v2.nivel == -60.0, "%.1f" % v2.nivel)
procesos.cerrar_todos()
vivos = [p for p in procesos._vivos if p.poll() is None]
check("no queda ningun ffmpeg escuchando", len(vivos) == 0, "%d vivos" % len(vivos))

print("")
print("=" * 62)
print("  %d comprobaciones OK, %d fallos" % (ok, len(fallos)))
if fallos:
    print("  Fallaron: " + ", ".join(fallos))
print("=" * 62)
sys.exit(1 if fallos else 0)
