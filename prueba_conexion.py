# -*- coding: utf-8 -*-
"""
PRUEBA DE CONEXION  --  ejecutar:  python prueba_conexion.py

Busca sola la combinacion correcta (puerto + forma de la clave) contra el
servidor y guarda la que funcione en ajustes.json.

Como sabe si acerto: el protocolo ICY de SHOUTcast contesta al saludo con "OK"
o con "Invalid password". No hay que interpretar nada, lo dice el servidor.

La clave NUNCA se muestra en pantalla ni se escribe en los mensajes: se pide
oculta y se guarda en credenciales.env, excluido del repositorio.

AVISO: al probar, el autoDJ deja de sonar un instante (el servidor solo admite
una fuente a la vez). Al terminar vuelve solo.
"""

import sys
import time
from getpass import getpass

import config
import emisor
import icy
import servidor

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def linea(c="-"):
    print(c * 68)


def pedir(texto, actual=""):
    suf = " [%s]" % actual if actual else ""
    r = input("%s%s: " % (texto, suf)).strip()
    return r or actual


def main():
    linea("=")
    print("  PRUEBA DE CONEXION AL SERVIDOR DE LA EMISORA")
    linea("=")

    aj = config.cargar()
    host = emisor.limpiar_host(
        pedir("Servidor", aj.get("host") or "cast1.asurahosting.com"))
    puerto_pub = int(pedir("Puerto publico (oyentes)",
                           str(aj.get("puerto_publico", 8024))))
    print("   -> se usara el host: %s" % host)

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
        r = input("      La prueba les cortara el audio un instante. Seguir? (s/n): ")
        if r.strip().lower() != "s":
            print("      Cancelado.")
            return 0

    # --- 2. credenciales
    print()
    print("[2/3] Datos de la Cuenta de DJ")
    print("      (los de 'Conexiones de fuentes en vivo' del panel de Centova)")
    usuario = pedir("Usuario DJ", aj.get("usuario") or "")
    clave = getpass("Clave DJ (no se vera al escribir): ").strip()
    if not usuario or not clave:
        print("  X  Hacen falta usuario y clave.")
        return 1

    # --- 3. buscar la combinacion buena
    print()
    print("[3/3] Probando combinaciones. Solo el saludo, es instantaneo.")
    print("      Se prueban los puertos internos: en SHOUTcast v1 el numero")
    print("      del panel es el de los oyentes y la fuente va en el +1.")
    print("        8025 = el que sale del 8024 del panel (sin autoDJ)")
    print("        8027 = el que sale del 8026 del panel (con autoDJ)")
    print()

    ganadora = None
    ultimo = ""
    for puerto, valor, etiqueta in icy.combinaciones(usuario, clave):
        print("  ... puerto %d  clave como %-14s" % (puerto, etiqueta),
              end="", flush=True)
        ok, explicacion = icy.probar(host, puerto, valor)
        if ok:
            print("   <== FUNCIONA")
            ganadora = (puerto, valor, etiqueta)
            break
        print("   no  (%s)" % explicacion[:44])
        ultimo = explicacion
        time.sleep(0.4)

    print()
    linea()
    if not ganadora:
        print("  NINGUNA COMBINACION FUNCIONO.")
        print()
        print("  Ultima respuesta del servidor: %s" % ultimo)
        print()
        if "rechazo la clave" in ultimo:
            print("  El servidor SI esta ahi y SI entiende el protocolo: lo unico")
            print("  que falla es la clave. Revisa en el panel de Centova:")
            print("     Configuracion  ->  Cuentas de DJ")
            print("  y usa el usuario y la contrasena de una cuenta de DJ")
            print("  (no los del panel, y no la clave de la fuente del servidor).")
        else:
            print("  Revisa el host y que el plan tenga el autoDJ encendido.")
        return 1

    puerto, valor, etiqueta = ganadora
    puerto_panel = puerto - 1          # lo que se escribe en la aplicacion
    print("  LISTO. Esta es la configuracion buena:")
    print("     Puerto ....... %d   (el de siempre; por dentro usa el %d)"
          % (puerto_panel, puerto))
    print("     Protocolo .... SHOUTcast v1")
    print("     Clave ........ %s" % etiqueta)
    print("     %s" % ("(sale al aire por el autoDJ: al colgar, vuelve solo)"
                       if puerto == 8027 else
                       "(sale directo al servidor, sin pasar por el autoDJ)"))
    config.guardar({"puerto": puerto_panel, "usuario": usuario,
                    "protocolo": "shoutcast_v1", "sumar_uno_v1": True,
                    "clave_con_usuario": etiqueta == "usuario:clave"})
    config.guardar_clave("clave_fuente", clave)
    print()
    print("  Guardado en ajustes.json y credenciales.env.")
    linea()

    # --- comprobacion de verdad: mandar audio y mirar si el servidor cambio
    print()
    print("Ahora la prueba de verdad: 8 segundos de tono al aire.")
    print("Si estas escuchando la emisora, deberias oir un pitido.")
    antes = servidor.estado()
    ok, msg = emisor.probar_conexion(host, puerto, usuario, clave,
                                     protocolo="shoutcast_v1", segundos=8,
                                     sumar_uno=False)
    if not ok:
        print("  X  %s" % msg)
        return 1
    print("  OK  %s" % msg)
    time.sleep(3)
    despues = servidor.estado()
    print()
    print("  Fuente antes  : %s" % (antes["dj"] or "?"))
    print("  Fuente ahora  : %s" % (despues["dj"] or "?"))
    print("  Sonando ahora : %s" % (despues["titulo"] or "-"))
    print()
    print("  Escuchalo aqui: http://%s:%d/stream" % (host, puerto_pub))
    print()
    print("TODO LISTO. Ya se puede transmitir desde la aplicacion.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(1)
