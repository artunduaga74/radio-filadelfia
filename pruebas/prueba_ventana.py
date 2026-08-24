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
a.mezclador.niveles = {"micro": -6.0, "micro0": -6.0, "micro1": -60.0,
                       "musica": -20.0, "efectos": -60.0,
                       "aire_i": -3.0, "aire_d": -3.0, "reduccion": 0.0}
a._tic_rapido()
a.update()
encendidos = sum(1 for i in range(28)
                 if a.vu["micro0"].itemcget("seg%d" % i, "fill") != mod_app.estilo.VU_APAGADO)
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

print("")
print("=== Varios microfonos en la mesa ===")
check("hay un boton por microfono",
      len(a.botones_micro) == len(a.mezclador.canales),
      "%d botones / %d canales" % (len(a.botones_micro),
                                   len(a.mezclador.canales)))
check("hay un vumetro por microfono",
      all(("micro%d" % c.indice) in a.vu for c in a.mezclador.canales))
check("y un fader por microfono",
      all(("micro%d" % c.indice) in a.faders for c in a.mezclador.canales))
check("los botones llevan el nombre de cada uno",
      a.botones_micro[0].cget("text") == a.mezclador.canales[0].nombre,
      a.botones_micro[0].cget("text"))
a.mezclador.canales[0].abierto = True
a.mezclador.canales[1].abierto = False
a._pintar_micros()
a.update()
check("el abierto se pinta en rojo",
      str(a.botones_micro[0].cget("style")) == "MicOn.TButton")
check("y el cerrado no",
      str(a.botones_micro[1].cget("style")) == "MicOff.TButton")
a._fader_micro(1, 55)
check("el fader del invitado cambia SU volumen",
      abs(a.mezclador.canales[1].volumen - 0.55) < 0.01,
      "%.2f" % a.mezclador.canales[1].volumen)
check("y no toca el del locutor",
      abs(a.mezclador.canales[0].volumen - 0.55) > 0.01 or
      a.mezclador.canales[0].volumen != a.mezclador.canales[1].volumen)
a.mezclador.canales[0].abierto = False
a._pintar_micros()

print("")
print("=== Ventana del monitor de aire ===")
config.guardar({"host": "cast1.asurahosting.com", "puerto_publico": 8024})
a.abrir_monitor_aire()
for _ in range(20):
    a.update()
va = getattr(a, "_ventana_aire", None)
check("la ventana se abre", va is not None and va.winfo_exists())
if va:
    check("tiene su vumetro", va.vu is not None)
    check("dice algo del estado", bool(va.lbl_estado.cget("text")),
          va.lbl_estado.cget("text"))
    check("puede quedarse siempre visible",
          isinstance(va.var_encima.get(), bool))
    va._pintar()
    a.update()
    va.cerrar()
    a.update()
    check("al cerrarla deja de escuchar",
          va.vigilante.estado == "apagado", va.vigilante.estado)

print("")
print("=== La barra espaciadora funciona con el foco donde sea ===")
config.guardar({"tecla_espacio": mod_app.ESPACIO_MICRO})
a.mezclador.corriendo = True
for c in a.mezclador.canales:
    c.micro = MicroSimulado()

def espacio_con_foco(widget):
    """Pulsa la barra de verdad, con el foco puesto en ese widget."""
    a.mezclador.canales[0].abierto = False
    widget.focus_set()
    a.update()
    a.event_generate("<space>")
    a.update()
    return a.mezclador.canales[0].abierto

for nombre, w in (("la ventana", a),
                  ("el boton de play", a.btn_play),
                  ("el boton del microfono", a.botones_micro[0]),
                  ("la lista", a.tabla),
                  ("el boton de grabar", a.btn_rec)):
    check("abre el micro con el foco en %s" % nombre, espacio_con_foco(w))
a.mezclador.canales[0].abierto = False
a._pintar_micros()

print("")
print("=== La musica al abrir el microfono ===")
a.lista.limpiar()
a.lista.agregar(biblioteca.sondear(TONO))
a._pintar_lista()
a.siguiente_pista()
for _ in range(10):
    a.update()

# con "bajar musica al hablar" MARCADO: la musica sigue sonando (baja sola)
a.var_ducking.set(True)
a._cambio_ducking()
a.alternar_microfono(0)
a.update()
check("con el check puesto, la musica NO se para",
      a.mezclador.pista_a.sonando)
check("y el mezclador la baja solo", a.mezclador.ducking)
a.alternar_microfono(0)
a.update()
check("al cerrar sigue sonando", a.mezclador.pista_a.sonando)

# SIN el check: la musica se pausa mientras se habla y vuelve al cerrar
a.var_ducking.set(False)
a._cambio_ducking()
a.alternar_microfono(0)
a.update()
check("sin el check, la musica se PAUSA", not a.mezclador.pista_a.sonando)
check("el boton muestra el play", a.btn_play.cget("text") == mod_app.ICO_PLAY)
a.alternar_microfono(0)
a.update()
check("al cerrar el micro la musica VUELVE", a.mezclador.pista_a.sonando)
check("y el boton muestra la pausa",
      a.btn_play.cget("text") == mod_app.ICO_PAUSA)

# el modo "reproducir y pausa" manda por encima del check
config.guardar({"tecla_espacio": mod_app.ESPACIO_PLAY})
sonaba = a.mezclador.pista_a.sonando
a._atajo_espacio()
a.update()
check("en modo reproducir, la barra pausa aunque el check este quitado",
      a.mezclador.pista_a.sonando != sonaba)
config.guardar({"tecla_espacio": mod_app.ESPACIO_MICRO})
a.var_ducking.set(True)
a._cambio_ducking()

print("")
print("=== Auriculares: cambiar de aparato y anti-acople ===")
salidas = [n for _, n, _, _ in mod_app.audio.listar(entrada=False)]
if len(salidas) >= 2:
    config.guardar({"monitor": salidas[0], "monitor_activo": True})
    a.mezclador.cambiar_monitor()
    primero = a.mezclador._monitor_puesto
    config.guardar({"monitor": salidas[1]})
    ok_cambio, detalle = a.mezclador.cambiar_monitor()
    check("cambiar de auriculares surte efecto",
          a.mezclador._monitor_puesto == salidas[1] and
          a.mezclador._monitor_puesto != primero,
          "%s -> %s" % (primero[:18], a.mezclador._monitor_puesto[:18]))
config.guardar({"monitor": "Auriculares que ya no existen"})
a.mezclador.cambiar_monitor()
check("avisa si el aparato elegido ya no esta",
      "No se encontro" in (a.mezclador.aviso_monitor or ""),
      (a.mezclador.aviso_monitor or "-")[:40])

a.mezclador.monitor_mudo_con_micro = True
a.mezclador.canales[0].abierto = True
check("con el micro abierto, los auriculares se callan",
      a.mezclador._ganancia_monitor() == 0.0)
a.mezclador.canales[0].abierto = False
check("y al cerrarlo vuelven",
      a.mezclador._ganancia_monitor() == a.mezclador.vol_monitor)
a.mezclador.monitor_mudo_con_micro = False

a.mezclador.acople = True
check("si hay acople, los auriculares se cortan",
      a.mezclador._ganancia_monitor() == 0.0)
a.mezclador.acople = False
a.mezclador.corriendo = False

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
