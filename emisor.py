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
"""

import queue
import shutil
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime

import numpy as np

import config
import procesos

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

PARADO = "parado"
CONECTANDO = "conectando"
AL_AIRE = "al_aire"
ERROR = "error"


def url_destino(host=None, puerto=None, mount=None, usuario=None, clave=None):
    """Arma la URL de la fuente. Icecast es lo que entiende el harbor del autoDJ."""
    host = host or config.get("host", "")
    host = host.replace("http://", "").replace("https://", "").strip("/")
    puerto = puerto or config.get("puerto", 8026)
    mount = mount if mount is not None else config.get("mount", "/")
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
            "-content_type", "audio/mpeg", "-f", "mp3"]


def construir_comando(destino=None, grabar=None, legacy=False):
    """El comando de ffmpeg: PCM crudo por la entrada, servidor por la salida."""
    aj = config.cargar()
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning",
           "-f", "f32le", "-ar", str(int(aj["muestreo"])),
           "-ac", str(int(aj["canales"])),
           "-thread_queue_size", "512", "-i", "pipe:0"]

    cmd += _salida_codec(aj.get("codec", "mp3"), int(aj["bitrate"]))
    # ffmpeg convierte 48k (mezclador) -> 44.1k (servidor) con soxr, gratis
    cmd += ["-ar", str(int(aj.get("muestreo_salida", 44100))), "-ac", "2"]
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
        self._cola = queue.Queue(maxsize=64)
        self._parar = threading.Event()
        self._lock = threading.Lock()

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

    def arrancar(self, legacy=False):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return True
            if not config.get("host"):
                self._poner(ERROR, "Falta configurar el servidor")
                return False

            config.asegurar_carpetas()
            self.grabacion = None
            if config.get("grabar_al_aire", True):
                nombre = datetime.now().strftime("programa_%Y-%m-%d_%H-%M.mp3")
                self.grabacion = config.CARPETA_GRABA / nombre

            cmd = construir_comando(grabar=self.grabacion, legacy=legacy)
            self._log("Conectando a %s:%s%s" % (config.get("host"),
                                                config.get("puerto"),
                                                config.get("mount")))
            self._poner(CONECTANDO, "")
            try:
                self._proc = procesos.lanzar(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE)
            except Exception as e:
                self._poner(ERROR, "No se pudo iniciar ffmpeg: %s" % e)
                return False

            self._parar.clear()
            self.bytes_enviados = 0
            threading.Thread(target=self._escritor, daemon=True).start()
            threading.Thread(target=self._vigilar_errores, daemon=True).start()
            return True

    def detener(self):
        with self._lock:
            self._parar.set()
            proc = self._proc
            self._proc = None
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
        self.desde = 0.0
        self._poner(PARADO, "")

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
        primero = True
        while not self._parar.is_set():
            proc = self._proc
            if not proc or proc.poll() is not None:
                break
            try:
                bloque = self._cola.get(timeout=0.5)
            except queue.Empty:
                n = int(config.get("muestreo", 44100) * 0.5)
                bloque = np.zeros((n, int(config.get("canales", 2))),
                                  dtype=np.float32)
            try:
                datos = np.clip(bloque, -1.0, 1.0).astype(np.float32).tobytes()
                proc.stdin.write(datos)
                self.bytes_enviados += len(datos)
                if primero:
                    primero = False
                    self.desde = time.time()
                    self._poner(AL_AIRE, "")
            except (BrokenPipeError, OSError, ValueError, AttributeError):
                break
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
                                         "failed to resolve", "timed out")):
                self._poner(ERROR, "No se pudo conectar: " + txt)

    def _caida(self):
        detalle = self.detalle if self.estado == ERROR else "Se perdio la conexion"
        self.desde = 0.0
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


def probar_conexion(host, puerto, usuario, clave, mount, legacy=False,
                    segundos=6, codec="mp3", bitrate=128):
    """
    Manda un tono de prueba al servidor durante unos segundos.
    Devuelve (ok, mensaje). No usa el mezclador: es una prueba aislada.
    """
    destino = url_destino(host, puerto, mount, usuario, clave)
    if clave:
        tapado = destino.replace(urllib.parse.quote(clave, safe=""), "***")
    else:
        tapado = destino
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
        return True, "Conectado y transmitiendo (%s)" % tapado
    ultimas = [l for l in salida.splitlines() if l.strip()][-4:]
    return False, "\n".join(ultimas) or "Fallo sin mensaje (codigo %d)" % r.returncode
