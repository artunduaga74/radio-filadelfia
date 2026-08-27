# -*- coding: utf-8 -*-
"""
Comprobaciones del editor de metadatos, del titulo al aire y de los iconos.

Las tres cosas que se arreglaron el 2026-08-25:

  1. El autor desaparecia del "sonando ahora" (la radio ponia "Unknown")
     porque el cambio de cancion pisaba lo que se habia puesto con "Poner".
  2. El editor de metadatos: leer y escribir etiquetas de un programa ya
     grabado, sin recodificar y sin perder el archivo si algo falla.
  3. Al .ico le faltaban los tamanos que pide la barra de tareas cuando la
     pantalla esta escalada (30, 36 y 60 px).

Todo se MIDE: las etiquetas se releen con ffprobe, y la definicion del icono
se calcula, no se mira.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA.parent))

import config

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Leccion 8: las pruebas NUNCA escriben en la configuracion real del usuario.
pruebas = Path(tempfile.mkdtemp(prefix="radio_meta_"))
config.ARCHIVO_AJUSTES = pruebas / "ajustes.json"
config.ARCHIVO_CLAVES = pruebas / "credenciales.env"
config.CARPETA_DATOS = pruebas / "datos"
config.CARPETA_GRABA = pruebas / "grabaciones"
config._cache = None

import estilo
import metadatos
import servidor

ok, fallos = 0, []


def check(nombre, cond, detalle=""):
    global ok
    if cond:
        ok += 1
        print("  OK   %s %s" % (nombre, detalle))
    else:
        fallos.append(nombre)
        print("  FALLA %s %s" % (nombre, detalle))


def audio_de_prueba(ruta, segundos=2):
    """Un MP3 corto y sin etiquetas, hecho con ffmpeg."""
    subprocess.run([metadatos.FFMPEG, "-hide_banner", "-loglevel", "error",
                    "-y", "-f", "lavfi",
                    "-i", "aevalsrc=0.3*sin(440*2*PI*t):d=%d" % segundos,
                    "-c:a", "libmp3lame", str(ruta)], check=True)
    return ruta


print("")
print("=== 1. Como se compone el 'sonando ahora' ===")
# Medido contra el servidor real: Centova parte la cadena por el primer " - "
# para sacar el artista. Sin separador, el artista sale como "Unknown".
check("autor y titulo se juntan",
      servidor.componer_titulo("Simeon y Ana", "Fernando Miranda")
      == "Fernando Miranda - Simeon y Ana")
check("sin autor va solo el titulo",
      servidor.componer_titulo("Simeon y Ana", "") == "Simeon y Ana")
check("sin titulo va solo el autor",
      servidor.componer_titulo("", "Fernando Miranda") == "Fernando Miranda")
check("los espacios sobrantes se quitan",
      servidor.componer_titulo("  Simeon  ", "  Erick  ") == "Erick - Simeon")
check("no duplica el separador si ya venia compuesto",
      servidor.componer_titulo("Erick - Simeon", "Erick") == "Erick - Simeon",
      servidor.componer_titulo("Erick - Simeon", "Erick"))
check("los dos vacios no inventan nada",
      servidor.componer_titulo("", "") == "")

print("")
print("=== 2. El cambio de cancion ya no borra el autor ===")
# Este era el fallo: `biblioteca.etiqueta` devuelve SOLO el titulo cuando el
# archivo no trae artista, y se mandaba tal cual al servidor.
import biblioteca
sin_artista = {"titulo": "Pista suelta", "artista": ""}
check("el problema de origen sigue ahi (el archivo no dice el artista)",
      biblioteca.etiqueta(sin_artista) == "Pista suelta")


class VentanaFalsa(object):
    """Lo justo para probar la logica sin abrir la interfaz."""
    _texto_de_pista = None      # se rellena abajo


import app as mod_app

falsa = VentanaFalsa()
falsa._texto_de_pista = mod_app.App._texto_de_pista.__get__(falsa)
config.guardar({"nombre_emisora": "Voz de Filadelfia"})
check("sin artista en el archivo, firma la emisora",
      falsa._texto_de_pista(sin_artista) == "Voz de Filadelfia - Pista suelta",
      falsa._texto_de_pista(sin_artista))
con_artista = {"titulo": "Simeon y Ana", "artista": "Fernando Miranda"}
check("con artista en el archivo, se respeta",
      falsa._texto_de_pista(con_artista) == "Fernando Miranda - Simeon y Ana")
check("nunca queda sin separador (que es lo que da 'Unknown')",
      " - " in falsa._texto_de_pista(sin_artista))

print("")
print("=== 3. Leer etiquetas ===")
carpeta = pruebas / "audio"
carpeta.mkdir(parents=True, exist_ok=True)
mp3 = audio_de_prueba(carpeta / "programa.mp3")
leido = metadatos.leer(mp3)
check("lee un archivo recien hecho", leido["error"] == "", leido["error"])
check("mide la duracion", 1.5 < leido["duracion"] < 2.6,
      "%.2f s" % leido["duracion"])
check("un archivo pelado no tiene caratula", leido["tiene_portada"] is False)
falta = metadatos.leer(carpeta / "no_existe.mp3")
check("un archivo que no esta se avisa, no revienta",
      falta["error"] != "" and falta["etiquetas"] == {}, falta["error"])

print("")
print("=== 4. Escribir etiquetas (y releerlas) ===")
from PIL import Image
tapa = carpeta / "tapa.png"
Image.new("RGB", (400, 400), (20, 120, 180)).save(tapa)
datos = {"title": "Simeon y Ana", "artist": "Fernando Erick Miranda",
         "album": "Temporada 2", "genre": "Cristiano",
         "date": "2026-08-25", "comment": "prueba"}
correcto, detalle = metadatos.escribir(mp3, datos, portada=tapa)
check("guarda sin error", correcto, detalle)
r = metadatos.leer(mp3)["etiquetas"]
for clave, valor in datos.items():
    check("queda escrito %s" % clave, r.get(clave) == valor,
          repr(r.get(clave)))
check("pone tambien el artista del album (o los telefonos agrupan mal)",
      r.get("album_artist") == datos["artist"], repr(r.get("album_artist")))
check("firma la aplicacion", r.get("encoded_by") == "Filadelfia Broadcaster")
check("la caratula queda dentro", metadatos.leer(mp3)["tiene_portada"])

print("")
print("=== 5. El audio NO se recodifica ===")
antes = metadatos.leer(mp3)["duracion"]
metadatos.escribir(mp3, dict(datos, title="Otro titulo"))
despues = metadatos.leer(mp3)
check("la duracion no se mueve", abs(despues["duracion"] - antes) < 0.05,
      "%.3f -> %.3f" % (antes, despues["duracion"]))
check("la caratula se conserva sola", despues["tiene_portada"])
check("el titulo si cambio", despues["etiquetas"].get("title") == "Otro titulo")

print("")
print("=== 6. Borrar campos y quitar la caratula ===")
metadatos.escribir(mp3, {"title": "Solo el titulo"})
r = metadatos.leer(mp3)["etiquetas"]
check("lo que se deja en blanco desaparece", r.get("artist") is None,
      repr(r.get("artist")))
check("lo que se escribe queda", r.get("title") == "Solo el titulo")
metadatos.escribir(mp3, {"title": "Sin tapa"}, quitar_portada=True)
check("la caratula se puede quitar",
      metadatos.leer(mp3)["tiene_portada"] is False)

print("")
print("=== 7. Si algo falla, el archivo original no se pierde ===")
mp3b = audio_de_prueba(carpeta / "intacto.mp3")
metadatos.escribir(mp3b, {"title": "Bueno", "artist": "Erick"})
tamano_antes = os.path.getsize(mp3b)
correcto, detalle = metadatos.escribir(mp3b, {"title": "X"},
                                       portada=carpeta / "no_existe.png")
check("avisa de que la imagen no esta", correcto is False, detalle)
check("el archivo sigue igual de tamano",
      os.path.getsize(mp3b) == tamano_antes)
check("y conserva sus etiquetas",
      metadatos.leer(mp3b)["etiquetas"].get("title") == "Bueno")
sobras = [f for f in os.listdir(carpeta) if f.startswith(".meta_")]
check("no deja archivos temporales tirados", sobras == [], str(sobras))

print("")
print("=== 8. Extraer la caratula para enseniarla ===")
metadatos.escribir(mp3b, {"title": "Con tapa", "artist": "Erick"}, portada=tapa)
sale = metadatos.extraer_portada(mp3b, carpeta / "sale.jpg")
check("la saca a un archivo", sale is not None and os.path.exists(sale))
if sale:
    check("y es una imagen de verdad", Image.open(sale).size[0] > 0,
          str(Image.open(sale).size))
vacio = audio_de_prueba(carpeta / "vacio.mp3")
check("de un archivo sin caratula devuelve None",
      metadatos.extraer_portada(vacio, carpeta / "nada.jpg") is None)

print("")
print("=== 9. Los tamanos de icono que pide la barra de tareas ===")
import numpy as np


def definicion(imagen):
    """Cuanto contorno le queda. Numero grande = se ve nitido."""
    g = np.asarray(imagen.convert("L"), dtype=float)
    return float(np.sqrt((np.diff(g, axis=1) ** 2).mean()
                         + (np.diff(g, axis=0) ** 2).mean()))


medidas = [lado for lado, _ in estilo.MEDIDAS_ICONO]
for lado, escala in ((30, "125 %"), (36, "150 %"), (60, "250 %")):
    check("esta el de %d px (barra de tareas al %s)" % (lado, escala),
          lado in medidas)
check("siguen los de siempre",
      all(l in medidas for l in (16, 20, 24, 32, 48, 256)))

raiz = Path(__file__).resolve().parent.parent
ico = raiz / "icono.ico"
if ico.exists():
    from PIL import Image as Im
    archivo = Im.open(ico)
    guardados = sorted(lado for lado, _ in archivo.ico.sizes())
    check("el .ico los lleva todos dentro",
          guardados == sorted(medidas), str(guardados))
    original = Im.open(raiz / "icono.png").convert("RGBA")
    nativo = definicion(estilo._encoger(original, 36))
    encogido = definicion(archivo.ico.getimage((48, 48))
                          .convert("RGBA").resize((36, 36), Im.BILINEAR))
    check("a 36 px se ve mejor que dejandoselo a Windows",
          nativo > encogido * 1.3,
          "%.1f frente a %.1f" % (nativo, encogido))
    check("el de 36 del archivo es el bueno",
          abs(definicion(archivo.ico.getimage((36, 36))) - nativo) < 0.1,
          "%.1f" % definicion(archivo.ico.getimage((36, 36))))
else:
    print("      (no hay icono.ico: se genera al abrir la aplicacion)")

print("")
print("=== 10. La ventana, abierta de verdad desde la aplicacion ===")
import time

import procesos

ventana = mod_app.App()
ventana.update()
barra = ventana.nametowidget(ventana.cget("menu"))
etiquetas = [barra.entrycget(i, "label") for i in range(barra.index("end") + 1)]
check("hay un menu Metadatos", "Metadatos" in etiquetas, str(etiquetas))
check("esta justo al lado de Ver",
      etiquetas.index("Metadatos") == etiquetas.index("Ver") + 1, str(etiquetas))

editor = ventana.abrir_metadatos()
ventana.update()
check("la ventana del editor abre", bool(editor.winfo_exists()))
check("no se abren dos", ventana.abrir_metadatos() is editor)
check("estan los mismos campos que en Configuracion",
      sorted(editor.vars) == sorted(c for c, _ in metadatos.CAMPOS))
check("cabe en la pantalla (leccion 2)",
      editor.winfo_width() <= editor.winfo_screenwidth()
      and editor.winfo_height() <= editor.winfo_screenheight(),
      "%dx%d" % (editor.winfo_width(), editor.winfo_height()))
check("Guardar arranca apagado (no hay archivo)",
      "disabled" in editor.btn_guardar.state())

editor.abrir(str(mp3b))
ventana.update()
check("carga las etiquetas del archivo",
      editor.vars["title"].get() == "Con tapa", editor.vars["title"].get())
check("ensenia la caratula que trae", editor.tenia_portada)
check("recien abierto no hay nada que guardar", editor.hay_cambios() is False)
editor.vars["artist"].set("")
ventana.update()
check("sin autor, la vista previa avisa de 'Unknown'",
      "Unknown" in editor.vista["artist"].cget("text"),
      editor.vista["artist"].cget("text"))
check("y detecta el cambio", editor.hay_cambios() is True)

editor.vars["artist"].set("Fernando Erick Miranda")
editor.guardar()
for _ in range(100):                       # el hilo escribe; la ventana sondea
    ventana.update()
    time.sleep(0.05)
    if "Guardando" not in editor.lbl_estado.cget("text"):
        break
check("guarda desde la ventana", editor.lbl_estado.cget("text") == "Guardado.",
      editor.lbl_estado.cget("text"))
check("y el archivo lo tiene",
      metadatos.leer(mp3b)["etiquetas"].get("artist") == "Fernando Erick Miranda")
check("ya no quedan cambios pendientes", editor.hay_cambios() is False)
editor.cerrar()
ventana.update()
check("cierra sin preguntar si esta todo guardado",
      not editor.winfo_exists())
check("la aplicacion la olvida",
      getattr(ventana, "ventana_metadatos", None) is None)

print("")
print("=== 11. El titulo del programa manda sobre la musica ===")
ventana.var_titulo.set("Explorando el Apocalipsis")
ventana.var_autor_aire.set("Erick Miranda")
check("compone Autor - Titulo",
      ventana._texto_al_aire() == "Erick Miranda - Explorando el Apocalipsis",
      ventana._texto_al_aire())
check("de entrada no hay programa fijado", ventana.titulo_programa == "")
ventana.titulo_programa = ventana._texto_al_aire()
check("una vez puesto, queda fijado",
      ventana.titulo_programa == "Erick Miranda - Explorando el Apocalipsis")
ventana.var_titulo.set("")
ventana.var_autor_aire.set("")
ventana.poner_titulo()
check("vaciando los dos campos se suelta y vuelve a anunciar canciones",
      ventana.titulo_programa == "")

try:
    ventana._al_cerrar()
except Exception:
    pass
try:
    ventana.destroy()
except Exception:
    pass
procesos.cerrar_todos()

print("")
print("=" * 62)
print("  %d comprobaciones OK, %d fallos" % (ok, len(fallos)))
if fallos:
    print("  Fallaron: " + ", ".join(fallos))
print("=" * 62)
sys.exit(1 if fallos else 0)
