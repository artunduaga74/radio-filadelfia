# -*- coding: utf-8 -*-
"""
Vigilante de la emisora: escucha lo que se oye DE VERDAD.

Preguntarle al servidor si esta "en linea" no basta: la fuente puede seguir
conectada y estar mandando silencio, que es la peor averia de una radio porque
nadie se entera. Aqui se abre el mismo chorro que oyen los oyentes, se mide su
nivel y se cuenta cuanto lleva callado.

OJO: escuchar el stream **cuenta como un oyente** y gasta el ancho de banda de
un oyente (128 kbps). Por eso el vigilante solo corre cuando la ventana del
monitor esta abierta.
"""

import shutil
import subprocess
import threading
import time

import numpy as np

import config
import procesos

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

MUESTREO = 8000          # de sobra para medir nivel, y casi no gasta
BLOQUE = 800             # 100 ms
UMBRAL_SILENCIO = -48.0  # por debajo de esto lo damos por callado

APAGADO = "apagado"
CONECTANDO = "conectando"
SONANDO = "sonando"
CALLADO = "callado"
CAIDA = "caida"


def url_publica():
    host = (config.get("host") or "").strip()
    if not host:
        return ""
    host = host.replace("http://", "").replace("https://", "").split("/")[0]
    return "http://%s:%s/stream" % (host, config.get("puerto_publico", 8024))


class VigilanteAire:
    """
    Uso:
        v = VigilanteAire(al_cambiar=funcion)
        v.arrancar()
        ...
        v.detener()

    `al_cambiar(estado)` recibe un diccionario con lo que se sabe del aire.
    """

    def __init__(self, al_cambiar=None):
        self.al_cambiar = al_cambiar
        self.estado = APAGADO
        self.nivel = -60.0
        self.callado_desde = 0.0
        self.detalle = ""
        self.desde = 0.0
        self._proc = None
        self._parar = threading.Event()
        self._hilo = None

    # ------------------------------------------------------------ control

    def arrancar(self):
        if self._hilo and self._hilo.is_alive():
            return True
        if not url_publica():
            self._poner(CAIDA, "Falta configurar el servidor")
            return False
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()
        return True

    def detener(self):
        self._parar.set()
        p, self._proc = self._proc, None
        if p:
            try:
                p.terminate()
            except Exception:
                pass
        self.nivel = -60.0
        self._poner(APAGADO, "")

    @property
    def segundos_callado(self):
        if self.estado not in (CALLADO, SONANDO) or not self.callado_desde:
            return 0.0
        return time.time() - self.callado_desde

    # ------------------------------------------------------------ interno

    def _poner(self, estado, detalle=""):
        if estado != self.estado or detalle != self.detalle:
            self.estado = estado
            self.detalle = detalle
        if self.al_cambiar:
            try:
                self.al_cambiar(self)
            except Exception:
                pass

    def _abrir(self):
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
               "-reconnect", "1", "-reconnect_streamed", "1",
               "-reconnect_delay_max", "5",
               "-user_agent", "VozFiladelfia-Monitor",
               "-i", url_publica(),
               "-f", "f32le", "-ar", str(MUESTREO), "-ac", "1", "pipe:1"]
        return procesos.lanzar(cmd, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL,
                               bufsize=BLOQUE * 4 * 4)

    def _bucle(self):
        while not self._parar.is_set():
            self._poner(CONECTANDO, "")
            try:
                self._proc = self._abrir()
            except Exception as e:
                self._poner(CAIDA, str(e))
                self._parar.wait(5)
                continue

            self.desde = time.time()
            self.callado_desde = time.time()
            leidos = 0
            while not self._parar.is_set():
                try:
                    crudo = self._proc.stdout.read(BLOQUE * 4)
                except Exception:
                    crudo = b""
                if not crudo:
                    break
                leidos += len(crudo)
                muestras = np.frombuffer(crudo, dtype=np.float32)
                if not len(muestras):
                    continue
                pico = float(np.max(np.abs(muestras)))
                self.nivel = (-60.0 if pico <= 1e-6
                              else max(-60.0, 20.0 * np.log10(pico)))
                if self.nivel > UMBRAL_SILENCIO:
                    self.callado_desde = time.time()
                    self._poner(SONANDO, "")
                else:
                    self._poner(CALLADO, "")

            if self._parar.is_set():
                break
            self.nivel = -60.0
            self._poner(CAIDA, "La emisora no responde"
                        if leidos == 0 else "Se corto la senal")
            self._parar.wait(5)      # y se vuelve a intentar

        self.nivel = -60.0
