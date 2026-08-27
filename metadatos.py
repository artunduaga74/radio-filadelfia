# -*- coding: utf-8 -*-
"""
Leer y escribir las etiquetas de un archivo de audio ya grabado.

Por que existe: `grabador.py` pone las etiquetas MIENTRAS graba, con lo que
diga la configuracion. Pero a un programa ya guardado no se le puede cambiar
nada, y siempre hay algo que corregir despues: el titulo que se escribio con
prisa, el numero del episodio, la caratula de la temporada nueva.

Se usa ffmpeg/ffprobe, que ya son necesarios para todo lo demas: no hace falta
otra dependencia. Los campos son EXACTAMENTE los mismos que escribe
`grabador.etiquetas()`, para que un archivo retocado a mano no se distinga de
uno recien grabado.

Regla de seguridad: nunca se escribe encima del original. Se genera un archivo
temporal completo y solo si ffmpeg termina bien se sustituye (`os.replace`, que
en Windows es atomico dentro del mismo disco). Si falla a mitad, el programa
grabado sigue intacto.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import procesos

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

EXTENSIONES = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav", ".wma")

# Orden y rotulo de los campos, el mismo de Configuracion -> Transmision.
# (clave del contenedor, rotulo en pantalla)
CAMPOS = (
    ("title", "Titulo:"),
    ("artist", "Autor:"),
    ("album", "Album o temporada:"),
    ("genre", "Genero:"),
    ("date", "Fecha:"),
    ("comment", "Comentario:"),
)

# Los que se escriben pero no se editan a mano.
DERIVADOS = ("album_artist",)


def _sin_consola():
    """En Windows, que ffprobe no abra una ventana negra."""
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": si}


def leer(ruta):
    """
    Devuelve {"etiquetas": {...}, "duracion": s, "tiene_portada": bool}.

    Las claves de las etiquetas vienen en minusculas: los contenedores no se
    ponen de acuerdo en si es TITLE, title o Title.
    """
    vacio = {"etiquetas": {}, "duracion": 0.0, "tiene_portada": False,
             "error": ""}
    ruta = str(ruta)
    if not os.path.exists(ruta):
        vacio["error"] = "No se encuentra el archivo"
        return vacio
    cmd = [FFPROBE, "-hide_banner", "-loglevel", "error", "-of", "json",
           "-show_format", "-show_streams", ruta]
    try:
        salida = subprocess.run(cmd, capture_output=True, timeout=30,
                                **_sin_consola())
        datos = json.loads(salida.stdout.decode("utf-8", "replace") or "{}")
    except Exception as e:
        vacio["error"] = "%s: %s" % (type(e).__name__, e)
        return vacio

    formato = datos.get("format") or {}
    etiquetas = {str(k).lower(): str(v)
                 for k, v in (formato.get("tags") or {}).items()}
    # algunos contenedores guardan las etiquetas en la pista de audio
    for pista in datos.get("streams") or []:
        if pista.get("codec_type") == "audio":
            for k, v in (pista.get("tags") or {}).items():
                etiquetas.setdefault(str(k).lower(), str(v))

    tiene = any(p.get("codec_type") == "video"
                and (p.get("disposition") or {}).get("attached_pic")
                for p in datos.get("streams") or [])
    try:
        duracion = float(formato.get("duration") or 0.0)
    except (TypeError, ValueError):
        duracion = 0.0
    return {"etiquetas": etiquetas, "duracion": duracion,
            "tiene_portada": tiene, "error": ""}


def extraer_portada(ruta, destino):
    """
    Saca la caratula incrustada a un archivo suelto. Devuelve la ruta o None.

    Sirve para enseniarla en la ventana sin tocar el original.
    """
    destino = str(destino)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(ruta),
           "-an", "-map", "0:v?", "-frames:v", "1", "-c:v", "copy", destino]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30, **_sin_consola())
    except Exception:
        return None
    return destino if os.path.exists(destino) and os.path.getsize(destino) else None


def _valores(datos):
    """Limpia lo que llega de la ventana y aniade los campos derivados."""
    fuera = {}
    for clave, valor in (datos or {}).items():
        valor = (valor or "").strip()
        if valor:
            fuera[str(clave).lower()] = valor
    if fuera.get("artist") and not fuera.get("album_artist"):
        # sin este campo, muchos telefonos agrupan los programas por "Varios"
        fuera["album_artist"] = fuera["artist"]
    if fuera.get("date") and not fuera.get("TYER"):
        fuera["TYER"] = fuera["date"][:4]
    return fuera


def escribir(ruta, datos, portada=None, quitar_portada=False):
    """
    Guarda las etiquetas dentro del archivo. Devuelve (ok, explicacion).

    - `datos`: {"title": ..., "artist": ...}. Los campos que no vengan se
      BORRAN del archivo (`-map_metadata -1`), que es lo que uno espera de un
      editor: lo que se ve en pantalla es lo que queda.
    - `portada`: ruta de una imagen nueva. Si es None se conserva la que haya.
    - `quitar_portada`: la saca y no pone ninguna.

    El audio no se recodifica en ningun caso (`-c copy`): la calidad del
    programa no se toca por cambiarle el titulo.
    """
    origen = Path(ruta)
    if not origen.exists():
        return False, "No se encuentra el archivo"

    campos = _valores(datos)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(origen)]
    if portada:
        if not Path(portada).exists():
            return False, "No se encuentra la imagen de la caratula"
        cmd += ["-i", str(portada)]

    cmd += ["-map", "0:a", "-c", "copy", "-map_metadata", "-1"]
    if portada:
        cmd += ["-map", "1:v", "-c:v", "mjpeg"]
    elif not quitar_portada:
        cmd += ["-map", "0:v?"]
    if portada or not quitar_portada:
        cmd += ["-disposition:v", "attached_pic",
                "-metadata:s:v", "title=Portada",
                "-metadata:s:v", "comment=Cover (front)"]

    for clave, valor in campos.items():
        cmd += ["-metadata", "%s=%s" % (clave, valor)]
    cmd += ["-metadata", "encoded_by=Filadelfia Broadcaster"]
    if origen.suffix.lower() == ".mp3":
        cmd += ["-id3v2_version", "3", "-write_id3v1", "1"]

    # temporal en la MISMA carpeta: os.replace solo es atomico dentro del
    # mismo disco, y la carpeta de grabaciones puede estar en otra unidad
    tmp = tempfile.NamedTemporaryFile(delete=False, dir=str(origen.parent),
                                      prefix=".meta_", suffix=origen.suffix)
    tmp.close()
    try:
        proc = procesos.lanzar(cmd + [tmp.name], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, err = proc.communicate(timeout=180)
        if proc.returncode != 0 or not os.path.getsize(tmp.name):
            detalle = (err or b"").decode("utf-8", "replace").strip()
            return False, (detalle.splitlines()[-1][:180] if detalle
                           else "ffmpeg no pudo escribir el archivo")
        os.replace(tmp.name, str(origen))
        return True, "Guardado"
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)
    finally:
        try:
            if os.path.exists(tmp.name):
                os.remove(tmp.name)
        except Exception:
            pass
