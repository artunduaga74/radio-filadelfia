# -*- coding: utf-8 -*-
"""
Voz de Filadelfia - estudio de transmision.

Una sola ventana, con todo a la vista:
  izquierda   la lista de lo que va a sonar
  derecha     lo que esta sonando, el mezclador y los oyentes

Reglas de la casa:
  - El hilo del audio NUNCA toca la interfaz (tkinter no es seguro entre
    hilos). La ventana consulta los niveles cada 60 ms con `after`.
  - Rojo = al aire. No se usa ese rojo para nada mas.
"""

import os
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import audio
import biblioteca
import config
import emisor as mod_emisor
import eq as mod_eq
import estilo
import grabador as mod_grabador
import motor
import procesos
import servidor
from estilo import Consejo, px

TITULO = "Voz de Filadelfia - Estudio"

# como se llaman los protocolos en pantalla
CORTINAS = 4          # cuantos botones de cortina hay

# Que hace la barra espaciadora (se elige en Configuracion > Audio)
ESPACIO_MICRO = "microfono"
ESPACIO_PLAY = "reproducir"
ESPACIO_NADA = "nada"
ESPACIO_TEXTOS = {
    ESPACIO_MICRO: "Abrir y cerrar el microfono",
    ESPACIO_PLAY: "Reproducir / pausa",
    ESPACIO_NADA: "Nada (desactivada)",
}

ICO_PLAY = "▶"          # play
ICO_PAUSA = "⏸"         # pausa
ICO_PARAR = "⏹"         # parar
ICO_SIGUIENTE = "⏭"     # siguiente
ICO_REC = "⏺"           # grabar

PROTO_V1 = "SHOUTcast v1  (el de esta emisora)"
PROTO_ICE = "Icecast"
PROTOCOLOS = {"shoutcast_v1": PROTO_V1, "icecast": PROTO_ICE}
EXTS = " ".join("*" + e for e in sorted(biblioteca.EXTENSIONES))


def reloj(segundos):
    segundos = int(max(0, segundos))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return "%d:%02d:%02d" % (h, m, s)


# ==================================================================== ventana

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(TITULO)
        # px() cuenta el escalado de Windows: al 150 % una ventana "de 1180"
        # mide 1770 px reales y no cabe en una pantalla de 1920x1080. Se pide
        # lo deseado pero recortado a lo que hay.
        ancho = min(px(1180), self.winfo_screenwidth() - px(40))
        alto = min(px(700), self.winfo_screenheight() - px(70))
        self.geometry("%dx%d" % (ancho, alto))
        self.minsize(min(px(940), ancho), min(px(600), alto))
        estilo.aplicar(self)
        try:
            ico = Path(__file__).with_name("icono.ico")
            if ico.exists():
                self.iconbitmap(str(ico))
        except Exception:
            pass

        config.asegurar_carpetas()

        # --- piezas de audio
        self.emisor = mod_emisor.Emisor(al_cambiar=self._emisor_cambio,
                                        al_registrar=self._anotar)
        self.grabador = mod_grabador.Grabador(al_registrar=self._anotar)
        self.mezclador = motor.Mezclador(emisor=self.emisor,
                                         grabador=self.grabador)
        self.lista = biblioteca.Lista()
        self.biblio = biblioteca.Biblioteca(config.get("carpeta_musica", ""))
        self.historial = servidor.Historial()
        self.vigilante = servidor.Vigilante(historial=self.historial)

        self.registro = []
        self.auto_siguiente = True
        self.ultimo_titulo_enviado = ""
        self._explorando = False

        self._construir_menu()
        self._construir()
        self._cargar_ajustes_en_pantalla()

        self.vigilante.arrancar()
        self.protocol("WM_DELETE_WINDOW", self._al_cerrar)
        self.after(60, self._tic_rapido)
        self.after(1000, self._tic_lento)
        self.after(300, self._primer_arranque)

    # ---------------------------------------------------------------- menu

    def _construir_menu(self):
        barra = tk.Menu(self, tearoff=0)

        m = tk.Menu(barra, tearoff=0)
        m.add_command(label="Configuracion...", command=self.abrir_configuracion)
        m.add_command(label="Probar conexion con el servidor",
                      command=self.probar_servidor)
        m.add_separator()
        m.add_command(label="Abrir la pagina de la emisora", command=self.abrir_web)
        m.add_command(label="Carpeta de grabaciones", command=self.abrir_grabaciones)
        m.add_separator()
        m.add_command(label="Salir", command=self._al_cerrar)
        barra.add_cascade(label="Emisora", menu=m)

        m = tk.Menu(barra, tearoff=0)
        m.add_command(label="Agregar archivos...", command=self.agregar_archivos)
        m.add_command(label="Agregar carpeta...", command=self.agregar_carpeta)
        m.add_separator()
        m.add_command(label="Abrir lista...", command=self.abrir_lista)
        m.add_command(label="Guardar lista...", command=self.guardar_lista)
        m.add_separator()
        m.add_command(label="Vaciar la lista", command=self.vaciar_lista)
        barra.add_cascade(label="Lista", menu=m)

        m = tk.Menu(barra, tearoff=0)
        m.add_command(label="Registro tecnico", command=self.ver_registro)
        m.add_command(label="Estadisticas de oyentes", command=self.ver_estadisticas)
        barra.add_cascade(label="Ver", menu=m)

        m = tk.Menu(barra, tearoff=0)
        m.add_command(label="Atajos de teclado", command=self.ver_atajos)
        barra.add_cascade(label="Ayuda", menu=m)

        self.config(menu=barra)

        # La barra espaciadora se decide en Configuracion (por defecto, el
        # microfono). F1 y F2 valen siempre, hagan lo que hagan los demas.
        self.bind("<space>", lambda e: self._atajo_espacio())
        self.bind("<F1>", lambda e: self._atajo(self.alternar_microfono))
        self.bind("<F2>", lambda e: self._atajo(self.alternar_grabacion))
        self.bind("<Control-Right>", lambda e: self._atajo(self.siguiente_pista))

    def _atajo(self, funcion):
        """
        Ejecuta el atajo, salvo que se este escribiendo en algun campo: si no,
        poner el titulo del programa abriria el microfono a cada espacio.
        """
        foco = self.focus_get()
        if isinstance(foco, (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox,
                             ttk.Spinbox)):
            return
        funcion()
        return "break"

    def _atajo_espacio(self):
        accion = config.get("tecla_espacio", ESPACIO_MICRO)
        if accion == ESPACIO_MICRO:
            return self._atajo(self.alternar_microfono)
        if accion == ESPACIO_PLAY:
            return self._atajo(self.play_pausa)
        return None                    # desactivada

    # ---------------------------------------------------------------- montaje

    def _construir(self):
        self._barra_superior()
        # OJO: la barra de estado va ANTES que el cuerpo. En `pack` el espacio
        # se reparte por orden, y un cuerpo con expand=True deja sin sitio a lo
        # que se empaquete despues (ya paso en el editor de video).
        self._barra_estado()

        cuerpo = ttk.Frame(self, padding=(px(8), 0, px(8), px(4)))
        cuerpo.pack(fill="both", expand=True)
        cuerpo.columnconfigure(0, weight=3, minsize=px(400))
        cuerpo.columnconfigure(1, weight=2, minsize=px(370))
        cuerpo.rowconfigure(0, weight=1)

        izquierda = ttk.Frame(cuerpo)
        izquierda.grid(row=0, column=0, sticky="nsew")
        izquierda.rowconfigure(0, weight=1)      # la lista se lleva el alto
        izquierda.columnconfigure(0, weight=1)
        self._panel_lista(izquierda)
        self._panel_oyentes(izquierda)

        derecha = ttk.Frame(cuerpo)
        derecha.grid(row=0, column=1, sticky="nsew", padx=(px(8), 0))
        derecha.rowconfigure(2, weight=1)        # hueco elastico al final
        derecha.columnconfigure(0, weight=1)
        self._panel_aire(derecha)
        self._panel_mezcla(derecha)

    # -------------------------------------------------- barra superior

    def _barra_superior(self):
        top = ttk.Frame(self, padding=(px(10), px(8)))
        top.pack(fill="x")

        izq = ttk.Frame(top)
        izq.pack(side="left")
        self.lbl_emisora = ttk.Label(izq, text=config.get("nombre_emisora"),
                                     style="Titulo.TLabel")
        self.lbl_emisora.pack(anchor="w")
        self.lbl_servidor = ttk.Label(izq, text="", style="Suave.TLabel")
        self.lbl_servidor.pack(anchor="w")

        der = ttk.Frame(top)
        der.pack(side="right")
        self.btn_aire = ttk.Button(der, text="SALIR AL AIRE", style="Salir.TButton",
                                   command=self.alternar_aire, width=16)
        self.btn_aire.pack(side="right", padx=(px(10), 0))

        estado = ttk.Frame(der)
        estado.pack(side="right")
        self.lbl_estado_aire = ttk.Label(estado, text="fuera del aire",
                                         style="Suave.TLabel")
        self.lbl_estado_aire.pack(anchor="e")
        self.lbl_tiempo_aire = ttk.Label(estado, text="0:00:00", style="Reloj.TLabel")
        self.lbl_tiempo_aire.pack(anchor="e")

    # -------------------------------------------------- lista

    def _panel_lista(self, padre):
        caja = ttk.Labelframe(padre, text=" LISTA DE REPRODUCCION ",
                              style="Caja.TLabelframe")
        caja.grid(row=0, column=0, sticky="nsew")
        caja.rowconfigure(2, weight=1)
        caja.columnconfigure(0, weight=1)

        herr = ttk.Frame(caja, style="Caja.TFrame")
        herr.grid(row=0, column=0, sticky="ew", pady=(0, px(6)))
        ttk.Button(herr, text="+ Archivos", style="Caja.TButton",
                   command=self.agregar_archivos).pack(side="left")
        ttk.Button(herr, text="+ Carpeta", style="Caja.TButton",
                   command=self.agregar_carpeta).pack(side="left", padx=px(4))
        ttk.Button(herr, text="Quitar", style="Caja.TButton",
                   command=self.quitar_seleccion).pack(side="left")
        ttk.Button(herr, text="Subir", style="Caja.TButton",
                   command=lambda: self.mover_seleccion(-1)).pack(side="left", padx=px(4))
        ttk.Button(herr, text="Bajar", style="Caja.TButton",
                   command=lambda: self.mover_seleccion(1)).pack(side="left")

        self.var_repetir = tk.BooleanVar(value=True)
        self.var_mezclar = tk.BooleanVar(value=False)
        ttk.Checkbutton(herr, text="Repetir", variable=self.var_repetir,
                        style="Caja.TCheckbutton",
                        command=self._aplicar_modo_lista).pack(side="right")
        ttk.Checkbutton(herr, text="Aleatorio", variable=self.var_mezclar,
                        style="Caja.TCheckbutton",
                        command=self._aplicar_modo_lista).pack(side="right", padx=px(6))

        busca = ttk.Frame(caja, style="Caja.TFrame")
        busca.grid(row=1, column=0, sticky="ew", pady=(0, px(6)))
        ttk.Label(busca, text="Buscar:", style="CajaSuave.TLabel").pack(side="left")
        self.var_busca = tk.StringVar()
        e = ttk.Entry(busca, textvariable=self.var_busca)
        e.pack(side="left", fill="x", expand=True, padx=px(6))
        e.bind("<KeyRelease>", lambda ev: self._filtrar())

        marco = ttk.Frame(caja, style="Caja.TFrame")
        marco.grid(row=2, column=0, sticky="nsew")
        marco.rowconfigure(0, weight=1)
        marco.columnconfigure(0, weight=1)

        cols = ("n", "titulo", "artista", "dur")
        self.tabla = ttk.Treeview(marco, columns=cols, show="headings",
                                  selectmode="extended")
        for c, txt, ancho, anclaje in (
                ("n", "#", px(34), "center"),
                ("titulo", "TITULO", px(230), "w"),
                ("artista", "ARTISTA", px(140), "w"),
                ("dur", "DURACION", px(70), "e")):
            self.tabla.heading(c, text=txt)
            self.tabla.column(c, width=ancho, anchor=anclaje,
                              stretch=(c == "titulo"))
        self.tabla.grid(row=0, column=0, sticky="nsew")
        self.tabla.tag_configure("sonando", background=estilo.ACENTO_OSC,
                                 foreground="#12161c")
        self.tabla.bind("<Double-1>", self._doble_clic_lista)

        sb = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tabla.configure(yscrollcommand=sb.set)

        pie = ttk.Frame(caja, style="Caja.TFrame")
        pie.grid(row=3, column=0, sticky="ew", pady=(px(6), 0))
        self.lbl_lista = ttk.Label(pie, text="lista vacia", style="CajaSuave.TLabel")
        self.lbl_lista.pack(side="left")
        ttk.Button(pie, text="Guardar lista", style="Caja.TButton",
                   command=self.guardar_lista).pack(side="right")
        ttk.Button(pie, text="Abrir lista", style="Caja.TButton",
                   command=self.abrir_lista).pack(side="right", padx=px(4))

    # -------------------------------------------------- al aire

    def _panel_aire(self, padre):
        caja = ttk.Labelframe(padre, text=" SONANDO AHORA ",
                              style="Caja.TLabelframe")
        caja.grid(row=0, column=0, sticky="ew")
        caja.columnconfigure(0, weight=1)

        self.lbl_pista = ttk.Label(caja, text="- nada -", style="Caja.TLabel",
                                   font=estilo.FUENTE_GDE, anchor="w")
        self.lbl_pista.grid(row=0, column=0, sticky="ew")
        self.lbl_artista = ttk.Label(caja, text="", style="CajaSuave.TLabel",
                                     anchor="w")
        self.lbl_artista.grid(row=1, column=0, sticky="ew", pady=(0, px(6)))

        self.barra_pista = ttk.Progressbar(caja, maximum=1000)
        self.barra_pista.grid(row=2, column=0, sticky="ew")

        tiempos = ttk.Frame(caja, style="Caja.TFrame")
        tiempos.grid(row=3, column=0, sticky="ew", pady=(px(3), px(8)))
        self.lbl_transcurrido = ttk.Label(tiempos, text="0:00", style="CajaMono.TLabel")
        self.lbl_transcurrido.pack(side="left")
        self.lbl_restante = ttk.Label(tiempos, text="-0:00", style="CajaMono.TLabel")
        self.lbl_restante.pack(side="right")

        botones = ttk.Frame(caja, style="Caja.TFrame")
        botones.grid(row=4, column=0, sticky="ew")
        self.btn_play = ttk.Button(botones, text=ICO_PLAY,
                                   style="Transporte.TButton",
                                   command=self.play_pausa)
        self.btn_play.pack(side="left")
        Consejo(self.btn_play, "Reproducir / pausa   (barra espaciadora)")
        b = ttk.Button(botones, text=ICO_SIGUIENTE, style="Transporte.TButton",
                       command=self.siguiente_pista)
        b.pack(side="left", padx=px(4))
        Consejo(b, "Siguiente pista   (Ctrl + flecha derecha)")
        b = ttk.Button(botones, text=ICO_PARAR, style="Transporte.TButton",
                       command=self.parar_musica)
        b.pack(side="left")
        Consejo(b, "Parar la musica")

        self.btn_rec = ttk.Button(botones, text="%s  Grabar" % ICO_REC,
                                  style="Rec.TButton",
                                  command=self.alternar_grabacion)
        self.btn_rec.pack(side="right")
        Consejo(self.btn_rec,
                "Grabar el programa. Es independiente de estar al aire: puedes poner musica sin grabarla y empezar a grabar cuando arranque el programa.")

        # titulo manual de la transmision
        tit = ttk.Frame(caja, style="Caja.TFrame")
        tit.grid(row=5, column=0, sticky="ew", pady=(px(8), 0))
        ttk.Label(tit, text="Titulo del programa:",
                  style="CajaSuave.TLabel").pack(anchor="w")
        fila = ttk.Frame(tit, style="Caja.TFrame")
        fila.pack(fill="x", pady=(px(2), 0))
        self.var_titulo = tk.StringVar()
        ttk.Entry(fila, textvariable=self.var_titulo).pack(
            side="left", fill="x", expand=True)
        ttk.Button(fila, text="Poner al aire", style="Caja.TButton",
                   command=self.poner_titulo).pack(side="left", padx=(px(4), 0))

    # -------------------------------------------------- mezcla

    def _panel_mezcla(self, padre):
        caja = ttk.Labelframe(padre, text=" MEZCLADOR ", style="Caja.TLabelframe")
        caja.grid(row=1, column=0, sticky="ew", pady=(px(8), 0))
        caja.columnconfigure(1, weight=1)

        self.vu = {}
        self.faders = {}
        filas = (("micro", "MICROFONO", "vol_micro"),
                 ("musica", "MUSICA", "vol_musica"),
                 ("efectos", "CORTINAS", "vol_efectos"))
        for i, (clave, texto, ajuste) in enumerate(filas):
            ttk.Label(caja, text=texto, style="CajaSuave.TLabel",
                      width=10).grid(row=i, column=0, sticky="w", pady=px(2))
            v = estilo.Vumetro(caja, ancho=px(150), alto=px(11))
            v.grid(row=i, column=1, sticky="ew", padx=px(6))
            self.vu[clave] = v
            var = tk.DoubleVar(value=float(config.get(ajuste, 0.8)) * 100)
            f = ttk.Scale(caja, from_=0, to=100, variable=var, style="Caja.Horizontal.TScale",
                          command=lambda val, a=ajuste: self._fader(a, val))
            f.grid(row=i, column=2, sticky="ew")
            f.configure(length=px(90))
            self.faders[ajuste] = var

        ttk.Separator(caja, orient="horizontal").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=px(6))

        ttk.Label(caja, text="AL AIRE", style="Caja.TLabel",
                  width=10).grid(row=4, column=0, sticky="w")
        marco_aire = ttk.Frame(caja, style="Caja.TFrame")
        marco_aire.grid(row=4, column=1, columnspan=2, sticky="ew", padx=px(6))
        self.vu["aire_i"] = estilo.Vumetro(marco_aire, ancho=px(230), alto=px(9))
        self.vu["aire_i"].pack(fill="x")
        self.vu["aire_d"] = estilo.Vumetro(marco_aire, ancho=px(230), alto=px(9))
        self.vu["aire_d"].pack(fill="x", pady=(px(2), 0))

        acciones = ttk.Frame(caja, style="Caja.TFrame")
        acciones.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(px(8), 0))
        self.btn_micro = ttk.Button(acciones, text="ABRIR MICROFONO",
                                    style="MicOff.TButton",
                                    command=self.alternar_microfono)
        self.btn_micro.pack(side="left")
        Consejo(self.btn_micro, "Abrir o cerrar el microfono al aire   (F1)")
        self.var_ducking = tk.BooleanVar(value=bool(config.get("ducking", True)))
        ttk.Checkbutton(acciones, text="Bajar musica al hablar",
                        variable=self.var_ducking, style="Caja.TCheckbutton",
                        command=self._cambio_ducking).pack(side="left", padx=px(10))

        # cortinas: sonidos cortos listos para lanzar encima de lo que suene
        ttk.Label(caja, text="CORTINAS   ·   clic para lanzar, clic derecho "
                              "para asignar o renombrar",
                  style="CajaSuave.TLabel").grid(row=6, column=0, columnspan=3,
                                                 sticky="w", pady=(px(8), px(2)))
        cort = ttk.Frame(caja, style="Caja.TFrame")
        cort.grid(row=7, column=0, columnspan=3, sticky="ew")
        self.botones_cortina = []
        self.cortinas = [None] * CORTINAS
        self.nombres_cortina = [""] * CORTINAS
        for i in range(CORTINAS):
            b = ttk.Button(cort, text=str(i + 1), style="Caja.TButton", width=9,
                           command=lambda n=i: self.disparar_cortina(n))
            b.pack(side="left", padx=(0, px(4)))
            b.bind("<Button-3>", lambda e, n=i: self.menu_cortina(n, e))
            self.botones_cortina.append(b)

    # -------------------------------------------------- oyentes

    def _panel_oyentes(self, padre):
        caja = ttk.Labelframe(padre, text=" OYENTES ", style="Caja.TLabelframe")
        caja.grid(row=1, column=0, sticky="ew", pady=(px(8), 0))
        caja.columnconfigure(2, weight=1)

        self.lbl_oyentes = ttk.Label(caja, text="0", style="Caja.TLabel",
                                     font=("Segoe UI Semibold", 24))
        self.lbl_oyentes.grid(row=0, column=0, rowspan=2, sticky="w",
                              padx=(0, px(8)))
        detalle = ttk.Frame(caja, style="Caja.TFrame")
        detalle.grid(row=0, column=1, rowspan=2, sticky="w", padx=(0, px(10)))
        self.lbl_oyentes_det = ttk.Label(detalle, text="escuchando ahora",
                                         style="CajaSuave.TLabel")
        self.lbl_oyentes_det.pack(anchor="w")
        self.lbl_oyentes_pico = ttk.Label(detalle, text="", style="CajaSuave.TLabel")
        self.lbl_oyentes_pico.pack(anchor="w")
        self.lbl_sonando_srv = ttk.Label(detalle, text="", style="CajaMono.TLabel")
        self.lbl_sonando_srv.pack(anchor="w")

        self.grafico = estilo.Grafico(caja, ancho=px(260), alto=px(62))
        self.grafico.grid(row=0, column=2, rowspan=2, sticky="ew")

    # -------------------------------------------------- estado

    def _barra_estado(self):
        barra = ttk.Frame(self, padding=(px(10), px(4)))
        barra.pack(side="bottom", fill="x")
        self.lbl_msg = ttk.Label(barra, text="Listo.", style="Suave.TLabel")
        self.lbl_msg.pack(side="left")
        self.lbl_grabando = ttk.Label(barra, text="", style="Suave.TLabel")
        self.lbl_grabando.pack(side="right")

    # ---------------------------------------------------------------- estado

    def mensaje(self, texto):
        try:
            self.lbl_msg.configure(text=texto)
        except tk.TclError:
            pass

    def _anotar(self, linea):
        self.registro.append("%s  %s" % (time.strftime("%H:%M:%S"), linea))
        del self.registro[:-500]

    def _emisor_cambio(self, estado, detalle):
        # llega desde otro hilo: solo dejamos la nota, la pinta el tic
        self._anotar("[%s] %s" % (estado, detalle or "-"))

    # ---------------------------------------------------------------- tics

    def _tic_rapido(self):
        """Vumetros y barra de la pista: 16 veces por segundo."""
        try:
            n = self.mezclador.niveles
            for clave, medidor in self.vu.items():
                medidor.poner(n.get(clave, -60.0))

            p = self.mezclador.pista_a
            if p.duracion > 0:
                frac = min(1.0, p.posicion / p.duracion)
                self.barra_pista["value"] = frac * 1000
                self.lbl_transcurrido.configure(
                    text=biblioteca.duracion_texto(p.posicion))
                self.lbl_restante.configure(
                    text="-" + biblioteca.duracion_texto(p.restante))
        except tk.TclError:
            return
        self.after(60, self._tic_rapido)

    def _tic_lento(self):
        """Una vez por segundo: reloj al aire, encadenar pistas, oyentes."""
        try:
            e = self.emisor
            if e.al_aire:
                self.lbl_tiempo_aire.configure(text=reloj(e.tiempo_al_aire()))
                self.lbl_estado_aire.configure(text="AL AIRE",
                                               foreground=estilo.ROJO)
                self.btn_aire.configure(text="CORTAR", style="AlAire.TButton")
            elif e.estado == mod_emisor.CONECTANDO:
                self.lbl_estado_aire.configure(text="conectando...",
                                               foreground=estilo.AMARILLO)
            elif e.estado == mod_emisor.ERROR:
                self.lbl_estado_aire.configure(text=e.detalle[:40] or "error",
                                               foreground=estilo.ROJO)
                self.btn_aire.configure(text="SALIR AL AIRE", style="Salir.TButton")
            else:
                self.lbl_tiempo_aire.configure(text="0:00:00")
                self.lbl_estado_aire.configure(text="fuera del aire",
                                               foreground=estilo.TEXTO_SUAVE)
                self.btn_aire.configure(text="SALIR AL AIRE", style="Salir.TButton")

            self._pintar_grabacion()
            self._encadenar()
            self._pintar_oyentes()
        except tk.TclError:
            return
        self.after(1000, self._tic_lento)

    def _encadenar(self):
        """Cuando una pista termina, entra la siguiente de la lista."""
        p = self.mezclador.pista_a
        if self.auto_siguiente and p.termino and self.lista.pistas:
            p.termino = False
            self.siguiente_pista()

    def _pintar_oyentes(self):
        est = self.vigilante.ultimo
        if not est:
            return
        if est["error"]:
            self.lbl_oyentes_det.configure(text="sin datos del servidor")
            return
        self.lbl_oyentes.configure(text=str(est["oyentes"]))
        self.lbl_oyentes_det.configure(text="escuchando ahora")
        self.lbl_oyentes_pico.configure(
            text="pico %d  ·  tope del plan %d" % (est["pico"], est["maximo"]))
        self.lbl_sonando_srv.configure(text=est["titulo"][:60])
        datos = [c for _, c in self.historial.ultimos(120)]
        self.grafico.pintar(datos[-160:])

    # ---------------------------------------------------------------- aire

    def alternar_aire(self):
        if self.emisor.al_aire or self.emisor.estado == mod_emisor.CONECTANDO:
            if not messagebox.askyesno(
                    "Cortar la transmision",
                    "Se va a cortar la senal en vivo.\n\n"
                    "Los oyentes volveran a la programacion automatica.\n\n"
                    "Seguro?", parent=self):
                return
            self.emisor.detener()
            self.mezclador.detener()
            self.mensaje("Fuera del aire.")
            return

        if not config.configurado():
            messagebox.showwarning(
                "Falta configurar",
                "Primero hay que poner los datos del servidor.\n\n"
                "Menu Emisora > Configuracion.", parent=self)
            self.abrir_configuracion()
            return

        self.mezclador.arrancar()
        if self.mezclador.error:
            self._anotar(self.mezclador.error)
            self.mensaje(self.mezclador.error)
        if self.emisor.arrancar():
            self.mensaje("Conectando con el servidor...")
        else:
            self.mensaje(self.emisor.detalle)

    def _pintar_grabacion(self):
        if self.grabador.grabando:
            self.btn_rec.configure(text="%s  %s" % (ICO_REC,
                                                    reloj(self.grabador.duracion())),
                                   style="RecOn.TButton")
            nombre = Path(self.grabador.archivo).name if self.grabador.archivo else ""
            self.lbl_grabando.configure(text="grabando: %s" % nombre)
        else:
            self.btn_rec.configure(text="%s  Grabar" % ICO_REC, style="Rec.TButton")
            self.lbl_grabando.configure(text="")

    def alternar_grabacion(self):
        """El boton de grabar. No tiene nada que ver con estar al aire."""
        if self.grabador.grabando:
            archivo = self.grabador.detener()
            self._pintar_grabacion()
            if archivo:
                self.mensaje("Grabacion guardada: %s" % Path(archivo).name)
            return
        if not self.mezclador.corriendo:
            self.mezclador.arrancar()
        if self.grabador.iniciar(self.var_titulo.get().strip()):
            self._pintar_grabacion()
            self.mensaje("Grabando. Se guarda en la carpeta de grabaciones.")
        else:
            self.mensaje(self.grabador.detalle or "No se pudo grabar.")

    def alternar_microfono(self):
        if not self.mezclador.corriendo:
            self.mezclador.arrancar()
        if not self.mezclador.micro.abierto:
            messagebox.showwarning(
                "Microfono",
                "No se pudo abrir el microfono.\n\n%s\n\n"
                "Revisa cual esta elegido en Configuracion."
                % (self.mezclador.micro.error or "-"), parent=self)
            return
        self.mezclador.micro_abierto = not self.mezclador.micro_abierto
        if self.mezclador.micro_abierto:
            self.btn_micro.configure(text="MICROFONO ABIERTO", style="MicOn.TButton")
            self.mensaje("Microfono abierto.")
        else:
            self.btn_micro.configure(text="ABRIR MICROFONO", style="MicOff.TButton")
            self.mensaje("Microfono cerrado.")

    def poner_titulo(self):
        titulo = self.var_titulo.get().strip()
        if not titulo:
            return
        ok, detalle = servidor.actualizar_titulo(titulo)
        self.mensaje("Titulo al aire: %s" % titulo if ok
                     else "No se pudo poner el titulo (%s)" % detalle)
        self._anotar("titulo -> %s (%s)" % (titulo, detalle))

    # ---------------------------------------------------------------- musica

    def play_pausa(self):
        p = self.mezclador.pista_a
        if p.sonando:
            p.pausar()
            self.btn_play.configure(text=ICO_PLAY)
            self.mensaje("Musica en pausa.")
            return
        if not p.ruta:
            self.siguiente_pista()
            return
        if not self.mezclador.corriendo:
            self.mezclador.arrancar()
        p.reproducir()
        self.btn_play.configure(text=ICO_PAUSA)

    def siguiente_pista(self):
        pista = self.lista.siguiente()
        if not pista:
            self.mensaje("La lista se acabo.")
            return
        self._poner_pista(pista)

    def _poner_pista(self, pista):
        if not self.mezclador.corriendo:
            self.mezclador.arrancar()
        p = self.mezclador.pista_a
        p.detener()
        if not os.path.exists(pista["ruta"]):
            self.mensaje("No se encuentra: %s" % os.path.basename(pista["ruta"]))
            self._anotar("archivo perdido: %s" % pista["ruta"])
            return
        p.cargar(pista["ruta"], biblioteca.etiqueta(pista),
                 float(pista.get("duracion", 0) or 0))
        p.reproducir(fundido_ms=300)
        self.btn_play.configure(text=ICO_PAUSA)
        self.lbl_pista.configure(text=pista.get("titulo", "")[:42] or "-")
        self.lbl_artista.configure(text=pista.get("artista", ""))
        self._marcar_sonando()
        # avisar al servidor que cambio la cancion
        etiqueta = biblioteca.etiqueta(pista)
        if etiqueta and etiqueta != self.ultimo_titulo_enviado and self.emisor.al_aire:
            self.ultimo_titulo_enviado = etiqueta
            threading.Thread(target=servidor.actualizar_titulo,
                             args=(etiqueta,), daemon=True).start()

    def parar_musica(self):
        self.mezclador.pista_a.detener(fundido_ms=400)
        self.btn_play.configure(text=ICO_PLAY)
        self.mensaje("Musica detenida.")

    def disparar_cortina(self, n):
        ruta = self.cortinas[n]
        if not ruta:
            self.asignar_cortina(n)
            return
        if not self.mezclador.corriendo:
            self.mezclador.arrancar()
        self.mezclador.disparar_efecto(ruta, self._texto_cortina(n))

    def _texto_cortina(self, n):
        """Lo que se lee en el boton: el nombre puesto, o el del archivo."""
        if self.nombres_cortina[n]:
            return self.nombres_cortina[n]
        if self.cortinas[n]:
            return Path(self.cortinas[n]).stem[:12]
        return str(n + 1)

    def _pintar_cortina(self, n):
        b = self.botones_cortina[n]
        b.configure(text=self._texto_cortina(n))
        ruta = self.cortinas[n]
        Consejo(b, ("%s\nArchivo: %s" % (self._texto_cortina(n), Path(ruta).name))
                if ruta else "Sin asignar. Clic derecho para elegir un audio.")

    def menu_cortina(self, n, evento):
        """Clic derecho sobre una cortina."""
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Asignar un audio...",
                      command=lambda: self.asignar_cortina(n))
        m.add_command(label="Cambiar el nombre...",
                      command=lambda: self.renombrar_cortina(n))
        if self.cortinas[n]:
            m.add_separator()
            m.add_command(label="Quitar", command=lambda: self.quitar_cortina(n))
        try:
            m.tk_popup(evento.x_root, evento.y_root)
        finally:
            m.grab_release()

    def asignar_cortina(self, n):
        ruta = filedialog.askopenfilename(
            title="Elegir el audio de la cortina %d" % (n + 1), parent=self,
            filetypes=[("Audio", EXTS), ("Todos", "*.*")])
        if not ruta:
            return
        self.cortinas[n] = ruta
        if not self.nombres_cortina[n]:          # nombre de partida, editable
            self.nombres_cortina[n] = Path(ruta).stem[:12]
        self._pintar_cortina(n)
        self._guardar_cortinas()
        self.mensaje("Cortina %d: %s" % (n + 1, self._texto_cortina(n)))

    def renombrar_cortina(self, n):
        nuevo = simpledialog.askstring(
            "Nombre de la cortina",
            "Como quieres que se lea el boton %d?" % (n + 1),
            initialvalue=self.nombres_cortina[n] or str(n + 1), parent=self)
        if nuevo is None:
            return
        self.nombres_cortina[n] = nuevo.strip()[:14]
        self._pintar_cortina(n)
        self._guardar_cortinas()
        self.mensaje("Cortina %d: %s" % (n + 1, self._texto_cortina(n)))

    def quitar_cortina(self, n):
        self.cortinas[n] = None
        self.nombres_cortina[n] = ""
        self._pintar_cortina(n)
        self._guardar_cortinas()

    def _guardar_cortinas(self):
        try:
            config.guardar({"cortinas": self.cortinas,
                            "cortinas_nombres": self.nombres_cortina})
        except Exception:
            pass

    # ---------------------------------------------------------------- lista

    def agregar_archivos(self):
        rutas = filedialog.askopenfilenames(
            title="Agregar audios a la lista", parent=self,
            filetypes=[("Audio", EXTS), ("Todos", "*.*")])
        if not rutas:
            return
        self.mensaje("Leyendo %d archivo(s)..." % len(rutas))
        self.update_idletasks()
        for r in rutas:
            self.lista.agregar(biblioteca.sondear(r))
        self._pintar_lista()
        self.mensaje("Agregados %d." % len(rutas))

    def agregar_carpeta(self):
        carpeta = filedialog.askdirectory(title="Carpeta de musica", parent=self)
        if not carpeta:
            return
        config.guardar({"carpeta_musica": carpeta})
        self.biblio = biblioteca.Biblioteca(carpeta)
        self._explorar_en_hilo()

    def _explorar_en_hilo(self):
        if self._explorando:
            return
        self._explorando = True

        def avanzar(i, total, nombre):
            self.after(0, lambda: self.mensaje(
                "Leyendo la carpeta... %d de %d  (%s)" % (i, total, nombre[:30])))

        def trabajo():
            try:
                pistas = self.biblio.explorar(al_avanzar=avanzar)
            except Exception as e:
                pistas = []
                self.after(0, lambda: self.mensaje("Error leyendo la carpeta: %s" % e))
            self.after(0, lambda: self._carpeta_lista(pistas))

        threading.Thread(target=trabajo, daemon=True).start()

    def _carpeta_lista(self, pistas):
        self._explorando = False
        if not pistas:
            self.mensaje("No se encontro audio en esa carpeta.")
            return
        self.lista.agregar_varias(pistas)
        self._pintar_lista()
        self.mensaje("Agregadas %d pistas de la carpeta." % len(pistas))

    def _pintar_lista(self):
        self.tabla.delete(*self.tabla.get_children())
        filtro = self.var_busca.get().strip().lower()
        for i, p in enumerate(self.lista.pistas):
            if filtro:
                heno = ("%s %s" % (p.get("titulo", ""), p.get("artista", ""))).lower()
                if filtro not in heno:
                    continue
            self.tabla.insert("", "end", iid=str(i), values=(
                i + 1, p.get("titulo", "")[:60], p.get("artista", "")[:30],
                biblioteca.duracion_texto(p.get("duracion", 0))))
        total = self.lista.duracion_total
        self.lbl_lista.configure(
            text="%d pistas  ·  %s en total" % (len(self.lista.pistas),
                                                biblioteca.duracion_texto(total)))
        self._marcar_sonando()

    def _marcar_sonando(self):
        for iid in self.tabla.get_children():
            self.tabla.item(iid, tags=())
        i = self.lista.actual
        if i >= 0 and self.tabla.exists(str(i)):
            self.tabla.item(str(i), tags=("sonando",))
            self.tabla.see(str(i))

    def _filtrar(self):
        self._pintar_lista()

    def _doble_clic_lista(self, ev):
        sel = self.tabla.selection()
        if not sel:
            return
        i = int(sel[0])
        pista = self.lista.ir_a(i)
        if pista:
            self._poner_pista(pista)

    def quitar_seleccion(self):
        indices = sorted((int(i) for i in self.tabla.selection()), reverse=True)
        for i in indices:
            self.lista.quitar(i)
        self._pintar_lista()

    def mover_seleccion(self, paso):
        sel = self.tabla.selection()
        if len(sel) != 1:
            return
        i = int(sel[0])
        j = i + paso
        if 0 <= j < len(self.lista.pistas):
            self.lista.mover(i, j)
            self._pintar_lista()
            self.tabla.selection_set(str(j))

    def vaciar_lista(self):
        if self.lista.pistas and not messagebox.askyesno(
                "Vaciar", "Quitar todas las pistas de la lista?", parent=self):
            return
        self.lista.limpiar()
        self._pintar_lista()

    def _aplicar_modo_lista(self):
        self.lista.repetir = self.var_repetir.get()
        self.lista.mezclar = self.var_mezclar.get()

    def guardar_lista(self):
        ruta = filedialog.asksaveasfilename(
            title="Guardar lista", parent=self, defaultextension=".lista",
            filetypes=[("Lista de la emisora", "*.lista"), ("M3U", "*.m3u")])
        if not ruta:
            return
        try:
            if ruta.lower().endswith(".m3u"):
                self.lista.exportar_m3u(ruta)
            else:
                self.lista.guardar(ruta)
            self.mensaje("Lista guardada: %s" % os.path.basename(ruta))
        except Exception as e:
            messagebox.showerror("Guardar lista", str(e), parent=self)

    def abrir_lista(self):
        ruta = filedialog.askopenfilename(
            title="Abrir lista", parent=self,
            filetypes=[("Listas", "*.lista *.m3u"), ("Todos", "*.*")])
        if not ruta:
            return
        try:
            if ruta.lower().endswith(".m3u"):
                self.lista.limpiar()
                self.lista.importar_m3u(ruta)
            else:
                self.lista.abrir(ruta)
            self.var_repetir.set(self.lista.repetir)
            self.var_mezclar.set(self.lista.mezclar)
            self._pintar_lista()
            self.mensaje("Lista abierta: %d pistas" % len(self.lista.pistas))
        except Exception as e:
            messagebox.showerror("Abrir lista", str(e), parent=self)

    # ---------------------------------------------------------------- faders

    def _fader(self, ajuste, valor):
        v = float(valor) / 100.0
        config.guardar({ajuste: v})
        self.mezclador.aplicar_ajustes()

    def _cambio_ducking(self):
        config.guardar({"ducking": self.var_ducking.get()})
        self.mezclador.aplicar_ajustes()

    # ---------------------------------------------------------------- varios

    def _cargar_ajustes_en_pantalla(self):
        self.lbl_emisora.configure(text=config.get("nombre_emisora"))
        host = config.get("host")
        self.lbl_servidor.configure(
            text=("%s:%s%s" % (host, config.get("puerto"), config.get("mount")))
            if host else "sin servidor configurado")
        guardadas = config.cargar().get("cortinas") or []
        nombres = config.cargar().get("cortinas_nombres") or []
        for i in range(CORTINAS):
            r = guardadas[i] if i < len(guardadas) else None
            if r and os.path.exists(r):
                self.cortinas[i] = r
            self.nombres_cortina[i] = (nombres[i] if i < len(nombres) else "") or ""
            self._pintar_cortina(i)
        carpeta = config.get("carpeta_musica")
        if carpeta and os.path.isdir(carpeta):
            self.biblio = biblioteca.Biblioteca(carpeta)

    def _primer_arranque(self):
        if not config.configurado():
            self.mensaje("Falta configurar el servidor: menu Emisora > Configuracion.")

    def abrir_configuracion(self):
        DialogoConfig(self)
        self._cargar_ajustes_en_pantalla()

    def probar_servidor(self):
        est = servidor.estado()
        if est["error"]:
            messagebox.showerror("Servidor", "No respondio:\n\n%s" % est["error"],
                                 parent=self)
            return
        messagebox.showinfo(
            "Servidor",
            "Emisora: %s\nAl aire: %s\nSonando: %s\n\n"
            "Oyentes: %d (pico %d, tope %d)\nCalidad: %d kbps"
            % (est["emisora"], "si" if est["en_linea"] else "no", est["titulo"],
               est["oyentes"], est["pico"], est["maximo"], est["bitrate"]),
            parent=self)

    def abrir_web(self):
        host = config.get("host")
        if host:
            webbrowser.open("http://%s:%s/index.html"
                            % (host, config.get("puerto_publico")))

    def abrir_grabaciones(self):
        config.asegurar_carpetas()
        try:
            os.startfile(str(config.CARPETA_GRABA))
        except Exception as e:
            messagebox.showerror("Grabaciones", str(e), parent=self)

    def ver_registro(self):
        v = tk.Toplevel(self)
        v.title("Registro tecnico")
        v.geometry("%dx%d" % (px(760), px(420)))
        v.configure(bg=estilo.FONDO)
        t = tk.Text(v, wrap="none", font=estilo.FUENTE_MONO)
        t.pack(fill="both", expand=True, padx=px(8), pady=px(8))
        t.insert("1.0", "\n".join(self.registro) or "(sin novedades)")
        t.configure(state="disabled")

    def ver_estadisticas(self):
        v = tk.Toplevel(self)
        v.title("Oyentes por dia")
        v.geometry("%dx%d" % (px(420), px(320)))
        v.configure(bg=estilo.FONDO)
        estilo.aplicar(v)
        ttk.Label(v, text="Ultimos 7 dias", style="Titulo.TLabel").pack(
            anchor="w", padx=px(10), pady=px(8))
        filas = self.historial.resumen_dia(7)
        if not filas:
            ttk.Label(v, text="Todavia no hay historial.",
                      style="Suave.TLabel").pack(padx=px(10))
            return
        tabla = ttk.Treeview(v, columns=("d", "p", "m"), show="headings", height=10)
        for c, txt in (("d", "DIA"), ("p", "PICO"), ("m", "PROMEDIO")):
            tabla.heading(c, text=txt)
            tabla.column(c, width=px(110), anchor="center")
        for f in filas:
            tabla.insert("", "end", values=f)
        tabla.pack(fill="both", expand=True, padx=px(10), pady=px(8))

    def ver_atajos(self):
        espacio = ESPACIO_TEXTOS.get(config.get("tecla_espacio", ESPACIO_MICRO),
                                     ESPACIO_TEXTOS[ESPACIO_MICRO])
        messagebox.showinfo(
            "Atajos",
            "Barra espaciadora .... %s\n"
            "F1 ................... abrir / cerrar el microfono\n"
            "F2 ................... empezar / parar la grabacion\n"
            "Ctrl + flecha der .... siguiente pista\n"
            "Doble clic en la lista  reproducir esa pista\n"
            "Clic derecho en una cortina  asignarla o renombrarla\n\n"
            "La barra espaciadora se elige en Configuracion > Audio.\n"
            "Mientras se escribe en un campo, los atajos no actuan."
            % espacio.lower(), parent=self)

    # ---------------------------------------------------------------- cierre

    def _al_cerrar(self):
        if self.emisor.al_aire:
            if not messagebox.askyesno(
                    "Salir",
                    "ESTAS AL AIRE.\n\nSi cierras, se corta la transmision.\n\n"
                    "Seguro que quieres salir?", parent=self):
                return
        if self.grabador.grabando:
            self.grabador.detener()
        try:
            self.vigilante.detener()
            self.emisor.detener()
            self.mezclador.detener()
        except Exception:
            pass
        procesos.cerrar_todos()
        self.destroy()


# ==================================================================== config

class DialogoConfig(tk.Toplevel):
    """Ventana de ajustes: servidor, audio y carpetas."""

    def __init__(self, padre):
        super().__init__(padre)
        self.padre = padre
        self.title("Configuracion")
        self.configure(bg=estilo.FONDO)
        self.resizable(False, False)
        self.transient(padre)
        self.grab_set()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=px(10), pady=px(10))
        self.vars = {}
        self._pestana_servidor(nb)
        self._pestana_audio(nb)
        self._pestana_microfono(nb)
        self._pestana_carpetas(nb)

        pie = ttk.Frame(self, padding=(px(10), 0, px(10), px(10)))
        pie.pack(fill="x")
        ttk.Button(pie, text="Guardar", style="Accion.TButton",
                   command=self.guardar).pack(side="right")
        ttk.Button(pie, text="Cancelar", command=self.destroy).pack(
            side="right", padx=px(6))
        ttk.Button(pie, text="Probar conexion",
                   command=self.probar).pack(side="left")

        self.update_idletasks()
        x = padre.winfo_rootx() + (padre.winfo_width() - self.winfo_width()) // 2
        y = padre.winfo_rooty() + px(60)
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))
        self.wait_window()

    def _campo(self, padre, fila, etiqueta, clave, ancho=34, oculto=False):
        ttk.Label(padre, text=etiqueta).grid(row=fila, column=0, sticky="w",
                                             pady=px(3), padx=(0, px(8)))
        var = tk.StringVar(value=str(config.get(clave, "")))
        e = ttk.Entry(padre, textvariable=var, width=ancho,
                      show="*" if oculto else "")
        e.grid(row=fila, column=1, sticky="ew", pady=px(3))
        self.vars[clave] = var
        return var

    def _pestana_servidor(self, nb):
        f = ttk.Frame(nb, padding=px(12))
        nb.add(f, text="Servidor")
        f.columnconfigure(1, weight=1)

        self._campo(f, 0, "Servidor (host):", "host")
        ttk.Label(f, text="solo el nombre: cast1.asurahosting.com  "
                          "(sin http:// y sin la ruta de la pagina)",
                  style="Suave.TLabel").grid(row=1, column=1, sticky="w")

        ttk.Label(f, text="Protocolo:").grid(row=2, column=0, sticky="w", pady=px(3))
        self.var_proto = tk.StringVar(
            value=PROTOCOLOS.get(config.get("protocolo"), PROTO_V1))
        ttk.Combobox(f, textvariable=self.var_proto, state="readonly", width=32,
                     values=(PROTO_V1, PROTO_ICE)).grid(row=2, column=1, sticky="w",
                                                        pady=px(3))

        self._campo(f, 3, "Puerto:", "puerto", 10)
        self.lbl_puerto = ttk.Label(f, text="", style="Suave.TLabel")
        self.lbl_puerto.grid(row=4, column=1, sticky="w")
        self.vars["puerto"].trace_add("write", lambda *a: self._pista_puerto())
        self.var_proto.trace_add("write", lambda *a: self._pista_puerto())
        self._pista_puerto()

        self._campo(f, 5, "Usuario DJ:", "usuario", 20)
        ttk.Label(f, text="Clave DJ:").grid(row=6, column=0, sticky="w", pady=px(3))
        self.var_clave = tk.StringVar(value=config.clave("clave_fuente"))
        ttk.Entry(f, textvariable=self.var_clave, show="*", width=34).grid(
            row=6, column=1, sticky="ew", pady=px(3))
        ttk.Label(f, text="los de una Cuenta de DJ del panel, no los del panel",
                  style="Suave.TLabel").grid(row=7, column=1, sticky="w")

        self._campo(f, 8, "Punto de montaje:", "mount", 14)
        ttk.Label(f, text="solo lo usa Icecast; con SHOUTcast v1 se ignora",
                  style="Suave.TLabel").grid(row=9, column=1, sticky="w")

        self._campo(f, 10, "Puerto publico (oyentes):", "puerto_publico", 10)

        ttk.Separator(f, orient="horizontal").grid(row=11, column=0, columnspan=2,
                                                   sticky="ew", pady=px(8))
        self._campo(f, 12, "Nombre de la emisora:", "nombre_emisora")
        self._campo(f, 13, "Genero:", "genero", 20)
        self._campo(f, 14, "Sitio web:", "url_emisora")

        ttk.Separator(f, orient="horizontal").grid(row=15, column=0, columnspan=2,
                                                   sticky="ew", pady=px(8))
        ttk.Label(f, text="Calidad:").grid(row=16, column=0, sticky="w")
        cal = ttk.Frame(f)
        cal.grid(row=16, column=1, sticky="w")
        self.var_bitrate = tk.StringVar(value=str(config.get("bitrate")))
        ttk.Combobox(cal, textvariable=self.var_bitrate, width=6, state="readonly",
                     values=("64", "96", "128", "192")).pack(side="left")
        ttk.Label(cal, text=" kbps   formato ").pack(side="left")
        self.var_codec = tk.StringVar(value=config.get("codec"))
        ttk.Combobox(cal, textvariable=self.var_codec, width=6, state="readonly",
                     values=("mp3", "aac")).pack(side="left")

        ttk.Label(f, text="El plan contratado admite 128 kbps y 120 oyentes.",
                  style="Suave.TLabel").grid(row=17, column=0, columnspan=2,
                                             sticky="w", pady=(px(6), 0))

    def _pista_puerto(self):
        """Explica en vivo a que puerto se conectara de verdad."""
        try:
            puerto = int(self.vars["puerto"].get().strip())
        except (ValueError, KeyError):
            self.lbl_puerto.configure(text="el mismo que pone el panel")
            return
        if self.var_proto.get() == PROTO_V1:
            texto = ("el mismo que pone el panel (y que usan BUTT o RadioBOSS); "
                     "por dentro se conecta al %d" % (puerto + 1))
        else:
            texto = "se conecta directamente al %d" % puerto
        self.lbl_puerto.configure(text=texto)

    def _pestana_audio(self, nb):
        f = ttk.Frame(nb, padding=px(12))
        nb.add(f, text="Audio")
        f.columnconfigure(1, weight=1)

        entradas = [n for _, n, _, _ in audio.listar(entrada=True)]
        salidas = [n for _, n, _, _ in audio.listar(entrada=False)]

        ttk.Label(f, text="Microfono:").grid(row=0, column=0, sticky="w", pady=px(4))
        self.var_micro = tk.StringVar(value=config.get("microfono"))
        ttk.Combobox(f, textvariable=self.var_micro, values=entradas,
                     width=40, state="readonly").grid(row=0, column=1, sticky="ew")

        ttk.Label(f, text="Monitor (auriculares):").grid(row=1, column=0, sticky="w",
                                                         pady=px(4))
        self.var_monitor = tk.StringVar(value=config.get("monitor"))
        ttk.Combobox(f, textvariable=self.var_monitor, values=salidas,
                     width=40, state="readonly").grid(row=1, column=1, sticky="ew")

        self.var_mon_act = tk.BooleanVar(value=bool(config.get("monitor_activo")))
        ttk.Checkbutton(f, text="Escuchar por los auriculares lo que sale al aire",
                        variable=self.var_mon_act).grid(row=2, column=0, columnspan=2,
                                                        sticky="w", pady=px(6))

        fila_prueba = ttk.Frame(f)
        fila_prueba.grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Button(fila_prueba, text="Probar los auriculares",
                   command=self.probar_monitor).pack(side="left")
        self.lbl_monitor = ttk.Label(fila_prueba, text="", style="Suave.TLabel")
        self.lbl_monitor.pack(side="left", padx=px(8))
        ttk.Label(f, text="Los auriculares Bluetooth funcionan: Windows convierte "
                          "el muestreo por su cuenta.",
                  style="Suave.TLabel").grid(row=4, column=0, columnspan=2,
                                             sticky="w", pady=(px(2), 0))

        ttk.Separator(f, orient="horizontal").grid(row=5, column=0, columnspan=2,
                                                   sticky="ew", pady=px(8))
        self.var_duck = tk.BooleanVar(value=bool(config.get("ducking")))
        ttk.Checkbutton(f, text="Bajar la musica automaticamente al hablar",
                        variable=self.var_duck).grid(row=6, column=0, columnspan=2,
                                                     sticky="w")
        ttk.Label(f, text="Cuanto baja:").grid(row=7, column=0, sticky="w", pady=px(4))
        self.var_duck_niv = tk.DoubleVar(value=float(config.get("ducking_nivel")) * 100)
        ttk.Scale(f, from_=5, to=80, variable=self.var_duck_niv,
                  length=px(200)).grid(row=7, column=1, sticky="w")

        ttk.Separator(f, orient="horizontal").grid(row=8, column=0, columnspan=2,
                                                   sticky="ew", pady=px(8))
        ttk.Label(f, text="Barra espaciadora:").grid(row=9, column=0, sticky="w",
                                                     pady=px(4))
        self.var_espacio = tk.StringVar(
            value=ESPACIO_TEXTOS.get(config.get("tecla_espacio", ESPACIO_MICRO),
                                     ESPACIO_TEXTOS[ESPACIO_MICRO]))
        ttk.Combobox(f, textvariable=self.var_espacio, state="readonly", width=30,
                     values=[ESPACIO_TEXTOS[k] for k in
                             (ESPACIO_MICRO, ESPACIO_PLAY, ESPACIO_NADA)]).grid(
            row=9, column=1, sticky="w")
        ttk.Label(f, text="F1 abre el microfono y F2 graba, elijas lo que elijas. "
                          "Mientras se escribe en un campo, la barra no hace nada.",
                  style="Suave.TLabel").grid(row=10, column=0, columnspan=2,
                                             sticky="w")

        ttk.Separator(f, orient="horizontal").grid(row=11, column=0, columnspan=2,
                                                   sticky="ew", pady=px(8))
        ttk.Label(f, text="Cambiar de microfono o de auriculares exige volver a "
                          "salir al aire.",
                  style="Suave.TLabel").grid(row=12, column=0, columnspan=2,
                                             sticky="w")

    def probar_monitor(self):
        """Un pitido por los auriculares elegidos, sin tocar la emision."""
        self._recoger()
        self.lbl_monitor.configure(text="sonando...")
        self.update_idletasks()
        ok, detalle = self.padre.mezclador.probar_monitor()
        self.lbl_monitor.configure(text=("se oyo bien" if ok else "no se pudo"))
        if not ok:
            messagebox.showerror(
                "Auriculares",
                "%s\n\nSi son Bluetooth, comprueba que esten conectados y "
                "elegidos arriba." % detalle, parent=self)

    def _pestana_microfono(self, nb):
        """Ecualizador de la voz: ajustes de fabrica y uno a su gusto."""
        f = ttk.Frame(nb, padding=px(12))
        nb.add(f, text="Microfono")
        f.columnconfigure(1, weight=1)

        self.var_eq_activo = tk.BooleanVar(value=bool(config.get("eq_activo", True)))
        ttk.Checkbutton(f, text="Ecualizador de voz encendido",
                        variable=self.var_eq_activo,
                        command=self._refrescar_eq).grid(
            row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(f, text="Ajuste:").grid(row=1, column=0, sticky="w", pady=px(6))
        self.var_eq_preset = tk.StringVar(value=config.get("eq_preset", "Plano"))
        cb = ttk.Combobox(f, textvariable=self.var_eq_preset, state="readonly",
                          width=22, values=mod_eq.ORDEN_PRESETS)
        cb.grid(row=1, column=1, sticky="w", pady=px(6))
        cb.bind("<<ComboboxSelected>>", lambda e: self._cargar_preset_eq())

        valores = dict(mod_eq.PRESETS["Plano"])
        valores.update(config.get("eq_valores") or {})
        self.vars_eq, self.lbls_eq = {}, {}
        fila = 2
        for clave, etiqueta, frec, _, _ in mod_eq.BANDAS:
            hz = "%d Hz" % frec if frec < 1000 else "%.0f kHz" % (frec / 1000.0)
            ttk.Label(f, text="%s  (%s)" % (etiqueta, hz)).grid(
                row=fila, column=0, sticky="w", pady=px(2))
            var = tk.DoubleVar(value=float(valores.get(clave, 0)))
            ttk.Scale(f, from_=-mod_eq.LIMITE_DB, to=mod_eq.LIMITE_DB,
                      variable=var, length=px(210),
                      command=lambda v, c=clave: self._mover_eq(c)).grid(
                row=fila, column=1, sticky="w")
            lbl = ttk.Label(f, text="", width=6, style="Suave.TLabel")
            lbl.grid(row=fila, column=2, sticky="w")
            self.vars_eq[clave] = var
            self.lbls_eq[clave] = lbl
            fila += 1

        self.var_corte = tk.BooleanVar(value=bool(valores.get("corte_grave", True)))
        ttk.Checkbutton(f, text="Quitar el retumbe grave (golpes de mesa, aire)",
                        variable=self.var_corte,
                        command=self._refrescar_eq).grid(
            row=fila, column=0, columnspan=3, sticky="w", pady=px(6))
        fila += 1

        self.curva = estilo.CurvaEQ(f, ancho=px(320), alto=px(96))
        self.curva.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=px(4))
        fila += 1

        acciones = ttk.Frame(f)
        acciones.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=px(6))
        ttk.Button(acciones, text="Guardar como 'A mi gusto'",
                   command=self._guardar_mi_gusto).pack(side="left")
        ttk.Button(acciones, text="Escuchar el microfono",
                   command=self._escuchar_micro).pack(side="left", padx=px(6))
        fila += 1

        ttk.Label(f, text="Consejo: enciende el monitor, abre el microfono y mueve las bandas mientras hablas.",
                  style="Suave.TLabel", justify="left").grid(
            row=fila, column=0, columnspan=3, sticky="w")
        self._refrescar_eq()

    def _valores_eq(self):
        v = {c: round(float(var.get()), 1) for c, var in self.vars_eq.items()}
        v["corte_grave"] = bool(self.var_corte.get())
        return v

    def _mover_eq(self, clave):
        """Al mover una banda deja de ser un ajuste de fabrica."""
        if self.var_eq_preset.get() != "A mi gusto":
            self.var_eq_preset.set("A mi gusto")
        self._refrescar_eq()

    def _cargar_preset_eq(self):
        nombre = self.var_eq_preset.get()
        base = (config.get("eq_mi_gusto") if nombre == "A mi gusto"
                else mod_eq.PRESETS.get(nombre)) or {}
        for clave, var in self.vars_eq.items():
            var.set(float(base.get(clave, 0)))
        self.var_corte.set(bool(base.get("corte_grave", True)))
        self._refrescar_eq()

    def _refrescar_eq(self):
        """Reetiqueta, redibuja la curva y lo aplica en vivo al microfono."""
        valores = self._valores_eq()
        for clave, lbl in self.lbls_eq.items():
            lbl.configure(text="%+.0f dB" % valores.get(clave, 0))
        try:
            self.curva.pintar(mod_eq.respuesta(
                valores, int(config.get("muestreo", 48000))))
        except Exception:
            pass
        config.guardar({"eq_activo": self.var_eq_activo.get(),
                        "eq_preset": self.var_eq_preset.get(),
                        "eq_valores": valores})
        self.padre.mezclador.aplicar_ajustes()

    def _guardar_mi_gusto(self):
        config.guardar({"eq_mi_gusto": self._valores_eq(),
                        "eq_preset": "A mi gusto"})
        self.var_eq_preset.set("A mi gusto")
        self._refrescar_eq()
        messagebox.showinfo("Microfono",
                            "Guardado como 'A mi gusto'.", parent=self)

    def _escuchar_micro(self):
        """Abre el microfono con el monitor para oirse mientras se ajusta."""
        m = self.padre.mezclador
        if not m.corriendo:
            m.arrancar()
        if not m.micro.abierto:
            messagebox.showwarning("Microfono", m.micro.error or
                                   "No se pudo abrir el microfono.", parent=self)
            return
        m.micro_abierto = True
        self.padre.btn_micro.configure(text="MICROFONO ABIERTO", style="MicOn.TButton")
        messagebox.showinfo("Microfono",
                            "Microfono abierto. Habla y mueve las bandas.",
                            parent=self)

    def _pestana_carpetas(self, nb):
        f = ttk.Frame(nb, padding=px(12))
        nb.add(f, text="Carpetas")
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Carpeta de musica:").grid(row=0, column=0, sticky="w",
                                                     pady=px(4))
        self.var_carpeta = tk.StringVar(value=config.get("carpeta_musica"))
        ttk.Entry(f, textvariable=self.var_carpeta, width=38).grid(row=0, column=1,
                                                                   sticky="ew")
        ttk.Button(f, text="...", width=3,
                   command=lambda: self._elegir(self.var_carpeta)).grid(row=0, column=2)

        self.var_grabar = tk.BooleanVar(value=bool(config.get("grabar_al_aire")))
        ttk.Checkbutton(f, text="Grabar en el disco todo lo que salga al aire",
                        variable=self.var_grabar).grid(row=1, column=0, columnspan=3,
                                                       sticky="w", pady=px(8))
        ttk.Label(f, text="Se guarda en: %s" % config.CARPETA_GRABA,
                  style="Suave.TLabel").grid(row=2, column=0, columnspan=3, sticky="w")

        self.var_reconectar = tk.BooleanVar(value=bool(config.get("reconectar")))
        ttk.Checkbutton(f, text="Reconectar solo si se cae el internet",
                        variable=self.var_reconectar).grid(row=3, column=0,
                                                           columnspan=3, sticky="w",
                                                           pady=px(8))

    def _elegir(self, var):
        d = filedialog.askdirectory(parent=self)
        if d:
            var.set(d)

    def probar(self):
        self._recoger()
        self.config(cursor="watch")
        self.update_idletasks()
        ok, msg = mod_emisor.probar_conexion(
            config.get("host"), config.get("puerto"), config.get("usuario"),
            self.var_clave.get(), config.get("mount"),
            protocolo=config.get("protocolo"), segundos=4)
        self.config(cursor="")
        if ok:
            messagebox.showinfo("Prueba", msg, parent=self)
        else:
            messagebox.showerror(
                "Prueba",
                "No se pudo conectar:\n\n%s\n\n"
                "Si no aciertas con el puerto o el montaje, cierra la aplicacion y\n"
                "ejecuta   python prueba_conexion.py   que los busca solo."
                % msg, parent=self)

    def _recoger(self):
        datos = {}
        for clave, var in self.vars.items():
            valor = var.get().strip()
            if clave in ("puerto", "puerto_publico"):
                try:
                    valor = int(valor)
                except ValueError:
                    valor = config.get(clave)
            datos[clave] = valor
        # el host se limpia siempre: pegar la direccion de la pagina del panel
        # en vez del nombre del servidor es el error mas facil de cometer
        datos["host"] = mod_emisor.limpiar_host(datos.get("host", ""))
        datos["protocolo"] = ("shoutcast_v1" if self.var_proto.get() == PROTO_V1
                              else "icecast")
        datos["bitrate"] = int(self.var_bitrate.get())
        datos["codec"] = self.var_codec.get()
        datos["microfono"] = self.var_micro.get()
        datos["monitor"] = self.var_monitor.get()
        datos["monitor_activo"] = self.var_mon_act.get()
        inverso = {v: k for k, v in ESPACIO_TEXTOS.items()}
        datos["tecla_espacio"] = inverso.get(self.var_espacio.get(), ESPACIO_MICRO)
        datos["ducking"] = self.var_duck.get()
        datos["ducking_nivel"] = round(self.var_duck_niv.get() / 100.0, 2)
        datos["carpeta_musica"] = self.var_carpeta.get().strip()
        datos["grabar_al_aire"] = self.var_grabar.get()
        datos["reconectar"] = self.var_reconectar.get()
        config.guardar(datos)
        if self.var_clave.get():
            config.guardar_clave("clave_fuente", self.var_clave.get())

    def guardar(self):
        self._recoger()
        self.padre.mezclador.aplicar_ajustes()
        self.padre.mensaje("Configuracion guardada.")
        self.destroy()


# ==================================================================== arranque

def mostrar_error(texto):
    """Si algo revienta al arrancar, que no se cierre en silencio."""
    try:
        v = tk.Tk()
        v.title("Error al arrancar")
        v.geometry("760x420")
        t = tk.Text(v, wrap="word")
        t.pack(fill="both", expand=True)
        t.insert("1.0", texto)
        tk.Button(v, text="Copiar", command=lambda: (
            v.clipboard_clear(), v.clipboard_append(texto))).pack(pady=6)
        v.mainloop()
    except Exception:
        print(texto)


def main():
    try:
        app = App()
        app.mainloop()
    except Exception:
        detalle = traceback.format_exc()
        try:
            Path(__file__).with_name("error_arranque.log").write_text(
                detalle, encoding="utf-8")
        except Exception:
            pass
        mostrar_error(detalle)
    finally:
        procesos.cerrar_todos()


if __name__ == "__main__":
    main()
