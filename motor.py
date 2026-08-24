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
import eq as mod_eq

CANALES = 2
BLOQUE = 1024


class CanalMicro:
    """
    Un microfono de la mesa: el suyo, el del invitado, etc.

    Cada uno lleva su propio aparato, su volumen y su ecualizador, porque una
    voz de invitado casi nunca necesita el mismo ajuste que la del locutor.
    """

    def __init__(self, indice, ajustes, muestreo, bloque):
        self.indice = indice
        self.nombre = ajustes.get("nombre") or ("Micro %d" % (indice + 1))
        self.micro = audio.Microfono(ajustes.get("dispositivo") or None,
                                     muestreo, bloque)
        self.volumen = float(ajustes.get("volumen", 0.9))
        self.eq = mod_eq.Ecualizador(muestreo,
                                     activo=bool(config.get("eq_activo", True)))
        self.eq.cargar(ajustes.get("eq") or {}, ajustes.get("eq_preset", "Plano"))
        self.comp = mod_eq.Compresor(
            muestreo,
            umbral_db=float(ajustes.get("comp_umbral", -26)),
            relacion=float(ajustes.get("comp_relacion", 4)),
            makeup_db=float(ajustes.get("comp_makeup", 8)),
            activo=bool(ajustes.get("comp", True)))
        self.abierto = False
        self.nivel = -60.0

    @property
    def dispositivo(self):
        return self.micro.dispositivo

    @property
    def listo(self):
        return self.micro.abierto

    @property
    def error(self):
        return self.micro.error

    def leer(self, cuadros):
        """El audio de este microfono, ya ecualizado y con su volumen."""
        if not (self.abierto and self.micro.abierto):
            self.nivel = -60.0
            return None
        bloque = self.micro.leer(cuadros)
        if not self.eq.plano:
            bloque = self.eq.procesar(bloque)
        # el compresor va ANTES del fader: su umbral es absoluto, asi que debe
        # ver el nivel que entra por el aparato, no el que uno haya puesto
        bloque = self.comp.procesar(bloque)
        bloque = bloque * self.volumen
        self.nivel = audio.nivel(bloque)
        return bloque


class Mezclador:

    def __init__(self, emisor=None, al_medir=None, grabador=None):
        self.emisor = emisor
        self.grabador = grabador
        self.al_medir = al_medir          # funcion(niveles) para los vumetros
        self.muestreo = int(config.get("muestreo", 48000))

        self.canales = [CanalMicro(i, aj, self.muestreo, BLOQUE)
                        for i, aj in enumerate(config.microfonos())]
        self.pista_a = audio.Pista(self.muestreo, BLOQUE)
        self.pista_b = audio.Pista(self.muestreo, BLOQUE)
        self.efectos = []                 # pistas de un solo uso (jingles)

        self.vol_micro = float(config.get("vol_micro", 0.9))
        self.vol_musica = float(config.get("vol_musica", 0.8))
        self.vol_efectos = float(config.get("vol_efectos", 0.85))
        self.vol_monitor = float(config.get("volumen_monitor", 0.8))
        self.monitor_activo = bool(config.get("monitor_activo", True))
        self.monitor_mudo_con_micro = bool(config.get("monitor_mudo_con_micro"))
        self.proteccion_acople = bool(config.get("proteccion_acople", True))
        self.acople = False               # se ha detectado realimentacion
        self.aviso_monitor = ""
        self._monitor_puesto = config.get("monitor") or ""
        self._apretado_desde = 0.0        # cuanto lleva el limitador sufriendo

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

    # --- atajos al primer microfono, que es el del locutor -----------------

    @property
    def micro(self):
        return self.canales[0].micro

    @micro.setter
    def micro(self, valor):
        self.canales[0].micro = valor

    @property
    def eq(self):
        return self.canales[0].eq

    @property
    def micro_abierto(self):
        """True si HAY ALGUN microfono abierto (el ducking mira esto)."""
        return any(c.abierto for c in self.canales)

    @micro_abierto.setter
    def micro_abierto(self, valor):
        self.canales[0].abierto = bool(valor)

    def alternar_micro(self, indice):
        """Abre o cierra un microfono. Devuelve como quedo."""
        if 0 <= indice < len(self.canales):
            c = self.canales[indice]
            c.abierto = not c.abierto
            return c.abierto
        return False

    # ------------------------------------------------------------ arranque

    def arrancar(self):
        if self.corriendo:
            return True
        self.error = ""
        fallos = []
        for c in self.canales:
            if not c.micro.abrir():
                fallos.append("%s: %s" % (c.nombre, c.micro.error))
        if fallos:
            # se sigue igual: se puede transmitir con los que si abrieron
            self.error = "  |  ".join(fallos)

        if self.monitor_activo and not self._abrir_monitor():
            self.monitor_activo = False   # sin monitor, pero al aire igual

        self._parar.clear()
        self.corriendo = True
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()
        return True

    def _abrir_monitor(self):
        """
        Abre los auriculares. Se intenta primero dejando que Windows convierta
        el muestreo: los auriculares Bluetooth suelen ir a 44100 y el mezclador
        a 48000, y sin eso la salida falla con "Invalid sample rate" y uno se
        queda sin monitor sin enterarse.
        """
        nombre = config.get("monitor") or ""
        idx = audio.buscar(nombre, entrada=False)
        self.aviso_monitor = ""
        if nombre and idx is None:
            # antes se caia sin avisar en el aparato por defecto del sistema,
            # que casi siempre no es el que uno habia elegido
            self.aviso_monitor = ("No se encontro '%s'. Sonara por la salida "
                                  "del sistema." % nombre)
        intentos = (
            ("con conversion de Windows", audio.ajustes_wasapi(idx)),
            ("directo", None),
        )
        ultimo = ""
        for _, extras in intentos:
            try:
                self._salida = sd.OutputStream(
                    samplerate=self.muestreo, blocksize=BLOQUE, device=idx,
                    channels=CANALES, dtype="float32", latency="low",
                    extra_settings=extras)
                self._salida.start()
                self.error = self.aviso_monitor
                return True
            except Exception as e:
                ultimo = str(e)
                self._salida = None
        self.error = ("No se pudo abrir el monitor (%s): %s"
                      % (config.get("monitor") or "el del sistema", ultimo))
        return False

    def cambiar_monitor(self):
        """
        Cierra la salida que este abierta y abre la que se acabe de elegir.

        Hace falta porque el monitor solo se abria al arrancar el mezclador:
        cambiar de auriculares en Configuracion no surtia ningun efecto y
        se seguia oyendo por el aparato de antes.
        """
        s, self._salida = self._salida, None
        if s:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._monitor_puesto = config.get("monitor") or ""
        self.monitor_activo = bool(config.get("monitor_activo", True))
        if not self.monitor_activo:
            self.error = ""
            return True, "Monitor apagado."
        if not self.corriendo:
            return True, "Se abrira al arrancar."
        if self._abrir_monitor():
            return True, "Ahora suena por: %s" % (self._monitor_puesto
                                                  or "la salida del sistema")
        return False, self.error

    def probar_monitor(self, segundos=1.0, hz=440.0):
        """
        Un pitido corto por los auriculares, para comprobarlos sin salir al
        aire. Devuelve (ok, explicacion).
        """
        idx = audio.buscar(config.get("monitor") or "", entrada=False)
        for extras in (audio.ajustes_wasapi(idx), None):
            try:
                s = sd.OutputStream(samplerate=self.muestreo, blocksize=BLOQUE,
                                    device=idx, channels=CANALES,
                                    dtype="float32", extra_settings=extras)
                s.start()
                n = int(self.muestreo * segundos)
                t = np.arange(n) / float(self.muestreo)
                tono = (0.25 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
                # entra y sale suave, que un pitido seco molesta
                rampa = int(self.muestreo * 0.02)
                tono[:rampa] *= np.linspace(0, 1, rampa)
                tono[-rampa:] *= np.linspace(1, 0, rampa)
                bloque = np.column_stack([tono, tono]) * self.vol_monitor
                s.write(bloque.astype(np.float32))
                s.stop()
                s.close()
                return True, "Sonando por: %s" % (config.get("monitor")
                                                  or "la salida del sistema")
            except Exception as e:
                ultimo = str(e)
        return False, "No se pudo usar esa salida: %s" % ultimo

    def detener(self):
        self._parar.set()
        self.corriendo = False
        if self._hilo:
            self._hilo.join(timeout=2)
        for c in self.canales:
            c.micro.cerrar()
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
            if self.grabador is not None:
                self.grabador.recibir(bloque)

            if self._salida is not None:
                try:
                    # esto bloquea el tiempo del bloque: es nuestro reloj
                    self._salida.write(bloque * self._ganancia_monitor())
                except Exception:
                    self._salida = None
            else:
                siguiente += periodo
                espera = siguiente - time.perf_counter()
                if espera > 0:
                    time.sleep(espera)
                else:
                    siguiente = time.perf_counter()   # ibamos tarde: al dia

            self._vigilar_acople()
            contador += 1
            if self.al_medir and contador % 3 == 0:   # ~14 avisos por segundo
                try:
                    self.al_medir(self.niveles)
                except Exception:
                    pass

    def _ganancia_monitor(self):
        """
        Cuanto sale por los auriculares. Cero cuando hay riesgo de acople.

        Si el monitor va a unos altavoces (o a un aparato Bluetooth que no son
        auriculares), abrir el microfono monta el pitido de siempre: el micro
        se oye a si mismo. Con `monitor_mudo_con_micro` se callan mientras haya
        un microfono abierto, que es lo que hacen las emisoras de verdad con
        los altavoces del estudio.
        """
        if self.acople:
            return 0.0
        if self.monitor_mudo_con_micro and self.micro_abierto:
            return 0.0
        return self.vol_monitor

    def _vigilar_acople(self):
        """
        Red de seguridad: si con el microfono abierto el limitador lleva un
        buen rato recortando a base de bien, casi seguro es realimentacion.
        Se callan los auriculares y se avisa, en vez de dejar el pitido al aire.
        """
        if not self.proteccion_acople:
            self.acople = False
            return
        apretando = (self.micro_abierto
                     and self.niveles.get("reduccion", 0.0) < -6.0)
        ahora = time.perf_counter()
        if apretando:
            if not self._apretado_desde:
                self._apretado_desde = ahora
            elif ahora - self._apretado_desde > 2.0:
                self.acople = True
        else:
            self._apretado_desde = 0.0
            if self.acople and not self.micro_abierto:
                self.acople = False        # al cerrar el micro, se rearma

    # ------------------------------------------------------------ la mezcla

    def _mezclar(self, cuadros):
        # --- microfonos (el del locutor y los de los invitados)
        mic = np.zeros((cuadros, CANALES), dtype=np.float32)
        hablando = False
        for c in self.canales:
            bloque_mic = c.leer(cuadros)
            if bloque_mic is not None:
                mic += bloque_mic
                if c.nivel > -42.0:
                    hablando = True
        mic *= self.vol_micro          # fader general de voces

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
        if self.ducking and hablando:
            objetivo = float(config.get("ducking_nivel", 0.25))
        self._duck = self._suavizar(self._duck, objetivo, cuadros)

        musica = musica * (self.vol_musica * self._duck)
        efectos = efectos * self.vol_efectos

        mezcla = mic + musica + efectos
        mezcla, reduccion = self._limitar(mezcla)

        self.niveles = {
            "micro": audio.nivel(mic),
            **{"micro%d" % c.indice: c.nivel for c in self.canales},
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
        self.monitor_mudo_con_micro = bool(config.get("monitor_mudo_con_micro"))
        self.proteccion_acople = bool(config.get("proteccion_acople", True))
        # si han cambiado los auriculares, se reabre la salida al momento
        if (config.get("monitor") or "") != self._monitor_puesto or                 bool(config.get("monitor_activo", True)) != self.monitor_activo:
            self.cambiar_monitor()
        activo = bool(config.get("eq_activo", True))
        for aj, c in zip(config.microfonos(), self.canales):
            c.nombre = aj.get("nombre") or c.nombre
            c.volumen = float(aj.get("volumen", c.volumen))
            c.comp.ajustar(umbral_db=aj.get("comp_umbral"),
                           relacion=aj.get("comp_relacion"),
                           makeup_db=aj.get("comp_makeup"),
                           activo=aj.get("comp"))
            c.eq.activo = activo
            c.eq.cargar(aj.get("eq") or {}, aj.get("eq_preset", "Plano"))
