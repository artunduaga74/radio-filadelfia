# -*- coding: utf-8 -*-
"""
Todo lo que se le pregunta o se le manda al servidor de streaming.

Confirmado contra el servidor real (SHOUTcast DNAS 2.6.1.777 en Centova Cast):
  http://HOST:8024/stats?sid=1&json=1     -> oyentes, pico, titulo... SIN clave
  http://HOST:8024/statistics?json=1      -> resumen global
  http://HOST:8024/7.html                 -> formato viejo, de reserva

El historial de oyentes se guarda en SQLite, junto a la app, para poder ver
despues cuanta gente hubo el domingo a las 8.
"""

import json as _json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

import config

TIEMPO_ESPERA = 10


def _pedir(url, tiempo=TIEMPO_ESPERA):
    peticion = urllib.request.Request(url, headers={"User-Agent": "VozFiladelfia/1.0"})
    with urllib.request.urlopen(peticion, timeout=tiempo) as r:
        return r.read().decode("utf-8", "replace")


def _base_publica():
    host = config.get("host", "").strip()
    if not host:
        return ""
    host = host.replace("http://", "").replace("https://", "").strip("/")
    return "http://%s:%s" % (host, config.get("puerto_publico", 8024))


def estado():
    """
    Estado actual de la senal. Devuelve siempre un diccionario con las mismas
    claves; si el servidor no responde, en_linea viene en False y el resto en
    cero, para que la interfaz nunca tenga que adivinar.
    """
    vacio = {
        "en_linea": False, "oyentes": 0, "pico": 0, "maximo": 0, "unicos": 0,
        "titulo": "", "bitrate": 0, "uptime": 0, "dj": "", "emisora": "",
        "error": "", "momento": time.time(),
    }
    base = _base_publica()
    if not base:
        vacio["error"] = "Falta configurar el servidor"
        return vacio
    try:
        d = _json.loads(_pedir(base + "/stats?sid=1&json=1"))
        return {
            "en_linea": bool(d.get("streamstatus", 0)),
            "oyentes": int(d.get("currentlisteners", 0) or 0),
            "pico": int(d.get("peaklisteners", 0) or 0),
            "maximo": int(d.get("maxlisteners", 0) or 0),
            "unicos": int(d.get("uniquelisteners", 0) or 0),
            "titulo": (d.get("songtitle") or "").strip(),
            "bitrate": int(str(d.get("bitrate", 0) or 0).strip() or 0),
            "uptime": int(d.get("streamuptime", 0) or 0),
            "dj": (d.get("dj") or "").strip(),
            "emisora": (d.get("servertitle") or "").strip(),
            "error": "",
            "momento": time.time(),
        }
    except Exception as e:
        vacio["error"] = "%s: %s" % (type(e).__name__, e)
        return vacio


def componer_titulo(titulo, autor):
    """
    Lo que se lee en la radio, en el formato que esperan los reproductores.

    SHOUTcast manda **una sola cadena** de texto, no dos campos. Centova (y con
    el todos los reproductores web y los telefonos) la parte por el primer
    " - " para sacar el artista y el titulo: por eso, mandando solo el titulo,
    el hueco del artista sale como "Unknown".

    Comprobado contra el servidor real el 2026-08-25:
        rawmeta "Fernando Miranda - Simeon y Ana"
        -> track {"artist": "Fernando Miranda", "title": "Simeon y Ana"}

    Aguanta que falte cualquiera de los dos, y quita un " - " que ya viniera
    escrito en el titulo para no acabar con dos separadores.
    """
    titulo = (titulo or "").strip()
    autor = (autor or "").strip()
    if not autor:
        return titulo
    if not titulo:
        return autor
    if titulo.lower().startswith(autor.lower() + " - "):
        return titulo                      # ya venia compuesto
    return "%s - %s" % (autor, titulo)


def actualizar_titulo(titulo):
    """
    Pone el "sonando ahora" que ven los oyentes.
    Prueba las dos formas: la de Icecast (que es la que entiende el harbor de
    Liquidsoap) y la del DNAS. Devuelve (ok, detalle).
    """
    base = _base_publica()
    if not base or not titulo:
        return False, "sin servidor o sin titulo"
    clave = config.clave("clave_fuente")
    usuario = config.get("usuario", "source")
    mount = config.get("mount", "/") or "/"
    t = urllib.parse.quote(titulo)
    intentos = [
        (base + "/admin/metadata?mount=" + urllib.parse.quote(mount)
         + "&mode=updinfo&song=" + t, (usuario, clave)),
        (base + "/admin.cgi?sid=1&pass=" + urllib.parse.quote(clave)
         + "&mode=updinfo&song=" + t, None),
    ]
    ultimo = ""
    for url, auth in intentos:
        try:
            if auth:
                gestor = urllib.request.HTTPPasswordMgrWithDefaultRealm()
                gestor.add_password(None, url, auth[0], auth[1])
                op = urllib.request.build_opener(
                    urllib.request.HTTPBasicAuthHandler(gestor))
                with op.open(url, timeout=TIEMPO_ESPERA) as r:
                    if r.status < 400:
                        return True, "actualizado"
            else:
                _pedir(url)
                return True, "actualizado"
        except Exception as e:
            ultimo = "%s: %s" % (type(e).__name__, e)
    return False, ultimo


class Historial:
    """Guarda una fila por sondeo para poder dibujar la curva de oyentes."""

    def __init__(self, ruta=None):
        config.asegurar_carpetas()
        self.ruta = str(ruta or (config.CARPETA_DATOS / "oyentes.db"))
        self._lock = threading.Lock()
        self._crear()

    def _conex(self):
        c = sqlite3.connect(self.ruta, timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _crear(self):
        with self._lock, self._conex() as c:
            c.execute("CREATE TABLE IF NOT EXISTS oyentes ("
                      "momento INTEGER PRIMARY KEY, cantidad INTEGER NOT NULL,"
                      "pico INTEGER, titulo TEXT, en_linea INTEGER)")

    def anotar(self, est):
        try:
            with self._lock, self._conex() as c:
                c.execute("INSERT OR REPLACE INTO oyentes VALUES (?,?,?,?,?)",
                          (int(est["momento"]), est["oyentes"], est["pico"],
                           est["titulo"], 1 if est["en_linea"] else 0))
        except Exception:
            pass

    def ultimos(self, minutos=60):
        desde = int(time.time()) - minutos * 60
        try:
            with self._lock, self._conex() as c:
                return c.execute(
                    "SELECT momento, cantidad FROM oyentes WHERE momento>=? "
                    "ORDER BY momento", (desde,)).fetchall()
        except Exception:
            return []

    def resumen_dia(self, dias=7):
        """(fecha, pico, promedio) por dia, para el panel de estadisticas."""
        desde = int(time.time()) - dias * 86400
        try:
            with self._lock, self._conex() as c:
                filas = c.execute(
                    "SELECT momento, cantidad FROM oyentes WHERE momento>=?",
                    (desde,)).fetchall()
        except Exception:
            return []
        por_dia = {}
        for m, cant in filas:
            d = datetime.fromtimestamp(m).strftime("%Y-%m-%d")
            por_dia.setdefault(d, []).append(cant)
        return [(d, max(v), round(sum(v) / len(v), 1))
                for d, v in sorted(por_dia.items())]


class Vigilante:
    """Sondea el servidor en segundo plano y avisa a la interfaz."""

    def __init__(self, al_saber=None, historial=None):
        self.al_saber = al_saber          # funcion(estado) -> None
        self.historial = historial or Historial()
        self.ultimo = None
        self._parar = threading.Event()
        self._hilo = None

    def arrancar(self):
        if self._hilo and self._hilo.is_alive():
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def detener(self):
        self._parar.set()

    def _bucle(self):
        while not self._parar.is_set():
            est = estado()
            self.ultimo = est
            if est["en_linea"] or not est["error"]:
                self.historial.anotar(est)
            if self.al_saber:
                try:
                    self.al_saber(est)
                except Exception:
                    pass
            self._parar.wait(max(5, int(config.get("sondeo_oyentes_seg", 15))))
