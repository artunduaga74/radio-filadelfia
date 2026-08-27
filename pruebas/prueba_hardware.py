# -*- coding: utf-8 -*-
"""
Comprobaciones del cambio de aparatos de audio en caliente.

El problema que resuelve: PortAudio se queda con la lista de aparatos que
habia al arrancar, asi que enchufar otro microfono con la aplicacion abierta
no se nota. Para que se note hay que reiniciar PortAudio, y eso **invalida
todos los streams abiertos**.

Lo que aqui se MIDE, que es lo delicado:
  - que preguntar "¿hay algo nuevo?" sea barato y no toque la tarjeta de sonido
  - que al cambiar los aparatos **el emisor siga recibiendo audio a tiempo**,
    porque eso es lo que mantiene la emisora al aire
"""

import sys
import tempfile
import time
from pathlib import Path

import numpy as np

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA.parent))

import config

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Leccion 8: las pruebas NUNCA escriben en la configuracion real.
pruebas = Path(tempfile.mkdtemp(prefix="radio_hw_"))
config.ARCHIVO_AJUSTES = pruebas / "ajustes.json"
config.ARCHIVO_CLAVES = pruebas / "credenciales.env"
config.CARPETA_DATOS = pruebas / "datos"
config.CARPETA_GRABA = pruebas / "grabaciones"
config._cache = None

import audio
import motor

ok, fallos = 0, []


def check(nombre, cond, detalle=""):
    global ok
    if cond:
        ok += 1
        print("  OK   %s %s" % (nombre, detalle))
    else:
        fallos.append(nombre)
        print("  FALLA %s %s" % (nombre, detalle))


class EmisorFalso(object):
    """Anota CUANDO llega cada bloque: es lo que mantiene viva la emisora."""

    def __init__(self):
        self.marcas = []
        self.muestras = 0

    def enviar(self, bloque):
        self.marcas.append(time.perf_counter())
        self.muestras += len(bloque)


print("")
print("=== 1. Preguntar por el hardware es barato y no toca el audio ===")
huella = audio.huella_hardware()
check("da una foto de los aparatos", isinstance(huella, tuple))
check("encuentra alguno", len(huella) > 0, "%d activos" % len(huella))
check("es estable si no se toca nada", audio.huella_hardware() == huella)

t0 = time.perf_counter()
for _ in range(30):
    audio.huella_hardware()
coste = (time.perf_counter() - t0) / 30 * 1000
check("cuesta menos de 20 ms (se pregunta cada 4 s)", coste < 20,
      "%.2f ms de media" % coste)

# la prueba de que NO pasa por la tarjeta de sonido: con un stream abierto,
# preguntar mil veces no lo estropea
import sounddevice as sd

salidas = audio.listar(entrada=False)
if salidas:
    try:
        s = sd.OutputStream(samplerate=48000, blocksize=512,
                            device=salidas[0][0], channels=2, dtype="float32",
                            extra_settings=audio.ajustes_wasapi(salidas[0][0]))
        s.start()
        for _ in range(20):
            audio.huella_hardware()
        s.write(np.zeros((512, 2), dtype=np.float32))
        check("un stream abierto sobrevive a 20 preguntas", True)
        s.stop()
        s.close()
    except Exception as e:
        print("      (no hay salida utilizable aqui: %s)" % str(e)[:50])
else:
    print("      (este equipo no tiene salidas de audio)")

print("")
print("=== 2. Reiniciar PortAudio SI mata los streams (por eso el cuidado) ===")
if salidas:
    try:
        s = sd.OutputStream(samplerate=48000, blocksize=512,
                            device=salidas[0][0], channels=2, dtype="float32",
                            extra_settings=audio.ajustes_wasapi(salidas[0][0]))
        s.start()
        s.write(np.zeros((512, 2), dtype=np.float32))
        audio.refrescar()
        murio = False
        try:
            s.write(np.zeros((512, 2), dtype=np.float32))
        except Exception:
            murio = True
        check("tras refrescar, el stream viejo ya no vale", murio,
              "por eso `refrescar_dispositivos` los cierra y reabre a mano")
        try:
            s.close()
        except Exception:
            pass
    except Exception as e:
        print("      (no se pudo montar la prueba: %s)" % str(e)[:50])

print("")
print("=== 3. Cambiar los aparatos NO corta el aire ===")
emisor = EmisorFalso()
mezclador = motor.Mezclador(emisor=emisor)
mezclador.monitor_activo = bool(salidas)
if salidas:
    config.guardar({"monitor": salidas[0][1], "monitor_activo": True})
periodo = mezclador.bloque / float(mezclador.muestreo) * 1000
print("      un bloque cada %.1f ms (bloque=%d, muestreo=%d)"
      % (periodo, mezclador.bloque, mezclador.muestreo))

mezclador.arrancar()
time.sleep(1.2)
antes = len(emisor.marcas)
check("el mezclador esta entregando audio", antes > 50, "%d bloques" % antes)

t0 = time.perf_counter()
correcto, detalle = mezclador.refrescar_dispositivos()
tardanza = (time.perf_counter() - t0) * 1000
print("      refrescar_dispositivos(): %.0f ms -> %s" % (tardanza, detalle))
check("el refresco termina", correcto or "Pero:" in detalle, detalle[:60])
# se mira AQUI, con el mezclador todavia en marcha: mirarlo despues de
# `detener()` daria siempre que no (detener cierra el monitor a proposito)
monitor_recuperado = mezclador._salida is not None
banderas_limpias = (not mezclador._soltar.is_set()
                    and not mezclador._soltado.is_set())
foto_al_dia = mezclador.hardware == audio.huella_hardware()
time.sleep(1.2)
mezclador.detener()

huecos = np.diff(emisor.marcas) * 1000
peor = float(huecos.max())
# ¿Por que 250 ms y no un numero cualquiera? Porque es la mitad del unico
# limite que existe de verdad: `emisor._escritor` espera **500 ms** con la cola
# vacia antes de empezar a meter silencio, y el servidor no suelta la fuente
# hasta los 30 s de inactividad. Un tropiezo de 100 ms mientras se cambia de
# aparato no llega ni a rozarlo, y es justo lo que dice el CLAUDE.md:
# "preferimos perder 20 ms de audio antes que frenar el hilo del mezclador".
#
# Se mide ademas la MEDIANA, que es lo que delata una regresion de verdad: el
# peor dato ocasional lo pone Windows planificando, no nuestro codigo.
LIMITE = 250.0
mediana = float(np.median(huecos))
check("el emisor nunca se quedo seco durante el cambio", peor < LIMITE,
      "peor hueco %.1f ms (limite %.0f, silencio del emisor a los 500)"
      % (peor, LIMITE))
check("y el ritmo normal no se movio", mediana < periodo * 1.5,
      "mediana %.1f ms, lo normal es %.1f" % (mediana, periodo))

segundos = emisor.marcas[-1] - emisor.marcas[0]
entregado = emisor.muestras / float(mezclador.muestreo)
desfase = abs(entregado / segundos - 1) * 100
check("se entrego tanto audio como tiempo paso (reloj de pared intacto)",
      desfase < 5, "%.2f s de audio en %.2f s de reloj (%.1f%% de desfase)"
                   % (entregado, segundos, desfase))

print("")
print("=== 4. Los aparatos vuelven a quedar como estaban ===")
if salidas and mezclador.monitor_activo:
    check("los auriculares vuelven a abrirse solos", monitor_recuperado,
          "monitor abierto=%s  %s" % (monitor_recuperado, mezclador.error[:40]))
check("las banderas quedan limpias (no se queda a medias)", banderas_limpias)
check("la foto del hardware se actualiza", foto_al_dia)

print("")
print("=== 4b. EL MICROFONO SIGUE PUDIENDO ABRIRSE (regresion del 25-08) ===")
# Lo que reporto el usuario: tras pulsar "Buscar aparatos nuevos", asignar el
# aparato nuevo y darle al boton del microfono, salia "No se pudo abrir
# Micro 1." con el motivo VACIO. Causa: el refresco cerraba todos los streams
# y solo reabria los que estuvieran YA al aire; como lo normal es tenerlos
# cerrados mientras uno trastea en Configuracion, quedaban todos muertos, y el
# boton de la mesa solo levanta una bandera: no sabe abrir un stream cerrado.
entradas = audio.listar(entrada=True)
if entradas:
    micros = config.microfonos()
    micros[0]["dispositivo"] = entradas[0][1]
    config.guardar_microfonos(micros)

    m3 = motor.Mezclador(emisor=None)
    m3.monitor_activo = False
    m3.arrancar()
    time.sleep(0.4)
    abierto_antes = m3.canales[0].micro.abierto
    check("recien arrancado, el microfono esta listo", abierto_antes,
          m3.canales[0].micro.error[:50])

    m3.refrescar_dispositivos()
    check("TRAS refrescar el hardware sigue listo (era el fallo)",
          m3.canales[0].micro.abierto,
          "error=%r" % (m3.canales[0].micro.error or "-"))
    check("y no se queda encendido solo",
          m3.canales[0].abierto is False)

    # y ahora asignarle OTRO aparato sin reiniciar la aplicacion
    if len(entradas) > 1:
        micros = config.microfonos()
        micros[0]["dispositivo"] = entradas[1][1]
        config.guardar_microfonos(micros)
        m3.aplicar_ajustes()
        check("cambiar el aparato en Configuracion llega al canal",
              m3.canales[0].micro.dispositivo == entradas[1][1],
              repr(m3.canales[0].micro.dispositivo))
        check("y queda abierto con el nuevo", m3.canales[0].micro.abierto,
              m3.canales[0].micro.error[:50])

    # el ultimo recurso: aunque alguien lo cierre, se puede recuperar
    m3.canales[0].micro.cerrar()
    m3.sincronizar_microfonos()
    check("un microfono cerrado a mano se recupera solo",
          m3.canales[0].micro.abierto)
    m3.detener()
else:
    print("      (este equipo no tiene microfonos)")

print("")
print("=== 5. Sin mezclador en marcha tambien funciona ===")
parado = motor.Mezclador(emisor=None)
parado.monitor_activo = False
correcto, detalle = parado.refrescar_dispositivos()
check("refresca sin estar sonando", correcto, detalle[:60])
check("y no deja banderas puestas",
      not parado._soltar.is_set() and not parado._soltado.is_set())

print("")
print("=== 6. El aviso solo salta cuando algo cambia de verdad ===")
m2 = motor.Mezclador(emisor=None)
check("recien creado no avisa de nada", m2.hay_hardware_nuevo() is False)
m2.hardware = tuple(list(m2.hardware) + ["Capture:{inventado}"])
check("con la foto cambiada, avisa", m2.hay_hardware_nuevo() is True)
m2.hardware = ()
check("sin foto fiable NO inventa un aviso", m2.hay_hardware_nuevo() is False)

print("")
print("=== 7. El boton, en la ventana de Configuracion de verdad ===")
import tkinter as tk

import app as mod_app
import procesos

# el dialogo es modal (grab_set + wait_window); aqui se le quita para poder
# pilotarlo desde la prueba
_grab, _wait = tk.Toplevel.grab_set, tk.Misc.wait_window
tk.Toplevel.grab_set = lambda self: None
tk.Misc.wait_window = lambda self, w=None: None
try:
    ventana = mod_app.App()
    ventana.update()
    dialogo = mod_app.DialogoConfig(ventana)
    ventana.update()
finally:
    tk.Toplevel.grab_set, tk.Misc.wait_window = _grab, _wait

check("hay boton para buscar aparatos", hasattr(dialogo, "btn_buscar_hw"))
check("se registraron los desplegables para repoblarlos",
      len(dialogo._combos_entrada) > 0 and len(dialogo._combos_salida) > 0,
      "%d entradas, %d salidas" % (len(dialogo._combos_entrada),
                                   len(dialogo._combos_salida)))
# Leccion 2: esta ventana ya median 1048 px en una pantalla de 1080. La
# funcion nueva NO puede robarle margen o los botones de abajo se salen.
alto, pantalla = dialogo.winfo_height(), dialogo.winfo_screenheight()
check("la ventana sigue cabiendo en la pantalla", alto <= pantalla,
      "%d px de alto, pantalla de %d (margen %d)" % (alto, pantalla,
                                                     pantalla - alto))

dialogo.buscar_hardware()
peor_congelacion = 0.0
inicio = time.perf_counter()
for _ in range(400):
    t = time.perf_counter()
    ventana.update()
    peor_congelacion = max(peor_congelacion, (time.perf_counter() - t) * 1000)
    time.sleep(0.02)
    if "buscando" not in dialogo.lbl_hw.cget("text"):
        break
check("la busqueda termina", "buscando" not in dialogo.lbl_hw.cget("text"),
      dialogo.lbl_hw.cget("text"))
# lo importante: se hace en otro hilo, asi que la ventana NO se congela
# aunque un aparato Bluetooth tarde en despertar
check("la ventana no se congela mientras busca", peor_congelacion < 150,
      "peor parada %.0f ms" % peor_congelacion)
check("el boton vuelve a poder pulsarse",
      "disabled" not in dialogo.btn_buscar_hw.state())
check("queda anotado en el registro tecnico",
      any("hardware de audio" in l for l in ventana.registro))

try:
    dialogo.destroy()
    ventana.update()
    ventana._al_cerrar()
    ventana.destroy()
except Exception:
    pass
procesos.cerrar_todos()

print("")
print("=" * 62)
print("  %d comprobaciones OK, %d fallos" % (ok, len(fallos)))
if fallos:
    print("  Fallaron: " + ", ".join(fallos))
print("=" * 62)
sys.exit(1 if fallos else 0)
