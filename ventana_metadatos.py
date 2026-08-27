# -*- coding: utf-8 -*-
"""
Editor de metadatos: arreglar las etiquetas de un programa YA grabado.

Los campos y la tarjeta de vista previa son los MISMOS de
Configuracion -> Transmision, a proposito: alli se decide como saldran las
grabaciones nuevas y aqui se corrige una vieja, asi que no tiene sentido que se
parezcan a dos cosas distintas.

Lo que hace y lo que no:
  - NO recodifica el audio. Cambiar el titulo no toca la calidad del programa.
  - NO escribe encima hasta que ffmpeg termina bien (ver `metadatos.escribir`).
  - Avisa antes de cerrar si queda algo sin guardar.
"""

import os
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import config
import estilo
import metadatos
from estilo import px

TITULO = "Editor de metadatos"


class VentanaMetadatos(tk.Toplevel):

    def __init__(self, padre):
        super().__init__(padre)
        self.padre = padre
        self.title(TITULO)
        self.configure(bg=estilo.FONDO)
        estilo.aplicar(self)

        self.ruta = None              # archivo abierto
        self.vars = {}                # clave -> StringVar
        self.portada_nueva = None     # imagen elegida a mano
        self.quitar_portada = False
        self.tenia_portada = False
        self._original = {}           # para saber si hay cambios
        self._tapa_img = None
        self._tmp_tapa = None
        self._resultado = None        # lo deja el hilo que escribe

        self._construir()
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        self._colocar()
        self._pintar_vista()

    # ---------------------------------------------------------------- montaje

    def _construir(self):
        cuerpo = ttk.Frame(self, padding=(px(12), px(10)))
        cuerpo.pack(fill="both", expand=True)
        cuerpo.columnconfigure(1, weight=1)
        fila = 0

        # --- archivo ---------------------------------------------------
        ttk.Label(cuerpo, text="ARCHIVO", style="Suave.TLabel").grid(
            row=fila, column=0, columnspan=3, sticky="w")
        fila += 1
        self.lbl_archivo = ttk.Label(cuerpo, text="Ningun archivo abierto.",
                                     style="Suave.TLabel")
        self.lbl_archivo.grid(row=fila, column=0, columnspan=2, sticky="w",
                              pady=px(3))
        ttk.Button(cuerpo, text="Abrir...", width=9,
                   command=self.abrir).grid(row=fila, column=2, sticky="e")
        fila += 1

        ttk.Separator(cuerpo, orient="horizontal").grid(
            row=fila, column=0, columnspan=3, sticky="ew", pady=px(8))
        fila += 1

        # --- campos ----------------------------------------------------
        ttk.Label(cuerpo, text="DATOS QUE VAN DENTRO DEL ARCHIVO",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        fila += 1
        for clave, rotulo in metadatos.CAMPOS:
            ttk.Label(cuerpo, text=rotulo).grid(row=fila, column=0, sticky="w",
                                                pady=px(3))
            var = tk.StringVar()
            var.trace_add("write", lambda *_: self._pintar_vista())
            e = ttk.Entry(cuerpo, textvariable=var, width=38)
            e.grid(row=fila, column=1, columnspan=2, sticky="ew")
            self.vars[clave] = var
            fila += 1
        ttk.Label(cuerpo, text="Lo que se deje en blanco se BORRA del archivo.",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        fila += 1

        # --- caratula --------------------------------------------------
        ttk.Label(cuerpo, text="Caratula:").grid(row=fila, column=0, sticky="w",
                                                 pady=px(3))
        self.lbl_tapa_est = ttk.Label(cuerpo, text="-", style="Suave.TLabel")
        self.lbl_tapa_est.grid(row=fila, column=1, sticky="w")
        botones_tapa = ttk.Frame(cuerpo)
        botones_tapa.grid(row=fila, column=2, sticky="e")
        ttk.Button(botones_tapa, text="Cambiar", width=8,
                   command=self.elegir_portada).pack(side="left")
        ttk.Button(botones_tapa, text="Quitar", width=7,
                   command=self.sacar_portada).pack(side="left", padx=(px(4), 0))
        fila += 1

        ttk.Separator(cuerpo, orient="horizontal").grid(
            row=fila, column=0, columnspan=3, sticky="ew", pady=px(8))
        fila += 1

        # --- vista previa (misma tarjeta que Configuracion) ------------
        ttk.Label(cuerpo, text="ASI SE VERA EN UN REPRODUCTOR",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        fila += 1
        tarjeta = tk.Frame(cuerpo, bg=estilo.PANEL_HUND, bd=0,
                           highlightthickness=1,
                           highlightbackground=estilo.BORDE)
        tarjeta.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=px(6))
        self.lbl_tapa = tk.Label(tarjeta, bg=estilo.PANEL_HUND, bd=0,
                                 width=10, height=5)
        self.lbl_tapa.pack(side="left", padx=px(8), pady=px(8))
        letras = tk.Frame(tarjeta, bg=estilo.PANEL_HUND)
        letras.pack(side="left", fill="both", expand=True, pady=px(8))
        self.vista = {}
        for clave, fuente, color in (
                ("title", ("Segoe UI Semibold", 11), estilo.TEXTO),
                ("artist", ("Segoe UI", 9), estilo.ACENTO),
                ("album", ("Segoe UI", 9), estilo.TEXTO_SUAVE),
                ("otros", ("Segoe UI", 8), estilo.TEXTO_SUAVE)):
            l = tk.Label(letras, text="", bg=estilo.PANEL_HUND, fg=color,
                         font=fuente, anchor="w", justify="left")
            l.pack(anchor="w", fill="x")
            self.vista[clave] = l
        fila += 1

        # --- pie -------------------------------------------------------
        pie = ttk.Frame(cuerpo)
        pie.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=(px(8), 0))
        self.lbl_estado = ttk.Label(pie, text="", style="Suave.TLabel")
        self.lbl_estado.pack(side="left")
        ttk.Button(pie, text="Cerrar", width=9,
                   command=self.cerrar).pack(side="right")
        self.btn_guardar = ttk.Button(pie, text="Guardar", width=10,
                                      style="Accion.TButton",
                                      command=self.guardar)
        self.btn_guardar.pack(side="right", padx=(0, px(6)))
        self.btn_guardar.state(["disabled"])

    def _colocar(self):
        """Centrada y nunca mas grande que la pantalla (leccion 2)."""
        self.update_idletasks()
        ancho = min(self.winfo_reqwidth(), self.winfo_screenwidth() - px(40))
        alto = min(self.winfo_reqheight(), self.winfo_screenheight() - px(80))
        self.minsize(ancho, alto)
        x = max(0, (self.winfo_screenwidth() - ancho) // 2)
        y = max(0, (self.winfo_screenheight() - alto) // 3)
        self.geometry("%dx%d+%d+%d" % (ancho, alto, x, y))

    # ---------------------------------------------------------------- abrir

    def abrir(self, ruta=None):
        if ruta is None:
            if not self._puede_descartar():
                return
            patrones = " ".join("*" + e for e in metadatos.EXTENSIONES)
            ruta = filedialog.askopenfilename(
                title="Elegir el archivo", parent=self,
                initialdir=str(config.carpeta_graba()),
                filetypes=[("Audio", patrones), ("Todos", "*.*")])
            if not ruta:
                return
        datos = metadatos.leer(ruta)
        if datos["error"]:
            messagebox.showerror(TITULO, "No se pudo leer el archivo:\n%s"
                                 % datos["error"], parent=self)
            return

        self.ruta = Path(ruta)
        self.portada_nueva = None
        self.quitar_portada = False
        self.tenia_portada = datos["tiene_portada"]
        et = datos["etiquetas"]
        for clave, var in self.vars.items():
            var.set(et.get(clave, ""))
        self._original = {c: v.get() for c, v in self.vars.items()}

        minutos, segundos = divmod(int(datos["duracion"]), 60)
        self.lbl_archivo.configure(
            text="%s  (%d:%02d)" % (self.ruta.name, minutos, segundos))
        self.title("%s - %s" % (self.ruta.name, TITULO))
        self.btn_guardar.state(["!disabled"])
        self._cargar_tapa()
        self._pintar_vista()
        self.lbl_estado.configure(text="", foreground=estilo.TEXTO_SUAVE)

    # ---------------------------------------------------------------- caratula

    def _cargar_tapa(self):
        """Saca la caratula incrustada a un temporal para poder enseniarla."""
        self._tmp_tapa = None
        if self.ruta is None or not self.tenia_portada:
            return
        try:
            destino = os.path.join(tempfile.gettempdir(),
                                   "filadelfia_tapa_%d.jpg" % os.getpid())
            self._tmp_tapa = metadatos.extraer_portada(self.ruta, destino)
        except Exception:
            self._tmp_tapa = None

    def elegir_portada(self):
        ruta = filedialog.askopenfilename(
            title="Elegir la caratula", parent=self,
            filetypes=[("Imagenes", "*.png *.jpg *.jpeg *.webp *.bmp"),
                       ("Todos", "*.*")])
        if ruta:
            self.portada_nueva = ruta
            self.quitar_portada = False
            self._pintar_vista()

    def sacar_portada(self):
        self.portada_nueva = None
        self.quitar_portada = True
        self._pintar_vista()

    # ---------------------------------------------------------------- vista

    def _ruta_tapa(self):
        if self.quitar_portada:
            return None
        return self.portada_nueva or self._tmp_tapa

    def _texto_tapa(self):
        if self.quitar_portada:
            return "ninguna"
        if self.portada_nueva:
            return "nueva: " + os.path.basename(self.portada_nueva)
        return "la del archivo" if self.tenia_portada else "ninguna"

    def _pintar_vista(self):
        datos = {c: v.get().strip() for c, v in self.vars.items()}
        try:
            self.vista["title"].configure(
                text=datos.get("title") or "(sin titulo)")
            # el aviso es el mismo que se ve en la radio cuando falta el autor
            self.vista["artist"].configure(
                text=datos.get("artist") or "Unknown (falta el autor)")
            self.vista["album"].configure(text=datos.get("album", ""))
            self.vista["otros"].configure(
                text="%s  ·  %s" % (datos.get("genre", ""),
                                         datos.get("date", "")))
            self.lbl_tapa_est.configure(text=self._texto_tapa()[:34])
        except tk.TclError:
            return

        tapa = self._ruta_tapa()
        try:
            if tapa and os.path.exists(tapa):
                from PIL import Image, ImageTk
                im = Image.open(tapa).convert("RGB")
                im.thumbnail((px(72), px(72)), Image.LANCZOS)
                self._tapa_img = ImageTk.PhotoImage(im)
                self.lbl_tapa.configure(image=self._tapa_img, text="",
                                        width=px(72), height=px(72))
            else:
                self._tapa_img = None
                self.lbl_tapa.configure(image="", text="sin\nimagen",
                                        fg=estilo.TEXTO_SUAVE,
                                        width=10, height=5)
        except Exception:
            pass

    # ---------------------------------------------------------------- guardar

    def hay_cambios(self):
        if self.ruta is None:
            return False
        if self.portada_nueva or self.quitar_portada:
            return True
        return any(v.get() != self._original.get(c, "")
                   for c, v in self.vars.items())

    def guardar(self):
        """
        Escribe en segundo plano: un programa de una hora tarda un momento en
        volver a empaquetarse y la ventana no puede quedarse congelada.

        El hilo NO toca ningun widget: deja el resultado en `_resultado` y la
        ventana lo recoge con `after`, que es como funciona el resto de la
        aplicacion (tkinter no es seguro entre hilos, y llamar `after` desde
        fuera del hilo de la interfaz revienta con "main thread is not in main
        loop").
        """
        if self.ruta is None:
            return
        datos = {c: v.get() for c, v in self.vars.items()}
        portada, quitar = self.portada_nueva, self.quitar_portada
        self.btn_guardar.state(["disabled"])
        self.lbl_estado.configure(text="Guardando...",
                                  foreground=estilo.TEXTO_SUAVE)
        self._resultado = None

        def trabajo():
            self._resultado = metadatos.escribir(self.ruta, datos,
                                                 portada=portada,
                                                 quitar_portada=quitar)

        threading.Thread(target=trabajo, daemon=True).start()
        self._esperar_guardado()

    def _esperar_guardado(self):
        resultado = getattr(self, "_resultado", None)
        if resultado is None:
            try:
                self.after(100, self._esperar_guardado)
            except tk.TclError:
                pass                       # la ventana ya no esta
            return
        self._resultado = None
        self._guardado(*resultado)

    def _guardado(self, ok, detalle):
        try:
            self.btn_guardar.state(["!disabled"])
        except tk.TclError:
            return
        if ok:
            self._original = {c: v.get() for c, v in self.vars.items()}
            if self.portada_nueva:
                self.tenia_portada = True
            elif self.quitar_portada:
                self.tenia_portada = False
            self.portada_nueva = None
            self.quitar_portada = False
            self._cargar_tapa()
            self._pintar_vista()
            self.lbl_estado.configure(text="Guardado.", foreground=estilo.VERDE)
            try:
                self.padre._anotar("metadatos guardados: %s" % self.ruta.name)
            except Exception:
                pass
        else:
            self.lbl_estado.configure(text=detalle[:60], foreground=estilo.ROJO)
            messagebox.showerror(TITULO, "No se pudo guardar:\n%s" % detalle,
                                 parent=self)

    # ---------------------------------------------------------------- cerrar

    def _puede_descartar(self):
        if not self.hay_cambios():
            return True
        r = messagebox.askyesnocancel(
            TITULO, "Hay cambios sin guardar en\n%s\n\nGuardarlos?"
                    % self.ruta.name, parent=self)
        if r is None:
            return False
        if r:
            self.guardar()
        return True

    def cerrar(self):
        if not self._puede_descartar():
            return
        try:
            if self._tmp_tapa and os.path.exists(self._tmp_tapa):
                os.remove(self._tmp_tapa)
        except Exception:
            pass
        try:
            self.padre.ventana_metadatos = None
        except Exception:
            pass
        self.destroy()
