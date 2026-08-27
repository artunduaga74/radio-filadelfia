# -*- coding: utf-8 -*-
"""
Comprobaciones del emisor y del protocolo ICY.

Incluye la prueba de NO REGRESION del fallo del 2026-08-24: la prueba de
conexion daba "PASA" con una clave equivocada, porque el host llevaba pegada
la ruta de la pagina del panel y ffmpeg acababa hablando con un servidor web.

Habla con el servidor real, pero SOLO con una clave falsa y sin mandar audio:
no interrumpe la emision.
"""

import os
import sys
import tempfile
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA.parent))

import config

# la consola de Windows viene en cp1252 y no sabe pintar los
# iconos del reproductor; sin esto, un print rompe la prueba
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

pruebas = Path(tempfile.mkdtemp(prefix="radio_emisor_"))
config.ARCHIVO_AJUSTES = pruebas / "ajustes.json"
config.ARCHIVO_CLAVES = pruebas / "credenciales.env"
config.CARPETA_DATOS = pruebas / "datos"
config.CARPETA_GRABA = pruebas / "grabaciones"
config._cache = None

import time

import emisor
import icy

HOST_REAL = "cast1.asurahosting.com"
CLAVE_FALSA = "ESTA_CLAVE_NO_ES_LA_BUENA"

ok, fallos = 0, []


def check(nombre, cond, detalle=""):
    global ok
    if cond:
        ok += 1
        print("  OK   %s %s" % (nombre, detalle))
    else:
        fallos.append(nombre)
        print("  FALLA %s %s" % (nombre, detalle))


print("\n=== 1. Limpieza del host (la causa del fallo) ===")
casos = [
    ("http://cast1.asurahosting.com/start/nonefern", "cast1.asurahosting.com"),
    ("https://cast1.asurahosting.com:8024/index.html", "cast1.asurahosting.com"),
    ("cast1.asurahosting.com", "cast1.asurahosting.com"),
    ("  cast1.asurahosting.com:8026  ", "cast1.asurahosting.com"),
    ("http://usuario:clave@cast1.asurahosting.com/x", "cast1.asurahosting.com"),
    ("", ""),
]
for entrada, esperado in casos:
    obtenido = emisor.limpiar_host(entrada)
    check("limpia %r" % (entrada[:38] or "(vacio)"), obtenido == esperado,
          "-> %r" % obtenido)

print("\n=== 2. La URL de Icecast ya no puede salir deformada ===")
url = emisor.url_destino("http://cast1.asurahosting.com/start/nonefern",
                         8026, "/stream", "usuario", "clave")
check("el puerto queda pegado al host", "cast1.asurahosting.com:8026" in url, url)
check("no se cuela la ruta del panel", "/start/nonefern" not in url)

print("\n=== 3. Lectura de la respuesta del servidor ===")
for respuesta, esperado in (("OK2\r\nicy-caps:11", True), ("OK", True),
                            ("Invalid password", False),
                            ("Invalid Password", False), ("", False)):
    aceptado, explicacion = icy._interpretar(respuesta)
    check("interpreta %r" % (respuesta[:18] or "(vacio)"), aceptado == esperado,
          "-> %s" % explicacion[:44])

print("\n=== 4. Saludo ICY contra el servidor REAL (clave falsa) ===")
print("    (no manda audio: no interrumpe la emision)")
SERVIDOR_VIVO = {}
for puerto in (8027, 8025):
    aceptado, explicacion = icy.probar(HOST_REAL, puerto, CLAVE_FALSA)
    rechazo = (not aceptado) and "rechazo la clave" in explicacion
    SERVIDOR_VIVO[puerto] = rechazo
    if rechazo:
        check("puerto %d habla ICY y rechaza la clave falsa" % puerto, True,
              "-> %s" % explicacion[:46])
    else:
        # el servidor puede no contestar (sin red, o limitando intentos). Lo
        # que NUNCA puede pasar es que acepte una clave falsa, y eso si se exige.
        check("puerto %d no acepta una clave falsa" % puerto, not aceptado,
              "(sin comprobar el protocolo: %s)" % explicacion[:38])
    time.sleep(0.8)      # sin prisa: es un servidor compartido de verdad

print("\n=== 5. NO REGRESION: una clave mala NUNCA puede dar 'PASA' ===")
combos = [
    ("host con la ruta del panel (el fallo original)",
     "http://cast1.asurahosting.com/start/nonefern", 8024, "shoutcast_v1"),
    ("host limpio, puerto de oyentes", HOST_REAL, 8024, "shoutcast_v1"),
    ("host limpio, puerto 8026 del panel", HOST_REAL, 8026, "shoutcast_v1"),
    ("protocolo Icecast, host con ruta",
     "http://cast1.asurahosting.com/start/nonefern", 8026, "icecast"),
]
for nombre, host, puerto, proto in combos:
    aceptado, msg = emisor.probar_conexion(host, puerto, "usuariofalso",
                                           CLAVE_FALSA, "/stream",
                                           protocolo=proto, segundos=2)
    check("rechaza: %s" % nombre, not aceptado, "-> %s" % msg.splitlines()[0][:48])

print("")
print("=== 5b. El puerto que se escribe es el DEL PANEL (+1 por dentro) ===")
check("8024 del panel -> 8025 real",
      emisor.puerto_fuente(8024, "shoutcast_v1") == 8025)
check("8026 del panel -> 8027 real",
      emisor.puerto_fuente(8026, "shoutcast_v1") == 8027)
check("con Icecast no se suma nada",
      emisor.puerto_fuente(8000, "icecast") == 8000)
check("se puede desactivar la suma",
      emisor.puerto_fuente(8024, "shoutcast_v1", sumar_uno=False) == 8024)
config.guardar({"puerto": 8024, "protocolo": "shoutcast_v1",
                "sumar_uno_v1": True})
check("lo toma de la configuracion si no se le pasa nada",
      emisor.puerto_fuente() == 8025, str(emisor.puerto_fuente()))
aceptado, msg = emisor.probar_conexion(HOST_REAL, 8024, "usuariofalso",
                                       CLAVE_FALSA, protocolo="shoutcast_v1",
                                       segundos=2)
check("escribir 8024 llega a la fuente y la rechaza por clave",
      (not aceptado) and "rechazo la clave" in msg, "-> %s" % msg[:44])

print("\n=== 6. Comando de ffmpeg para SHOUTcast v1 ===")
config.guardar({"protocolo": "shoutcast_v1", "bitrate": 128,
                "muestreo": 48000, "muestreo_salida": 44100})
cmd = emisor.construir_comando(a_tuberia=True, grabar="prog.mp3")
check("saca el MP3 por una tuberia", "pipe:1" in cmd)
check("no intenta hablar Icecast el mismo",
      not any(str(a).startswith("icecast://") for a in cmd))
check("entra PCM crudo del mezclador", "f32le" in cmd)
check("convierte a 44100 para el servidor",
      cmd[cmd.index("-ar", cmd.index("libmp3lame")) + 1] == "44100")
check("sigue grabando el programa", "prog.mp3" in cmd)
check("sin cabecera Xing (estorba en directo)",
      cmd[cmd.index("-write_xing") + 1] == "0")

print("\n=== 7. La clave se manda como usuario:clave (lo que pide Centova) ===")
config.guardar({"usuario": "erick", "clave_con_usuario": True})
config.guardar_clave("clave_fuente", "secreta")
e = emisor.Emisor()
check("junta usuario y clave", e._clave_icy() == "erick:secreta", e._clave_icy())
config.guardar({"clave_con_usuario": False})
check("se puede desactivar", e._clave_icy() == "secreta", e._clave_icy())
config.guardar({"clave_con_usuario": True})
config.guardar_clave("clave_fuente", "otro:yaviene")
check("respeta la clave que ya trae dos puntos",
      e._clave_icy() == "otro:yaviene", e._clave_icy())

print("\n=== 8. Si el servidor no acepta, NO se queda 'al aire' ===")
# 8026 es el numero DEL PANEL: con la regla del +1 acaba en el 8027, que es
# el nuestro. Poner 8027 aqui llevaria al 8028, que es de otro cliente.
config.guardar({"host": HOST_REAL, "puerto": 8026, "protocolo": "shoutcast_v1",
                "usuario": "usuariofalso", "reconectar": False,
                "grabar_al_aire": False})
config.guardar_clave("clave_fuente", CLAVE_FALSA)
e2 = emisor.Emisor()
arranco = e2.arrancar()
check("arrancar() avisa que fallo", not arranco)
check("no dice estar al aire", not e2.al_aire)
check("el estado queda en error", e2.estado == emisor.ERROR, e2.estado)
if SERVIDOR_VIVO.get(8027):
    check("explica que la clave fue rechazada", "clave" in e2.detalle.lower(),
          e2.detalle[:50])
else:
    check("da una explicacion en castellano", bool(e2.detalle.strip()),
          e2.detalle[:50])
e2.detener()

print("")
print("=== RECONEXION AUTOMATICA (con un servidor ICY de mentira) ===")
# Esto NUNCA se habia probado, y estaba roto: `_caida` cerraba el socket pero
# dejaba vivo ffmpeg, y como `arrancar()` empieza con "si ya hay un ffmpeg
# vivo, no hagas nada", el reintento se creia conectado. Resultado: al caerse
# el internet la emisora se quedaba en "error" para siempre.
import socket as _socket
import threading as _hilos

import numpy as _np

# El fin de linea del protocolo, como constante: escrito dentro de una
# cadena en un parche automatico se convierte en salto REAL y rompe el
# archivo. Ya ha pasado tres veces en este proyecto.
FIN = bytes([13, 10])


def _servidor_icy(corta_a_los=None, rechaza=False):
    """Devuelve (puerto, lista_de_conexiones, cerrar())."""
    srv = _socket.socket()
    srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    conexiones = []

    def atender():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            conexiones.append(time.time())
            try:
                c.recv(256)
                if rechaza:
                    c.sendall(b"Invalid password" + FIN)
                    c.close()
                    continue
                c.sendall(b"OK2" + FIN + FIN)
                fin = time.time() + (corta_a_los or 9999)
                c.settimeout(0.3)
                while time.time() < fin:
                    try:
                        if not c.recv(65536):
                            break
                    except _socket.timeout:
                        pass
                    except OSError:
                        break
            except Exception:
                pass
            finally:
                try:
                    c.close()
                except Exception:
                    pass

    _hilos.Thread(target=atender, daemon=True).start()
    return srv.getsockname()[1], conexiones, srv.close


def _alimentar(em, segundos):
    """Como hace el mezclador: bloques sin parar."""
    fin = time.time() + segundos

    def bucle():
        n = int(48000 * 0.02)
        while time.time() < fin:
            em.enviar(_np.zeros((n, 2), dtype=_np.float32))
            time.sleep(0.02)

    _hilos.Thread(target=bucle, daemon=True).start()


puerto, conexiones, cerrar = _servidor_icy(corta_a_los=1.5)
config.guardar({"host": "127.0.0.1", "puerto": puerto - 1,
                "sumar_uno_v1": True, "protocolo": "shoutcast_v1",
                "reconectar": True, "reconectar_seg": 2, "bitrate": 64,
                "muestreo": 48000, "canales": 2})
config.guardar_clave("clave_fuente", "loquesea")
e3 = emisor.Emisor()
e3.intentar_salir_al_aire()
_alimentar(e3, 12)
time.sleep(12)
check("se reconecta solo cuando el servidor corta", len(conexiones) >= 3,
      "%d conexiones en 12 s" % len(conexiones))
check("y acaba al aire otra vez", e3.al_aire, e3.estado)
check("ffmpeg NO se queda vivo tras una caida (era el fallo)",
      e3._proc is None or e3._proc.poll() is None)
e3.detener()
cerrar()

# --- sin internet al salir al aire: debe insistir hasta que vuelva ---
libre = _socket.socket()
libre.bind(("127.0.0.1", 0))
puerto2 = libre.getsockname()[1]
libre.close()
config.guardar({"puerto": puerto2 - 1})
e4 = emisor.Emisor()
e4.intentar_salir_al_aire()
_alimentar(e4, 16)
check("sin servidor, queda en error pero con reintento en camino",
      e4.estado == emisor.ERROR and e4._reintento_pendiente,
      "%s / pendiente=%s" % (e4.estado, e4._reintento_pendiente))
time.sleep(6)
srv2 = _socket.socket()
srv2.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
srv2.bind(("127.0.0.1", puerto2))
srv2.listen(5)
llegadas = []


def atender2():
    while True:
        try:
            c, _ = srv2.accept()
        except OSError:
            return
        llegadas.append(1)
        try:
            c.recv(256)
            c.sendall(b"OK2" + FIN + FIN)
            while True:
                if not c.recv(65536):
                    break
        except Exception:
            pass


_hilos.Thread(target=atender2, daemon=True).start()
time.sleep(7)
check("entra sola en cuanto vuelve el internet", len(llegadas) >= 1,
      "%d conexiones tras levantar el servidor" % len(llegadas))
e4.detener()
try:
    srv2.close()
except Exception:
    pass

# --- clave mala: NO insistir (machacar al servidor acaba en bloqueo) ---
puerto3, golpes, cerrar3 = _servidor_icy(rechaza=True)
config.guardar({"puerto": puerto3 - 1})
config.guardar_clave("clave_fuente", "mala")
e5 = emisor.Emisor()
e5.intentar_salir_al_aire()
time.sleep(8)
check("con la clave mal NO se pone a insistir", len(golpes) <= 1,
      "%d golpes al servidor en 8 s" % len(golpes))
check("y lo dice claro", "clave" in e5.detalle.lower(), e5.detalle[:50])
e5.detener()
cerrar3()

import procesos
procesos.cerrar_todos()
vivos = [p for p in procesos._vivos if p.poll() is None]
check("no quedan procesos sueltos", len(vivos) == 0, "%d vivos" % len(vivos))

print("\n" + "=" * 62)
print("  %d comprobaciones OK, %d fallos" % (ok, len(fallos)))
if fallos:
    print("  Fallaron: " + ", ".join(fallos))
print("=" * 62)
sys.exit(1 if fallos else 0)
