# -*- coding: utf-8 -*-
"""Comprobaciones de la ventana. Escribe la config en una carpeta de PRUEBAS."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

# la consola de Windows viene en cp1252 y no sabe pintar los
# iconos del reproductor; sin esto, un print rompe la prueba
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

pruebas = Path(tempfile.mkdtemp(prefix="radio_ui_"))
config.ARCHIVO_AJUSTES = pruebas / "ajustes.json"
config.ARCHIVO_CLAVES = pruebas / "credenciales.env"
config.CARPETA_DATOS = pruebas / "datos"
config.CARPETA_GRABA = pruebas / "grabaciones"
config._cache = None

import tkinter as tk
import numpy as np

import biblioteca
import app as mod_app

CARPETA = Path(__file__).parent / "medios"
TONO = str(CARPETA / "tono.wav")
JINGLE = str(CARPETA / "jingle.wav")

ok, fallos = 0, []


def check(nombre, cond, detalle=""):
    global ok
    if cond:
        ok += 1
        print("  OK   %s %s" % (nombre, detalle))
    else:
        fallos.append(nombre)
        print("  FALLA %s %s" % (nombre, detalle))


print("\n=== Abriendo la ventana ===")
a = mod_app.App()
a.update()
a.update_idletasks()
check("la ventana cabe en la pantalla",
      a.winfo_width() <= a.winfo_screenwidth() and
      a.winfo_height() <= a.winfo_screenheight() - 30,
      "%dx%d en pantalla %dx%d" % (a.winfo_width(), a.winfo_height(),
                                   a.winfo_screenwidth(), a.winfo_screenheight()))
a.update()
a.update_idletasks()
check("la ventana abre", a.winfo_exists())
check("titulo correcto", a.title() == mod_app.TITULO, a.title())

print("\n=== Todo cabe en la ventana ===")
alto_ventana = a.winfo_height()
for nombre, w in (("boton AL AIRE", a.btn_aire),
                  ("boton microfono", a.btn_micro),
                  ("lista", a.tabla),
                  ("vumetro del aire", a.vu["aire_i"]),
                  ("grafico de oyentes", a.grafico),
                  ("barra de estado", a.lbl_msg)):
    y = w.winfo_rooty() - a.winfo_rooty()
    dentro = w.winfo_ismapped() and 0 <= y < alto_ventana and w.winfo_width() > 1
    check("se ve: %s" % nombre, dentro,
          "y=%d alto=%d ancho=%d" % (y, w.winfo_height(), w.winfo_width()))

print("\n=== Ventana pequena (minimo) ===")
a.geometry("940x620")
a.update()
a.update_idletasks()
alto_ventana = a.winfo_height()
for nombre, w in (("boton AL AIRE", a.btn_aire),
                  ("boton microfono", a.btn_micro),
                  ("barra de estado", a.lbl_msg)):
    y = w.winfo_rooty() - a.winfo_rooty()
    check("sigue visible en 940x620: %s" % nombre,
          w.winfo_ismapped() and 0 <= y < alto_ventana, "y=%d" % y)
a.geometry("1180x720")
a.update()

print("\n=== Lista de reproduccion ===")
a.lista.agregar(biblioteca.sondear(TONO))
a.lista.agregar(biblioteca.sondear(JINGLE))
a._pintar_lista()
a.update()
check("aparecen las 2 pistas", len(a.tabla.get_children()) == 2,
      "%d filas" % len(a.tabla.get_children()))
check("muestra el resumen", "2 pistas" in a.lbl_lista.cget("text"),
      a.lbl_lista.cget("text"))

a.var_busca.set("jingle")
a._filtrar()
a.update()
check("el buscador filtra", len(a.tabla.get_children()) == 1,
      "%d filas" % len(a.tabla.get_children()))
a.var_busca.set("")
a._filtrar()

a.tabla.selection_set("0")
a.mover_seleccion(1)
check("se puede reordenar", a.lista.pistas[1]["ruta"] == TONO)
a.tabla.selection_set("0")
a.quitar_seleccion()
check("se puede quitar", len(a.lista.pistas) == 1)

print("\n=== Reproduccion (sin salir al aire) ===")
a.lista.limpiar()
a.lista.agregar(biblioteca.sondear(TONO))
a._pintar_lista()
a.siguiente_pista()
for _ in range(20):
    a.update()
p = a.mezclador.pista_a
check("la pista quedo cargada", p.ruta == TONO)
check("esta sonando", p.sonando)
check("el titulo aparece en pantalla", a.lbl_pista.cget("text") != "- nada -",
      a.lbl_pista.cget("text"))
check("la fila se marca como sonando", "sonando" in a.tabla.item("0", "tags"))
a.play_pausa()
check("pausa funciona", not p.sonando)
check("el boton cambia al icono de play",
      a.btn_play.cget("text") == mod_app.ICO_PLAY,
      repr(a.btn_play.cget("text")))
a.play_pausa()
check("reanuda", p.sonando)

print("\n=== Vumetros ===")
a.mezclador.niveles = {"micro": -6.0, "musica": -20.0, "efectos": -60.0,
                       "aire_i": -3.0, "aire_d": -3.0, "reduccion": 0.0}
a._tic_rapido()
a.update()
encendidos = sum(1 for i in range(28)
                 if a.vu["micro"].itemcget("seg%d" % i, "fill") != mod_app.estilo.VU_APAGADO)
check("el vumetro del micro se enciende", encendidos > 20, "%d segmentos" % encendidos)
apagados = sum(1 for i in range(28)
               if a.vu["efectos"].itemcget("seg%d" % i, "fill") == mod_app.estilo.VU_APAGADO)
check("en silencio queda apagado", apagados >= 27, "%d apagados" % apagados)

print("\n=== Cortinas ===")
a.cortinas[0] = JINGLE
a.disparar_cortina(0)
for _ in range(5):
    a.update()
check("la cortina suena encima", len(a.mezclador.efectos) == 1)
a.mezclador.parar_efectos()

print("")
print("=== Botones de transporte con iconos ===")
import tkinter.font as tkfont
fuente = tkfont.Font(family="Segoe UI Symbol", size=15)
for nombre, icono in (("play", mod_app.ICO_PLAY), ("pausa", mod_app.ICO_PAUSA),
                      ("parar", mod_app.ICO_PARAR),
                      ("siguiente", mod_app.ICO_SIGUIENTE),
                      ("grabar", mod_app.ICO_REC)):
    check("el icono de %s se dibuja" % nombre, fuente.measure(icono) > 3,
          "%d px" % fuente.measure(icono))
check("los botones siguen grandes", a.btn_play.winfo_width() >= 30,
      "%d px de ancho" % a.btn_play.winfo_width())

print("")
print("=== Boton de grabar (independiente del aire) ===")
check("arranca sin grabar", not a.grabador.grabando)
check("dice Grabar", "Grabar" in a.btn_rec.cget("text"))
a.alternar_grabacion()
for _ in range(10):
    a.update()
check("empieza a grabar sin estar al aire",
      a.grabador.grabando and not a.emisor.al_aire)
a._pintar_grabacion()
a.update()
check("el boton se pone en rojo",
      str(a.btn_rec.cget("style")) == "RecOn.TButton", str(a.btn_rec.cget("style")))
check("la barra de estado lo dice",
      "grabando" in a.lbl_grabando.cget("text"), a.lbl_grabando.cget("text"))
archivo = a.grabador.archivo
a.alternar_grabacion()
a.update()
check("se puede parar", not a.grabador.grabando)
check("y queda el archivo", bool(archivo) and Path(archivo).exists(),
      Path(archivo).name if archivo else "-")
check("el boton vuelve a su sitio",
      str(a.btn_rec.cget("style")) == "Rec.TButton")

print("")
print("=== Cortinas con nombre propio ===")
check("arrancan numeradas", a.botones_cortina[0].cget("text") == "1",
      repr(a.botones_cortina[0].cget("text")))
a.cortinas[0] = JINGLE
a.nombres_cortina[0] = ""
a._pintar_cortina(0)
check("al asignar audio toma el nombre del archivo",
      a.botones_cortina[0].cget("text") == "jingle",
      repr(a.botones_cortina[0].cget("text")))
a.nombres_cortina[0] = "Entrada"
a._pintar_cortina(0)
a._guardar_cortinas()
check("se puede poner el nombre que uno quiera",
      a.botones_cortina[0].cget("text") == "Entrada")
guardado = config.cargar()
check("el nombre queda guardado",
      (guardado.get("cortinas_nombres") or [""])[0] == "Entrada",
      repr((guardado.get("cortinas_nombres") or [""])[0]))
check("y el audio tambien",
      (guardado.get("cortinas") or [None])[0] == JINGLE)
a.nombres_cortina[0] = "1"
a._pintar_cortina(0)
check("se puede cambiar por un numero", a.botones_cortina[0].cget("text") == "1")
a.quitar_cortina(0)
check("al quitarla vuelve a su numero",
      a.botones_cortina[0].cget("text") == "1" and a.cortinas[0] is None)
check("las demas siguen numeradas",
      [b.cget("text") for b in a.botones_cortina[1:]] == ["2", "3", "4"],
      str([b.cget("text") for b in a.botones_cortina[1:]]))

print("")
print("=== Barra espaciadora configurable ===")
check("por defecto abre el microfono",
      config.get("tecla_espacio") == mod_app.ESPACIO_MICRO,
      repr(config.get("tecla_espacio")))

class FocoFalso:
    """Para simular que el foco NO esta en un campo de texto."""
    pass

a.focus_get = lambda: None          # como si el foco estuviera en la ventana

class MicroSimulado:
    """El micro real puede no abrirse en un equipo de pruebas; simulamos uno."""
    abierto = True
    error = ""

    def leer(self, n):
        return np.zeros((n, 2), dtype=np.float32)

    def cerrar(self):
        pass

a.mezclador.micro = MicroSimulado()
a.mezclador.micro_abierto = False
antes_musica = a.mezclador.pista_a.sonando
a._atajo_espacio()
a.update()
check("la barra ABRE el microfono", a.mezclador.micro_abierto is True)
check("el boton se pone en rojo",
      str(a.btn_micro.cget("style")) == "MicOn.TButton",
      str(a.btn_micro.cget("style")))
check("y NO toca la musica", a.mezclador.pista_a.sonando == antes_musica)
a._atajo_espacio()
a.update()
check("y la barra lo CIERRA", a.mezclador.micro_abierto is False)
check("el boton vuelve a apagado",
      str(a.btn_micro.cget("style")) == "MicOff.TButton")

config.guardar({"tecla_espacio": mod_app.ESPACIO_PLAY})
sonaba = a.mezclador.pista_a.sonando
a._atajo_espacio()
a.update()
check("puesta en reproducir, la barra da al play/pausa",
      a.mezclador.pista_a.sonando != sonaba,
      "%s -> %s" % (sonaba, a.mezclador.pista_a.sonando))

config.guardar({"tecla_espacio": mod_app.ESPACIO_NADA})
sonaba = a.mezclador.pista_a.sonando
micro = a.mezclador.micro_abierto
a._atajo_espacio()
a.update()
check("desactivada, la barra no hace nada",
      a.mezclador.pista_a.sonando == sonaba and
      a.mezclador.micro_abierto == micro)

config.guardar({"tecla_espacio": mod_app.ESPACIO_MICRO})

class EntryFalso(tk.Entry):
    pass

campo = tk.Entry(a)
a.focus_get = lambda: campo
micro = a.mezclador.micro_abierto
a._atajo_espacio()
check("escribiendo en un campo, la barra no dispara nada",
      a.mezclador.micro_abierto == micro)
campo.destroy()
a.focus_get = lambda: None

print("\n=== Estado del aire ===")
check("arranca fuera del aire", not a.emisor.al_aire)
check("el boton dice SALIR AL AIRE", a.btn_aire.cget("text") == "SALIR AL AIRE",
      a.btn_aire.cget("text"))
check("el micro arranca cerrado", not a.mezclador.micro_abierto)

print("\n=== Configuracion ===")
config.guardar({"vol_musica": 0.55})
a.mezclador.aplicar_ajustes()
check("los faders llegan al mezclador", abs(a.mezclador.vol_musica - 0.55) < 0.01,
      "%.2f" % a.mezclador.vol_musica)

print("\n=== Cierre limpio ===")
a.vigilante.detener()
a.emisor.detener()
a.mezclador.detener()
existia = a.winfo_exists()
a.destroy()
try:
    cerrada = not a.winfo_exists()
except tk.TclError:
    cerrada = True
check("la ventana se cerro", existia and cerrada)

import procesos
procesos.cerrar_todos()
vivos = [p for p in procesos._vivos if p.poll() is None]
check("no quedan procesos sueltos", len(vivos) == 0, "%d vivos" % len(vivos))

print("\n" + "=" * 60)
print("  %d comprobaciones OK, %d fallos" % (ok, len(fallos)))
if fallos:
    print("  Fallaron: " + ", ".join(fallos))
print("  Config de pruebas en: %s" % pruebas)
print("=" * 60)
sys.exit(1 if fallos else 0)
