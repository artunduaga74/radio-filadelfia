# -*- coding: utf-8 -*-
"""
Ecualizador de voz para el microfono.

Cuatro bandas, las mismas que usan las mesas de radio pequenas:

    GRAVES     100 Hz   cuerpo de la voz. Subir = mas pecho, bajar = menos retumbe
    MEDIOS     400 Hz   el "carton". Bajarlo suele limpiar mucho una voz
    PRESENCIA  3 kHz    claridad, que se entiendan las consonantes
    AIRE       9 kHz    brillo. Poco y con cuidado, o suenan las eses

Ademas un filtro de corte grave (80 Hz) que quita el retumbe del escritorio,
los golpes de mesa y el aire acondicionado. Casi siempre conviene dejarlo.

Los filtros son biquads del recetario de Robert Bristow-Johnson, el estandar
de toda la vida. El filtrado lo hace scipy en C (`sosfilt`), guardando el
estado entre bloques para que no haya chasquidos en las costuras.
"""

import numpy as np
from scipy import signal

CANALES = 2

# Las bandas: (clave, etiqueta, frecuencia, tipo, Q)
BANDAS = (
    ("graves",    "Graves",    100.0, "lowshelf",  0.7),
    ("medios",    "Medios",    400.0, "peaking",   1.0),
    ("presencia", "Presencia", 3000.0, "peaking",  1.2),
    ("aire",      "Aire",      9000.0, "highshelf", 0.7),
)

LIMITE_DB = 12.0        # tope por banda, arriba y abajo

# Ajustes de fabrica. "A mi gusto" es el hueco del usuario.
PRESETS = {
    "Plano": {
        "graves": 0, "medios": 0, "presencia": 0, "aire": 0, "corte_grave": True},
    "Voz clara": {
        "graves": -1, "medios": -3, "presencia": 4, "aire": 2, "corte_grave": True},
    "Voz calida": {
        "graves": 3, "medios": -1, "presencia": 1, "aire": -1, "corte_grave": True},
    "Radio (con cuerpo)": {
        "graves": 4, "medios": -3, "presencia": 3, "aire": 2, "corte_grave": True},
    "Menos ruido": {
        "graves": -4, "medios": -2, "presencia": 2, "aire": -3, "corte_grave": True},
    "A mi gusto": {
        "graves": 0, "medios": 0, "presencia": 0, "aire": 0, "corte_grave": True},
}

ORDEN_PRESETS = ("Plano", "Voz clara", "Voz calida", "Radio (con cuerpo)",
                 "Menos ruido", "A mi gusto")


def _biquad(tipo, f0, ganancia_db, Q, fs):
    """Coeficientes de un biquad, en formato de seccion de segundo orden."""
    A = 10.0 ** (ganancia_db / 40.0)
    w0 = 2.0 * np.pi * f0 / fs
    cos_w0 = np.cos(w0)
    alfa = np.sin(w0) / (2.0 * Q)

    if tipo == "peaking":
        b = [1 + alfa * A, -2 * cos_w0, 1 - alfa * A]
        a = [1 + alfa / A, -2 * cos_w0, 1 - alfa / A]
    elif tipo == "lowshelf":
        raiz = 2.0 * np.sqrt(A) * alfa
        b = [A * ((A + 1) - (A - 1) * cos_w0 + raiz),
             2 * A * ((A - 1) - (A + 1) * cos_w0),
             A * ((A + 1) - (A - 1) * cos_w0 - raiz)]
        a = [(A + 1) + (A - 1) * cos_w0 + raiz,
             -2 * ((A - 1) + (A + 1) * cos_w0),
             (A + 1) + (A - 1) * cos_w0 - raiz]
    elif tipo == "highshelf":
        raiz = 2.0 * np.sqrt(A) * alfa
        b = [A * ((A + 1) + (A - 1) * cos_w0 + raiz),
             -2 * A * ((A - 1) + (A + 1) * cos_w0),
             A * ((A + 1) + (A - 1) * cos_w0 - raiz)]
        a = [(A + 1) - (A - 1) * cos_w0 + raiz,
             2 * ((A - 1) - (A + 1) * cos_w0),
             (A + 1) - (A - 1) * cos_w0 - raiz]
    elif tipo == "highpass":
        b = [(1 + cos_w0) / 2, -(1 + cos_w0), (1 + cos_w0) / 2]
        a = [1 + alfa, -2 * cos_w0, 1 - alfa]
    else:
        raise ValueError("tipo de filtro desconocido: %s" % tipo)

    a0 = a[0]
    return [b[0] / a0, b[1] / a0, b[2] / a0, 1.0, a[1] / a0, a[2] / a0]


class Ecualizador:
    """
    Uso:
        eq = Ecualizador(48000)
        eq.aplicar_preset("Voz clara")
        bloque = eq.procesar(bloque)      # (muestras x 2) float32
    """

    def __init__(self, muestreo=48000, activo=True):
        self.muestreo = int(muestreo)
        self.activo = bool(activo)
        self.valores = dict(PRESETS["Plano"])
        self.preset = "Plano"
        self._sos = None
        self._estado = None
        self._recalcular()

    # ------------------------------------------------------------ ajustes

    def aplicar_preset(self, nombre):
        if nombre not in PRESETS:
            return False
        self.preset = nombre
        self.valores = dict(PRESETS[nombre])
        self._recalcular()
        return True

    def poner(self, clave, valor):
        """Cambia una banda (dB) o el corte grave (True/False)."""
        if clave == "corte_grave":
            self.valores["corte_grave"] = bool(valor)
        elif clave in self.valores:
            self.valores[clave] = max(-LIMITE_DB, min(LIMITE_DB, float(valor)))
        else:
            return False
        self._recalcular()
        return True

    def cargar(self, valores, preset=""):
        for k, v in (valores or {}).items():
            if k == "corte_grave":
                self.valores["corte_grave"] = bool(v)
            elif k in self.valores:
                self.valores[k] = max(-LIMITE_DB, min(LIMITE_DB, float(v)))
        self.preset = preset or self.preset
        self._recalcular()

    def como_diccionario(self):
        return dict(self.valores)

    @property
    def plano(self):
        """True si no esta tocando nada (asi nos ahorramos el filtrado)."""
        if self.valores.get("corte_grave"):
            return False
        return all(abs(float(self.valores.get(c, 0))) < 0.05
                   for c, _, _, _, _ in BANDAS)

    # ------------------------------------------------------------ motor

    def _recalcular(self):
        secciones = []
        if self.valores.get("corte_grave"):
            secciones.append(_biquad("highpass", 80.0, 0.0, 0.707, self.muestreo))
        for clave, _, frec, tipo, Q in BANDAS:
            g = float(self.valores.get(clave, 0.0))
            if abs(g) < 0.05:
                continue                      # banda a cero: no gasta nada
            secciones.append(_biquad(tipo, frec, g, Q, self.muestreo))
        if not secciones:
            self._sos = None
            self._estado = None
            return
        self._sos = np.array(secciones, dtype=np.float64)
        # el estado se conserva entre bloques; al cambiar el filtro se reinicia
        self._estado = np.zeros((self._sos.shape[0], 2, CANALES))

    def reiniciar(self):
        if self._sos is not None:
            self._estado = np.zeros((self._sos.shape[0], 2, CANALES))

    def procesar(self, bloque):
        """Devuelve el bloque ecualizado. Si no hay nada que hacer, el mismo."""
        if not self.activo or self._sos is None or bloque is None or not len(bloque):
            return bloque
        try:
            salida, self._estado = signal.sosfilt(
                self._sos, bloque.astype(np.float64), axis=0, zi=self._estado)
            return salida.astype(np.float32)
        except Exception:
            # ante cualquier problema, mejor la voz sin ecualizar que sin voz
            return bloque


def respuesta(valores, muestreo=48000, puntos=64):
    """
    La curva del ecualizador, para dibujarla: devuelve [(hz, dB)].
    Sirve para que se vea lo que se esta tocando.
    """
    eq = Ecualizador(muestreo)
    eq.cargar(valores or {})
    frecuencias = np.logspace(np.log10(40), np.log10(min(16000, muestreo / 2.2)),
                              puntos)
    if eq._sos is None:
        return [(float(f), 0.0) for f in frecuencias]
    w, h = signal.sosfreqz(eq._sos, worN=frecuencias, fs=muestreo)
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(np.abs(h), 1e-6))
    return list(zip([float(x) for x in w], [float(x) for x in db]))


# ------------------------------------------------------------------ compresor

class Compresor:
    """
    Nivelador de voz: sube lo flojo y frena lo fuerte.

    Es lo que de verdad arregla un microfono que no se puede tener pegado a la
    boca. Subir el volumen a secas amplifica igual la voz que el ruido de la
    sala y ademas deja los picos disparados; el compresor aprieta solo cuando
    hace falta y luego levanta todo por parejo (`makeup`), asi que la voz sale
    pareja aunque uno se mueva o hable mas bajo.

    La envolvente se calcula con un filtro de un polo en C (`lfilter`), no con
    un bucle de Python: hay que hacerlo 48000 veces por segundo.
    """

    def __init__(self, muestreo=48000, umbral_db=-26.0, relacion=4.0,
                 makeup_db=8.0, activo=False, tiempo_ms=25.0):
        self.muestreo = int(muestreo)
        self.umbral_db = float(umbral_db)
        self.relacion = max(1.0, float(relacion))
        self.makeup_db = float(makeup_db)
        self.activo = bool(activo)
        self.tiempo_ms = float(tiempo_ms)
        self.reduccion = 0.0          # cuanto esta apretando ahora, en dB
        self._zi = None
        self._coef()

    def _coef(self):
        tau = max(0.001, self.tiempo_ms / 1000.0)
        self._a = float(np.exp(-1.0 / (tau * self.muestreo)))
        self._zi = None

    def ajustar(self, umbral_db=None, relacion=None, makeup_db=None,
                activo=None):
        if umbral_db is not None:
            self.umbral_db = float(umbral_db)
        if relacion is not None:
            self.relacion = max(1.0, float(relacion))
        if makeup_db is not None:
            self.makeup_db = float(makeup_db)
        if activo is not None:
            self.activo = bool(activo)

    def procesar(self, bloque):
        if not self.activo or bloque is None or not len(bloque):
            self.reduccion = 0.0
            return bloque
        try:
            mono = np.max(np.abs(bloque), axis=1).astype(np.float64)
            # envolvente: filtro de un polo, con estado entre bloques
            if self._zi is None:
                self._zi = np.array([mono[0] * (1.0 - self._a)])
            env, self._zi = signal.lfilter([1.0 - self._a], [1.0, -self._a],
                                           mono, zi=self._zi)
            env_db = 20.0 * np.log10(np.maximum(env, 1e-7))
            exceso = np.maximum(0.0, env_db - self.umbral_db)
            recorte = exceso * (1.0 - 1.0 / self.relacion)      # dB a bajar
            ganancia_db = self.makeup_db - recorte
            self.reduccion = float(-np.max(recorte)) if len(recorte) else 0.0
            ganancia = np.power(10.0, ganancia_db / 20.0)
            return (bloque * ganancia[:, None]).astype(np.float32)
        except Exception:
            return bloque      # ante la duda, la voz sin comprimir


def ganancia_a_db(ganancia):
    """De factor lineal a dB (0 -> -inf, se corta en -40)."""
    g = float(ganancia)
    if g <= 0.0001:
        return -40.0
    return max(-40.0, min(24.0, 20.0 * np.log10(g)))


def db_a_ganancia(db):
    """De dB a factor lineal. -40 dB o menos se toma como silencio."""
    d = float(db)
    if d <= -40.0:
        return 0.0
    return float(np.power(10.0, d / 20.0))
