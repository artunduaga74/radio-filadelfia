# -*- coding: utf-8 -*-
"""
Grabacion del programa a disco, con su propio boton.

Va SEPARADA de la emision a proposito. Antes la grabacion era una segunda
salida del ffmpeg que emitia, asi que empezaba y terminaba con la transmision;
eso obliga a grabar la musica de relleno de antes del programa. Ahora es un
proceso aparte que recibe la misma mezcla, y se enciende y se apaga cuando uno
quiera:

  - se puede estar al aire sin grabar (musica de fondo antes de empezar)
  - se puede grabar sin estar al aire (ensayar, o preparar un pregrabado)
  - se puede parar la grabacion y seguir al aire

Cada grabacion es un MP3 a 192 kbps en la carpeta `grabaciones`.
"""

import queue
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime

import numpy as np

import config
import procesos

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

PARADO = "parado"
GRABANDO = "grabando"
ERROR = "error"


def nombre_sugerido(titulo=""):
    """Nombre de archivo con la fecha y, si lo hay, el titulo del programa."""
    sello = datetime.now().strftime("%Y-%m-%d_%H-%M")
    limpio = re.sub(r"[^\w\s-]", "", (titulo or "")).strip()
    limpio = re.sub(r"\s+", "_", limpio)[:50]
    return ("%s_%s.mp3" % (sello, limpio)) if limpio else ("programa_%s.mp3" % sello)


class Grabador:
    """
    Uso:
        g = Grabador()
        g.iniciar("mi programa")
        g.recibir(bloque)      # el mezclador se lo manda siempre
        g.detener()
    """

    def __init__(self, al_cambiar=None, al_registrar=None):
        self.al_cambiar = al_cambiar
        self.al_registrar = al_registrar
        self.estado = PARADO
        self.detalle = ""
        self.archivo = None
        self.desde = 0.0
        self.bytes_escritos = 0

        self._proc = None
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
    def grabando(self):
        return self.estado == GRABANDO

    def duracion(self):
        return time.time() - self.desde if self.desde else 0.0

    # ------------------------------------------------------------ control

    def iniciar(self, titulo="", ruta=None):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return True
            config.asegurar_carpetas()
            destino = ruta or (config.CARPETA_GRABA / nombre_sugerido(titulo))
            aj = config.cargar()
            cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-y",
                   "-f", "f32le", "-ar", str(int(aj["muestreo"])),
                   "-ac", str(int(aj["canales"])),
                   "-thread_queue_size", "512", "-i", "pipe:0",
                   "-c:a", "libmp3lame",
                   "-b:a", "%dk" % int(aj.get("bitrate_grabacion", 192)),
                   "-ar", "44100", "-ac", "2", str(destino)]
            try:
                self._proc = procesos.lanzar(cmd, stdin=subprocess.PIPE,
                                             stdout=subprocess.DEVNULL,
                                             stderr=subprocess.PIPE)
            except Exception as e:
                self._poner(ERROR, "No se pudo iniciar la grabacion: %s" % e)
                return False

            self.archivo = destino
            self.desde = time.time()
            self.bytes_escritos = 0
            self._parar.clear()
            try:                                  # vaciar restos de antes
                while True:
                    self._cola.get_nowait()
            except queue.Empty:
                pass
            threading.Thread(target=self._escritor, daemon=True).start()
            threading.Thread(target=self._vigilar, daemon=True).start()
            self._poner(GRABANDO, str(destino))
            self._log("Grabando en %s" % destino)
            return True

    def detener(self):
        """Cierra el archivo y devuelve la ruta (o None si no se grababa)."""
        with self._lock:
            if not self._proc:
                return None
            self._parar.set()
            proc, self._proc = self._proc, None
        archivo = self.archivo
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=6)      # dejar que ffmpeg cierre bien el MP3
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        self.desde = 0.0
        self._poner(PARADO, str(archivo or ""))
        self._log("Grabacion guardada: %s" % archivo)
        return archivo

    def alternar(self, titulo=""):
        """Para el boton: si graba para, si no empieza. Devuelve si quedo grabando."""
        if self.grabando:
            self.detener()
            return False
        self.iniciar(titulo)
        return self.grabando

    # ------------------------------------------------------------ audio

    def recibir(self, bloque):
        """El mezclador manda SIEMPRE; si no se esta grabando, se tira."""
        if not self.grabando or self._parar.is_set():
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
        while not self._parar.is_set():
            proc = self._proc
            if not proc or proc.poll() is not None:
                break
            try:
                bloque = self._cola.get(timeout=0.5)
            except queue.Empty:
                continue          # grabando en silencio: no pasa nada
            try:
                datos = np.clip(bloque, -1.0, 1.0).astype(np.float32).tobytes()
                proc.stdin.write(datos)
                self.bytes_escritos += len(datos)
            except (BrokenPipeError, OSError, ValueError, AttributeError):
                break

    def _vigilar(self):
        """Drenar stderr o ffmpeg se bloquea cuando se llene la tuberia."""
        proc = self._proc
        if not proc or not proc.stderr:
            return
        for linea in iter(proc.stderr.readline, b""):
            txt = linea.decode("utf-8", "replace").strip()
            if txt:
                self._log("grabacion: " + txt)
