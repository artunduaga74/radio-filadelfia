# -*- coding: utf-8 -*-
"""
Ventana pequena "Monitor de aire": que se oye en la emisora, ahora mismo.

Se abre aparte, se puede dejar SIEMPRE VISIBLE encima de todo y ocupa poco,
para tenerla en una esquina mientras se trabaja en otra cosa.

Muestra tres cosas que el panel del servidor no dice:
  - el NIVEL de audio real que sale, medido escuchando el chorro
  - cuanto lleva CALLADO (el fallo mas peligroso: la fuente sigue conectada
    pero manda silencio y nadie se entera)
  - el titulo y los oyentes

OJO: mientras esta abierta cuenta como UN OYENTE y consume el ancho de banda
de uno. Se cierra y deja de gastar.
"""

import tkinter as tk
from tkinter import ttk

import config
import estilo
import monitor_aire
import servidor
from estilo import px

SEGUNDOS_ALARMA = 15        # a partir de aqui, el silencio se pinta en rojo


class VentanaAire(tk.Toplevel):

    def __init__(self, padre):
        super().__init__(padre)
        self.padre = padre
        self.title("Monitor de aire")
        self.configure(bg=estilo.FONDO)
        self.resizable(False, False)
        estilo.aplicar(self)

        self.vigilante = monitor_aire.VigilanteAire()
        self.estado_srv = None
        self._ultimo_sondeo = 0.0

        self._construir()
        self.protocol("WM_DELETE_WINDOW", self.cerrar)

        if config.get("aire_siempre_visible", True):
            self.var_encima.set(True)
            self._cambiar_encima()

        self.vigilante.arrancar()
        self._tic()
        self._colocar()

    # ---------------------------------------------------------------- montaje

    def _construir(self):
        cuerpo = ttk.Frame(self, padding=(px(12), px(10)))
        cuerpo.pack(fill="both", expand=True)

        arriba = ttk.Frame(cuerpo)
        arriba.pack(fill="x")
        self.luz = tk.Canvas(arriba, width=px(22), height=px(22),
                             bg=estilo.FONDO, highlightthickness=0, bd=0)
        self.luz.pack(side="left")
        self.bola = self.luz.create_oval(px(3), px(3), px(19), px(19),
                                         fill=estilo.TEXTO_SUAVE, outline="")
        self.lbl_estado = ttk.Label(arriba, text="conectando...",
                                    style="Grande.TLabel")
        self.lbl_estado.pack(side="left", padx=px(8))

        self.lbl_titulo = ttk.Label(cuerpo, text="", style="Suave.TLabel",
                                    wraplength=px(320), justify="left")
        self.lbl_titulo.pack(fill="x", pady=(px(6), px(2)))

        self.vu = estilo.Vumetro(cuerpo, ancho=px(320), alto=px(12))
        self.vu.pack(fill="x", pady=px(4))

        abajo = ttk.Frame(cuerpo)
        abajo.pack(fill="x", pady=(px(4), 0))
        self.lbl_oyentes = ttk.Label(abajo, text="", style="Suave.TLabel")
        self.lbl_oyentes.pack(side="left")
        self.lbl_silencio = ttk.Label(abajo, text="", style="Suave.TLabel")
        self.lbl_silencio.pack(side="right")

        pie = ttk.Frame(cuerpo)
        pie.pack(fill="x", pady=(px(8), 0))
        self.var_encima = tk.BooleanVar(value=False)
        ttk.Checkbutton(pie, text="Siempre visible", variable=self.var_encima,
                        command=self._cambiar_encima).pack(side="left")
        ttk.Button(pie, text="Cerrar", command=self.cerrar).pack(side="right")

    def _colocar(self):
        """Arriba a la derecha de la pantalla, que no estorbe."""
        self.update_idletasks()
        x = self.winfo_screenwidth() - self.winfo_width() - px(30)
        y = px(40)
        try:
            guardada = config.get("aire_posicion") or ""
            if guardada:
                x, y = [int(v) for v in guardada.split(",")]
        except Exception:
            pass
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))

    def _cambiar_encima(self):
        encima = bool(self.var_encima.get())
        try:
            self.attributes("-topmost", encima)
        except tk.TclError:
            pass
        config.guardar({"aire_siempre_visible": encima})

    # ---------------------------------------------------------------- pintado

    def _tic(self):
        try:
            self._pintar()
        except tk.TclError:
            return
        self.after(200, self._tic)

    def _pintar(self):
        import time
        v = self.vigilante

        # el servidor se pregunta cada 10 s; el nivel se mide sin parar
        ahora = time.time()
        if ahora - self._ultimo_sondeo > 10:
            self._ultimo_sondeo = ahora
            import threading
            threading.Thread(target=self._sondear, daemon=True).start()

        self.vu.poner(v.nivel)
        callado = v.segundos_callado

        if v.estado == monitor_aire.CAIDA:
            color, texto = estilo.ROJO, "EMISORA CAIDA"
        elif v.estado == monitor_aire.CONECTANDO:
            color, texto = estilo.AMARILLO, "conectando..."
        elif v.estado == monitor_aire.APAGADO:
            color, texto = estilo.TEXTO_SUAVE, "detenido"
        elif callado >= SEGUNDOS_ALARMA:
            color, texto = estilo.ROJO, "SIN AUDIO"
        elif v.estado == monitor_aire.CALLADO:
            color, texto = estilo.AMARILLO, "en silencio"
        else:
            color, texto = estilo.VERDE, "AL AIRE"

        self.luz.itemconfigure(self.bola, fill=color)
        self.lbl_estado.configure(text=texto, foreground=color)

        if v.estado == monitor_aire.CAIDA:
            self.lbl_silencio.configure(text=v.detalle[:34],
                                        foreground=estilo.ROJO)
        elif callado >= 2:
            self.lbl_silencio.configure(
                text="callado %d s" % int(callado),
                foreground=estilo.ROJO if callado >= SEGUNDOS_ALARMA
                else estilo.TEXTO_SUAVE)
        else:
            self.lbl_silencio.configure(text="", foreground=estilo.TEXTO_SUAVE)

        est = self.estado_srv
        if est and not est["error"]:
            self.lbl_titulo.configure(text=est["titulo"] or "(sin titulo)")
            self.lbl_oyentes.configure(
                text="%d oyentes  ·  pico %d  ·  %d kbps"
                     % (est["oyentes"], est["pico"], est["bitrate"]))
        elif est:
            self.lbl_oyentes.configure(text="sin datos del servidor")

    def _sondear(self):
        try:
            self.estado_srv = servidor.estado()
        except Exception:
            pass

    # ---------------------------------------------------------------- cierre

    def cerrar(self):
        try:
            config.guardar({"aire_posicion": "%d,%d" % (self.winfo_x(),
                                                        self.winfo_y())})
        except Exception:
            pass
        self.vigilante.detener()
        try:
            self.destroy()
        except tk.TclError:
            pass
