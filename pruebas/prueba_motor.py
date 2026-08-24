# -*- coding: utf-8 -*-
"""Comprobaciones del mezclador SIN tocar el servidor ni la config real."""
import os
import sys
import tempfile

# la app debe escribir su config en un sitio de pruebas, no en la carpeta real
CARPETA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(CARPETA))   # la app esta un nivel arriba

import numpy as np
import config

# la consola de Windows viene en cp1252 y no sabe pintar los
# iconos del reproductor; sin esto, un print rompe la prueba
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

pruebas = tempfile.mkdtemp(prefix="radio_pruebas_")
config.ARCHIVO_AJUSTES = __import__("pathlib").Path(pruebas) / "ajustes.json"
config.ARCHIVO_CLAVES = __import__("pathlib").Path(pruebas) / "credenciales.env"
config.CARPETA_DATOS = __import__("pathlib").Path(pruebas) / "datos"
config.CARPETA_GRABA = __import__("pathlib").Path(pruebas) / "grabaciones"

import audio
import motor

TONO = os.path.join(CARPETA, "medios", "tono.wav")
JINGLE = os.path.join(CARPETA, "medios", "jingle.wav")

ok = 0
fallos = []


def check(nombre, condicion, detalle=""):
    global ok
    if condicion:
        ok += 1
        print("  OK   %s %s" % (nombre, detalle))
    else:
        fallos.append(nombre)
        print("  FALLA %s %s" % (nombre, detalle))


def rms(b):
    return float(np.sqrt(np.mean(b ** 2))) if len(b) else 0.0


print("\n=== 1. Pista (decodificar y reproducir un archivo) ===")
p = audio.Pista(48000, 1024)
check("carga el archivo", p.cargar(TONO, "Tono de prueba", 5.0))
check("en silencio antes de dar play", rms(p.leer(1024)) == 0.0)
p.reproducir()
b = p.leer(1024)
check("suena al dar play", rms(b) > 0.25, "rms=%.3f (esperado ~0.35)" % rms(b))
check("bloque del tamano correcto", b.shape == (1024, 2), str(b.shape))
check("avanza la posicion", abs(p.posicion - 1024 / 48000.0) < 1e-6,
      "%.4f s" % p.posicion)

# leer hasta el final
vueltas = 0
while p.sonando and vueltas < 400:
    p.leer(1024)
    vueltas += 1
check("detecta el final del archivo", p.termino, "tras %d bloques" % vueltas)
check("el final cae donde toca (~5 s)", 200 < vueltas < 260, "%d bloques" % vueltas)

print("\n=== 2. Fundidos ===")
p2 = audio.Pista(48000, 1024)
p2.cargar(TONO)
p2.reproducir(fundido_ms=200)
primero = rms(p2.leer(1024))
for _ in range(12):
    ultimo = rms(p2.leer(1024))
check("el fundido de entrada empieza bajo", primero < ultimo * 0.5,
      "%.3f -> %.3f" % (primero, ultimo))
p2.detener(fundido_ms=100)
antes = rms(p2.leer(1024))
for _ in range(6):
    p2.leer(1024)
check("el fundido de salida apaga la pista", not p2.sonando)

print("\n=== 3. Nivel en dBFS ===")
check("silencio = -60 dB", audio.nivel(np.zeros((100, 2), dtype=np.float32)) == -60.0)
check("tope = 0 dB", abs(audio.nivel(np.ones((100, 2), dtype=np.float32))) < 0.01)
medio = audio.nivel(np.full((100, 2), 0.5, dtype=np.float32))
check("mitad = -6 dB", abs(medio + 6.02) < 0.1, "%.2f dB" % medio)

print("\n=== 4. Mezclador ===")
m = motor.Mezclador(emisor=None)
m.monitor_activo = False
m.pista_a.cargar(TONO)
m.pista_a.reproducir()
mezcla = m._mezclar(1024)
check("la musica llega a la mezcla", rms(mezcla) > 0.2,
      "rms=%.3f (0.35 x volumen 0.8 = 0.28)" % rms(mezcla))
check("mide el nivel de musica", m.niveles["musica"] > -12,
      "%.1f dB" % m.niveles["musica"])
check("mide el nivel al aire", m.niveles["aire_i"] > -12,
      "%.1f dB" % m.niveles["aire_i"])

print("\n=== 5. Efectos encima de la musica ===")
antes = rms(m._mezclar(1024))
m.disparar_efecto(JINGLE, "Jingle")
juntos = rms(m._mezclar(1024))
check("el jingle suma sobre la musica", juntos > antes,
      "%.3f -> %.3f" % (antes, juntos))
check("el efecto queda registrado", len(m.efectos) == 1)
m.parar_efectos()
check("se pueden cortar los efectos", len(m.efectos) == 0)

print("\n=== 6. Ducking (la musica se aparta al hablar) ===")
m2 = motor.Mezclador(emisor=None)
m2.monitor_activo = False
m2.ducking = True
m2.pista_a.cargar(TONO)
m2.pista_a.reproducir()


class MicroFalso:
    """
    Microfono de mentira. Da un tono de 200 Hz, no una senal continua: el
    ecualizador lleva un corte de graves a 80 Hz que se comeria una senal
    constante, y entonces el detector del ducking no veria nada.
    """

    abierto = True
    error = ""

    def __init__(self, amplitud, hz=200.0, fs=48000):
        self.amplitud = amplitud
        self.hz = hz
        self.fs = fs
        self.fase = 0

    def leer(self, n):
        t = (np.arange(n) + self.fase) / self.fs
        self.fase += n
        onda = (self.amplitud * np.sin(2 * np.pi * self.hz * t)).astype(np.float32)
        return np.column_stack([onda, onda])

    def cerrar(self):
        pass


m2.micro = MicroFalso(0.0)
m2.micro_abierto = False
for _ in range(30):
    m2._mezclar(1024)
duck_sin_hablar = m2._duck
m2.micro = MicroFalso(0.7)          # ahora "habla"
m2.micro_abierto = True
for _ in range(200):
    m2._mezclar(1024)
duck_hablando = m2._duck
check("sin hablar la musica esta entera", duck_sin_hablar > 0.95,
      "factor=%.2f" % duck_sin_hablar)
check("al hablar la musica baja", duck_hablando < 0.4,
      "factor=%.2f" % duck_hablando)
m2.micro = MicroFalso(0.0)
m2.micro_abierto = False
for _ in range(900):
    m2._mezclar(1024)
check("al callar la musica vuelve", m2._duck > 0.9, "factor=%.2f" % m2._duck)

print("\n=== 7. Limitador (nunca saturar) ===")
m3 = motor.Mezclador(emisor=None)
fuerte = np.full((1024, 2), 3.0, dtype=np.float32)
limitado, red = m3._limitar(fuerte)
check("recorta el pico a 0.97", abs(float(np.max(np.abs(limitado))) - 0.97) < 0.001,
      "pico=%.3f" % float(np.max(np.abs(limitado))))
check("informa la reduccion", red < -9, "%.1f dB" % red)
suave = np.full((1024, 2), 0.5, dtype=np.float32)
igual, red2 = m3._limitar(suave)
check("no toca lo que no satura", np.allclose(igual, suave) and red2 == 0.0)

print("\n=== 8. El emisor nunca se queda sin audio ===")
import emisor as mod_emisor
cmd = mod_emisor.construir_comando(destino="icecast://u:x@h:8026/")
check("entrada f32le al muestreo del motor", "-f" in cmd and "f32le" in cmd)
check("convierte a 44100 para el servidor",
      cmd[cmd.index("-ar", cmd.index("libmp3lame")) + 1] == "44100")
check("manda el nombre de la emisora", "-ice_name" in cmd)

e = mod_emisor.Emisor()
b1 = np.full((1024, 2), 0.5, dtype=np.float32)
for _ in range(200):
    e.enviar(b1)
check("la cola no crece sin limite", e._cola.qsize() <= 64,
      "%d bloques" % e._cola.qsize())

print("")
print("=== 9. Monitor por auriculares (incluido Bluetooth) ===")
import sounddevice as sd
salidas = audio.listar(entrada=False)
check("hay alguna salida", len(salidas) > 0, "%d encontradas" % len(salidas))
for i_dev, nombre_dev, api_dev, ch_dev in salidas:
    extras = audio.ajustes_wasapi(i_dev)
    if api_dev == "Windows WASAPI":
        check("pide conversion a Windows: %s" % nombre_dev[:26], extras is not None)
    abierto, fallo = False, ""
    for ex in (extras, None):
        try:
            st = sd.OutputStream(samplerate=48000, blocksize=1024, device=i_dev,
                                 channels=2, dtype="float32", extra_settings=ex)
            st.start()
            st.write(np.zeros((1024, 2), dtype=np.float32))   # silencio: no suena
            st.stop()
            st.close()
            abierto = True
            break
        except Exception as e:
            fallo = str(e)[:42]
    check("se abre a 48 kHz: %s" % nombre_dev[:26], abierto, fallo)

print("")
print("=== 10. Varios microfonos (locutor + invitados) ===")
m4 = motor.Mezclador(emisor=None)
m4.monitor_activo = False
check("se crean los canales configurados", len(m4.canales) >= 2,
      "%d canales" % len(m4.canales))
check("cada uno con su nombre",
      all(c.nombre for c in m4.canales),
      " / ".join(c.nombre for c in m4.canales))

for c in m4.canales:
    c.micro = MicroFalso(0.5)
    c.abierto = False
    c.volumen = 1.0
m4.vol_micro = 1.0

silencio = rms(m4._mezclar(1024))
check("con todos cerrados no entra voz", silencio < 0.01, "rms=%.4f" % silencio)

m4.canales[0].abierto = True
for _ in range(3):
    m4._mezclar(1024)
uno = rms(m4._mezclar(1024))
check("con uno abierto se oye", uno > 0.2, "rms=%.3f" % uno)
check("el vumetro del 1 sube", m4.niveles["micro0"] > -20,
      "%.1f dB" % m4.niveles["micro0"])
check("el del 2 sigue apagado", m4.niveles["micro1"] <= -60,
      "%.1f dB" % m4.niveles["micro1"])

m4.canales[1].abierto = True
for _ in range(3):
    m4._mezclar(1024)
dos = rms(m4._mezclar(1024))
check("con los dos abiertos suena mas", dos > uno * 1.5,
      "%.3f -> %.3f" % (uno, dos))
check("los dos vumetros marcan",
      m4.niveles["micro0"] > -20 and m4.niveles["micro1"] > -20,
      "%.1f / %.1f dB" % (m4.niveles["micro0"], m4.niveles["micro1"]))

m4.canales[0].abierto = False
for _ in range(3):
    m4._mezclar(1024)
solo2 = rms(m4._mezclar(1024))
check("cerrar el 1 no calla al 2", solo2 > 0.2, "rms=%.3f" % solo2)
check("micro_abierto avisa si hay ALGUNO abierto", m4.micro_abierto is True)
m4.canales[1].abierto = False
check("y es False con todos cerrados", m4.micro_abierto is False)

print("")
print("=== 11. El invitado tambien baja la musica (ducking) ===")
m5 = motor.Mezclador(emisor=None)
m5.monitor_activo = False
m5.ducking = True
m5.pista_a.cargar(TONO)
m5.pista_a.reproducir()
for c in m5.canales:
    c.micro = MicroFalso(0.0)
    c.abierto = False
    c.volumen = 1.0
for _ in range(30):
    m5._mezclar(1024)
check("callados, la musica esta entera", m5._duck > 0.95, "factor=%.2f" % m5._duck)

# habla SOLO el invitado (el segundo canal)
m5.canales[1].micro = MicroFalso(0.7)
m5.canales[1].abierto = True
for _ in range(200):
    m5._mezclar(1024)
check("si habla el invitado, la musica baja igual", m5._duck < 0.4,
      "factor=%.2f" % m5._duck)

print("")
print("=== 12. Cada microfono con su propio ecualizador ===")
m6 = motor.Mezclador(emisor=None)
m6.monitor_activo = False
m6.canales[0].eq.cargar({"graves": 0, "medios": 0, "presencia": 0, "aire": 0,
                         "corte_grave": False})
m6.canales[1].eq.cargar({"graves": 0, "medios": -12, "presencia": 0, "aire": 0,
                         "corte_grave": False})
# el compresor nivela las diferencias, y aqui queremos medir SOLO el
# ecualizador: se apaga en los dos canales
for c in m6.canales:
    c.comp.activo = False
check("son ecualizadores distintos", m6.canales[0].eq is not m6.canales[1].eq)
check("el 1 queda plano", m6.canales[0].eq.plano)
check("y el 2 no", not m6.canales[1].eq.plano)

# un tono de 400 Hz por los dos: el segundo debe salir mas bajo
for c in m6.canales:
    c.micro = MicroFalso(0.5, hz=400.0)
    c.volumen = 1.0
    c.abierto = False
m6.vol_micro = 1.0
m6.canales[0].abierto = True
for _ in range(10):
    m6._mezclar(1024)
n1 = m6.niveles["micro0"]
m6.canales[0].abierto = False
m6.canales[1].abierto = True
for _ in range(10):
    m6._mezclar(1024)
n2 = m6.niveles["micro1"]
check("el ecualizador del 2 le baja los 400 Hz", n1 - n2 > 8,
      "%.1f dB vs %.1f dB" % (n1, n2))

print("\n" + "=" * 60)
print("  %d comprobaciones OK, %d fallos" % (ok, len(fallos)))
if fallos:
    print("  Fallaron: " + ", ".join(fallos))
print("=" * 60)
sys.exit(1 if fallos else 0)
