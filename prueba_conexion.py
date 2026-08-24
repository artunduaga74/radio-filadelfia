# -*- coding: utf-8 -*-
"""
PRUEBA DE CONEXION (Fase 0)  --  ejecutar:  python prueba_conexion.py

Busca sola la combinacion correcta de puerto / protocolo / punto de montaje
contra el servidor, y guarda la que funcione en ajustes.json.

La clave NUNCA se muestra en pantalla ni se escribe en los mensajes: se pide
oculta y se guarda en credenciales.env, que esta excluido del repositorio.

AVISO: mientras hace la prueba, el autoDJ deja de sonar unos segundos (es
normal: el servidor solo admite una fuente a la vez). Al terminar vuelve solo.
"""

import sys
import time
from getpass import getpass

import config
import emisor
import servidor

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def linea(c="-"):
    print(c * 66)


def pedir(texto, actual=""):
    suf = " [%s]" % actual if actual else ""
    r = input("%s%s: " % (texto, suf)).strip()
    return r or actual


def main():
    linea("=")
    print("  PRUEBA DE CONEXION AL SERVIDOR DE LA EMISORA")
    linea("=")

    aj = config.cargar()
    host = pedir("Servidor", aj.get("host") or "cast1.asurahosting.com")
    puerto_pub = int(pedir("Puerto publico (oyentes)", str(aj.get("puerto_publico", 8024))))

    # --- 1. lo que se puede saber sin clave
    print()
    print("[1/3] Preguntando al servidor (sin clave)...")
    config.guardar({"host": host, "puerto_publico": puerto_pub})
    est = servidor.estado()
    if est["error"]:
        print("  X  No respondio: %s" % est["error"])
        print("     Revisa el nombre del servidor y que tengas internet.")
        return 1
    print("  OK  Servidor localizado.")
    print("      Emisora .......... %s" % (est["emisora"] or "(sin nombre)"))
    print("      Al aire .......... %s" % ("si" if est["en_linea"] else "no"))
    print("      Sonando .......... %s" % (est["titulo"] or "-"))
    print("      Oyentes .......... %d (pico %d, tope del plan %d)"
          % (est["oyentes"], est["pico"], est["maximo"]))
    print("      Calidad .......... %d kbps" % est["bitrate"])

    if est["oyentes"] > 0:
        print()
        print("  !!  HAY %d OYENTE(S) ESCUCHANDO AHORA MISMO." % est["oyentes"])
        if input("      La prueba les cortara el audio unos segundos. Seguir? (s/n): ").strip().lower() != "s":
            print("      Cancelado.")
            return 0

    # --- 2. credenciales
    print()
    print("[2/3] Datos de la cuenta de DJ (los de 'Conexiones de fuentes en vivo')")
    usuario = pedir("Usuario DJ", aj.get("usuario") or "")
    clave = getpass("Clave DJ (no se vera al escribir): ").strip()
    if not usuario or not clave:
        print("  X  Hacen falta usuario y clave.")
        return 1

    # --- 3. buscar la combinacion buena
    print()
    print("[3/3] Probando combinaciones (cada intento dura ~3 s)...")
    print()

    combinaciones = []
    for puerto in (8026, 8027, 8025):
        for mount in ("/", "/stream", "/live", "/" + usuario):
            for legacy in (False, True):
                combinaciones.append((puerto, mount, legacy))

    ganadora = None
    fallos = []
    for puerto, mount, legacy in combinaciones:
        etiqueta = "puerto %d  mount %-12s  %s" % (
            puerto, mount, "SOURCE (v1)" if legacy else "PUT (icecast)")
        print("  ... %s" % etiqueta, end="", flush=True)
        ok, msg = emisor.probar_conexion(host, puerto, usuario, clave, mount,
                                         legacy=legacy, segundos=3)
        if ok:
            print("   <== FUNCIONA")
            ganadora = (puerto, mount, legacy)
            break
        corto = msg.splitlines()[-1][:60] if msg else "sin detalle"
        print("   no  (%s)" % corto)
        fallos.append((etiqueta, msg))
        time.sleep(0.6)

    print()
    linea()
    if not ganadora:
        print("  NINGUNA COMBINACION FUNCIONO.")
        print()
        print("  Lo mas probable, por orden:")
        print("   1. El usuario o la clave no son los de una Cuenta de DJ.")
        print("      En Centova: Configuracion > Cuentas de DJ.")
        print("   2. El autoDJ esta apagado -> habria que probar el puerto 8025")
        print("      con la clave de FUENTE del servidor (no la de DJ).")
        print()
        print("  Ultimo mensaje del servidor:")
        for l in (fallos[-1][1] or "").splitlines()[-3:]:
            print("     " + l)
        return 1

    puerto, mount, legacy = ganadora
    print("  LISTO. Esta es la configuracion buena:")
    print("     Puerto ....... %d" % puerto)
    print("     Mount ........ %s" % mount)
    print("     Protocolo .... %s" % ("SHOUTcast v1 (SOURCE)" if legacy
                                      else "Icecast (PUT)"))
    config.guardar({"puerto": puerto, "mount": mount, "usuario": usuario,
                    "protocolo": "shoutcast_v1" if legacy else "icecast"})
    config.guardar_clave("clave_fuente", clave)
    print()
    print("  Guardado en ajustes.json y credenciales.env.")
    linea()

    # --- comprobar que el tono se oyo de verdad
    print()
    print("Comprobando que la senal llego (tono de 8 s)...")
    import threading
    res = {}

    def _emitir():
        res["ok"], res["msg"] = emisor.probar_conexion(
            host, puerto, usuario, clave, mount, legacy=legacy, segundos=8)

    h = threading.Thread(target=_emitir)
    h.start()
    time.sleep(4)
    est2 = servidor.estado()
    print("  El servidor dice que la fuente es: %s" % (est2["dj"] or "?"))
    print("  Titulo al aire: %s" % (est2["titulo"] or "-"))
    h.join(timeout=30)
    print()
    print("  Escuchalo tu mismo aqui: http://%s:%d/stream" % (host, puerto_pub))
    print()
    print("TODO LISTO. Ya se puede transmitir desde la aplicacion.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(1)
