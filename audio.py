# -*- coding: utf-8 -*-
"""
Audio local: dispositivos, microfono y reproductores de pista.

Todo trabaja en el mismo formato interno, para que el mezclador solo tenga que
sumar: float32, dos canales, al muestreo del motor (48000 por defecto, que es
lo que usa WASAPI en Windows).

Los archivos se decodifican con ffmpeg, no con una libreria de Python: asi
suena cualquier cosa (mp3, wav, flac, m4a, ogg, opus...) sin instalar nada mas.
"""

import queue
import shutil
import subprocess
import threading

import numpy as np
import sounddevice as sd

import config
import procesos

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
CANALES = 2


# ------------------------------------------------------------------ dispositivos

def _apis():
    return sd.query_hostapis()


def listar(entrada=True, api=None):
    """
    Dispositivos disponibles. Devuelve [(indice, nombre, api, canales)].
    Por defecto solo los de la API preferida (WASAPI): la lista completa de
    Windows repite el mismo aparato cuatro veces y confunde.
    """
    api = api or config.get("api_audio", "Windows WASAPI")
    apis = _apis()
    fuera = []
    for i, d in enumerate(sd.query_devices()):
        canales = d["max_input_channels"] if entrada else d["max_output_channels"]
        if canales <= 0:
            continue
        nombre_api = apis[d["hostapi"]]["name"]
        if api and nombre_api != api:
            continue
        fuera.append((i, d["name"], nombre_api, canales))
    if not fuera and api:                 # esa API no tiene nada: mostrar todo
        return listar(entrada, api="")
    return fuera


def buscar(nombre, entrada=True):
    """Del nombre guardado en los ajustes al indice real. None = el del sistema."""
    if not nombre:
        return None
    opciones = listar(entrada)
    for i, n, _, _ in opciones:
        if n == nombre:
            return i
    for i, n, _, _ in opciones:           # el nombre puede venir recortado
        if nombre.lower() in n.lower() or n.lower() in nombre.lower():
            return i
    return None


def nivel(bloque):
    """Nivel de un bloque en dBFS (-60 = silencio, 0 = tope). Para los vumetros."""
    if bloque is None or len(bloque) == 0:
        return -60.0
    pico = float(np.max(np.abs(bloque)))
    if pico <= 1e-6:
        return -60.0
    return max(-60.0, 20.0 * np.log10(pico))


# ------------------------------------------------------------------ microfono

class Microfono:
    """
    Captura del microfono. Deja los bloques en una cola pequena que el
    mezclador vacia. Si el mezclador no llega a tiempo se tiran los bloques
    viejos: mas vale perder audio que acumular retraso.
    """

    def __init__(self, dispositivo=None, muestreo=None, bloque=1024):
        self.muestreo = muestreo or int(config.get("muestreo", 48000))
        self.bloque = bloque
        self.dispositivo = dispositivo
        self.stream = None
        self.error = ""
        self.abierto = False
        self._cola = queue.Queue(maxsize=8)
        self.ultimo_nivel = -60.0

    def abrir(self):
        self.cerrar()
        idx = buscar(self.dispositivo, entrada=True) if isinstance(
            self.dispositivo, str) else self.dispositivo
        try:
            canales_disp = CANALES
            if idx is not None:
                info = sd.query_devices(idx)
                canales_disp = min(CANALES, max(1, info["max_input_channels"]))
            self._canales = canales_disp
            self.stream = sd.InputStream(
                samplerate=self.muestreo, blocksize=self.bloque,
                device=idx, channels=canales_disp, dtype="float32",
                callback=self._llegada, latency="low")
            self.stream.start()
            self.abierto = True
            self.error = ""
        except Exception as e:
            self.stream = None
            self.abierto = False
            self.error = "%s: %s" % (type(e).__name__, e)
        return self.abierto

    def cerrar(self):
        self.abierto = False
        s, self.stream = self.stream, None
        if s:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        try:
            while True:
                self._cola.get_nowait()
        except queue.Empty:
            pass

    def _llegada(self, datos, cuadros, tiempo, estado):   # hilo de PortAudio
        bloque = np.array(datos, dtype=np.float32, copy=True)
        if bloque.shape[1] == 1:                # microfono mono -> a los dos lados
            bloque = np.repeat(bloque, 2, axis=1)
        self.ultimo_nivel = nivel(bloque)
        try:
            self._cola.put_nowait(bloque)
        except queue.Full:
            try:
                self._cola.get_nowait()
                self._cola.put_nowait(bloque)
            except Exception:
                pass

    def leer(self, cuadros):
        """Devuelve un bloque del tamano pedido; silencio si aun no hay nada."""
        try:
            b = self._cola.get_nowait()
        except queue.Empty:
            return np.zeros((cuadros, CANALES), dtype=np.float32)
        if len(b) == cuadros:
            return b
        if len(b) > cuadros:
            return b[:cuadros]
        relleno = np.zeros((cuadros, CANALES), dtype=np.float32)
        relleno[:len(b)] = b
        return relleno


# ------------------------------------------------------------------ pista

class Pista:
    """
    Un reproductor de archivo. ffmpeg lo decodifica y nosotros vamos leyendo
    bloques. Soporta pausa, salto y desvanecidos de entrada y salida.
    """

    def __init__(self, muestreo=None, bloque=1024):
        self.muestreo = muestreo or int(config.get("muestreo", 48000))
        self.bloque = bloque
        self.ruta = ""
        self.titulo = ""
        self.duracion = 0.0
        self.posicion = 0.0
        self.sonando = False
        self.termino = False
        self.ultimo_nivel = -60.0
        self._proc = None
        self._lock = threading.Lock()
        self._resto = np.zeros((0, CANALES), dtype=np.float32)
        self._fundido = None        # (muestras_hechas, muestras_totales, sube)

    # -------------------------------------------------- control

    def cargar(self, ruta, titulo="", duracion=0.0, desde=0.0):
        self.detener()
        with self._lock:
            self.ruta = str(ruta)
            self.titulo = titulo or self.ruta
            self.duracion = float(duracion or 0.0)
            self.posicion = float(desde)
            self.termino = False
            self._resto = np.zeros((0, CANALES), dtype=np.float32)
            self._abrir(desde)
        return bool(self._proc)

    def _abrir(self, desde=0.0):
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin"]
        if desde > 0.05:
            cmd += ["-ss", "%.3f" % desde]
        cmd += ["-i", self.ruta,
                "-f", "f32le", "-ar", str(self.muestreo), "-ac", str(CANALES),
                "pipe:1"]
        try:
            self._proc = procesos.lanzar(cmd, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL,
                                         bufsize=self.bloque * CANALES * 8)
        except Exception:
            self._proc = None

    def reproducir(self, fundido_ms=0):
        if not self._proc:
            return False
        self.sonando = True
        if fundido_ms:
            n = int(self.muestreo * fundido_ms / 1000.0)
            self._fundido = [0, max(1, n), True]
        return True

    def pausar(self):
        self.sonando = False

    def detener(self, fundido_ms=0):
        if fundido_ms and self.sonando:
            n = int(self.muestreo * fundido_ms / 1000.0)
            self._fundido = [0, max(1, n), False]
            return
        self.sonando = False
        with self._lock:
            p, self._proc = self._proc, None
        if p:
            try:
                p.terminate()
            except Exception:
                pass
        self._resto = np.zeros((0, CANALES), dtype=np.float32)

    def saltar_a(self, segundos):
        if not self.ruta:
            return
        sonaba = self.sonando
        self.detener()
        self.cargar(self.ruta, self.titulo, self.duracion, desde=segundos)
        if sonaba:
            self.reproducir()

    @property
    def restante(self):
        return max(0.0, self.duracion - self.posicion) if self.duracion else 0.0

    # -------------------------------------------------- lectura

    def leer(self, cuadros):
        """Bloque de audio de esta pista (silencio si no esta sonando)."""
        silencio = np.zeros((cuadros, CANALES), dtype=np.float32)
        if not self.sonando or not self._proc:
            self.ultimo_nivel = -60.0
            return silencio

        faltan = cuadros * CANALES * 4
        try:
            crudo = self._proc.stdout.read(faltan)
        except Exception:
            crudo = b""

        if not crudo:
            self.termino = True
            self.sonando = False
            self.ultimo_nivel = -60.0
            return silencio

        bloque = np.frombuffer(crudo, dtype=np.float32)
        if len(bloque) % CANALES:
            bloque = bloque[:len(bloque) - (len(bloque) % CANALES)]
        bloque = bloque.reshape(-1, CANALES).copy()

        if len(bloque) < cuadros:                 # ultimo trozo del archivo
            relleno = np.zeros((cuadros, CANALES), dtype=np.float32)
            relleno[:len(bloque)] = bloque
            bloque = relleno
            self.termino = True
            self.sonando = False

        bloque = self._aplicar_fundido(bloque)
        self.posicion += cuadros / float(self.muestreo)
        self.ultimo_nivel = nivel(bloque)
        return bloque

    def _aplicar_fundido(self, bloque):
        if not self._fundido:
            return bloque
        hechas, total, sube = self._fundido
        n = len(bloque)
        ini = hechas / float(total)
        fin = min(1.0, (hechas + n) / float(total))
        rampa = np.linspace(ini, fin, n, dtype=np.float32)
        if not sube:
            rampa = 1.0 - rampa
        bloque = bloque * rampa[:, None]
        self._fundido[0] += n
        if self._fundido[0] >= total:
            termino_bajando = not sube
            self._fundido = None
            if termino_bajando:
                self.detener()
        return bloque
