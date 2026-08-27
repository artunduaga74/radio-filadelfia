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
import ventana_aire
from estilo import Consejo, px

TITULO = "Filadelfia Broadcaster"

# como se llaman los protocolos en pantalla
CORTINAS = 8              # cuantos botones tiene el soundpad
POR_FILA_SOUNDPAD = 4    # se reparten en filas de cuatro
ANCHO_SOUNDPAD = 13      # en caracteres: caben nombres mas largos

# Que hace la barra espaciadora (se elige en Configuracion > Audio)
ESPACIO_MICRO = "microfono"
ESPACIO_PLAY = "reproducir"
ESPACIO_NADA = "nada"
ESPACIO_TEXTOS = {
    ESPACIO_MICRO: "Abrir y cerrar el microfono",
    ESPACIO_PLAY: "Reproducir / pausa",
    ESPACIO_NADA: "Nada (desactivada)",
}

BLOQUES_TEXTO = {
    1024: "Normal (mas seguro)",
    512:  "Corto (recomendado)",
    256:  "Muy corto (exige mas)",
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

# Un salto de linea como constante: meterlo escapado dentro de las cadenas
# de un parche automatico se convierte en salto REAL y rompe el archivo.
# Ya paso el 2026-08-24 y volvio a pasar hoy.
SALTO = chr(10)


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
        self.logo = None
        self._preparar_icono()

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
        # titulo puesto a mano con "Poner"; mientras no este vacio,
        # el cambio de cancion no lo sobreescribe
        self.titulo_programa = ""
        self._explorando = False
        self._aviso_acople = False
        self._musica_en_pausa_por_micro = False

        self._construir_menu()
        self._construir()
        self._botones_sin_foco(self)
        self._cargar_ajustes_en_pantalla()

        self.vigilante.arrancar()
        self.protocol("WM_DELETE_WINDOW", self._al_cerrar)
        self.after(60, self._tic_rapido)
        self.after(1000, self._tic_lento)
        self.after(300, self._primer_arranque)

    def _preparar_icono(self):
        """
        El icono de la ventana y el de la barra de tareas.

        Windows agrupa las ventanas en la barra por una "identidad de
        aplicacion", y la nuestra era la de Python: por eso salia el icono de
        Python en vez del nuestro. Se arregla declarando una identidad propia
        ANTES de que aparezca la ventana.

        Ademas se prepara una segunda version con un punto rojo, que es la que
        se pone mientras se esta al aire: asi, con la aplicacion de fondo, se
        ve de un vistazo en la barra si la emisora esta saliendo.
        """
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "VozDeFiladelfia.Broadcaster")
        except Exception:
            pass

        carpeta = Path(__file__).resolve().parent
        png = carpeta / "icono.png"
        self.ico_normal = carpeta / "icono.ico"
        self.ico_aire = carpeta / "icono_aire.ico"
        try:
            if png.exists():
                from PIL import ImageTk, Image
                nuevo = (not self.ico_normal.exists()
                         or not self.ico_aire.exists()
                         or self.ico_normal.stat().st_mtime < png.stat().st_mtime)
                if nuevo:
                    imagen = estilo.generar_iconos(png, self.ico_normal,
                                                   self.ico_aire)
                else:
                    imagen = Image.open(png).convert("RGBA")
                lado_logo = px(34)
                chico = imagen.copy()
                chico.thumbnail((lado_logo, lado_logo), Image.LANCZOS)
                self.logo = ImageTk.PhotoImage(chico)
            if self.ico_normal.exists():
                # `default` lo aplica tambien a las ventanas que se abran luego
                self.iconbitmap(default=str(self.ico_normal))
        except Exception:
            self.logo = None          # sin icono se sigue trabajando igual
        self._icono_puesto = "normal"

    def _icono_segun_aire(self, al_aire):
        """
        Cambia el icono y el titulo de la ventana segun se este al aire.

        El titulo importa tanto como el icono: es lo que se lee al pasar el
        raton por la barra de tareas y en el conmutador de ventanas.
        """
        quiere = "aire" if al_aire else "normal"
        if quiere == getattr(self, "_icono_puesto", None):
            return
        self._icono_puesto = quiere
        ruta = self.ico_aire if al_aire else self.ico_normal
        try:
            if ruta and Path(ruta).exists():
                self.iconbitmap(default=str(ruta))
        except Exception:
            pass
        self.title(("* AL AIRE - " + TITULO) if al_aire else TITULO)

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
        m.add_command(label="Monitor de aire...", command=self.abrir_monitor_aire)
        m.add_separator()
        m.add_command(label="Registro tecnico", command=self.ver_registro)
        m.add_command(label="Estadisticas de oyentes", command=self.ver_estadisticas)
        barra.add_cascade(label="Ver", menu=m)

        m = tk.Menu(barra, tearoff=0)
        m.add_command(label="Editor de metadatos...",
                      command=self.abrir_metadatos)
        barra.add_cascade(label="Metadatos", menu=m)

        m = tk.Menu(barra, tearoff=0)
        m.add_command(label="Atajos de teclado", command=self.ver_atajos)
        barra.add_cascade(label="Ayuda", menu=m)

        self.config(menu=barra)

        # La barra espaciadora se decide en Configuracion (por defecto, el
        # microfono). F1 y F2 valen siempre, hagan lo que hagan los demas.
        self.bind("<space>", lambda e: self._atajo_espacio())
        # Y ademas hay que quitarsela a los botones: Tk se la manda al que
        # tenga el foco ANTES que a nosotros, asi que con el foco en el boton
        # del microfono la barra lo abria (el boton) y lo cerraba (el atajo)
        # en el mismo golpe. Reproducido y corregido el 2026-08-24.
        for clase in ("TButton", "TCheckbutton", "TRadiobutton"):
            self.bind_class(clase, "<space>", self._espacio_en_boton)
        self.bind("<F1>", lambda e: self._atajo(self.alternar_microfono))
        self.bind("<F2>", lambda e: self._atajo(self.alternar_grabacion))
        self.bind("<Control-Right>", lambda e: self._atajo(self.siguiente_pista))
        for n in range(config.MAX_MICROS):
            self.bind("<Control-Key-%d>" % (n + 1),
                      lambda e, i=n: self._atajo(lambda: self.alternar_microfono(i)))

    def _espacio_en_boton(self, evento):
        """
        La barra pulsada con el foco en un boton.

        En la ventana principal manda el atajo (y se corta ahi, para que el
        boton no se pulse tambien). En los dialogos se deja el comportamiento
        de siempre: la barra pulsa el boton que tenga el foco.
        """
        try:
            if evento.widget.winfo_toplevel() is not self:
                return None
        except tk.TclError:
            return None
        self._atajo_espacio()
        return "break"

    def _botones_sin_foco(self, padre):
        """
        Que ningun boton se quede el foco del teclado.

        Si un boton tiene el foco, Tk le manda la barra espaciadora A EL (lo
        pulsa) ADEMAS de a nuestro atajo: con el foco en el boton del
        microfono, la barra lo abria y lo cerraba en el mismo golpe, y parecia
        que el atajo no funcionaba. Reproducido y corregido el 2026-08-24.
        """
        for hijo in padre.winfo_children():
            if isinstance(hijo, (ttk.Button, ttk.Checkbutton, ttk.Radiobutton,
                                 ttk.Scale)):
                try:
                    hijo.configure(takefocus=False)
                except tk.TclError:
                    pass
            self._botones_sin_foco(hijo)

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
        caja.rowconfigure(3, weight=1)
        caja.columnconfigure(0, weight=1)

        marca = ttk.Frame(caja, style="Caja.TFrame")
        marca.grid(row=0, column=0, sticky="ew", pady=(0, px(6)))
        if self.logo is not None:
            tk.Label(marca, image=self.logo, bg=estilo.PANEL,
                     bd=0).pack(side="left", padx=(0, px(8)))
        ttk.Label(marca, text=TITULO, style="Caja.TLabel",
                  font=("Segoe UI Semibold", 13)).pack(side="left")

        herr = ttk.Frame(caja, style="Caja.TFrame")
        herr.grid(row=1, column=0, sticky="ew", pady=(0, px(6)))
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
        self.var_cortar = tk.BooleanVar(
            value=bool(config.get("cortar_al_terminar", True)))
        c_cortar = ttk.Checkbutton(herr, text="Cortar al final",
                                   variable=self.var_cortar,
                                   style="Caja.TCheckbutton",
                                   command=self._aplicar_modo_lista)
        c_cortar.pack(side="right", padx=(px(6), 0))
        Consejo(c_cortar, "Sin 'Repetir', al acabarse la lista se corta la "
                          "transmision sola y la emisora vuelve a su "
                          "programacion automatica.")
        ttk.Checkbutton(herr, text="Repetir", variable=self.var_repetir,
                        style="Caja.TCheckbutton",
                        command=self._aplicar_modo_lista).pack(side="right")
        ttk.Checkbutton(herr, text="Aleatorio", variable=self.var_mezclar,
                        style="Caja.TCheckbutton",
                        command=self._aplicar_modo_lista).pack(side="right", padx=px(6))

        busca = ttk.Frame(caja, style="Caja.TFrame")
        busca.grid(row=2, column=0, sticky="ew", pady=(0, px(6)))
        ttk.Label(busca, text="Buscar:", style="CajaSuave.TLabel").pack(side="left")
        self.var_busca = tk.StringVar()
        e = ttk.Entry(busca, textvariable=self.var_busca)
        e.pack(side="left", fill="x", expand=True, padx=px(6))
        e.bind("<KeyRelease>", lambda ev: self._filtrar())

        marco = ttk.Frame(caja, style="Caja.TFrame")
        marco.grid(row=3, column=0, sticky="nsew")
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
        pie.grid(row=4, column=0, sticky="ew", pady=(px(6), 0))
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
                                   font=estilo.FUENTE_TIT, anchor="w")
        self.lbl_pista.grid(row=0, column=0, sticky="ew")
        self.titulo_completo = "- nada -"
        self.lbl_pista.bind("<Configure>", lambda e: self._ajustar_titulo())
        self.lbl_artista = ttk.Label(caja, text="", style="CajaSuave.TLabel",
                                     anchor="w")
        self.lbl_artista.grid(row=1, column=0, sticky="ew", pady=(0, px(2)))

        # deslizador de posicion: se arrastra para ir a otro punto de la pista
        self.var_pos = tk.DoubleVar(value=0.0)
        self.barra_pista = ttk.Scale(caja, from_=0, to=1000,
                                     variable=self.var_pos,
                                     style="Caja.Horizontal.TScale")
        self.barra_pista.grid(row=2, column=0, sticky="ew")
        self.barra_pista.bind("<ButtonPress-1>", self._tomar_pista)
        self.barra_pista.bind("<ButtonRelease-1>", self._soltar_pista)
        self._arrastrando = False
        Consejo(self.barra_pista, "Arrastra para ir a otro punto de la pista")

        tiempos = ttk.Frame(caja, style="Caja.TFrame")
        tiempos.grid(row=3, column=0, sticky="ew", pady=(0, px(4)))
        self.lbl_transcurrido = ttk.Label(tiempos, text="0:00", style="CajaMono.TLabel")
        self.lbl_transcurrido.pack(side="left")
        self.lbl_restante = ttk.Label(tiempos, text="-0:00", style="CajaMono.TLabel")
        self.lbl_restante.pack(side="right")

        botones = ttk.Frame(caja, style="Caja.TFrame")
        botones.grid(row=4, column=0, sticky="ew")
        # Los tres de transporte llevan `width` fijo (en caracteres): sin el,
        # el relleno del estilo los estiraba hasta pegar "Grabar" con el de
        # parar, sin un hueco donde soltar el raton.
        self.btn_play = ttk.Button(botones, text=ICO_PLAY, width=3,
                                   style="Transporte.TButton",
                                   command=self.play_pausa)
        self.btn_play.pack(side="left")
        Consejo(self.btn_play, "Reproducir / pausa   (barra espaciadora)")
        b = ttk.Button(botones, text=ICO_SIGUIENTE, width=3,
                       style="Transporte.TButton",
                       command=self.siguiente_pista)
        b.pack(side="left", padx=px(4))
        Consejo(b, "Siguiente pista   (Ctrl + flecha derecha)")
        b = ttk.Button(botones, text=ICO_PARAR, width=3,
                       style="Transporte.TButton",
                       command=self.parar_musica)
        b.pack(side="left")
        Consejo(b, "Parar la musica")

        self.btn_rec = ttk.Button(botones, text="%s  Grabar" % ICO_REC,
                                  style="Rec.TButton",
                                  command=self.alternar_grabacion)
        self.btn_rec.pack(side="right", padx=(px(12), 0))
        Consejo(self.btn_rec,
                "Grabar el programa. Es independiente de estar al aire: puedes poner musica sin grabarla y empezar a grabar cuando arranque el programa.")

        # Lo que se lee en la radio. Va en UNA sola fila (antes eran dos, con
        # su rotulo encima) para hacer sitio al autor sin crecer hacia abajo:
        # si el panel crece, los botones de cortina se quedan sin espacio.
        fila = ttk.Frame(caja, style="Caja.TFrame")
        fila.grid(row=5, column=0, sticky="ew", pady=(px(6), 0))
        ttk.Label(fila, text="Al aire:", style="CajaSuave.TLabel").pack(
            side="left", padx=(0, px(4)))
        self.var_titulo = tk.StringVar()
        e_tit = ttk.Entry(fila, textvariable=self.var_titulo)
        e_tit.pack(side="left", fill="x", expand=True)
        Consejo(e_tit, "Titulo del programa, lo que se lee en la radio.")
        self.var_autor_aire = tk.StringVar(value=config.get("autor", ""))
        e_aut = ttk.Entry(fila, textvariable=self.var_autor_aire, width=16)
        e_aut.pack(side="left", padx=(px(4), 0))
        Consejo(e_aut, "Quien presenta. Sin esto, la radio muestra 'Unknown' "
                       "donde va el autor.")
        ttk.Button(fila, text="Poner", style="Caja.TButton", width=7,
                   command=self.poner_titulo).pack(side="left", padx=(px(4), 0))

    # -------------------------------------------------- mezcla

    def _panel_mezcla(self, padre):
        caja = ttk.Labelframe(padre, text=" MEZCLADOR ", style="Caja.TLabelframe")
        caja.grid(row=1, column=0, sticky="ew", pady=(px(8), 0))
        caja.columnconfigure(1, weight=1)

        self.vu = {}
        self.faders = {}
        self.botones_micro = []
        self.lbls_micro_db = []
        fila = 0

        # --- un canal por microfono: el del locutor y los de los invitados
        for c in self.mezclador.canales:
            b = ttk.Button(caja, text=c.nombre, style="MicOff.TButton", width=10,
                           command=lambda n=c.indice: self.alternar_microfono(n))
            b.grid(row=fila, column=0, sticky="w", pady=px(2))
            Consejo(b, "Abrir o cerrar %s al aire   (Ctrl+%d)"
                    % (c.nombre, c.indice + 1))
            self.botones_micro.append(b)

            v = estilo.Vumetro(caja, ancho=px(150), alto=px(11))
            v.grid(row=fila, column=1, sticky="ew", padx=px(6))
            self.vu["micro%d" % c.indice] = v

            # en dB, no en "porcentaje": un microfono lejano necesita
            # amplificarse de verdad, hasta +24 dB (dieciseis veces)
            var = tk.DoubleVar(value=mod_eq.ganancia_a_db(c.volumen))
            f = ttk.Scale(caja, from_=-40, to=24, variable=var,
                          style="Caja.Horizontal.TScale",
                          command=lambda val, n=c.indice: self._fader_micro(n, val))
            f.grid(row=fila, column=2, sticky="ew")
            f.configure(length=px(80))
            Consejo(f, "Volumen de %s, en decibelios. 0 dB es el nivel tal cual "
                       "entra; a la derecha, se amplifica." % c.nombre)
            self.faders["micro%d" % c.indice] = var
            lbl = ttk.Label(caja, text="", style="CajaMono.TLabel", width=7)
            lbl.grid(row=fila, column=3, sticky="w")
            self.lbls_micro_db.append(lbl)
            fila += 1

        # --- musica y cortinas
        for clave, texto, ajuste in (("musica", "MUSICA", "vol_musica"),
                                     ("efectos", "CORTINAS", "vol_efectos")):
            ttk.Label(caja, text=texto, style="CajaSuave.TLabel",
                      width=10).grid(row=fila, column=0, sticky="w", pady=px(2))
            v = estilo.Vumetro(caja, ancho=px(150), alto=px(11))
            v.grid(row=fila, column=1, sticky="ew", padx=px(6))
            self.vu[clave] = v
            var = tk.DoubleVar(value=float(config.get(ajuste, 0.8)) * 100)
            f = ttk.Scale(caja, from_=0, to=100, variable=var,
                          style="Caja.Horizontal.TScale",
                          command=lambda val, a=ajuste: self._fader(a, val))
            f.grid(row=fila, column=2, sticky="ew")
            f.configure(length=px(90))
            self.faders[ajuste] = var
            fila += 1

        ttk.Separator(caja, orient="horizontal").grid(
            row=fila, column=0, columnspan=3, sticky="ew", pady=px(6))
        fila += 1

        ttk.Label(caja, text="AL AIRE", style="Caja.TLabel",
                  width=10).grid(row=fila, column=0, sticky="w")
        marco_aire = ttk.Frame(caja, style="Caja.TFrame")
        marco_aire.grid(row=fila, column=1, columnspan=2, sticky="ew", padx=px(6))
        self.vu["aire_i"] = estilo.Vumetro(marco_aire, ancho=px(230), alto=px(9))
        self.vu["aire_i"].pack(fill="x")
        self.vu["aire_d"] = estilo.Vumetro(marco_aire, ancho=px(230), alto=px(9))
        self.vu["aire_d"].pack(fill="x", pady=(px(2), 0))
        fila += 1

        acciones = ttk.Frame(caja, style="Caja.TFrame")
        acciones.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=(px(8), 0))
        self.var_ducking = tk.BooleanVar(value=bool(config.get("ducking", True)))
        ttk.Checkbutton(acciones, text="Bajar musica al hablar",
                        variable=self.var_ducking, style="Caja.TCheckbutton",
                        command=self._cambio_ducking).pack(side="left")
        fila += 1
        # el primero es "el" microfono para los atajos y para el resto del codigo
        self.btn_micro = self.botones_micro[0]

        # soundpad: sonidos cortos listos para lanzar encima de lo que suene
        ttk.Label(caja, text="SOUNDPAD   ·   clic para lanzar, clic derecho "
                              "para asignar o renombrar",
                  style="CajaSuave.TLabel").grid(row=fila, column=0, columnspan=3,
                                                 sticky="w", pady=(px(8), px(2)))
        fila += 1
        cort = ttk.Frame(caja, style="Caja.TFrame")
        cort.grid(row=fila, column=0, columnspan=3, sticky="ew")
        for col in range(POR_FILA_SOUNDPAD):
            cort.columnconfigure(col, weight=1, uniform="pad")
        self.botones_cortina = []
        self.cortinas = [None] * CORTINAS
        self.nombres_cortina = [""] * CORTINAS
        # En rejilla y por filas: en una sola fila, ocho botones no caben sin
        # dejarlos tan estrechos que el nombre no se lee (que era la queja).
        for i in range(CORTINAS):
            b = ttk.Button(cort, text=str(i + 1), style="Caja.TButton",
                           width=ANCHO_SOUNDPAD,
                           command=lambda n=i: self.disparar_cortina(n))
            b.grid(row=i // POR_FILA_SOUNDPAD, column=i % POR_FILA_SOUNDPAD,
                   sticky="ew", padx=(0, px(4)), pady=(0, px(4)))
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
            if p.duracion > 0 and not self._arrastrando:
                frac = min(1.0, p.posicion / p.duracion)
                self.var_pos.set(frac * 1000)
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
            self._icono_segun_aire(e.al_aire)
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
            if self.mezclador.acople and not self._aviso_acople:
                self._aviso_acople = True
                self.mensaje("ACOPLE detectado: se callaron los auriculares. "
                             "Baja el volumen o usa audifonos cerrados.")
            elif not self.mezclador.acople:
                self._aviso_acople = False
            self._encadenar()
            self._pintar_oyentes()
            self._vigilar_hardware()
        except tk.TclError:
            return
        self.after(1000, self._tic_lento)

    def _vigilar_hardware(self):
        """
        Avisa (una sola vez) si se enchufa o se quita un aparato de audio.

        Se mira cada 4 segundos y cuesta unos 3 ms, porque se pregunta al
        registro de Windows y NO a la tarjeta de sonido: preguntarselo a
        PortAudio obligaria a reiniciarlo, y eso corta el microfono y los
        auriculares. Aqui solo se avisa; cambiar de verdad los aparatos lo
        decide el usuario en Configuracion -> Audio.
        """
        self._cuenta_hw = getattr(self, "_cuenta_hw", 0) + 1
        if self._cuenta_hw % 4:
            return
        if not self.mezclador.hay_hardware_nuevo():
            self._aviso_hw = False
            return
        if getattr(self, "_aviso_hw", False):
            return                        # ya se aviso de este cambio
        self._aviso_hw = True
        self.mensaje("Cambio un aparato de audio. Configuracion -> Audio -> "
                     "\"Buscar aparatos nuevos\" para usarlo.")

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
        # `intentar_salir_al_aire` (y no `arrancar`) para que, si todavia no
        # hay internet, siga intentandolo en vez de rendirse al primer golpe
        if self.emisor.intentar_salir_al_aire():
            self.mensaje("Conectando con el servidor...")
            if config.get("grabar_al_aire") and not self.grabador.grabando:
                # por el Grabador, para que lleve etiquetas y caratula
                self.grabador.iniciar(self.var_titulo.get().strip())
                self._pintar_grabacion()
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

    def alternar_microfono(self, indice=0):
        """Abre o cierra uno de los microfonos de la mesa."""
        if not self.mezclador.corriendo:
            self.mezclador.arrancar()
        if not (0 <= indice < len(self.mezclador.canales)):
            return
        canal = self.mezclador.canales[indice]
        if not canal.micro.abierto:
            # Antes esto se limitaba a protestar, y como el motivo salia
            # vacio ("-") no habia forma de saber que pasaba. Ahora se
            # intenta abrirlo AQUI MISMO: casi siempre es que el aparato se
            # acaba de asignar, o que se solto al cambiar de hardware.
            self.mezclador.sincronizar_microfonos()
        if not canal.micro.abierto:
            messagebox.showwarning(
                "Microfono",
                "No se pudo abrir %s." % canal.nombre + SALTO * 2
                + (canal.error or "Windows no dejo abrirlo: puede que lo "
                                 "este usando otro programa, o que el "
                                 "aparato asignado ya no este conectado.")
                + SALTO * 2
                + "Revisa cual tiene asignado en Configuracion > Audio.",
                parent=self)
            return
        abierto = self.mezclador.alternar_micro(indice)
        self._pintar_micros()
        self._musica_segun_micro()
        self.mensaje("%s %s." % (canal.nombre,
                                 "abierto" if abierto else "cerrado"))

    def _musica_segun_micro(self):
        """
        Que le pasa a la musica cuando se abre o se cierra un microfono.

        Con "Bajar musica al hablar" marcado, de eso ya se encarga el mezclador
        (baja el volumen y lo devuelve solo). Sin marcar, lo que se espera es
        que la musica se PARE mientras se habla y vuelva a sonar al cerrar.
        """
        if self.var_ducking.get():
            return                      # el ducking ya lo hace por su cuenta
        hay_micro = any(c.abierto for c in self.mezclador.canales)
        p = self.mezclador.pista_a
        if hay_micro and p.sonando:
            self._musica_en_pausa_por_micro = True
            p.pausar()
            self.btn_play.configure(text=ICO_PLAY)
            self.mensaje("Musica en pausa mientras hablas.")
        elif not hay_micro and getattr(self, "_musica_en_pausa_por_micro", False):
            self._musica_en_pausa_por_micro = False
            p.reproducir()
            self.btn_play.configure(text=ICO_PAUSA)

    def _pintar_micros(self):
        """Rojo el que este al aire; el resto, apagados."""
        for c in self.mezclador.canales:
            if c.indice >= len(self.botones_micro):
                continue
            b = self.botones_micro[c.indice]
            if c.abierto:
                b.configure(text=c.nombre.upper(), style="MicOn.TButton")
            else:
                b.configure(text=c.nombre, style="MicOff.TButton")

    def _fader_micro(self, indice, valor):
        """El volumen de un microfono. El deslizador va en dB."""
        if not (0 <= indice < len(self.mezclador.canales)):
            return
        db = float(valor)
        ganancia = mod_eq.db_a_ganancia(db)
        self.mezclador.canales[indice].volumen = ganancia
        if indice < len(self.lbls_micro_db):
            self.lbls_micro_db[indice].configure(
                text=("apagado" if db <= -40 else "%+.0f dB" % db))
        micros = config.microfonos()
        if indice < len(micros):
            micros[indice]["volumen"] = round(ganancia, 4)
            config.guardar_microfonos(micros)

    def _texto_al_aire(self):
        """Lo que se lee en la radio: "Autor - Titulo" (ver servidor)."""
        return servidor.componer_titulo(self.var_titulo.get(),
                                        self.var_autor_aire.get())

    def _texto_de_pista(self, pista):
        """
        Lo que se anuncia cuando cambia la cancion, con el autor SIEMPRE puesto.

        `biblioteca.etiqueta()` devuelve solo el titulo cuando el archivo no
        trae etiqueta de artista, y ese hueco es justo el que la radio muestra
        como "Unknown". Si el archivo no lo dice, firma la emisora.
        """
        autor = (pista.get("artista", "") or "").strip()
        if not autor:
            autor = (config.get("nombre_emisora", "") or "").strip()
        return servidor.componer_titulo(pista.get("titulo", ""), autor)

    def poner_titulo(self):
        texto = self._texto_al_aire()
        autor = self.var_autor_aire.get().strip()
        if not texto:
            # los dos campos vacios = soltar el programa y volver a anunciar
            # cada cancion, que es lo que hace la aplicacion por su cuenta
            if self.titulo_programa:
                self.titulo_programa = ""
                self.mensaje("Titulo del programa quitado: vuelve a anunciarse "
                             "cada cancion.")
            return
        # el autor se recuerda: casi siempre es el mismo
        config.guardar({"autor": autor})
        # Queda FIJADO: mientras haya un titulo de programa puesto a mano, el
        # cambio de cancion no lo pisa. Antes lo pisaba a los pocos segundos y
        # el autor desaparecia -> la radio ponia "Unknown".
        self.titulo_programa = texto
        self.ultimo_titulo_enviado = texto
        ok, detalle = servidor.actualizar_titulo(texto)
        self.mensaje("Al aire: %s" % texto if ok
                     else "No se pudo poner el titulo (%s)" % detalle)
        self._anotar("titulo -> %s (%s)" % (texto, detalle))

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
            self._fin_de_lista()
            return
        self._poner_pista(pista)

    def _fin_de_lista(self):
        """
        Se acabo la lista y no esta puesto "Repetir".

        Si asi se pidio, se corta la transmision sola: es la forma de dejar
        programado un bloque, irse, y que la emisora vuelva al autoDJ al
        terminar sin que nadie tenga que estar delante.
        """
        self.btn_play.configure(text=ICO_PLAY)
        if not config.get("cortar_al_terminar", True):
            self.mensaje("La lista se acabo.")
            return
        if self.grabador.grabando:
            archivo = self.grabador.detener()
            self._pintar_grabacion()
            if archivo:
                self._anotar("grabacion cerrada al acabar la lista: %s" % archivo)
        if self.emisor.al_aire or self.emisor.estado == mod_emisor.CONECTANDO:
            self.emisor.detener()
            self.mezclador.detener()
            self.mensaje("La lista se acabo: transmision cortada. "
                         "La emisora vuelve a su programacion.")
        else:
            self.mensaje("La lista se acabo.")

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
        self.titulo_completo = pista.get("titulo", "") or "-"
        self._ajustar_titulo()
        Consejo(self.lbl_pista, self.titulo_completo)
        self.lbl_artista.configure(text=pista.get("artista", ""))
        self._marcar_sonando()
        # avisar al servidor que cambio la cancion.
        # Si hay un titulo de programa puesto con "Poner", ese manda: en una
        # transmision en vivo lo que se anuncia es el programa, no el archivo
        # que suene de fondo.
        etiqueta = "" if self.titulo_programa else self._texto_de_pista(pista)
        if etiqueta and etiqueta != self.ultimo_titulo_enviado and self.emisor.al_aire:
            self.ultimo_titulo_enviado = etiqueta
            threading.Thread(target=servidor.actualizar_titulo,
                             args=(etiqueta,), daemon=True).start()

    def _tomar_pista(self, _=None):
        """Mientras se arrastra, el reloj deja de mover el deslizador."""
        if self.mezclador.pista_a.duracion > 0:
            self._arrastrando = True

    def _soltar_pista(self, _=None):
        """Al soltar, se salta al punto elegido."""
        if not self._arrastrando:
            return
        self._arrastrando = False
        p = self.mezclador.pista_a
        if p.duracion <= 0:
            return
        segundos = (self.var_pos.get() / 1000.0) * p.duracion
        p.saltar_a(segundos)
        self.lbl_transcurrido.configure(
            text=biblioteca.duracion_texto(segundos))
        self.mensaje("Pista en %s" % biblioteca.duracion_texto(segundos))

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

    def _ajustar_titulo(self):
        """
        Recorta el titulo con puntos suspensivos para que quepa en su sitio.

        Antes se cortaba a lo bruto por el borde y no se sabia si faltaba algo;
        ahora se ve que sigue ("Daniel 10 - Cautividad, Purifi...") y el titulo
        entero queda en el globo de ayuda.
        """
        try:
            import tkinter.font as tkfont
            ancho = self.lbl_pista.winfo_width() - px(6)
            if ancho < px(40):
                return
            fuente = tkfont.Font(font=self.lbl_pista.cget("font"))
            texto = self.titulo_completo
            if fuente.measure(texto) <= ancho:
                self.lbl_pista.configure(text=texto)
                return
            corto = texto
            while corto and fuente.measure(corto + "...") > ancho:
                corto = corto[:-1]
            self.lbl_pista.configure(text=corto.rstrip() + "...")
        except Exception:
            pass

    def _texto_cortina(self, n):
        """Lo que se lee en el boton: el nombre puesto, o el del archivo."""
        if self.nombres_cortina[n]:
            return self.nombres_cortina[n]
        if self.cortinas[n]:
            return Path(self.cortinas[n]).stem[:ANCHO_SOUNDPAD]
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
        self._aviso_acople = False
        self._musica_en_pausa_por_micro = False
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
        config.guardar({"cortar_al_terminar": self.var_cortar.get()})

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
        if self.var_ducking.get():
            # vuelve el modo "bajar": si estaba parada por el micro, que siga
            if getattr(self, "_musica_en_pausa_por_micro", False):
                self._musica_en_pausa_por_micro = False
                self.mezclador.pista_a.reproducir()
                self.btn_play.configure(text=ICO_PAUSA)
        else:
            self._musica_segun_micro()

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
        self._pintar_micros()
        for c in self.mezclador.canales:
            var = self.faders.get("micro%d" % c.indice)
            if var is not None:
                self._fader_micro(c.indice, var.get())
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
            os.startfile(str(config.carpeta_graba()))
        except Exception as e:
            messagebox.showerror("Grabaciones", str(e), parent=self)

    def abrir_monitor_aire(self):
        """La ventanita que dice si la emisora esta sonando de verdad."""
        v = getattr(self, "_ventana_aire", None)
        if v is not None:
            try:
                if v.winfo_exists():
                    v.deiconify()
                    v.lift()
                    return
            except tk.TclError:
                pass
        if not config.get("host"):
            messagebox.showwarning("Monitor de aire",
                                   "Primero hay que configurar el servidor.",
                                   parent=self)
            return
        self._ventana_aire = ventana_aire.VentanaAire(self)

    def abrir_metadatos(self):
        """
        El editor de etiquetas de un programa ya grabado.

        Una sola ventana: si ya esta abierta se trae al frente en vez de
        abrir otra, que llevaria a guardar dos veces el mismo archivo.
        """
        v = getattr(self, "ventana_metadatos", None)
        if v is not None:
            try:
                if v.winfo_exists():
                    v.deiconify()
                    v.lift()
                    return v
            except tk.TclError:
                pass
        import ventana_metadatos
        self.ventana_metadatos = ventana_metadatos.VentanaMetadatos(self)
        return self.ventana_metadatos

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
        v = getattr(self, "_ventana_aire", None)
        if v is not None:
            try:
                v.cerrar()
            except Exception:
                pass
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
        # Audio primero (es lo que mas se toca) y Servidor al final (se
        # configura una vez y no se vuelve a mirar)
        self._pestana_audio(nb)
        self._pestana_microfono(nb)
        self._pestana_transmision(nb)
        self._pestana_servidor(nb)

        # el pie se empaqueta ANTES que el cuaderno, para que los botones no
        # se queden nunca sin sitio (ya paso con la barra de estado)
        pie = ttk.Frame(self, padding=(px(10), 0, px(10), px(10)))
        pie.pack(side="bottom", fill="x")
        ttk.Button(pie, text="Guardar y cerrar", style="Accion.TButton",
                   command=self.guardar).pack(side="right")
        ttk.Button(pie, text="Cancelar", command=self.destroy).pack(
            side="right", padx=px(6))
        b_aplicar = ttk.Button(pie, text="Aplicar", command=self.aplicar)
        b_aplicar.pack(side="right", padx=(0, px(6)))
        Consejo(b_aplicar, "Guarda y aplica los cambios SIN cerrar la ventana, "
                           "para poder probarlos.")
        ttk.Button(pie, text="Probar conexion",
                   command=self.probar).pack(side="left")
        self.lbl_aplicado = ttk.Label(pie, text="", style="Suave.TLabel")
        self.lbl_aplicado.pack(side="left", padx=px(8))

        self._colocar(padre)
        self.wait_window()

    def _colocar(self, padre):
        """
        Centrada sobre la ventana principal, pero SIN salirse de la pantalla.

        Antes se abria a 60 px del borde de arriba de la ventana principal y,
        como el cuaderno es alto, los botones de abajo quedaban fuera y habia
        que mover la ventana para llegar a ellos.
        """
        self.update_idletasks()
        ancho, alto = self.winfo_width(), self.winfo_height()
        pantalla_a, pantalla_h = self.winfo_screenwidth(), self.winfo_screenheight()
        x = padre.winfo_rootx() + (padre.winfo_width() - ancho) // 2
        y = padre.winfo_rooty() + px(30)
        x = max(px(4), min(x, pantalla_a - ancho - px(4)))
        y = max(px(4), min(y, pantalla_h - alto - px(50)))   # deja la barra
        self.geometry("+%d+%d" % (x, y))

    def aplicar(self):
        """Guardar y que surta efecto, sin cerrar: asi se puede ir probando."""
        self._recoger()
        self.padre.mezclador.aplicar_ajustes()
        self.padre._cargar_ajustes_en_pantalla()
        self.padre.mensaje("Cambios aplicados.")
        detalle = self.padre.mezclador.error or ""
        self.lbl_aplicado.configure(
            text=(detalle[:44] if detalle else "aplicado"),
            foreground=estilo.ROJO if detalle else estilo.VERDE)
        self.after(4000, lambda: self._limpiar_aviso())

    def _limpiar_aviso(self):
        try:
            self.lbl_aplicado.configure(text="")
        except tk.TclError:
            pass

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

        ttk.Label(f, text="Volumen de emision:").grid(row=16, column=0,
                                                      sticky="w", pady=(px(6), 0))
        marco_m = ttk.Frame(f)
        marco_m.grid(row=16, column=1, sticky="w", pady=(px(6), 0))
        self.var_master = tk.DoubleVar(value=float(config.get("master_db", 0.0)))
        ttk.Scale(marco_m, from_=-12, to=12, variable=self.var_master,
                  length=px(180),
                  command=lambda v: self._pintar_master()).pack(side="left")
        self.lbl_master = ttk.Label(marco_m, text="", width=7,
                                    style="Suave.TLabel")
        self.lbl_master.pack(side="left", padx=px(6))

        self.var_mono = tk.BooleanVar(value=bool(config.get("emitir_mono")))
        ttk.Checkbutton(f, text="Emitir en mono (mejor calidad al mismo bitrate "
                                "si el programa es hablado)",
                        variable=self.var_mono).grid(row=17, column=0,
                                                     columnspan=2, sticky="w",
                                                     pady=(px(4), 0))
        ttk.Label(f, text="Medido el 24-08: tu senal salia a -18.9 LUFS y las "
                          "radios suelen ir a -16, o sea unos +3 dB.",
                  style="Suave.TLabel").grid(row=18, column=0, columnspan=2,
                                             sticky="w")
        ttk.Label(f, text="El plan contratado admite 128 kbps y 120 oyentes.",
                  style="Suave.TLabel").grid(row=19, column=0, columnspan=2,
                                             sticky="w", pady=(px(6), 0))
        self._pintar_master()

    def _pintar_master(self):
        db = float(self.var_master.get())
        self.lbl_master.configure(text="%+.1f dB" % db)
        self.padre.mezclador.master = mod_eq.db_a_ganancia(db)

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
        """
        Aparatos y niveles.

        Las filas se llevan con un contador, NO sumando a mano sobre una base:
        asi era como acababan dibujandose dos cosas en la misma fila y se veia
        una raya encima de un texto.
        """
        f = ttk.Frame(nb, padding=px(12))
        nb.add(f, text="Audio")
        f.columnconfigure(1, weight=1)
        fila = 0

        entradas = [n for _, n, _, _ in audio.listar(entrada=True)]
        salidas = [n for _, n, _, _ in audio.listar(entrada=False)]
        # se guardan para poder repoblarlos al encontrar hardware nuevo, sin
        # cerrar y volver a abrir la ventana de configuracion
        self._combos_entrada = []
        self._combos_salida = []

        # Enchufar un microfono con la aplicacion abierta no se nota solo:
        # PortAudio se queda con la lista que habia al arrancar. Este boton la
        # vuelve a pedir sin cortar la emision (ver
        # `motor.Mezclador.refrescar_dispositivos`).
        #
        # Va en la MISMA fila que el rotulo, y la explicacion en un globo de
        # ayuda, porque esta ventana ya median 1048 px en una pantalla de 1080:
        # dos filas mas la sacaban de la pantalla y los botones de abajo se
        # quedaban fuera. Es la leccion 2 del CLAUDE.md, otra vez.
        fila_hw = ttk.Frame(f)
        fila_hw.grid(row=fila, column=0, columnspan=3, sticky="ew")
        ttk.Label(fila_hw, text="MICROFONOS   .   uno por cada persona al aire",
                  style="Suave.TLabel").pack(side="left")
        self.btn_buscar_hw = ttk.Button(fila_hw, text="Buscar aparatos nuevos",
                                        command=self.buscar_hardware)
        self.btn_buscar_hw.pack(side="right")
        Consejo(self.btn_buscar_hw,
                "Si enchufas otro microfono o unos auriculares con la "
                "aplicacion ya abierta, Windows los ve pero la aplicacion no. "
                "Pulsa aqui y aparecen en las listas. No corta la emision: "
                "solo se va tu voz un cuarto de segundo.")
        self.lbl_hw = ttk.Label(fila_hw, text="", style="Suave.TLabel")
        self.lbl_hw.pack(side="right", padx=px(8))
        fila += 1
        self.vars_micros = []
        micros = config.microfonos()
        while len(micros) < config.MAX_MICROS:
            micros.append({"nombre": "Micro %d" % (len(micros) + 1),
                           "dispositivo": "", "volumen": 1.0,
                           "eq_preset": "Plano", "eq": {}})
        for i, m in enumerate(micros[:config.MAX_MICROS]):
            fila_m = ttk.Frame(f)
            fila_m.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=px(2))
            ttk.Label(fila_m, text="%d." % (i + 1), width=2).pack(side="left")
            v_nombre = tk.StringVar(value=m.get("nombre") or "")
            ttk.Entry(fila_m, textvariable=v_nombre, width=12).pack(side="left")
            v_disp = tk.StringVar(value=m.get("dispositivo") or "")
            combo = ttk.Combobox(fila_m, textvariable=v_disp,
                                 values=[""] + entradas, width=34,
                                 state="readonly")
            combo.pack(side="left", padx=px(6))
            self._combos_entrada.append(combo)
            self.vars_micros.append((v_nombre, v_disp))
            fila += 1
        ttk.Label(f, text="Deja el aparato en blanco para no usar ese canal. "
                          "Los microfonos se aplican al reiniciar.",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w", pady=(px(2), px(8)))
        fila += 1

        ttk.Separator(f, orient="horizontal").grid(row=fila, column=0,
                                                   columnspan=3, sticky="ew",
                                                   pady=px(6))
        fila += 1
        ttk.Label(f, text="Auriculares:").grid(row=fila, column=0, sticky="w",
                                               pady=px(4))
        self.var_monitor = tk.StringVar(value=config.get("monitor"))
        combo_mon = ttk.Combobox(f, textvariable=self.var_monitor,
                                 values=salidas, width=38, state="readonly")
        combo_mon.grid(row=fila, column=1, columnspan=2, sticky="ew")
        self._combos_salida.append(combo_mon)
        fila += 1

        ttk.Label(f, text="Su volumen:").grid(row=fila, column=0, sticky="w",
                                              pady=px(4))
        self.var_vol_mon = tk.DoubleVar(
            value=mod_eq.ganancia_a_db(float(config.get("volumen_monitor", 0.8))))
        ttk.Scale(f, from_=-40, to=6, variable=self.var_vol_mon, length=px(210),
                  command=lambda v: self._pintar_vol_mon()).grid(
            row=fila, column=1, sticky="w")
        self.lbl_vol_mon = ttk.Label(f, text="", width=7, style="Suave.TLabel")
        self.lbl_vol_mon.grid(row=fila, column=2, sticky="w")
        fila += 1
        ttk.Label(f, text="Solo cambia lo que oyes tu; no toca lo que sale al aire.",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        fila += 1

        self.var_mon_act = tk.BooleanVar(value=bool(config.get("monitor_activo")))
        ttk.Checkbutton(f, text="Escuchar por los auriculares lo que sale al aire",
                        variable=self.var_mon_act).grid(row=fila, column=0,
                                                        columnspan=3, sticky="w",
                                                        pady=px(4))
        fila += 1
        self.var_mudo_micro = tk.BooleanVar(
            value=bool(config.get("monitor_mudo_con_micro")))
        ttk.Checkbutton(f, text="Callarlos mientras el microfono este abierto "
                                "(evita el acople)",
                        variable=self.var_mudo_micro).grid(row=fila, column=0,
                                                           columnspan=3,
                                                           sticky="w")
        fila += 1
        self.var_anti_acople = tk.BooleanVar(
            value=bool(config.get("proteccion_acople", True)))
        ttk.Checkbutton(f, text="Cortarlos solo si detecta un pitido de acople",
                        variable=self.var_anti_acople).grid(row=fila, column=0,
                                                            columnspan=3,
                                                            sticky="w")
        fila += 1

        fila_prueba = ttk.Frame(f)
        fila_prueba.grid(row=fila, column=0, columnspan=3, sticky="w", pady=px(4))
        ttk.Button(fila_prueba, text="Probar los auriculares",
                   command=self.probar_monitor).pack(side="left")
        self.lbl_monitor = ttk.Label(fila_prueba, text="", style="Suave.TLabel")
        self.lbl_monitor.pack(side="left", padx=px(8))
        fila += 1
        ttk.Label(f, text="Los Bluetooth funcionan: Windows convierte el "
                          "muestreo por su cuenta.",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        fila += 1

        ttk.Separator(f, orient="horizontal").grid(row=fila, column=0,
                                                   columnspan=3, sticky="ew",
                                                   pady=px(6))
        fila += 1
        ttk.Label(f, text="Retraso al oirte:").grid(row=fila, column=0,
                                                    sticky="w", pady=px(4))
        self.var_bloque = tk.StringVar(
            value=BLOQUES_TEXTO.get(int(config.get("bloque_audio", 512)),
                                    BLOQUES_TEXTO[512]))
        ttk.Combobox(f, textvariable=self.var_bloque, state="readonly", width=28,
                     values=[BLOQUES_TEXTO[k] for k in (1024, 512, 256)]).grid(
            row=fila, column=1, columnspan=2, sticky="w")
        fila += 1
        ttk.Label(f, text="Cuanto mas corto, menos eco al oirte, pero mas "
                          "trabaja el ordenador.",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        fila += 1

        ttk.Separator(f, orient="horizontal").grid(row=fila, column=0,
                                                   columnspan=3, sticky="ew",
                                                   pady=px(6))
        fila += 1
        self.var_duck = tk.BooleanVar(value=bool(config.get("ducking")))
        ttk.Checkbutton(f, text="Bajar la musica automaticamente al hablar",
                        variable=self.var_duck).grid(row=fila, column=0,
                                                     columnspan=3, sticky="w")
        fila += 1
        ttk.Label(f, text="Cuanto baja:").grid(row=fila, column=0, sticky="w",
                                               pady=px(4))
        self.var_duck_niv = tk.DoubleVar(
            value=float(config.get("ducking_nivel")) * 100)
        ttk.Scale(f, from_=5, to=80, variable=self.var_duck_niv,
                  length=px(210)).grid(row=fila, column=1, sticky="w")
        fila += 1

        ttk.Separator(f, orient="horizontal").grid(row=fila, column=0,
                                                   columnspan=3, sticky="ew",
                                                   pady=px(6))
        fila += 1
        ttk.Label(f, text="Barra espaciadora:").grid(row=fila, column=0,
                                                     sticky="w", pady=px(4))
        self.var_espacio = tk.StringVar(
            value=ESPACIO_TEXTOS.get(config.get("tecla_espacio", ESPACIO_MICRO),
                                     ESPACIO_TEXTOS[ESPACIO_MICRO]))
        ttk.Combobox(f, textvariable=self.var_espacio, state="readonly", width=28,
                     values=[ESPACIO_TEXTOS[k] for k in
                             (ESPACIO_MICRO, ESPACIO_PLAY, ESPACIO_NADA)]).grid(
            row=fila, column=1, columnspan=2, sticky="w")
        fila += 1
        ttk.Label(f, text="F1 abre el microfono y F2 graba, elijas lo que elijas.",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        self._pintar_vol_mon()

    def _pintar_vol_mon(self):
        """El volumen de los auriculares se aplica al momento, sin guardar."""
        db = float(self.var_vol_mon.get())
        self.lbl_vol_mon.configure(text=("mudo" if db <= -40 else "%+.0f dB" % db))
        self.padre.mezclador.vol_monitor = mod_eq.db_a_ganancia(db)

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

    def buscar_hardware(self):
        """
        Vuelve a preguntar que aparatos de audio hay, con la app en marcha.

        Se hace en OTRO hilo, no aqui: enumerar la tarjeta de sonido tarda unos
        250 ms de normal, pero un aparato Bluetooth despertandose puede llevarse
        treinta segundos (medido), y con la ventana congelada eso parece que la
        aplicacion se ha colgado. **La emision no se toca**: el mezclador sigue
        girando y el emisor sigue recibiendo su bloque a tiempo; lo unico que
        parpadea es el microfono y los auriculares.
        """
        mez = self.padre.mezclador
        micro_abierto = any(c.abierto for c in mez.canales)
        if mez.corriendo and micro_abierto and self.padre.emisor.al_aire:
            seguir = messagebox.askyesno(
                "Buscar aparatos nuevos",
                "Estas AL AIRE con el microfono abierto." + SALTO * 2 +
                "La emision no se corta, pero tu voz se ira un cuarto de "
                "segundo mientras se cambian los aparatos." + SALTO * 2 +
                "¿Seguir?",
                parent=self)
            if not seguir:
                return

        self.btn_buscar_hw.state(["disabled"])
        self.lbl_hw.configure(text="buscando...")
        self._hw_resultado = None

        def trabajo():
            inicio = time.time()
            ok, detalle = mez.refrescar_dispositivos()
            self._hw_resultado = (ok, detalle, time.time() - inicio)

        threading.Thread(target=trabajo, daemon=True).start()
        self._esperar_hardware()

    def _esperar_hardware(self):
        """El hilo deja el resultado en un atributo; aqui se recoge."""
        resultado = getattr(self, "_hw_resultado", None)
        if resultado is None:
            try:
                self.after(120, self._esperar_hardware)
            except tk.TclError:
                pass
            return
        self._hw_resultado = None
        ok, detalle, segundos = resultado
        try:
            self.btn_buscar_hw.state(["!disabled"])
            self.lbl_hw.configure(
                text=("listo (%.1f s)" % segundos) if ok else "hubo un problema")
        except tk.TclError:
            return
        self._refrescar_listas_audio()
        self.padre.mensaje(detalle)
        self.padre._anotar("hardware de audio: %s" % detalle)
        if not ok:
            messagebox.showwarning("Buscar aparatos nuevos", detalle, parent=self)

    def _refrescar_listas_audio(self):
        """Repuebla los desplegables sin cerrar la ventana ni perder lo elegido."""
        entradas = [n for _, n, _, _ in audio.listar(entrada=True)]
        salidas = [n for _, n, _, _ in audio.listar(entrada=False)]
        for combo in getattr(self, "_combos_entrada", []):
            try:
                combo.configure(values=[""] + entradas)
            except tk.TclError:
                pass
        for combo in getattr(self, "_combos_salida", []):
            try:
                combo.configure(values=salidas)
            except tk.TclError:
                pass

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

        # cada microfono lleva su propio ajuste: la voz de un invitado casi
        # nunca necesita lo mismo que la del locutor
        micros = config.microfonos()
        self.nombres_micros_eq = [m.get("nombre") or ("Micro %d" % (i + 1))
                                  for i, m in enumerate(micros)]
        marco_sel = ttk.Frame(f)
        marco_sel.grid(row=1, column=0, columnspan=3, sticky="w", pady=px(6))
        ttk.Label(marco_sel, text="Ajustando:").pack(side="left")
        self.var_micro_eq = tk.StringVar(value=self.nombres_micros_eq[0])
        cb_micro = ttk.Combobox(marco_sel, textvariable=self.var_micro_eq,
                                state="readonly", width=16,
                                values=self.nombres_micros_eq)
        cb_micro.pack(side="left", padx=px(6))
        cb_micro.bind("<<ComboboxSelected>>", lambda e: self._cambiar_micro_eq())

        ttk.Label(f, text="Ajuste:").grid(row=2, column=0, sticky="w", pady=px(6))
        self.var_eq_preset = tk.StringVar(value=config.get("eq_preset", "Plano"))
        cb = ttk.Combobox(f, textvariable=self.var_eq_preset, state="readonly",
                          width=22, values=mod_eq.ORDEN_PRESETS)
        cb.grid(row=2, column=1, sticky="w", pady=px(6))
        cb.bind("<<ComboboxSelected>>", lambda e: self._cargar_preset_eq())

        valores = dict(mod_eq.PRESETS["Plano"])
        valores.update((micros[0].get("eq") or {}))
        self.var_eq_preset.set(micros[0].get("eq_preset") or "Plano")
        self.vars_eq, self.lbls_eq = {}, {}
        fila = 3
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

        ttk.Separator(f, orient="horizontal").grid(row=fila, column=0,
                                                   columnspan=3, sticky="ew",
                                                   pady=px(6))
        fila += 1
        self.var_comp = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Nivelar la voz (para microfonos lejanos)",
                        variable=self.var_comp,
                        command=self._guardar_compresor).grid(
            row=fila, column=0, columnspan=3, sticky="w")
        fila += 1
        ttk.Label(f, text="Refuerzo:").grid(row=fila, column=0, sticky="w",
                                            pady=px(2))
        self.var_comp_makeup = tk.DoubleVar(value=8.0)
        ttk.Scale(f, from_=0, to=20, variable=self.var_comp_makeup,
                  length=px(210),
                  command=lambda v: self._guardar_compresor()).grid(
            row=fila, column=1, sticky="w")
        self.lbl_comp = ttk.Label(f, text="", width=7, style="Suave.TLabel")
        self.lbl_comp.grid(row=fila, column=2, sticky="w")
        fila += 1
        ttk.Label(f, text="Sube lo flojo y frena lo fuerte, para no tener que "
                          "pegarse al microfono.",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w", pady=(0, px(4)))
        fila += 1
        self.var_puerta = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Callar el ruido de la sala entre frases",
                        variable=self.var_puerta,
                        command=self._guardar_compresor).grid(
            row=fila, column=0, columnspan=3, sticky="w")
        fila += 1
        ttk.Label(f, text="Desde:").grid(row=fila, column=0, sticky="w", pady=px(2))
        self.var_puerta_umbral = tk.DoubleVar(value=-45.0)
        ttk.Scale(f, from_=-60, to=-25, variable=self.var_puerta_umbral,
                  length=px(210),
                  command=lambda v: self._guardar_compresor()).grid(
            row=fila, column=1, sticky="w")
        self.lbl_puerta = ttk.Label(f, text="", width=7, style="Suave.TLabel")
        self.lbl_puerta.grid(row=fila, column=2, sticky="w")
        fila += 1
        ttk.Label(f, text="Util si amplificas mucho: sin esto, el ventilador y "
                          "la calle salen al aire cuando callas.",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w", pady=(0, px(4)))
        fila += 1
        ttk.Label(f, text="Quitar zumbido:").grid(row=fila, column=0, sticky="w",
                                                  pady=px(2))
        self.var_zumbido = tk.StringVar(value="60 Hz (America)")
        cbz = ttk.Combobox(f, textvariable=self.var_zumbido, state="readonly",
                           width=18,
                           values=("No quitarlo", "50 Hz (Europa)",
                                   "60 Hz (America)"))
        cbz.grid(row=fila, column=1, sticky="w")
        cbz.bind("<<ComboboxSelected>>", lambda e: self._guardar_compresor())
        fila += 1
        ttk.Label(f, text="El zumbido de la red electrica se cuela por el cable "
                          "del microfono. Aqui se mide a 60 Hz.",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w", pady=(0, px(4)))
        fila += 1

        acciones = ttk.Frame(f)
        acciones.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=px(6))
        ttk.Button(acciones, text="Guardar como 'A mi gusto'",
                   command=self._guardar_mi_gusto).pack(side="left")
        ttk.Button(acciones, text="Escuchar el microfono",
                   command=self._escuchar_micro).pack(side="left", padx=px(6))
        fila += 1

        self.var_comp.set(bool(micros[0].get("comp", True)))
        self.var_comp_makeup.set(float(micros[0].get("comp_makeup", 8)))
        self.lbl_comp.configure(text="+%.0f dB" % float(micros[0].get("comp_makeup", 8)))
        self.var_puerta.set(bool(micros[0].get("puerta", False)))
        self.var_puerta_umbral.set(float(micros[0].get("puerta_umbral", -45)))
        self.lbl_puerta.configure(text="%d dB" % int(micros[0].get("puerta_umbral", -45)))
        self.var_zumbido.set({0: "No quitarlo", 50: "50 Hz (Europa)", 60: "60 Hz (America)"}.get(
            int(micros[0].get("zumbido", 0) or 0), "No quitarlo"))
        ttk.Label(f, text="Consejo: enciende el monitor, abre el microfono y mueve las bandas mientras hablas.",
                  style="Suave.TLabel", justify="left").grid(
            row=fila, column=0, columnspan=3, sticky="w")
        self._refrescar_eq()

    def _guardar_compresor(self):
        """El nivelador de voz, guardado en la ficha del microfono elegido."""
        micros = config.microfonos()
        i = self._indice_eq()
        makeup = round(float(self.var_comp_makeup.get()), 1)
        self.lbl_comp.configure(text="+%.0f dB" % makeup)
        umbral = round(float(self.var_puerta_umbral.get()))
        self.lbl_puerta.configure(text="%d dB" % umbral)
        zumbido = {"No quitarlo": 0, "50 Hz (Europa)": 50,
                   "60 Hz (America)": 60}.get(self.var_zumbido.get(), 0)
        if i < len(micros):
            micros[i]["comp"] = bool(self.var_comp.get())
            micros[i]["comp_makeup"] = makeup
            micros[i]["puerta"] = bool(self.var_puerta.get())
            micros[i]["puerta_umbral"] = umbral
            micros[i]["zumbido"] = zumbido
            config.guardar_microfonos(micros)
            self.padre.mezclador.aplicar_ajustes()

    def _indice_eq(self):
        try:
            return self.nombres_micros_eq.index(self.var_micro_eq.get())
        except ValueError:
            return 0

    def _cambiar_micro_eq(self):
        """Al cambiar de microfono, se cargan SUS ajustes en los deslizadores."""
        micros = config.microfonos()
        i = self._indice_eq()
        m = micros[i] if i < len(micros) else {}
        base = dict(mod_eq.PRESETS["Plano"])
        base.update(m.get("eq") or {})
        for clave, var in self.vars_eq.items():
            var.set(float(base.get(clave, 0)))
        self.var_corte.set(bool(base.get("corte_grave", True)))
        self.var_eq_preset.set(m.get("eq_preset") or "Plano")
        self.var_comp.set(bool(m.get("comp", True)))
        self.var_comp_makeup.set(float(m.get("comp_makeup", 8)))
        self.lbl_comp.configure(text="+%.0f dB" % float(m.get("comp_makeup", 8)))
        self.var_puerta.set(bool(m.get("puerta", False)))
        self.var_puerta_umbral.set(float(m.get("puerta_umbral", -45)))
        self.lbl_puerta.configure(text="%d dB" % int(m.get("puerta_umbral", -45)))
        self.var_zumbido.set({0: "No quitarlo", 50: "50 Hz (Europa)", 60: "60 Hz (America)"}.get(
            int(m.get("zumbido", 0) or 0), "No quitarlo"))
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
        config.guardar({"eq_activo": self.var_eq_activo.get()})
        micros = config.microfonos()
        i = self._indice_eq()
        if i < len(micros):
            micros[i]["eq"] = valores
            micros[i]["eq_preset"] = self.var_eq_preset.get()
            config.guardar_microfonos(micros)
        self.padre.mezclador.aplicar_ajustes()

    def _guardar_mi_gusto(self):
        config.guardar({"eq_mi_gusto": self._valores_eq(),
                        "eq_preset": "A mi gusto"})
        self.var_eq_preset.set("A mi gusto")
        self._refrescar_eq()
        messagebox.showinfo("Microfono",
                            "Guardado como 'A mi gusto'.", parent=self)

    def _escuchar_micro(self):
        """Abre ESE microfono con el monitor, para oirse mientras se ajusta."""
        m = self.padre.mezclador
        if not m.corriendo:
            m.arrancar()
        i = self._indice_eq()
        if i >= len(m.canales):
            return
        canal = m.canales[i]
        if not canal.micro.abierto:
            messagebox.showwarning("Microfono", canal.error or
                                   "No se pudo abrir %s." % canal.nombre,
                                   parent=self)
            return
        canal.abierto = True
        self.padre._pintar_micros()
        messagebox.showinfo("Microfono",
                            "Microfono abierto. Habla y mueve las bandas.",
                            parent=self)

    def _pestana_transmision(self, nb):
        """
        Carpetas y datos que se graban dentro de cada MP3.

        Lo que se pone aqui es lo de siempre (la emisora, el autor, la
        caratula); el titulo de cada programa se escribe en la ventana
        principal, que cambia a diario.
        """
        f = ttk.Frame(nb, padding=px(12))
        nb.add(f, text="Transmision")
        f.columnconfigure(1, weight=1)
        fila = 0

        ttk.Label(f, text="CARPETAS", style="Suave.TLabel").grid(
            row=fila, column=0, columnspan=3, sticky="w")
        fila += 1
        ttk.Label(f, text="Musica:").grid(row=fila, column=0, sticky="w",
                                          pady=px(3))
        self.var_carpeta = tk.StringVar(value=config.get("carpeta_musica"))
        ttk.Entry(f, textvariable=self.var_carpeta, width=34).grid(
            row=fila, column=1, sticky="ew")
        ttk.Button(f, text="...", width=3,
                   command=lambda: self._elegir(self.var_carpeta)).grid(
            row=fila, column=2)
        fila += 1
        ttk.Label(f, text="Grabaciones:").grid(row=fila, column=0, sticky="w",
                                               pady=px(3))
        self.var_carpeta_grab = tk.StringVar(
            value=config.get("carpeta_grabaciones"))
        ttk.Entry(f, textvariable=self.var_carpeta_grab, width=34).grid(
            row=fila, column=1, sticky="ew")
        ttk.Button(f, text="...", width=3,
                   command=lambda: self._elegir(self.var_carpeta_grab)).grid(
            row=fila, column=2)
        fila += 1
        ttk.Label(f, text="En blanco = junto a la aplicacion (%s)."
                          % config.CARPETA_GRABA.name,
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        fila += 1

        ttk.Separator(f, orient="horizontal").grid(row=fila, column=0,
                                                   columnspan=3, sticky="ew",
                                                   pady=px(8))
        fila += 1
        ttk.Label(f, text="DATOS QUE SE GRABAN DENTRO DEL MP3",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        fila += 1

        self.vars_meta = {}
        campos = (("autor", "Autor:", "Fernando Erick Miranda"),
                  ("album_grabacion", "Album o temporada:", ""),
                  ("genero_grabacion", "Genero:", ""),
                  ("comentario", "Comentario:", ""))
        for clave, etiqueta, ayuda in campos:
            ttk.Label(f, text=etiqueta).grid(row=fila, column=0, sticky="w",
                                             pady=px(3))
            var = tk.StringVar(value=str(config.get(clave, "")))
            e = ttk.Entry(f, textvariable=var, width=34)
            e.grid(row=fila, column=1, columnspan=2, sticky="ew")
            e.bind("<KeyRelease>", lambda ev: self._refrescar_vista())
            self.vars_meta[clave] = var
            fila += 1
        ttk.Label(f, text="En blanco, cada uno toma el valor de la emisora. "
                          "El titulo se escribe en la ventana principal.",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        fila += 1

        ttk.Label(f, text="Caratula:").grid(row=fila, column=0, sticky="w",
                                            pady=px(3))
        self.var_portada = tk.StringVar(value=config.get("portada"))
        ttk.Entry(f, textvariable=self.var_portada, width=34).grid(
            row=fila, column=1, sticky="ew")
        ttk.Button(f, text="...", width=3,
                   command=self._elegir_portada).grid(row=fila, column=2)
        fila += 1
        ttk.Label(f, text="En blanco = la imagen de la aplicacion. Puedes poner "
                          "una distinta por temporada.",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        fila += 1

        ttk.Separator(f, orient="horizontal").grid(row=fila, column=0,
                                                   columnspan=3, sticky="ew",
                                                   pady=px(8))
        fila += 1
        ttk.Label(f, text="ASI SE VERA EN UN REPRODUCTOR",
                  style="Suave.TLabel").grid(row=fila, column=0, columnspan=3,
                                             sticky="w")
        fila += 1

        tarjeta = tk.Frame(f, bg=estilo.PANEL_HUND, bd=0,
                           highlightthickness=1,
                           highlightbackground=estilo.BORDE)
        tarjeta.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=px(6))
        self.lbl_tapa = tk.Label(tarjeta, bg=estilo.PANEL_HUND, bd=0,
                                 width=10, height=5)
        self.lbl_tapa.pack(side="left", padx=px(8), pady=px(8))
        letras = tk.Frame(tarjeta, bg=estilo.PANEL_HUND)
        letras.pack(side="left", fill="both", expand=True, pady=px(8))
        self.vista_meta = {}
        for clave, fuente, color in (
                ("title", ("Segoe UI Semibold", 11), estilo.TEXTO),
                ("artist", ("Segoe UI", 9), estilo.ACENTO),
                ("album", ("Segoe UI", 9), estilo.TEXTO_SUAVE),
                ("otros", ("Segoe UI", 8), estilo.TEXTO_SUAVE)):
            l = tk.Label(letras, text="", bg=estilo.PANEL_HUND, fg=color,
                         font=fuente, anchor="w", justify="left")
            l.pack(anchor="w", fill="x")
            self.vista_meta[clave] = l
        fila += 1

        ttk.Separator(f, orient="horizontal").grid(row=fila, column=0,
                                                   columnspan=3, sticky="ew",
                                                   pady=px(8))
        fila += 1
        self.var_grabar = tk.BooleanVar(value=bool(config.get("grabar_al_aire")))
        ttk.Checkbutton(f, text="Empezar a grabar sola al salir al aire",
                        variable=self.var_grabar).grid(row=fila, column=0,
                                                       columnspan=3, sticky="w")
        fila += 1
        self.var_reconectar = tk.BooleanVar(value=bool(config.get("reconectar")))
        ttk.Checkbutton(f, text="Reconectar solo si se cae el internet",
                        variable=self.var_reconectar).grid(row=fila, column=0,
                                                           columnspan=3,
                                                           sticky="w",
                                                           pady=px(4))
        self._refrescar_vista()

    def _elegir_portada(self):
        ruta = filedialog.askopenfilename(
            title="Elegir la caratula", parent=self,
            filetypes=[("Imagenes", "*.png *.jpg *.jpeg *.webp *.bmp"),
                       ("Todos", "*.*")])
        if ruta:
            self.var_portada.set(ruta)
            self._refrescar_vista()

    def _refrescar_vista(self):
        """
        Pinta la tarjeta con lo que se veria en un reproductor.

        Se calcula con las MISMAS funciones que graban el MP3, no con una copia
        del texto: si algo cambia ahi, aqui se ve al momento.
        """
        try:
            antes = {c: config.get(c) for c in list(self.vars_meta) + ["portada"]}
            config.guardar({c: v.get().strip()
                            for c, v in self.vars_meta.items()})
            config.guardar({"portada": self.var_portada.get().strip()})
            titulo = (self.padre.var_titulo.get().strip()
                      or self.padre.titulo_completo)
            datos = mod_grabador.etiquetas(titulo)
            tapa = mod_grabador.portada()
        except Exception:
            return

        self.vista_meta["title"].configure(text=datos.get("title", ""))
        self.vista_meta["artist"].configure(text=datos.get("artist", ""))
        self.vista_meta["album"].configure(text=datos.get("album", ""))
        self.vista_meta["otros"].configure(
            text="%s  ·  %s" % (datos.get("genre", ""), datos.get("date", "")))
        try:
            if tapa is not None:
                from PIL import Image, ImageTk
                im = Image.open(tapa)
                im.thumbnail((px(72), px(72)), Image.LANCZOS)
                self._tapa_vista = ImageTk.PhotoImage(im)
                self.lbl_tapa.configure(image=self._tapa_vista, text="",
                                        width=px(72), height=px(72))
            else:
                self._tapa_vista = None
                self.lbl_tapa.configure(image="", text="sin\
imagen",
                                        fg=estilo.TEXTO_SUAVE)
        except Exception:
            pass

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
        datos["emitir_mono"] = self.var_mono.get()
        datos["master_db"] = round(float(self.var_master.get()), 1)

        datos["monitor"] = self.var_monitor.get()
        datos["monitor_activo"] = self.var_mon_act.get()
        datos["volumen_monitor"] = round(
            mod_eq.db_a_ganancia(float(self.var_vol_mon.get())), 4)
        inverso_b = {v: k for k, v in BLOQUES_TEXTO.items()}
        datos["bloque_audio"] = inverso_b.get(self.var_bloque.get(), 512)
        datos["monitor_mudo_con_micro"] = self.var_mudo_micro.get()
        datos["proteccion_acople"] = self.var_anti_acople.get()
        micros = config.microfonos()
        while len(micros) < len(self.vars_micros):
            micros.append({"nombre": "", "dispositivo": "", "volumen": 0.9,
                           "eq_preset": "Plano", "eq": {}})
        for i, (v_nombre, v_disp) in enumerate(self.vars_micros):
            micros[i]["nombre"] = (v_nombre.get().strip()
                                   or "Micro %d" % (i + 1))[:14]
            micros[i]["dispositivo"] = v_disp.get().strip()
        # los canales sin aparato no se crean, pero se conserva su ficha
        config.guardar_microfonos(micros)

        inverso = {v: k for k, v in ESPACIO_TEXTOS.items()}
        datos["tecla_espacio"] = inverso.get(self.var_espacio.get(), ESPACIO_MICRO)
        datos["ducking"] = self.var_duck.get()
        datos["ducking_nivel"] = round(self.var_duck_niv.get() / 100.0, 2)
        datos["carpeta_musica"] = self.var_carpeta.get().strip()
        datos["carpeta_grabaciones"] = self.var_carpeta_grab.get().strip()
        for clave, var in self.vars_meta.items():
            datos[clave] = var.get().strip()
        datos["portada"] = self.var_portada.get().strip()
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
