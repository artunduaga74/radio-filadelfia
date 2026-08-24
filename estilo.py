# -*- coding: utf-8 -*-
"""
Aspecto de la aplicacion: estudio de radio de noche.

Grafito azulado de fondo, paneles un punto mas claros, ambar para lo que se
puede tocar y ROJO solo para una cosa: estar al aire. Ese rojo no se usa en
ningun otro sitio, para que de un vistazo, desde lejos, se sepa si la senal
esta saliendo.
"""

import ctypes
import tkinter as tk
from tkinter import ttk

# Windows puede tener la pantalla al 125/150/200 %. Declararse "consciente"
# evita que la ventana salga borrosa o descuadrada.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def factor():
    try:
        dc = ctypes.windll.user32.GetDC(0)
        ppp = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)   # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, dc)
        return max(1.0, ppp / 96.0)
    except Exception:
        return 1.0


ESCALA = factor()


def px(n):
    """Convierte una medida pensada al 100 % en pixeles reales."""
    return int(round(n * ESCALA))


# --- paleta
FONDO       = "#12161c"   # grafito azulado, casi negro
PANEL       = "#1b212a"   # cajas
PANEL_ALTO  = "#252d38"   # relieve / raton encima
PANEL_HUND  = "#0d1116"   # huecos (vumetros, listas)
BORDE       = "#333d4b"
TEXTO       = "#e6ebf2"
TEXTO_SUAVE = "#8a95a5"
ACENTO      = "#e0a458"   # ambar: lo que se toca
ACENTO_OSC  = "#b8823d"
AZUL        = "#2e9fc4"   # acciones secundarias
AZUL_OSC    = "#1f7b9b"
VERDE       = "#4caf7d"   # todo bien / conectado
ROJO        = "#e0453a"   # AL AIRE. solo para eso
ROJO_OSC    = "#b3352c"
AMARILLO    = "#e5c454"

# --- vumetros
VU_VERDE    = "#3fbf6f"
VU_AMBAR    = "#e5c454"
VU_ROJO     = "#e0453a"
VU_APAGADO  = "#1f2731"

FUENTE      = ("Segoe UI", 9)
FUENTE_TIT  = ("Segoe UI Semibold", 10)
FUENTE_GDE  = ("Segoe UI Semibold", 14)
FUENTE_RELOJ = ("Consolas", 20, "bold")
FUENTE_MONO = ("Consolas", 9)


def aplicar(root):
    """Aplica el tema a toda la ventana."""
    root.configure(bg=FONDO)
    try:
        root.tk.call("tk", "scaling", 1.3333 * ESCALA)
    except Exception:
        pass
    st = ttk.Style(root)
    try:
        st.theme_use("clam")          # el unico tema de ttk que deja pintar todo
    except tk.TclError:
        return st

    st.configure(".", background=FONDO, foreground=TEXTO, fieldbackground=PANEL,
                 bordercolor=BORDE, lightcolor=PANEL, darkcolor=PANEL, font=FUENTE)
    st.configure("TFrame", background=FONDO)
    st.configure("TLabel", background=FONDO, foreground=TEXTO)
    st.configure("Suave.TLabel", background=FONDO, foreground=TEXTO_SUAVE)
    st.configure("Titulo.TLabel", background=FONDO, foreground=ACENTO,
                 font=("Segoe UI Semibold", 12))
    st.configure("Grande.TLabel", background=FONDO, foreground=TEXTO, font=FUENTE_GDE)
    st.configure("Reloj.TLabel", background=FONDO, foreground=TEXTO, font=FUENTE_RELOJ)
    st.configure("Mono.TLabel", background=FONDO, foreground=TEXTO_SUAVE, font=FUENTE_MONO)

    # --- paneles (cajas con titulo)
    st.configure("TLabelframe", background=FONDO, bordercolor=BORDE)
    st.configure("TLabelframe.Label", background=FONDO, foreground=ACENTO,
                 font=FUENTE_TIT)
    st.configure("Caja.TLabelframe", background=PANEL, bordercolor=BORDE,
                 relief="solid", padding=(px(8), px(6)))
    st.configure("Caja.TLabelframe.Label", background=PANEL, foreground=ACENTO,
                 font=("Segoe UI Semibold", 9))
    st.configure("Caja.TFrame", background=PANEL)
    st.configure("Caja.TLabel", background=PANEL, foreground=TEXTO)
    st.configure("CajaSuave.TLabel", background=PANEL, foreground=TEXTO_SUAVE)
    st.configure("CajaMono.TLabel", background=PANEL, foreground=TEXTO_SUAVE,
                 font=FUENTE_MONO)
    st.configure("TSeparator", background=BORDE)

    # --- botones
    st.configure("TButton", background=PANEL, foreground=TEXTO, bordercolor=BORDE,
                 focuscolor=ACENTO, padding=(px(9), px(4)), relief="flat")
    st.map("TButton",
           background=[("disabled", PANEL), ("pressed", ACENTO_OSC),
                       ("active", PANEL_ALTO)],
           foreground=[("disabled", "#4d5867"), ("pressed", "#12161c")])

    st.configure("Caja.TButton", background=PANEL_ALTO, foreground=TEXTO,
                 bordercolor=BORDE, padding=(px(7), px(3)), relief="flat")
    st.map("Caja.TButton", background=[("active", "#2f3946"), ("pressed", ACENTO_OSC)])

    # AL AIRE: el boton rojo, el mas grande de la ventana
    st.configure("AlAire.TButton", background=ROJO, foreground="#fff4f3",
                 font=("Segoe UI Semibold", 12), padding=(px(16), px(9)),
                 relief="flat")
    st.map("AlAire.TButton",
           background=[("disabled", PANEL), ("pressed", ROJO_OSC),
                       ("active", "#f05548")],
           foreground=[("disabled", "#4d5867")])

    st.configure("Salir.TButton", background=PANEL_ALTO, foreground=TEXTO,
                 font=("Segoe UI Semibold", 12), padding=(px(16), px(9)),
                 relief="flat")
    st.map("Salir.TButton", background=[("active", "#2f3946")])

    # microfono abierto/cerrado
    st.configure("MicOn.TButton", background=ROJO, foreground="#fff4f3",
                 font=FUENTE_TIT, padding=(px(12), px(7)), relief="flat")
    st.map("MicOn.TButton", background=[("active", "#f05548")])
    st.configure("MicOff.TButton", background=PANEL_ALTO, foreground=TEXTO_SUAVE,
                 font=FUENTE_TIT, padding=(px(12), px(7)), relief="flat")
    st.map("MicOff.TButton", background=[("active", "#2f3946")])

    st.configure("Accion.TButton", background=AZUL, foreground="#f2fbfe",
                 font=FUENTE_TIT, padding=(px(12), px(6)))
    st.map("Accion.TButton",
           background=[("disabled", PANEL), ("pressed", AZUL_OSC),
                       ("active", "#3bb2d8")],
           foreground=[("disabled", "#4d5867")])

    st.configure("TMenubutton", background=PANEL, foreground=TEXTO,
                 bordercolor=BORDE, arrowcolor=ACENTO, padding=(px(9), px(4)),
                 relief="flat")
    st.map("TMenubutton",
           background=[("pressed", ACENTO_OSC), ("active", PANEL_ALTO)],
           foreground=[("pressed", "#12161c"), ("active", TEXTO)])

    # --- controles
    for clase, fondo in (("TCheckbutton", FONDO), ("TRadiobutton", FONDO)):
        st.configure(clase, background=fondo, foreground=TEXTO)
        st.map(clase, background=[("active", fondo)],
               indicatorcolor=[("selected", ACENTO), ("!selected", PANEL_HUND)])
    st.configure("Caja.TCheckbutton", background=PANEL, foreground=TEXTO)
    st.map("Caja.TCheckbutton", background=[("active", PANEL)],
           indicatorcolor=[("selected", ACENTO), ("!selected", PANEL_HUND)])

    st.configure("TEntry", fieldbackground=PANEL_HUND, foreground=TEXTO,
                 insertcolor=ACENTO, bordercolor=BORDE, padding=px(3))
    st.configure("TSpinbox", fieldbackground=PANEL_HUND, foreground=TEXTO,
                 arrowcolor=ACENTO, bordercolor=BORDE)
    st.configure("TCombobox", fieldbackground=PANEL_HUND, background=PANEL,
                 foreground=TEXTO, arrowcolor=ACENTO, bordercolor=BORDE)
    st.map("TCombobox", fieldbackground=[("readonly", PANEL_HUND)],
           selectbackground=[("readonly", PANEL_HUND)],
           selectforeground=[("readonly", TEXTO)])
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", TEXTO)
    root.option_add("*TCombobox*Listbox.selectBackground", ACENTO)
    root.option_add("*TCombobox*Listbox.selectForeground", "#12161c")

    # --- lista de reproduccion
    st.configure("Treeview", background=PANEL_HUND, fieldbackground=PANEL_HUND,
                 foreground=TEXTO, bordercolor=BORDE, rowheight=px(22))
    st.map("Treeview", background=[("selected", ACENTO_OSC)],
           foreground=[("selected", "#12161c")])
    st.configure("Treeview.Heading", background=PANEL_ALTO, foreground=TEXTO_SUAVE,
                 font=("Segoe UI Semibold", 8), relief="flat", padding=(px(6), px(4)))
    st.map("Treeview.Heading", background=[("active", "#2f3946")])

    st.configure("TNotebook", background=FONDO, bordercolor=BORDE,
                 tabmargins=(px(4), px(4), 0, 0))
    st.configure("TNotebook.Tab", background=PANEL, foreground=TEXTO_SUAVE,
                 padding=(px(14), px(7)), font=FUENTE)
    st.map("TNotebook.Tab",
           background=[("selected", FONDO), ("active", PANEL_ALTO)],
           foreground=[("selected", ACENTO), ("active", TEXTO)],
           expand=[("selected", (0, 0, 0, 2))])

    st.configure("TProgressbar", background=AZUL, troughcolor=PANEL_HUND,
                 bordercolor=BORDE, lightcolor=AZUL, darkcolor=AZUL_OSC,
                 thickness=px(10))
    for orientacion in ("Horizontal", "Vertical"):
        st.configure("%s.TScrollbar" % orientacion, background=PANEL,
                     troughcolor=FONDO, bordercolor=BORDE, arrowcolor=TEXTO_SUAVE)
        st.map("%s.TScrollbar" % orientacion, background=[("active", PANEL_ALTO)])
    st.configure("TScale", background=FONDO, troughcolor=PANEL_HUND, bordercolor=BORDE)
    # ojo: los estilos derivados de Scale necesitan la orientacion en el
    # nombre ("Caja.Horizontal.TScale"), si no ttk no encuentra el disenio
    st.configure("Caja.Horizontal.TScale", background=PANEL,
                 troughcolor=PANEL_HUND, bordercolor=BORDE)
    st.configure("Caja.Vertical.TScale", background=PANEL,
                 troughcolor=PANEL_HUND, bordercolor=BORDE)

    for clase in ("Text", "Listbox"):
        root.option_add("*%s.background" % clase, PANEL_HUND)
        root.option_add("*%s.foreground" % clase, TEXTO)
        root.option_add("*%s.selectBackground" % clase, ACENTO)
        root.option_add("*%s.selectForeground" % clase, "#12161c")
        root.option_add("*%s.highlightThickness" % clase, 0)
        root.option_add("*%s.borderWidth" % clase, 0)
    root.option_add("*Text.insertBackground", ACENTO)
    return st


# ------------------------------------------------------------------ vumetro

class Vumetro(tk.Canvas):
    """
    Medidor de nivel con la escala de siempre: verde hasta -12 dB, ambar hasta
    -3 y rojo arriba. Guarda la marca del pico un momento, como los de verdad.
    """

    def __init__(self, padre, ancho=px(160), alto=px(12), horizontal=True,
                 minimo=-54.0, **kw):
        super().__init__(padre, width=ancho, height=alto, bg=PANEL_HUND,
                         highlightthickness=0, bd=0, **kw)
        self.ancho, self.alto = ancho, alto
        self.horizontal = horizontal
        self.minimo = minimo
        self.pico = minimo
        self._pico_hasta = 0
        self._segmentos = 28
        self._dibujar_fondo()

    def _dibujar_fondo(self):
        self.delete("all")
        n = self._segmentos
        if self.horizontal:
            paso = self.ancho / float(n)
            for i in range(n):
                x = i * paso
                self.create_rectangle(x + 1, 1, x + paso - 1, self.alto - 1,
                                      fill=VU_APAGADO, outline="", tags="seg%d" % i)
        else:
            paso = self.alto / float(n)
            for i in range(n):
                y = self.alto - (i + 1) * paso
                self.create_rectangle(1, y + 1, self.ancho - 1, y + paso - 1,
                                      fill=VU_APAGADO, outline="", tags="seg%d" % i)

    def _color(self, i):
        frac = i / float(self._segmentos - 1)
        db = self.minimo + frac * (0 - self.minimo)
        if db >= -3:
            return VU_ROJO
        if db >= -12:
            return VU_AMBAR
        return VU_VERDE

    def poner(self, db):
        """db entre `minimo` y 0."""
        import time
        db = max(self.minimo, min(0.0, float(db)))
        encendidos = int(round((db - self.minimo) / (0 - self.minimo)
                               * self._segmentos))
        ahora = time.time()
        if db >= self.pico or ahora > self._pico_hasta:
            self.pico = db
            self._pico_hasta = ahora + 1.2
        seg_pico = int(round((self.pico - self.minimo) / (0 - self.minimo)
                             * self._segmentos))
        for i in range(self._segmentos):
            if i < encendidos:
                color = self._color(i)
            elif i == seg_pico - 1 and seg_pico > encendidos:
                color = self._color(i)
            else:
                color = VU_APAGADO
            try:
                self.itemconfigure("seg%d" % i, fill=color)
            except tk.TclError:
                pass


class Grafico(tk.Canvas):
    """Curva sencilla (oyentes en el tiempo). Sin librerias externas."""

    def __init__(self, padre, ancho=px(300), alto=px(90), color=AZUL, **kw):
        super().__init__(padre, width=ancho, height=alto, bg=PANEL_HUND,
                         highlightthickness=0, bd=0, **kw)
        self.ancho, self.alto, self.color = ancho, alto, color
        self.bind("<Configure>", lambda e: self._medir(e))
        self.datos = []

    def _medir(self, e):
        self.ancho, self.alto = e.width, e.height
        self.pintar(self.datos)

    def pintar(self, valores):
        self.datos = list(valores or [])
        self.delete("all")
        if not self.datos:
            self.create_text(self.ancho / 2, self.alto / 2,
                             text="sin datos todavia", fill=TEXTO_SUAVE,
                             font=FUENTE)
            return
        tope = max(2, max(self.datos))
        n = len(self.datos)
        margen = px(4)
        util_a = max(1, self.ancho - margen * 2)
        util_h = max(1, self.alto - margen * 2)

        for frac in (0.0, 0.5, 1.0):                    # rejilla
            y = margen + util_h * frac
            self.create_line(margen, y, self.ancho - margen, y,
                             fill="#1f2731")
        puntos = []
        for i, v in enumerate(self.datos):
            x = margen + (i / float(max(1, n - 1))) * util_a
            y = margen + util_h * (1 - v / float(tope))
            puntos += [x, y]
        if len(puntos) >= 4:
            relleno = puntos + [self.ancho - margen, self.alto - margen,
                                margen, self.alto - margen]
            self.create_polygon(relleno, fill="#16303c", outline="")
            self.create_line(puntos, fill=self.color, width=px(2), smooth=True)
        self.create_text(self.ancho - margen - px(2), margen + px(6),
                         text="max %d" % tope, fill=TEXTO_SUAVE, anchor="e",
                         font=("Segoe UI", 8))
