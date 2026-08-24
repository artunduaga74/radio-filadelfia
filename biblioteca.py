# -*- coding: utf-8 -*-
"""
La carpeta de trabajo: musica, cortinas y listas de reproduccion.

Los datos de cada archivo (duracion, artista, titulo) se leen con ffprobe una
sola vez y se guardan en un indice; volver a abrir la carpeta es instantaneo
aunque tenga miles de canciones.
"""

import json
import os
import subprocess
import threading
from pathlib import Path

import config
import procesos

FFPROBE = "ffprobe"

EXTENSIONES = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
               ".wma", ".aiff", ".aif", ".mp2", ".mp4"}


def sondear(ruta):
    """Duracion y etiquetas de un archivo. Devuelve un diccionario."""
    base = {"ruta": str(ruta), "titulo": Path(ruta).stem, "artista": "",
            "album": "", "duracion": 0.0}
    cmd = [FFPROBE, "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", str(ruta)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=25,
                           creationflags=procesos.SIN_VENTANA)
        d = json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception:
        return base
    fmt = d.get("format", {})
    try:
        base["duracion"] = float(fmt.get("duration", 0) or 0)
    except Exception:
        pass
    etiquetas = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    for s in d.get("streams", []):
        if s.get("codec_type") == "audio":
            etiquetas.update({k.lower(): v for k, v in (s.get("tags") or {}).items()})
            break
    base["titulo"] = (etiquetas.get("title") or base["titulo"]).strip()
    base["artista"] = (etiquetas.get("artist") or etiquetas.get("album_artist") or "").strip()
    base["album"] = (etiquetas.get("album") or "").strip()
    return base


def etiqueta(pista):
    """Como se muestra al aire: 'Artista - Titulo'."""
    a, t = pista.get("artista", ""), pista.get("titulo", "")
    return ("%s - %s" % (a, t)) if a else t


def duracion_texto(segundos):
    segundos = int(max(0, segundos))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return ("%d:%02d:%02d" % (h, m, s)) if h else ("%d:%02d" % (m, s))


class Biblioteca:
    """Indice de una carpeta con su cache en disco."""

    def __init__(self, carpeta="", nombre_indice="indice_musica.json"):
        self.carpeta = str(carpeta or "")
        config.asegurar_carpetas()
        self.indice = config.CARPETA_DATOS / nombre_indice
        self.pistas = []
        self._cache = self._leer_cache()
        self._lock = threading.Lock()

    def _leer_cache(self):
        try:
            if self.indice.exists():
                return json.loads(self.indice.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _guardar_cache(self):
        try:
            tmp = self.indice.with_suffix(".escribiendo")
            tmp.write_text(json.dumps(self._cache, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, self.indice)
        except Exception:
            pass

    def archivos(self):
        """Todos los audios de la carpeta y sus subcarpetas."""
        if not self.carpeta or not os.path.isdir(self.carpeta):
            return []
        fuera = []
        for raiz, _, nombres in os.walk(self.carpeta):
            for n in sorted(nombres):
                if Path(n).suffix.lower() in EXTENSIONES:
                    fuera.append(os.path.join(raiz, n))
        return fuera

    def explorar(self, al_avanzar=None, parar=None):
        """
        Lee la carpeta. Solo consulta con ffprobe los archivos nuevos o los que
        cambiaron de tamano, asi que la segunda vez es inmediata.
        """
        rutas = self.archivos()
        total = len(rutas)
        pistas = []
        nuevos = 0
        for i, ruta in enumerate(rutas):
            if parar and parar():
                break
            try:
                tam = os.path.getsize(ruta)
            except OSError:
                continue
            clave = "%s|%d" % (ruta, tam)
            info = self._cache.get(clave)
            if not info:
                info = sondear(ruta)
                info["tam"] = tam
                self._cache[clave] = info
                nuevos += 1
            pistas.append(dict(info, ruta=ruta))
            if al_avanzar and (i % 5 == 0 or i == total - 1):
                al_avanzar(i + 1, total, os.path.basename(ruta))
        with self._lock:
            self.pistas = pistas
        if nuevos:
            self._guardar_cache()
        return pistas

    def buscar(self, texto):
        if not texto:
            return list(self.pistas)
        t = texto.lower().strip()
        palabras = t.split()
        fuera = []
        for p in self.pistas:
            heno = ("%s %s %s %s" % (p.get("titulo", ""), p.get("artista", ""),
                                     p.get("album", ""),
                                     os.path.basename(p.get("ruta", "")))).lower()
            if all(w in heno for w in palabras):
                fuera.append(p)
        return fuera


class Lista:
    """
    La lista de lo que va a sonar. Es lo que se transmite cuando no se habla:
    se arma antes y la aplicacion la va reproduciendo sola, una tras otra.
    """

    def __init__(self):
        self.pistas = []
        self.actual = -1
        self.repetir = True
        self.mezclar = False
        self.ruta = ""

    def agregar(self, pista, posicion=None):
        if posicion is None:
            self.pistas.append(dict(pista))
        else:
            self.pistas.insert(posicion, dict(pista))

    def agregar_varias(self, pistas):
        for p in pistas:
            self.agregar(p)

    def quitar(self, indice):
        if 0 <= indice < len(self.pistas):
            self.pistas.pop(indice)
            if indice < self.actual:
                self.actual -= 1
            elif indice == self.actual:
                self.actual = min(self.actual, len(self.pistas) - 1)

    def mover(self, desde, hasta):
        if 0 <= desde < len(self.pistas) and 0 <= hasta < len(self.pistas):
            p = self.pistas.pop(desde)
            self.pistas.insert(hasta, p)

    def limpiar(self):
        self.pistas = []
        self.actual = -1

    def siguiente(self):
        """La proxima pista (y avanza el puntero). None si se acabo."""
        if not self.pistas:
            return None
        if self.mezclar:
            import random
            self.actual = random.randrange(len(self.pistas))
            return self.pistas[self.actual]
        self.actual += 1
        if self.actual >= len(self.pistas):
            if not self.repetir:
                self.actual = len(self.pistas) - 1
                return None
            self.actual = 0
        return self.pistas[self.actual]

    def ir_a(self, indice):
        if 0 <= indice < len(self.pistas):
            self.actual = indice
            return self.pistas[indice]
        return None

    @property
    def duracion_total(self):
        return sum(float(p.get("duracion", 0) or 0) for p in self.pistas)

    def restante_desde_actual(self):
        i = max(0, self.actual)
        return sum(float(p.get("duracion", 0) or 0) for p in self.pistas[i:])

    # ------------------------------------------------------- guardar / abrir

    def guardar(self, ruta):
        datos = {"version": 1, "repetir": self.repetir, "mezclar": self.mezclar,
                 "pistas": self.pistas}
        tmp = str(ruta) + ".escribiendo"
        Path(tmp).write_text(json.dumps(datos, indent=1, ensure_ascii=False),
                             encoding="utf-8")
        os.replace(tmp, str(ruta))
        self.ruta = str(ruta)

    def abrir(self, ruta):
        d = json.loads(Path(ruta).read_text(encoding="utf-8"))
        self.pistas = [p for p in d.get("pistas", []) if p.get("ruta")]
        self.repetir = bool(d.get("repetir", True))
        self.mezclar = bool(d.get("mezclar", False))
        self.actual = -1
        self.ruta = str(ruta)
        return len(self.pistas)

    def exportar_m3u(self, ruta):
        lineas = ["#EXTM3U"]
        for p in self.pistas:
            lineas.append("#EXTINF:%d,%s" % (int(p.get("duracion", 0)), etiqueta(p)))
            lineas.append(p["ruta"])
        Path(ruta).write_text("\n".join(lineas), encoding="utf-8")

    def importar_m3u(self, ruta):
        base = Path(ruta).parent
        for linea in Path(ruta).read_text(encoding="utf-8", errors="replace").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            p = Path(linea)
            if not p.is_absolute():
                p = base / p
            if p.exists():
                self.agregar(sondear(p))
        return len(self.pistas)
