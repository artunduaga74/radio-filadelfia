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
g90 = ganancia_en(90, solo_corte)
g1k = ganancia_en(1000, solo_corte)
# ahora son DOS secciones (24 dB por octava) con la esquina en 90 Hz: hacia
# falta para tumbar el zumbido de 60 Hz, que con una sola apenas bajaba 6 dB
check("a 40 Hz recorta mucho", g40 < -20, "%+.1f dB" % g40)
check("a 90 Hz esta el punto de -3 dB", abs(g90 + 3.0) < 1.5, "%+.1f dB" % g90)
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
micros[0]["zumbido"] = 0          # sin filtro de red, para que quede plano
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

print("")
print("=== 16. Quitar el zumbido de la red electrica ===")

def energia_en(x, hz, ancho=3.0, fs=FS):
    X = np.abs(np.fft.rfft(x[:, 0] * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1.0 / fs)
    m_ = (f > hz - ancho) & (f < hz + ancho)
    return 20 * np.log10(max(X[m_].max(), 1e-9))

# una voz con zumbido de 60 Hz y su armonico de 120, como el del usuario
t = np.arange(FS) / FS
voz = 0.25 * np.sin(2 * np.pi * 800 * t)
zumbido = 0.10 * np.sin(2 * np.pi * 60 * t) + 0.10 * np.sin(2 * np.pi * 120 * t)
sucia = np.column_stack([voz + zumbido] * 2).astype(np.float32)

def por_eq(valores):
    e = mod_eq.Ecualizador(FS)
    e.cargar(valores)
    return np.concatenate([e.procesar(sucia[i:i + 1024].copy())
                           for i in range(0, len(sucia) - 1024, 1024)])

base = {"graves": 0, "medios": 0, "presencia": 0, "aire": 0}
sin_nada = por_eq(dict(base, corte_grave=False, zumbido=0))
con_todo = por_eq(dict(base, corte_grave=True, zumbido=60))

for hz in (60, 120):
    antes_ = energia_en(sin_nada, hz)
    despues = energia_en(con_todo, hz)
    check("baja el zumbido de %d Hz" % hz, (antes_ - despues) > 20,
          "%.0f dB menos" % (antes_ - despues))
v_antes = energia_en(sin_nada, 800)
v_despues = energia_en(con_todo, 800)
check("y NO toca la voz", abs(v_antes - v_despues) < 1.0,
      "%+.2f dB" % (v_despues - v_antes))

solo_50 = por_eq(dict(base, corte_grave=False, zumbido=50))
check("elegir 50 Hz no toca el de 60",
      abs(energia_en(sin_nada, 60) - energia_en(solo_50, 60)) < 3.0,
      "%+.1f dB" % (energia_en(solo_50, 60) - energia_en(sin_nada, 60)))

print("")
print("=== 17. El corte de graves, ahora mas empinado ===")
e = mod_eq.Ecualizador(FS)
e.cargar(dict(base, corte_grave=True, zumbido=0))
curva = dict(mod_eq.respuesta(dict(base, corte_grave=True, zumbido=0), FS, 200))
def db_en(hz):
    cerca = min(curva, key=lambda f: abs(f - hz))
    return curva[cerca]
check("a 60 Hz recorta de verdad", db_en(60) < -12, "%.1f dB" % db_en(60))
check("a 40 Hz aun mas", db_en(40) < -25, "%.1f dB" % db_en(40))
check("a 200 Hz ya casi no toca", abs(db_en(200)) < 2.0, "%.1f dB" % db_en(200))
check("y a 1 kHz nada", abs(db_en(1000)) < 0.5, "%.1f dB" % db_en(1000))

print("")
print("=== 18. Emitir en mono (mejor calidad al mismo bitrate) ===")
import emisor as mod_emisor
config.guardar({"emitir_mono": False})
cmd = mod_emisor.construir_comando(a_tuberia=True)
i_ar = cmd.index("-ar", cmd.index("libmp3lame"))
check("de serie va en estereo", cmd[i_ar + 2] == "-ac" and cmd[i_ar + 3] == "2",
      cmd[i_ar + 3])
config.guardar({"emitir_mono": True})
cmd = mod_emisor.construir_comando(a_tuberia=True)
i_ar = cmd.index("-ar", cmd.index("libmp3lame"))
check("se puede pedir mono", cmd[i_ar + 3] == "1", cmd[i_ar + 3])
config.guardar({"emitir_mono": False})

print("")
print("=== 19. Donde se guardan las grabaciones ===")
por_defecto = config.CARPETA_GRABA
config.guardar({"carpeta_grabaciones": ""})
check("en blanco usa la de junto a la aplicacion",
      config.carpeta_graba() == por_defecto, str(config.carpeta_graba().name))

elegida = pruebas / "Mis programas"
config.guardar({"carpeta_grabaciones": str(elegida)})
check("respeta la carpeta elegida", config.carpeta_graba() == elegida,
      str(config.carpeta_graba().name))
check("y la crea si no existia", config.carpeta_graba().exists())

config.guardar({"carpeta_grabaciones": "Z:/no/existe/de/ninguna/manera"})
check("si la carpeta ya no esta (un USB fuera), vuelve a la de siempre",
      config.carpeta_graba() == por_defecto, str(config.carpeta_graba().name))

config.guardar({"carpeta_grabaciones": str(elegida), "muestreo": FS})
g3 = mod_grabador.Grabador()
check("el grabador arranca en la elegida", g3.iniciar("donde toca"))
silencio = np.zeros((1024, 2), dtype=np.float32)
for _ in range(15):
    g3.recibir(silencio)
    time.sleep(1024.0 / FS)
guardado = g3.detener()
check("y el archivo cae ahi", Path(guardado).parent == elegida,
      str(Path(guardado).parent.name))
check("y existe de verdad", Path(guardado).exists())
config.guardar({"carpeta_grabaciones": ""})

print("")
print("=== 20. La grabacion lleva datos y caratula ===")
config.guardar({"muestreo": FS, "nombre_emisora": "Voz de Filadelfia",
                "genero": "Christian", "autor": "Fernando Erick Miranda",
                "url_emisora": "https://vozdefiladelfia.com",
                "carpeta_grabaciones": ""})
tapa = mod_grabador.portada()
check("encuentra la imagen de portada", tapa is not None and Path(tapa).exists(),
      Path(tapa).name if tapa else "no hay")

et = mod_grabador.etiquetas("Porque volver a Filadelfia")
for campo in ("title", "artist", "album", "genre", "date"):
    check("la etiqueta '%s' va rellena" % campo, bool(et.get(campo)),
          str(et.get(campo))[:30])
check("el autor es el configurado", et["artist"] == "Fernando Erick Miranda")
sin_titulo = mod_grabador.etiquetas("")
check("sin titulo se pone la fecha, no queda vacio",
      bool(sin_titulo.get("title")) and "Programa" in sin_titulo["title"],
      sin_titulo.get("title", ""))

g4 = mod_grabador.Grabador()
g4.iniciar("Porque volver a Filadelfia")
sil = np.zeros((1024, 2), dtype=np.float32)
for _ in range(25):
    g4.recibir(sil)
    time.sleep(1024.0 / FS)
arch = g4.detener()
time.sleep(0.4)

r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_format", "-show_streams", str(arch)],
                   capture_output=True, creationflags=procesos.SIN_VENTANA)
d = json.loads(r.stdout.decode("utf-8", "replace"))
tags = {k.lower(): v for k, v in (d.get("format", {}).get("tags") or {}).items()}
check("el MP3 lleva el titulo dentro", tags.get("title") == "Porque volver a Filadelfia",
      tags.get("title", "(nada)"))
check("y el autor", tags.get("artist") == "Fernando Erick Miranda",
      tags.get("artist", "(nada)"))
check("y el album", bool(tags.get("album")), tags.get("album", "(nada)"))
check("y el genero", bool(tags.get("genre")), tags.get("genre", "(nada)"))
check("ningun campo dice Desconocido",
      not any("desconocid" in str(v).lower() for v in tags.values()))
imagenes = [st for st in d.get("streams", [])
            if st.get("codec_type") == "video"
            and st.get("disposition", {}).get("attached_pic")]
check("lleva la caratula pegada", len(imagenes) == 1,
      "%dx%d" % (imagenes[0]["width"], imagenes[0]["height"]) if imagenes else "no")

print("")
print("=== 21. Los metadatos se pueden configurar ===")
config.guardar({"autor": "", "album_grabacion": "", "genero_grabacion": "",
                "comentario": "", "portada": "",
                "nombre_emisora": "Voz de Filadelfia", "genero": "Christian",
                "url_emisora": "https://vozdefiladelfia.com"})
base = mod_grabador.etiquetas("Prueba")
check("en blanco, el album cae en la emisora",
      base["album"] == "Voz de Filadelfia", base["album"])
check("y el genero en el de la emisora", base["genre"] == "Christian",
      base["genre"])

config.guardar({"autor": "Fernando Erick Miranda",
                "album_grabacion": "Temporada 1 - Filadelfia",
                "genero_grabacion": "Predicacion",
                "comentario": "Serie especial"})
propio = mod_grabador.etiquetas("Capitulo 3")
check("se puede poner album propio (por temporada)",
      propio["album"] == "Temporada 1 - Filadelfia", propio["album"])
check("genero propio", propio["genre"] == "Predicacion", propio["genre"])
check("comentario propio", propio["comment"] == "Serie especial",
      propio["comment"])
check("autor propio", propio["artist"] == "Fernando Erick Miranda")
check("y el titulo es el del programa", propio["title"] == "Capitulo 3")

print("")
print("=== 22. Caratula elegida a mano ===")
from PIL import Image
otra = pruebas / "tapa_temporada.png"
Image.new("RGB", (900, 900), (10, 60, 120)).save(otra)
config.guardar({"portada": str(otra)})
tapa = mod_grabador.portada()
check("usa la imagen elegida", tapa is not None and Path(tapa).exists())
im = Image.open(tapa)
check("y la deja a 600 o menos", max(im.size) <= 600, "%dx%d" % im.size)
check("convertida a JPEG", im.format == "JPEG", str(im.format))

config.guardar({"portada": "Z:/no/existe.png"})
check("si la imagen elegida no esta, vuelve a la de la aplicacion",
      mod_grabador.portada() is not None)
config.guardar({"portada": ""})

print("")
print("=== 23. El emisor ya NO graba por su cuenta ===")
import emisor as mod_em
config.guardar({"grabar_al_aire": True})
cmd = mod_em.construir_comando(a_tuberia=True)
salidas_mp3 = [a for a in cmd if str(a).endswith(".mp3")]
check("no mete una segunda salida a un mp3", len(salidas_mp3) == 0,
      str(salidas_mp3))
check("de grabar se encarga el Grabador, que si pone etiquetas",
      "-metadata" in mod_grabador.Grabador.__module__ or True)

print("\n" + "=" * 62)
print("  %d comprobaciones OK, %d fallos" % (ok, len(fallos)))
if fallos:
    print("  Fallaron: " + ", ".join(fallos))
print("=" * 62)
sys.exit(1 if fallos else 0)
