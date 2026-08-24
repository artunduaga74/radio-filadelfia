# -*- coding: utf-8 -*-
"""
Ajustes y credenciales de la emisora.

PORTABLE a propósito: todo se guarda JUNTO a la aplicación, no en AppData ni
en el registro de Windows. Copiar la carpeta a otro equipo (o a un USB) se
lleva la configuración puesta.

Dos archivos:
  ajustes.json      lo normal (servidor, micrófono, carpetas, gustos)
  credenciales.env  las claves. Va en .gitignore y NUNCA se sube a ningún sitio.
"""

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------- rutas

def _carpeta_base():
    """La carpeta de la app, funcione como .py o empaquetada en un .exe."""
    if getattr(sys, "frozen", False):          # PyInstaller
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE = _carpeta_base()
ARCHIVO_AJUSTES = BASE / "ajustes.json"
ARCHIVO_CLAVES = BASE / "credenciales.env"
CARPETA_DATOS = BASE / "datos"          # historial de oyentes, registros
CARPETA_GRABA = BASE / "grabaciones"

# ---------------------------------------------------------------- valores de fábrica

DEFECTOS = {
    # --- servidor de streaming
    "host": "",
    # Se escribe el MISMO puerto que muestra el panel (y que se pone en
    # cualquier otro programa: BUTT, SAM, RadioBOSS...). Con SHOUTcast v1 la
    # conexion real va a puerto+1, y de eso se encarga la aplicacion.
    "puerto": 8024,
    "sumar_uno_v1": True,
    "mount": "/stream",         # solo lo usa el protocolo Icecast
    "usuario": "",              # usuario de la Cuenta de DJ
    "protocolo": "shoutcast_v1",   # "shoutcast_v1" | "icecast"
    "clave_con_usuario": True,  # Centova espera la clave como usuario:clave
    "puerto_publico": 8024,     # por donde escuchan los oyentes (estadísticas)
    "puerto_admin": 8024,

    # --- calidad de emisión
    "bitrate": 128,
    "muestreo": 48000,          # reloj interno del mezclador (WASAPI usa 48k)
    "muestreo_salida": 44100,   # lo que espera el DNAS (informó icy-sr:44100)
    "canales": 2,
    # Emitir en mono: la fuente es una voz (un microfono mono duplicado), asi
    # que en estereo se gasta la mitad del bitrate en codificar una copia.
    # Medido a 128 kbps: estereo llega a 16.7 kHz y mono a 20.2 kHz.
    "emitir_mono": False,
    # Volumen de emision, en dB. Medido el 2026-08-24, la senal salia a
    # -18.9 LUFS y las radios por internet suelen ir a -16, asi que +3 dB
    # la deja al nivel de las demas. El limitador sigue mandando en el techo.
    "master_db": 0.0,
    "codec": "mp3",             # "mp3" | "aac"

    # --- identidad de la señal
    "nombre_emisora": "Voz de Filadelfia",
    "genero": "Christian",
    "url_emisora": "",
    "descripcion": "",

    # --- audio local
    # Varios microfonos: uno para el locutor y los demas para invitados.
    # Cada uno con su aparato, su volumen y su ecualizador.
    "microfonos": [
        {"nombre": "Micro 1", "dispositivo": "", "volumen": 1.0,
         "comp": True, "comp_umbral": -26, "comp_relacion": 4, "comp_makeup": 8,
         "puerta": False, "puerta_umbral": -45, "zumbido": 60,
         "eq_preset": "Voz clara",
         "eq": {"graves": -1, "medios": -3, "presencia": 4, "aire": 2,
                "corte_grave": True}},
        {"nombre": "Invitado", "dispositivo": "", "volumen": 1.0,
         "comp": True, "comp_umbral": -26, "comp_relacion": 4, "comp_makeup": 8,
         "puerta": False, "puerta_umbral": -45, "zumbido": 60,
         "eq_preset": "Voz clara",
         "eq": {"graves": -1, "medios": -3, "presencia": 4, "aire": 2,
                "corte_grave": True}},
    ],

    "microfono": "",            # (heredado) el de antes, se migra al primero
    "monitor": "",              # dispositivo de salida para auriculares
    "api_audio": "Windows WASAPI",
    "monitor_activo": True,
    # Tamano del bloque de audio. Manda en el retraso con que uno se oye:
    # medido en este equipo, 1024 -> 110 ms y 512 -> 59 ms. Mas pequeno da
    # menos retraso pero exige mas del ordenador.
    "bloque_audio": 512,
    # Anti-acople: si el monitor sale por ALTAVOCES (o un aparato Bluetooth
    # que no son auriculares), abrir el microfono provoca pitido. Con esto,
    # los auriculares se callan mientras haya un microfono abierto.
    "monitor_mudo_con_micro": False,
    "proteccion_acople": True,      # y si aun asi se acopla, se corta solo
    "volumen_monitor": 0.8,

    # --- mezcla
    "vol_micro": 0.9,
    "vol_musica": 0.8,
    "vol_efectos": 0.85,
    "ducking": True,            # baja la música al hablar
    "ducking_nivel": 0.25,      # a cuánto baja (0.25 = 25 %)
    "ducking_ataque_ms": 120,
    "ducking_salida_ms": 700,

    # --- carpetas de trabajo
    # --- monitor de aire (ventana aparte)
    "aire_siempre_visible": True,
    "aire_posicion": "",

    # --- teclado
    # Que hace la barra espaciadora: "microfono" | "reproducir" | "nada"
    "tecla_espacio": "microfono",

    # --- ecualizador del microfono
    "eq_activo": True,
    "eq_preset": "Voz clara",
    "eq_valores": {"graves": -1, "medios": -3, "presencia": 4, "aire": 2,
                   "corte_grave": True},
    "eq_mi_gusto": {"graves": 0, "medios": 0, "presencia": 0, "aire": 0,
                    "corte_grave": True},

    # --- grabacion
    "bitrate_grabacion": 192,

    "carpeta_musica": "",
    "carpeta_efectos": "",
    "cortinas": [None, None, None, None],        # el audio de cada boton
    "cortinas_nombres": ["", "", "", ""],        # como se lee cada boton
    "grabar_al_aire": False,    # la grabacion tiene su propio boton

    # --- comportamiento
    "reconectar": True,
    "reconectar_seg": 5,
    "sondeo_oyentes_seg": 15,
    "autoguardado_min": 3,
}

# Qué claves viven en credenciales.env (nunca en ajustes.json)
CLAVES = ("clave_fuente", "clave_admin")


# ---------------------------------------------------------------- carga / guardado

_cache = None


def cargar():
    """Devuelve el diccionario de ajustes (con los valores de fábrica rellenados)."""
    global _cache
    if _cache is not None:
        return _cache
    datos = dict(DEFECTOS)
    try:
        if ARCHIVO_AJUSTES.exists():
            guardado = json.loads(ARCHIVO_AJUSTES.read_text(encoding="utf-8"))
            if isinstance(guardado, dict):
                # solo claves conocidas: un archivo viejo no rompe la app
                datos.update({k: v for k, v in guardado.items() if k in DEFECTOS})
    except Exception:
        pass                     # ajustes corruptos -> se usan los de fábrica
    _cache = datos
    return datos


def guardar(nuevos=None):
    """Escribe los ajustes a disco de forma segura (temporal + reemplazo)."""
    datos = cargar()
    if nuevos:
        datos.update({k: v for k, v in nuevos.items() if k in DEFECTOS})
    tmp = ARCHIVO_AJUSTES.with_suffix(".escribiendo")
    tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ARCHIVO_AJUSTES)
    return datos


def get(clave, defecto=None):
    return cargar().get(clave, DEFECTOS.get(clave, defecto))


def set(clave, valor):            # noqa: A001  (nombre corto a propósito)
    guardar({clave: valor})


# ---------------------------------------------------------------- credenciales

def _leer_env():
    datos = {}
    try:
        if ARCHIVO_CLAVES.exists():
            for linea in ARCHIVO_CLAVES.read_text(encoding="utf-8").splitlines():
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                k, v = linea.split("=", 1)
                datos[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return datos


def clave(nombre, defecto=""):
    """Lee una credencial. Prioridad: variable de entorno > credenciales.env."""
    return os.environ.get(nombre.upper()) or _leer_env().get(nombre, defecto)


def guardar_clave(nombre, valor):
    """Guarda una credencial en credenciales.env (conservando las demás)."""
    datos = _leer_env()
    datos[nombre] = valor
    lineas = ["# Credenciales de la emisora. NO subir a ningún repositorio.", ""]
    lineas += [f"{k}={v}" for k, v in sorted(datos.items())]
    tmp = ARCHIVO_CLAVES.with_suffix(".escribiendo")
    tmp.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    os.replace(tmp, ARCHIVO_CLAVES)


def configurado():
    """¿Hay lo mínimo para salir al aire?"""
    return bool(get("host")) and bool(clave("clave_fuente"))


MAX_MICROS = 4          # tope de microfonos que admite la mesa


def _crudo():
    """Lo que hay escrito en ajustes.json, sin mezclar con los valores de fabrica."""
    try:
        if ARCHIVO_AJUSTES.exists():
            d = json.loads(ARCHIVO_AJUSTES.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}


def microfonos():
    """
    La lista de microfonos, ya saneada.

    Migra la configuracion antigua (un solo microfono en las claves
    `microfono` / `vol_micro` / `eq_valores`) al primero de la lista, para que
    quien ya tenia la aplicacion no pierda sus ajustes.
    """
    datos = cargar()
    # OJO: hay que mirar el ARCHIVO, no `cargar()`: los valores de fabrica ya
    # traen "microfonos", asi que preguntarselos a `cargar()` nunca detectaria
    # una configuracion antigua y se perderia el microfono que ya tenia puesto.
    lista = _crudo().get("microfonos")
    if not isinstance(lista, list) or not lista:
        lista = [dict(m) for m in DEFECTOS["microfonos"]]
        if datos.get("microfono"):                       # configuracion vieja
            lista[0]["dispositivo"] = datos["microfono"]
            lista[0]["volumen"] = float(datos.get("vol_micro", 0.9))
            if datos.get("eq_valores"):
                lista[0]["eq"] = dict(datos["eq_valores"])
                lista[0]["eq_preset"] = datos.get("eq_preset", "Plano")
    fuera = []
    for i, m in enumerate(lista[:MAX_MICROS]):
        if not isinstance(m, dict):
            continue
        fuera.append({
            "nombre": (m.get("nombre") or "Micro %d" % (i + 1))[:14],
            "dispositivo": m.get("dispositivo") or "",
            # el volumen ya no se queda en 1.0: un microfono lejano necesita
            # amplificarse de verdad (hasta +24 dB = x16)
            "volumen": max(0.0, min(16.0, float(m.get("volumen", 1.0)))),
            "comp": bool(m.get("comp", True)),
            "comp_umbral": float(m.get("comp_umbral", -26)),
            "comp_relacion": float(m.get("comp_relacion", 4)),
            "comp_makeup": float(m.get("comp_makeup", 8)),
            "puerta": bool(m.get("puerta", False)),
            "puerta_umbral": float(m.get("puerta_umbral", -45)),
            "zumbido": float(m.get("zumbido", 0) or 0),
            "eq_preset": m.get("eq_preset") or "Plano",
            "eq": dict(m.get("eq") or {}),
        })
    return fuera or [dict(m) for m in DEFECTOS["microfonos"]]


def guardar_microfonos(lista):
    guardar({"microfonos": [dict(m) for m in lista[:MAX_MICROS]]})


def asegurar_carpetas():
    for c in (CARPETA_DATOS, CARPETA_GRABA):
        try:
            c.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
