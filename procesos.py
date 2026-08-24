# -*- coding: utf-8 -*-
"""
Control de los procesos hijos (ffplay / ffmpeg).

Dos redes de seguridad para que NUNCA quede audio sonando de fondo:

1. Un «job object» de Windows: todos los hijos se meten en él y el sistema los
   mata solo cuando muere la app, aunque se cierre de golpe o falle.
2. Un registro propio: al cerrar la ventana se cierran uno a uno (y `atexit`
   por si acaso).
"""

import atexit
import ctypes
import subprocess
import sys
import threading

SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_lock = threading.Lock()
_vivos = []          # procesos lanzados que siguen en marcha
_JOB = None


def _crear_job():
    """Job object que mata a los hijos cuando se cierra la app."""
    if sys.platform != "win32":
        return None
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class LIMITES(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", ctypes.c_uint32),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", ctypes.c_uint32),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", ctypes.c_uint32),
                        ("SchedulingClass", ctypes.c_uint32)]

        class CONTADORES(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class LIMITES_EXT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", LIMITES),
                        ("IoInfo", CONTADORES),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32.CreateJobObjectW.restype = ctypes.c_void_p
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = LIMITES_EXT()
        info.BasicLimitInformation.LimitFlags = 0x2000   # KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(ctypes.c_void_p(job), 9, ctypes.byref(info),
                                    ctypes.sizeof(info))
        return job
    except Exception:
        return None


_JOB = _crear_job()


def _adoptar(proc):
    """Mete el proceso en el job object (así muere con la app)."""
    if not _JOB or sys.platform != "win32":
        return
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        h = k32.OpenProcess(0x0100 | 0x0001, False, proc.pid)
        if h:
            k32.AssignProcessToJobObject(ctypes.c_void_p(_JOB), ctypes.c_void_p(h))
            k32.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        pass


def lanzar(cmd, **kw):
    """Como subprocess.Popen, pero el proceso queda vigilado y no puede sobrevivir."""
    kw.setdefault("creationflags", SIN_VENTANA)
    proc = subprocess.Popen(cmd, **kw)
    _adoptar(proc)
    with _lock:
        _vivos[:] = [p for p in _vivos if p.poll() is None]
        _vivos.append(proc)
    return proc


def cerrar_todos(espera=1.0):
    """Cierra todos los procesos hijos que sigan vivos."""
    with _lock:
        procesos = list(_vivos)
        _vivos.clear()
    for p in procesos:
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass
    for p in procesos:
        try:
            p.wait(timeout=espera)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


atexit.register(cerrar_todos)
