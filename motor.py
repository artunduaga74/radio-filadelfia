# -*- coding: utf-8 -*-
"""
El mezclador: junta microfono + musica + efectos y produce LA senal.

Corre en su propio hilo, a bloques de 1024 muestras (unos 21 ms a 48 kHz).
Cada vuelta hace siempre lo mismo:

    1. pide un bloque a cada fuente
    2. aplica volumen y "ducking" (bajar la musica cuando se habla)
    3. suma, limita para que nunca sature
    4. lo manda a los auriculares (monitor) y al emisor

El reloj lo marca la tarjeta de sonido cuando el monitor esta encendido
(escribir en la salida bloquea justo el tiempo que dura el bloque); si no hay
monitor, se marca por tiempo. En los dos casos el ritmo es constante, que es
lo que el servidor necesita para no cortarnos.
"""

import threading
import time

import numpy as np
import sounddevice as sd

import audio
import config

CANALES = 2
BLOQUE = 1024


class Mezclador:

    def __init__(self, emisor=None, al_medir=None):
        self.emisor = emisor
        self.al_medir = al_medir          # funcion(niveles) para los vumetros
        self.muestreo = int(config.get("muestreo", 48000))

        self.micro = audio.Microfono(config.get("microfono") or None,
                                     self.muestreo, BLOQUE)
        self.pista_a = audio.Pista(self.muestreo, BLOQUE)
        self.pista_b = audio.Pista(self.muestreo, BLOQUE)
        self.efectos = []                 # pistas de un solo uso (jingles)

        self.micro_abierto = False
        self.vol_micro = float(config.get("vol_micro", 0.9))
        self.vol_musica = float(config.get("vol_musica", 0.8))
        self.vol_efectos = float(config.get("vol_efectos", 0.85))
        self.vol_monitor = float(config.get("volumen_monitor", 0.8))
        self.monitor_activo = bool(config.get("monitor_activo", True))

        self.ducking = bool(config.get("ducking", True))
        self._duck = 1.0                  # factor actual (1 = sin bajar)

        self.niveles = {"micro": -60.0, "musica": -60.0, "efectos": -60.0,
                        "aire_i": -60.0, "aire_d": -60.0, "reduccion": 0.0}

        self.corriendo = False
        self.error = ""
        self._salida = None
        self._parar = threading.Event()
        self._hilo = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ arranque

    def arrancar(self):
        if self.corriendo:
            return True
        self.error = ""
        self.micro.dispositivo = config.get("microfono") or None
        if not self.micro.abrir():
            self.error = "Microfono: " + self.micro.error
            # seguimos igual: se puede transmitir solo musica

        if self.monitor_activo and not self._abrir_monitor():
            self.monitor_activo = False   # sin monitor, pero al aire igual

        self._parar.clear()
        self.corriendo = True
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()
        return True

    def _abrir_monitor(self):
        try:
            idx = audio.buscar(config.get("monitor") or "", entrada=False)
            self._salida = sd.OutputStream(
                samplerate=self.muestreo, blocksize=BLOQUE, device=idx,
                channels=CANALES, dtype="float32", latency="low")
            self._salida.start()
            return True
        except Exception as e:
            self.error = "Monitor: %s" % e
            self._salida = None
            return False

    def detener(self):
        self._parar.set()
        self.corriendo = False
        if self._hilo:
            self._hilo.join(timeout=2)
        self.micro.cerrar()
        s, self._salida = self._salida, None
        if s:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self.pista_a.detener()
        self.pista_b.detener()
        for e in list(self.efectos):
            e.detener()
        self.efectos.clear()

    # ------------------------------------------------------------ efectos

    def disparar_efecto(self, ruta, titulo=""):
        """Suelta un jingle encima de todo. Pueden sonar varios a la vez."""
        p = audio.Pista(self.muestreo, BLOQUE)
        if p.cargar(ruta, titulo):
            p.reproducir()
            with self._lock:
                self.efectos.append(p)
            return True
        return False

    def parar_efectos(self):
        with self._lock:
            pistas, self.efectos = list(self.efectos), []
        for p in pistas:
            p.detener()

    # ------------------------------------------------------------ el bucle

    def _bucle(self):
        periodo = BLOQUE / float(self.muestreo)
        siguiente = time.perf_counter()
        contador = 0
        while not self._parar.is_set():
            bloque = self._mezclar(BLOQUE)

            if self.emisor is not None:
                self.emisor.enviar(bloque)

            if self._salida is not None:
                try:
                    # esto bloquea el tiempo del bloque: es nuestro reloj
                    self._salida.write(bloque * self.vol_monitor)
                except Exception:
                    self._salida = None
            else:
                siguiente += periodo
                espera = siguiente - time.perf_counter()
                if espera > 0:
                    time.sleep(espera)
                else:
                    siguiente = time.perf_counter()   # ibamos tarde: al dia

            contador += 1
            if self.al_medir and contador % 3 == 0:   # ~14 avisos por segundo
                try:
                    self.al_medir(self.niveles)
                except Exception:
                    pass

    # ------------------------------------------------------------ la mezcla

    def _mezclar(self, cuadros):
        # --- microfono
        if self.micro_abierto and self.micro.abierto:
            mic = self.micro.leer(cuadros) * self.vol_micro
        else:
            mic = np.zeros((cuadros, CANALES), dtype=np.float32)

        # --- musica (las dos pistas suenan a la vez durante un cruce)
        musica = self.pista_a.leer(cuadros) + self.pista_b.leer(cuadros)

        # --- efectos
        efectos = np.zeros((cuadros, CANALES), dtype=np.float32)
        with self._lock:
            vivos = []
            for p in self.efectos:
                if p.sonando:
                    efectos += p.leer(cuadros)
                    vivos.append(p)
            self.efectos = vivos

        # --- ducking: la musica se aparta cuando se habla
        objetivo = 1.0
        if self.ducking and self.micro_abierto:
            if audio.nivel(mic) > -42.0:
                objetivo = float(config.get("ducking_nivel", 0.25))
        self._duck = self._suavizar(self._duck, objetivo, cuadros)

        musica = musica * (self.vol_musica * self._duck)
        efectos = efectos * self.vol_efectos

        mezcla = mic + musica + efectos
        mezcla, reduccion = self._limitar(mezcla)

        self.niveles = {
            "micro": audio.nivel(mic),
            "musica": audio.nivel(musica),
            "efectos": audio.nivel(efectos),
            "aire_i": audio.nivel(mezcla[:, 0]),
            "aire_d": audio.nivel(mezcla[:, 1]),
            "reduccion": reduccion,
        }
        return mezcla

    def _suavizar(self, actual, objetivo, cuadros):
        """Rampa del ducking: baja rapido, sube despacio (como en la radio)."""
        ms = (config.get("ducking_ataque_ms", 120) if objetivo < actual
              else config.get("ducking_salida_ms", 700))
        pasos = max(1.0, (float(ms) / 1000.0) * self.muestreo / cuadros)
        return actual + (objetivo - actual) / pasos

    def _limitar(self, bloque):
        """
        Techo de seguridad: si la suma se pasa de 1.0 se baja todo el bloque
        en proporcion. No es un compresor de radio, es un seguro contra la
        distorsion, que es lo unico imperdonable al aire.
        """
        pico = float(np.max(np.abs(bloque))) if len(bloque) else 0.0
        if pico <= 0.97:
            return bloque, 0.0
        factor = 0.97 / pico
        return bloque * factor, 20.0 * np.log10(factor)

    # ------------------------------------------------------------ ajustes en caliente

    def aplicar_ajustes(self):
        self.vol_micro = float(config.get("vol_micro", 0.9))
        self.vol_musica = float(config.get("vol_musica", 0.8))
        self.vol_efectos = float(config.get("vol_efectos", 0.85))
        self.vol_monitor = float(config.get("volumen_monitor", 0.8))
        self.ducking = bool(config.get("ducking", True))
