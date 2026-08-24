# -*- coding: utf-8 -*-
"""
Cliente de fuente SHOUTcast v1 (protocolo ICY).

Por que existe este archivo: el servidor de la emisora (tanto el DNAS en el
8025 como el harbor de Liquidsoap del autoDJ en el 8027) solo acepta fuentes
por el protocolo ICY de SHOUTcast v1, y **ffmpeg no sabe hablarlo** (solo habla
Icecast). Comprobado contra el servidor real: los montajes de Icecast dan 404 y,
en cambio, mandar texto plano al 8027 responde "Invalid password", que es la
firma de ICY.

El protocolo es simple:

    -> <clave>\\n
    <- OK2 / OK          (o "Invalid password" y cierra)
    -> icy-name:...\\r\\n
       icy-genre:...\\r\\n
       icy-pub:1\\r\\n
       icy-br:128\\r\\n
       content-type:audio/mpeg\\r\\n
       \\r\\n
    -> ...bytes MP3 sin parar...

Ojo con la clave: en Centova, para transmitir al autoDJ, la "clave" es
**usuario:contrasena** de una Cuenta de DJ (su panel lo dice con el ejemplo
`jsmith:secret`). Por eso `conectar` admite las dos formas y `probar` las tiende
las dos.
"""

import socket

TIEMPO_ESPERA = 12


class ErrorICY(Exception):
    """Falla al conectar como fuente. El mensaje ya viene en castellano."""


def _leer_respuesta(s, limite=256):
    datos = b""
    try:
        while len(datos) < limite:
            trozo = s.recv(limite)
            if not trozo:
                break
            datos += trozo
            if b"\r\n\r\n" in datos or datos.endswith(b"\n"):
                break
    except socket.timeout:
        pass
    return datos.decode("utf-8", "replace").strip()


def _interpretar(respuesta):
    """(aceptado, explicacion en castellano)."""
    r = (respuesta or "").strip()
    bajo = r.lower()
    if bajo.startswith("ok"):
        return True, "El servidor acepto la fuente (%s)" % r.splitlines()[0][:40]
    if "invalid" in bajo or "denied" in bajo or "incorrect" in bajo:
        return False, "El servidor rechazo la clave"
    if not r:
        return False, ("El servidor no contesto al saludo (puerto equivocado, "
                       "o ya hay otra fuente conectada)")
    return False, "Respuesta inesperada del servidor: %r" % r[:60]


def conectar(host, puerto, clave, nombre="Radio", genero="Misc", url="",
             bitrate=128, publico=True, tiempo=TIEMPO_ESPERA):
    """
    Abre la conexion de fuente y devuelve el socket listo para recibir MP3.
    Lanza ErrorICY con un mensaje claro si no se puede.
    """
    try:
        s = socket.create_connection((host, int(puerto)), timeout=tiempo)
    except Exception as e:
        raise ErrorICY("No se pudo abrir %s:%s (%s)" % (host, puerto, e))

    try:
        s.sendall((clave + "\n").encode("utf-8", "replace"))
        aceptado, explicacion = _interpretar(_leer_respuesta(s))
        if not aceptado:
            s.close()
            raise ErrorICY(explicacion)

        cabeceras = (
            "icy-name:%s\r\n"
            "icy-genre:%s\r\n"
            "icy-url:%s\r\n"
            "icy-pub:%d\r\n"
            "icy-br:%d\r\n"
            "content-type:audio/mpeg\r\n"
            "\r\n" % (nombre or "Radio", genero or "Misc", url or "",
                      1 if publico else 0, int(bitrate))
        )
        s.sendall(cabeceras.encode("utf-8", "replace"))
        s.settimeout(None)          # a partir de aqui solo escribimos audio
        return s
    except ErrorICY:
        raise
    except Exception as e:
        try:
            s.close()
        except Exception:
            pass
        raise ErrorICY("Fallo el saludo con el servidor: %s" % e)


def probar(host, puerto, clave, tiempo=TIEMPO_ESPERA):
    """
    Solo el saludo, sin mandar audio. Devuelve (ok, explicacion).
    Sirve para buscar el puerto y la forma de clave correctos sin interrumpir
    la emision mas de un instante.
    """
    try:
        s = socket.create_connection((host, int(puerto)), timeout=tiempo)
    except Exception as e:
        return False, "No se pudo abrir %s:%s (%s)" % (host, puerto, e)
    try:
        s.sendall((clave + "\n").encode("utf-8", "replace"))
        return _interpretar(_leer_respuesta(s))
    except Exception as e:
        return False, "Fallo el saludo: %s" % e
    finally:
        try:
            s.close()
        except Exception:
            pass


def combinaciones(usuario, clave, puertos=(8027, 8025)):
    """
    Las formas de clave y puertos que vale la pena probar, en orden.
    Devuelve [(puerto, forma_de_clave, etiqueta)].
    """
    formas = []
    if usuario:
        formas.append(("%s:%s" % (usuario, clave), "usuario:clave"))
    formas.append((clave, "solo la clave"))
    fuera = []
    for p in puertos:
        for valor, etiqueta in formas:
            fuera.append((p, valor, etiqueta))
    return fuera
