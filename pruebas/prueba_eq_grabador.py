# -*- coding: utf-8 -*-
"""
Comprobaciones del ecualizador de voz y del grabador.

El ecualizador se mide con tonos puros: se mira cuantos dB cambia cada
frecuencia, no si "parece" que suena distinto.
La grabacion se comprueba abriendo el MP3 resultante con ffprobe: duracion
real y que no sea silencio.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA.parent))

import numpy as np

import config

# la consola de Windows viene en cp1252 y no sabe pintar los
# iconos del reproductor; sin esto, un print rompe la prueba
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

pruebas = Path(tempfile.mkdtemp(prefix="radio_eqgrab_"))
config.ARCHIVO_AJUSTES = pruebas / "ajustes.json"
config.ARCHIVO_CLAVES = pruebas / "credenciales.env"
config.CARPETA_DATOS = pruebas / "datos"
config.CARPETA_GRABA = pruebas / "grabaciones"
config._cache = None

import eq as mod_eq
import grabador as mod_grabador
import motor
import procesos

FS = 48000
ok, fallos = 0, []


def check(nombre, cond, detalle=""):
    global ok
    if cond:
        ok += 1
        print("  OK   %s %s" % (nombre, detalle))
    else:
        fallos.append(nombre)
        print("  FALLA %s %s" % (nombre, detalle))


def ganancia_en(frecuencia, valores):
    """Cuantos dB cambia el ecualizador un tono puro de esa frecuencia."""
    e = mod_eq.Ecualizador(FS)
    e.cargar(valores)
    t = np.arange(FS) / FS
    tono = (0.25 * np.sin(2 * np.pi * frecuencia * t)).astype(np.float32)
    entrada = np.column_stack([tono, tono])
    salida = np.concatenate([e.procesar(entrada[i:i + 1024])
                             for i in range(0, FS, 1024)])
    m = len(salida) // 2                       # sin el arranque del filtro
    ent = np.sqrt(np.mean(entrada[m:, 0] ** 2))
    sal = np.sqrt(np.mean(salida[m:, 0] ** 2))
    return 20 * np.log10(max(sal, 1e-9) / ent)


def sondear(ruta):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_format", str(ruta)], capture_output=True,
                       creationflags=procesos.SIN_VENTANA)
    return json.loads(r.stdout.decode("utf-8", "replace")).get("format", {})


def volumen(ruta):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(ruta), "-af",
                        "volumedetect", "-f", "null", "-"],
                       capture_output=True, creationflags=procesos.SIN_VENTANA)
    texto = r.stderr.decode("utf-8", "replace")
    for linea in texto.splitlines():
        if "max_volume" in linea:
            return float(linea.split(":")[-1].replace("dB", "").strip())
    return -99.0


print("\n=== 1. Cada banda mueve la frecuencia que le toca ===")
solo_presencia = {"graves": 0, "medios": 0, "presencia": 6, "aire": 0,
                  "corte_grave": False}
g3k = ganancia_en(3000, solo_presencia)
g100 = ganancia_en(100, solo_presencia)
check("subir presencia +6 sube 3 kHz", abs(g3k - 6.0) < 0.6, "%+.1f dB" % g3k)
check("y casi no toca los 100 Hz", abs(g100) < 1.0, "%+.1f dB" % g100)

solo_medios = {"graves": 0, "medios": -6, "presencia": 0, "aire": 0,
               "corte_grave": False}
g400 = ganancia_en(400, solo_medios)
check("bajar medios -6 baja los 400 Hz", abs(g400 + 6.0) < 0.6, "%+.1f dB" % g400)

print("\n=== 2. El corte de graves quita el retumbe ===")
solo_corte = {"graves": 0, "medios": 0, "presencia": 0, "aire": 0,
              "corte_grave": True}
g40 = ganancia_en(40, solo_corte)
g80 = ganancia_en(80, solo_corte)
g1k = ganancia_en(1000, solo_corte)
check("a 40 Hz recorta fuerte", g40 < -9, "%+.1f dB" % g40)
check("a 80 Hz esta el punto de -3 dB", abs(g80 + 3.0) < 1.0, "%+.1f dB" % g80)
check("a 1 kHz no toca nada", abs(g1k) < 0.3, "%+.1f dB" % g1k)

print("\n=== 3. Sin chasquidos entre bloques ===")
e1 = mod_eq.Ecualizador(FS)
e1.cargar(mod_eq.PRESETS["Radio (con cuerpo)"])
t = np.arange(4096) / FS
onda = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
senal = np.column_stack([onda, onda])
por_bloques = np.concatenate([e1.procesar(senal[i:i + 1024])
                              for i in range(0, 4096, 1024)])
e2 = mod_eq.Ecualizador(FS)
e2.cargar(mod_eq.PRESETS["Radio (con cuerpo)"])
de_golpe = e2.procesar(senal)
dif = float(np.max(np.abs(por_bloques - de_golpe)))
check("por bloques = de una vez", dif < 1e-6, "diferencia %.1e" % dif)

print("\n=== 4. Con todo a cero no gasta nada ===")
e3 = mod_eq.Ecualizador(FS)
e3.cargar({"graves": 0, "medios": 0, "presencia": 0, "aire": 0,
           "corte_grave": False})
b = (np.random.randn(1024, 2) * 0.1).astype(np.float32)
check("se declara plano", e3.plano)
check("devuelve el mismo bloque sin copiarlo", e3.procesar(b) is b)

print("\n=== 5. Los ajustes de fabrica estan completos ===")
for nombre in mod_eq.ORDEN_PRESETS:
    valores = mod_eq.PRESETS.get(nombre)
    completo = valores is not None and all(
        c in valores for c, _, _, _, _ in mod_eq.BANDAS)
    check("preset '%s'" % nombre, completo)
curva = mod_eq.respuesta(mod_eq.PRESETS["Voz clara"], FS)
check("la curva se puede dibujar", len(curva) > 10 and
      all(len(p) == 2 for p in curva), "%d puntos" % len(curva))

print("\n=== 6. El grabador escribe un MP3 de verdad ===")
config.guardar({"muestreo": FS, "canales": 2, "bitrate_grabacion": 192})
g = mod_grabador.Grabador()
check("arranca parado", not g.grabando)
check("iniciar() funciona", g.iniciar("Programa de prueba"))
check("ahora si graba", g.grabando)
archivo = g.archivo
check("el nombre lleva el titulo", "Programa_de_prueba" in str(archivo),
      Path(archivo).name)

# dos segundos de tono a 440 Hz
t = np.arange(1024) / FS
bloque = np.column_stack([0.4 * np.sin(2 * np.pi * 440 * t)] * 2).astype(np.float32)
bloques = int(2 * FS / 1024)
for i in range(bloques):
    g.recibir(bloque)
    time.sleep(1024 / FS)          # a ritmo real, como el mezclador
devuelto = g.detener()
check("detener() devuelve la ruta", devuelto == archivo)
check("ya no graba", not g.grabando)

check("el archivo existe", Path(archivo).exists())
info = sondear(archivo)
dur = float(info.get("duration", 0) or 0)
check("dura unos 2 segundos", 1.5 < dur < 2.6, "%.2f s" % dur)
check("pesa algo", int(info.get("size", 0) or 0) > 10000,
      "%d bytes" % int(info.get("size", 0) or 0))
vol = volumen(archivo)
check("tiene audio, no silencio", vol > -20, "pico %.1f dB" % vol)

print("\n=== 7. Grabar y emitir son independientes ===")
g2 = mod_grabador.Grabador()
check("se puede grabar sin estar al aire", g2.iniciar("suelto"))
g2.recibir(bloque)
a2 = g2.detener()
check("y queda el archivo", a2 and Path(a2).exists())
check("si no se graba, los bloques se tiran sin quejarse",
      (g2.recibir(bloque) is None) and not g2.grabando)

print("\n=== 8. El mezclador alimenta al grabador ===")
class GrabadorFalso:
    def __init__(self):
        self.bloques = 0
        self.grabando = True

    def recibir(self, b):
        self.bloques += 1

gf = GrabadorFalso()
m = motor.Mezclador(emisor=None, grabador=gf)
m.monitor_activo = False
m._salida = None
m._parar.set()                      # no arrancamos el hilo: llamamos a mano
mezcla = m._mezclar(1024)
gf.recibir(mezcla)
check("el mezclador tiene grabador", m.grabador is gf)
check("le llegan bloques", gf.bloques == 1)

print("\n=== 9. El ecualizador se aplica al microfono ===")
micros = config.microfonos()
micros[0]["eq"] = dict(mod_eq.PRESETS["Voz clara"])
micros[0]["eq_preset"] = "Voz clara"
config.guardar_microfonos(micros)
config.guardar({"eq_activo": True})
m2 = motor.Mezclador(emisor=None)
m2.monitor_activo = False
check("el mezclador crea su ecualizador", m2.eq is not None)
check("y carga el ajuste guardado", not m2.eq.plano)
micros = config.microfonos()
micros[0]["eq"] = {"graves": 0, "medios": 0, "presencia": 0, "aire": 0,
                   "corte_grave": False}
config.guardar_microfonos(micros)
m2.aplicar_ajustes()
check("los cambios llegan en caliente", m2.eq.plano)

procesos.cerrar_todos()
print("")
print("=== 10. El nivelador de voz (compresor) ===")

def nivel_tras_compresor(amplitud, comp):
    t = np.arange(FS) / FS
    o = (amplitud * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    b = np.column_stack([o, o])
    sal = np.concatenate([comp.procesar(b[i:i + 1024]) for i in range(0, FS, 1024)])
    m_ = len(sal) // 2
    ent = 20 * np.log10(max(np.sqrt(np.mean(b[m_:, 0] ** 2)), 1e-9))
    fin = 20 * np.log10(max(np.sqrt(np.mean(sal[m_:, 0] ** 2)), 1e-9))
    return ent, fin

c = mod_eq.Compresor(FS, umbral_db=-26, relacion=4, makeup_db=8, activo=True)
ent_bajo, sal_bajo = nivel_tras_compresor(0.02, c)
check("una voz floja se levanta entera", (sal_bajo - ent_bajo) > 7.0,
      "%+.1f dB" % (sal_bajo - ent_bajo))
c2 = mod_eq.Compresor(FS, umbral_db=-26, relacion=4, makeup_db=8, activo=True)
ent_alto, sal_alto = nivel_tras_compresor(0.6, c2)
check("una voz fuerte se frena", (sal_alto - ent_alto) < 0,
      "%+.1f dB" % (sal_alto - ent_alto))
check("y asi se acercan entre ellas",
      (sal_alto - sal_bajo) < (ent_alto - ent_bajo) - 8,
      "antes %.0f dB de diferencia, ahora %.0f" % (ent_alto - ent_bajo,
                                                   sal_alto - sal_bajo))
c3 = mod_eq.Compresor(FS, activo=False)
b = (np.random.randn(1024, 2) * 0.1).astype(np.float32)
check("apagado no toca nada", c3.procesar(b) is b)

print("")
print("=== 11. Ganancia del microfono en decibelios ===")
for db, esperado in ((0, 1.0), (6, 2.0), (12, 3.98), (20, 10.0), (24, 15.85)):
    g = mod_eq.db_a_ganancia(db)
    check("%+d dB = x%.2f" % (db, esperado), abs(g - esperado) < 0.05,
          "x%.2f" % g)
check("-40 dB o menos es silencio", mod_eq.db_a_ganancia(-40) == 0.0)
check("la vuelta tambien cuadra",
      abs(mod_eq.ganancia_a_db(mod_eq.db_a_ganancia(9)) - 9) < 0.01)

print("")
print("=== 12. El compresor va en cada canal de microfono ===")
micros = config.microfonos()
micros[0]["comp"] = True
micros[0]["comp_makeup"] = 12
micros[1]["comp"] = False
config.guardar_microfonos(micros)
m3 = motor.Mezclador(emisor=None)
m3.monitor_activo = False
check("el canal 1 lo trae encendido", m3.canales[0].comp.activo)
check("con el refuerzo guardado", abs(m3.canales[0].comp.makeup_db - 12) < 0.1,
      "%.0f dB" % m3.canales[0].comp.makeup_db)
check("y el canal 2 apagado", not m3.canales[1].comp.activo)
micros[1]["comp"] = True
config.guardar_microfonos(micros)
m3.aplicar_ajustes()
check("se puede encender en caliente", m3.canales[1].comp.activo)

print("")
print("=== 13. Calidad del limitador (lo que sonaba mal) ===")

def costura(bloques):
    """El salto de una muestra a la siguiente EN LA UNION de dos bloques."""
    return max(abs(float(bloques[i][0, 0] - bloques[i - 1][-1, 0]))
               for i in range(1, len(bloques)))

def distorsion(x, hz=220.0):
    X = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1.0 / FS)
    fund = X[(f > hz - 20) & (f < hz + 20)].max()
    arm = sum((X[(f > hz * k - 20) & (f < hz * k + 20)].max()) ** 2
              for k in (2, 3, 4, 5))
    return 100.0 * np.sqrt(arm) / max(fund, 1e-9)

# una senal que le hace trabajar de verdad: sube y baja como una voz
t = np.arange(FS * 2) / FS
envol = 0.5 + 0.9 * np.abs(np.sin(2 * np.pi * 2.0 * t))
onda = (envol * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
senal = np.column_stack([onda, onda])

lim = mod_eq.Limitador(FS)
bloques = [lim.procesar(senal[i:i + 1024].copy())
           for i in range(0, len(senal) - 1024, 1024)]
sal = np.concatenate(bloques)

salto = costura(bloques)
thd = distorsion(sal[FS // 2:FS // 2 + 16384, 0])
pico = float(np.max(np.abs(sal)))
check("no deja escalones en las uniones de bloque", salto < 0.05,
      "salto %.4f (con el limitador viejo era 0.1450)" % salto)
check("casi no distorsiona", thd < 0.5, "%.2f %% (el viejo, 0.22 %%)" % thd)
check("NUNCA se pasa del techo", pico <= 0.9701, "pico %.4f" % pico)
check("y aprovecha el techo", pico > 0.9, "pico %.4f" % pico)

print("")
print("=== 14. Arranque: nada de mudez al empezar ===")
t1 = np.arange(1024) / FS
tono = np.column_stack([0.5 * np.sin(2 * np.pi * 220 * t1)] * 2).astype(np.float32)
for nombre, obj in (("limitador", mod_eq.Limitador(FS)),
                    ("puerta", mod_eq.Puerta(FS, activo=True)),
                    ("compresor", mod_eq.Compresor(FS, activo=True))):
    salida = obj.procesar(tono.copy())
    mitad = len(salida) // 2
    ent = np.sqrt(np.mean(tono[mitad:, 0] ** 2))
    fin = np.sqrt(np.mean(salida[mitad:, 0] ** 2))
    db = 20 * np.log10(max(fin, 1e-9) / ent)
    check("%s: el primer bloque sale entero" % nombre, db > -3.0,
          "%+.1f dB" % db)

print("")
print("=== 15. La puerta calla la sala, no la voz ===")
def por_la_puerta(x, umbral=-45):
    g = mod_eq.Puerta(FS, umbral_db=umbral, reduccion_db=-18, activo=True)
    b = np.column_stack([x, x])
    o = np.concatenate([g.procesar(b[i:i + 1024]) for i in range(0, len(x) - 1024, 1024)])
    m_ = len(o) // 2
    ent = 20 * np.log10(max(np.sqrt(np.mean(b[m_:, 0] ** 2)), 1e-9))
    fin = 20 * np.log10(max(np.sqrt(np.mean(o[m_:, 0] ** 2)), 1e-9))
    return fin - ent

ruido = (0.002 * np.random.randn(FS)).astype(np.float32)
voz = (0.3 * np.sin(2 * np.pi * 200 * np.arange(FS) / FS)).astype(np.float32)
d_ruido = por_la_puerta(ruido)
d_voz = por_la_puerta(voz)
check("baja el ruido de la sala", d_ruido < -8, "%+.1f dB" % d_ruido)
check("y deja la voz intacta", abs(d_voz) < 0.5, "%+.1f dB" % d_voz)

print("\n" + "=" * 62)
print("  %d comprobaciones OK, %d fallos" % (ok, len(fallos)))
if fallos:
    print("  Fallaron: " + ", ".join(fallos))
print("=" * 62)
sys.exit(1 if fallos else 0)
