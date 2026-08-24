@echo off
rem Abre el estudio sin ventana de consola.
cd /d "%~dp0"
start "" pythonw.exe app.py
