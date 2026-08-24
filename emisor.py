# -*- coding: utf-8 -*-
"""
El que saca la senal al aire.

Idea central (y es lo que evita los cortes): UN SOLO proceso de ffmpeg que se
arranca al empezar la transmision y NO se reinicia nunca. Todo lo demas
(cambiar de cancion, disparar un jingle, abrir el microfono) pasa antes, en el
mezclador. El servidor solo ve un chorro continuo de audio.

Ademas hay un "reloj de pared": si el mezclador se atrasa, este modulo escribe
silencio en vez de esperar. El servidor corta las fuentes inactivas a los 30
segundos, asi que quedarse callado es mucho mejor que quedarse quieto.

Dos formas de entregar el audio, segun lo que acepte el servidor:

  "shoutcast_v1"  ffmpeg comprime a MP3 y NOSOTROS empujamos los bytes por un
                  socket ICY (ver icy.py). Es lo que necesita esta emisora.
  "icecast"       ffmpeg habla directamente con el servidor. Mas simple, pero
                  este servidor no lo admite (todos los montajes dan 404).
"""

import queue
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime

import numpy as np

import config
import icy
import procesos

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

PARADO = "parado"
CONECTANDO = "conectando"
AL_AIRE = "al_aire"
ERROR = "error"

TROZO = 8192            # bytes de MP3 por envio al socket


def limpiar_host(texto):
    """
    Deja solo el nombre del servidor.

    Hace falta porque es facil pegar aqui la direccion de la pagina del panel
    ("http://cast1.asurahosting.com/start/nonefern") en vez del host. Si eso
    se cuela en la URL, ffmpeg acaba hablando con un servidor web cualquiera
    y todo *parece* funcionar aunque no salga nada al aire. Paso de verdad.
    """
    t = (texto or "").strip()
    if "//" in t:
        t = t.split("//", 1)[1]
    t = t.split("/", 1)[0]          # fuera la ruta
    t = t.split("@")[-1]            # por si trae usuario:clave@
    if ":" in t:                    # fuera el puerto, va aparte
        t = t.split(":", 1)[0]
    return t.strip()


def url_destino(host=None, puerto=None, mount=None, usuario=None, clave=None):
    """URL de fuente para el protocolo Icecast (ffmpeg habla directo)."""
    host = limpiar_host(host if host is not None else config.get("host", ""))
    puerto = puerto or config.get("puerto", 8026)
    mount = mount if mount is not None else config.get("mount", "/stream")
    usuario = usuario or config.get("usuario", "source")
    clave = clave if clave is not None else config.clave("clave_fuente")
    if not mount.startswith("/"):
        mount = "/" + mount
    u = urllib.parse.quote(usuario, safe="")
    c = urllib.parse.quote(clave, safe="")
    return "icecast://%s:%s@%s:%s%s" % (u, c, host, puerto, mount)


def _salida_codec(codec, bitrate):
    if codec == "aac":
        return ["-c:a", "aac", "-b:a", "%dk" % bitrate,
                "-content_type", "audio/aac", "-f", "adts"]
    return ["-c:a", "libmp3lame", "-b:a", "%dk" % bitrate,
            "-write_xing", "0", "-id3v2_version", "0",
            "-content_type", "audio/mpeg", "-f", "mp3"]


def construir_comando(destino=None, grabar=None, legacy=False, a_tuberia=False):
    """
    El comando de ffmpeg: PCM crudo por la entrada; por la salida, o bien el
    servidor (Icecast) o bien una tuberia que vaciamos nosotros (SHOUTcast v1).
    """
    aj = config.cargar()
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning",
           "-f", "f32le", "-ar", str(int(aj["muestreo"])),
           "-ac", str(int(aj["canales"])),
           "-thread_queue_size", "512", "-i", "pipe:0"]

    cmd += _salida_codec(aj.get("codec", "mp3"), int(aj["bitrate"]))
    # ffmpeg convierte 48k (mezclador) -> 44.1k (servidor) con soxr, gratis
    cmd += ["-ar", str(int(aj.get("muestreo_salida", 44100))), "-ac", "2"]

    if a_tuberia:
        cmd += ["pipe:1"]
    else:
        cmd += ["-ice_name", aj.get("nombre_emisora") or "Radio",
                "-ice_genre", aj.get("genero") or "Misc",
                "-ice_description", aj.get("descripcion") or "",
                "-ice_url", aj.get("url_emisora") or "",
                "-ice_public", "1"]
        if legacy:
            cmd += ["-legacy_icecast", "1"]
        cmd += [destino or url_destino()]

    if grabar:
        cmd += ["-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3", str(grabar)]
    return cmd


class Emisor:
    """
    Uso:
        e = Emisor(al_cambiar=funcion)
        e.arrancar()
        e.enviar(bloque_float32)    # desde el mezclador, todo el rato
        e.detener()
    """

    def __init__(self, al_cambiar=None, al_registrar=None):
        self.al_cambiar = al_cambiar
        self.al_registrar = al_registrar
        self.estado = PARADO
        self.detalle = ""
        self.desde = 0.0
        self.grabacion = None
        self.bytes_enviados = 0

        self._proc = None
        self._sock = None
        self._cola = queue.Queue(maxsize=64)
        self._parar = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ estado

    def _poner(self, estado, detalle=""):
        self.estado = estado
        self.detalle = detalle
        if self.al_cambiar:
            try:
                self.al_cambiar(estado, detalle)
            except Exception:
                pass

    def _log(self, linea):
        if self.al_registrar:
            try:
                self.al_registrar(linea)
            except Exception:
                pass

    @property
    def al_aire(self):
        return self.estado == AL_AIRE

    def tiempo_al_aire(self):
        return time.time() - self.desde if self.desde else 0.0

    # ------------------------------------------------------------ arranque

    def arrancar(self, legacy=False):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return True
            aj = config.cargar()
            host = limpiar_host(aj.get("host", ""))
            if not host:
                self._poner(ERROR, "Falta configurar el servidor")
                return False

            config.asegurar_carpetas()
            self.grabacion = None
            if aj.get("grabar_al_aire", True):
                nombre = datetime.now().strftime("programa_%Y-%m-%d_%H-%M.mp3")
                self.grabacion = config.CARPETA_GRABA / nombre

            por_icy = aj.get("protocolo") == "shoutcast_v1"
            self._poner(CONECTANDO, "")
            self._log("Conectando a %s:%s (%s)"
                      % (host, aj.get("puerto"),
                         "SHOUTcast v1" if por_icy else "Icecast"))

            # --- 1. si es ICY, el saludo va PRIMERO: si la clave esta mal lo
            #        sabemos ya, antes de arrancar nada mas.
            if por_icy:
                try:
                    self._sock = icy.conectar(
                        host, aj.get("puerto"), self._clave_icy(),
                        nombre=aj.get("nombre_emisora"), genero=aj.get("genero"),
                        url=aj.get("url_emisora"),
                        bitrate=int(aj.get("bitrate", 128)))
                except icy.ErrorICY as e:
                    self._sock = None
                    self._poner(ERROR, str(e))
                    self._log("ICY: %s" % e)
                    return False
                self._log("El servidor acepto la fuente.")

            # --- 2. ffmpeg
            cmd = construir_comando(grabar=self.grabacion, legacy=legacy,
                                    a_tuberia=por_icy)
            try:
                self._proc = procesos.lanzar(
                    cmd, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE if por_icy else subprocess.DEVNULL,
                    stderr=subprocess.PIPE)
            except Exception as e:
                self._cerrar_socket()
                self._poner(ERROR, "No se pudo iniciar ffmpeg: %s" % e)
                return False

            self._parar.clear()
            self.bytes_enviados = 0
            threading.Thread(target=self._escritor, daemon=True).start()
            threading.Thread(target=self._vigilar_errores, daemon=True).start()
            if por_icy:
                threading.Thread(target=self._bombear_icy, daemon=True).start()
            else:
                self.desde = time.time()
            return True

    def _clave_icy(self):
        """
        En Centova, para transmitir al autoDJ la clave es usuario:contrasena
        (su panel lo dice con el ejemplo "jsmith:secret"). Si el usuario ya la
        escribio con dos puntos, se respeta tal cual.
        """
        clave = config.clave("clave_fuente")
        usuario = (config.get("usuario") or "").strip()
        if config.get("clave_con_usuario", True) and usuario and ":" not in clave:
            return "%s:%s" % (usuario, clave)
        return clave

    def detener(self):
        with self._lock:
            self._parar.set()
            proc, self._proc = self._proc, None
        try:
            while True:
                self._cola.get_nowait()
        except queue.Empty:
            pass
        if proc:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
        self._cerrar_socket()
        self.desde = 0.0
        self._poner(PARADO, "")

    def _cerrar_socket(self):
        s, self._sock = self._sock, None
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass

    # ------------------------------------------------------------ envio

    def enviar(self, bloque):
        """
        Recibe un bloque float32 (muestras x canales) del mezclador.
        Si la cola esta llena, TIRA el bloque mas viejo: preferimos perder
        20 ms de audio antes que frenar el mezclador (eso si cortaria el aire).
        """
        if self._parar.is_set():
            return
        try:
            self._cola.put_nowait(bloque)
        except queue.Full:
            try:
                self._cola.get_nowait()
                self._cola.put_nowait(bloque)
            except Exception:
                pass

    def _escritor(self):
        """El reloj de pared: pase lo que pase, ffmpeg siempre recibe audio."""
        while not self._parar.is_set():
            proc = self._proc
            if not proc or proc.poll() is not None:
                break
            try:
                bloque = self._cola.get(timeout=0.5)
            except queue.Empty:
                n = int(config.get("muestreo", 48000) * 0.5)
                bloque = np.zeros((n, int(config.get("canales", 2))),
                                  dtype=np.float32)
            try:
                datos = np.clip(bloque, -1.0, 1.0).astype(np.float32).tobytes()
                proc.stdin.write(datos)
            except (BrokenPipeError, OSError, ValueError, AttributeError):
                break
        if not self._parar.is_set():
            self._caida()

    def _bombear_icy(self):
        """Saca el MP3 de ffmpeg y lo empuja por el socket, sin parar."""
        proc, sock = self._proc, self._sock
        if not proc or not sock:
            return
        primero = True
        while not self._parar.is_set():
            try:
                datos = proc.stdout.read(TROZO)
            except Exception:
                break
            if not datos:
                break
            try:
                sock.sendall(datos)
            except Exception as e:
                self._log("Se corto el envio al servidor: %s" % e)
                break
            self.bytes_enviados += len(datos)
            if primero:
                primero = False
                self.desde = time.time()
                self._poner(AL_AIRE, "")
        if not self._parar.is_set():
            self._caida()

    def _vigilar_errores(self):
        """
        Drena stderr de ffmpeg. Es OBLIGATORIO: si se llenan los 64 KB de la
        tuberia, ffmpeg se bloquea para siempre (ya paso en el editor de video).
        """
        proc = self._proc
        if not proc or not proc.stderr:
            return
        for linea in iter(proc.stderr.readline, b""):
            txt = linea.decode("utf-8", "replace").strip()
            if not txt:
                continue
            self._log(txt)
            bajo = txt.lower()
            if any(p in bajo for p in ("401", "unauthorized", "invalid password",
                                       "forbidden", "403")):
                self._poner(ERROR, "Usuario o clave rechazados por el servidor")
            elif any(p in bajo for p in ("connection refused", "no route",
                                         "failed to resolve", "timed out",
                                         "404")):
                self._poner(ERROR, "No se pudo conectar: " + txt)

    def _caida(self):
        if self.estado == ERROR:
            detalle = self.detalle
        elif self.estado == CONECTANDO:
            detalle = "El servidor no acepto la conexion"
        else:
            detalle = "Se perdio la conexion"
        self.desde = 0.0
        self._cerrar_socket()
        self._poner(ERROR, detalle)
        if config.get("reconectar", True) and not self._parar.is_set():
            espera = max(2, int(config.get("reconectar_seg", 5)))
            self._log("Reintentando en %d s..." % espera)
            t = threading.Timer(espera, self._reintentar)
            t.daemon = True
            t.start()

    def _reintentar(self):
        if self._parar.is_set():
            return
        self._log("Reconectando...")
        self.arrancar()


# ------------------------------------------------------------------ pruebas

def probar_conexion(host, puerto, usuario, clave, mount="/stream",
                    protocolo="shoutcast_v1", legacy=False, segundos=5,
                    codec="mp3", bitrate=128, con_audio=True):
    """
    Comprueba de verdad que el servidor nos acepta como fuente.
    Devuelve (ok, mensaje).

    Para SHOUTcast v1 la verificacion es el propio saludo: el servidor contesta
    "OK" o "Invalid password", asi que no hay lugar a dudas. (La version
    anterior se fiaba del codigo de salida de ffmpeg y llego a dar por buena
    una conexion con la clave equivocada, porque el host mal escrito hacia que
    ffmpeg hablara con un servidor web cualquiera.)
    """
    host = limpiar_host(host)
    if not host:
        return False, "Falta el nombre del servidor"

    if protocolo == "shoutcast_v1":
        return _probar_icy(host, puerto, usuario, clave, segundos, bitrate,
                           con_audio)
    return _probar_icecast(host, puerto, usuario, clave, mount, legacy,
                           segundos, codec, bitrate)


def _probar_icy(host, puerto, usuario, clave, segundos, bitrate, con_audio):
    if usuario and ":" not in clave:
        clave_larga = "%s:%s" % (usuario, clave)
    else:
        clave_larga = clave
    ok, explicacion = icy.probar(host, puerto, clave_larga)
    if not ok:
        return False, explicacion
    if not con_audio:
        return True, explicacion

    # el saludo fue bien: mandamos un tono corto para confirmar que fluye
    try:
        s = icy.conectar(host, puerto, clave_larga, nombre="Prueba",
                         bitrate=bitrate, publico=False)
    except icy.ErrorICY as e:
        return False, str(e)
    try:
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi",
               "-i", "sine=frequency=440:sample_rate=44100:duration=%d" % segundos,
               "-ac", "2"] + _salida_codec("mp3", bitrate) + ["pipe:1"]
        p = subprocess.run(cmd, capture_output=True, timeout=segundos + 20,
                           creationflags=procesos.SIN_VENTANA)
        if p.returncode != 0:
            return False, "ffmpeg no pudo comprimir el tono de prueba"
        s.sendall(p.stdout)
        return True, "El servidor acepto la fuente y recibio el tono de prueba"
    except Exception as e:
        return False, "El saludo fue bien pero fallo el envio: %s" % e
    finally:
        try:
            s.close()
        except Exception:
            pass


def _probar_icecast(host, puerto, usuario, clave, mount, legacy, segundos,
                    codec, bitrate):
    destino = url_destino(host, puerto, mount, usuario, clave)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "info", "-re", "-f", "lavfi",
           "-i", "sine=frequency=440:sample_rate=44100:duration=%d" % segundos,
           "-ac", "2"]
    cmd += _salida_codec(codec, bitrate)
    cmd += ["-ice_name", "Prueba", "-ice_public", "0"]
    if legacy:
        cmd += ["-legacy_icecast", "1"]
    cmd += [destino]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=segundos + 25,
                           creationflags=procesos.SIN_VENTANA)
    except subprocess.TimeoutExpired:
        return False, "El servidor no respondio a tiempo"
    salida = (r.stderr or b"").decode("utf-8", "replace")
    if r.returncode == 0:
        return True, "Conectado y transmitiendo"
    ultimas = [l for l in salida.splitlines() if l.strip()][-4:]
    return False, "\n".join(ultimas) or "Fallo sin mensaje (codigo %d)" % r.returncode
