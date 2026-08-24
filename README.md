# Voz de Filadelfia — Estudio de transmisión

Aplicación de escritorio para transmitir en vivo a la emisora web (SHOUTcast /
Centova Cast), con mezclador de micrófono y música, medidores de nivel,
grabación del programa y monitoreo de oyentes.

Es **portable**: toda la configuración se guarda junto a la aplicación. Copiar
la carpeta a otro equipo (o a un USB) se lleva los ajustes puestos.

---

## Puesta en marcha

### 1. Requisitos

- **Python 3.11 o superior** (probado en 3.13).
- **ffmpeg** en el PATH. Si no lo tienes:
  ```bash
  winget install Gyan.FFmpeg
  ```
- Las librerías de Python:
  ```bash
  pip install -r requirements.txt
  ```

### 2. Buscar la configuración del servidor

Solo la primera vez. Este programa prueba solo todas las combinaciones de
puerto, protocolo y punto de montaje hasta dar con la que funciona, y la guarda:

```bash
python prueba_conexion.py
```

Te pedirá el **usuario y la clave de una Cuenta de DJ** (los de "Conexiones de
fuentes en vivo" en el panel de Centova). La clave se escribe oculta y se
guarda en `credenciales.env`, que **nunca** se sube al repositorio.

> ⚠️ Mientras hace la prueba, el autoDJ deja de sonar unos segundos. El
> programa avisa antes si hay oyentes conectados.

### 3. Abrir el estudio

```bash
python app.py
```

O doble clic en `Estudio.bat` (abre sin ventana de consola).

---

## Cómo se usa

| Quiero... | Cómo |
|---|---|
| Salir al aire | Botón rojo **SALIR AL AIRE** (arriba a la derecha) |
| Hablar | **ABRIR MICROFONO** o la tecla `F1` |
| Poner música | Arrastrar archivos con **+ Archivos** o **+ Carpeta**, luego doble clic en una pista |
| Que suene solo sin hablar | Armar la lista, activar **Repetir** y darle a Reproducir: encadena una tras otra |
| Poner el título del programa | Campo **Título del programa** → *Poner al aire* |
| Disparar una cortina | Los 4 botones de abajo. **Clic derecho** en uno para asignarle un archivo |
| Ver cuánta gente escucha | Panel **OYENTES** (se actualiza solo cada 15 s) |
| Ver el historial por días | Menú **Ver → Estadísticas de oyentes** |

### Atajos

| Tecla | Acción |
|---|---|
| `Espacio` | Reproducir / pausa |
| `F1` | Abrir / cerrar el micrófono |
| `Ctrl + →` | Siguiente pista |

### El "ducking"

Con la casilla **Bajar música al hablar** activada, la música se aparta sola
cuando abres el micrófono y vuelve cuando callas. Es lo que hace que suene a
radio y no a dos cosas peleándose.

---

## Cómo está hecho

```
app.py               la ventana: lista, mezclador, oyentes
motor.py             el mezclador (suma micrófono + música + cortinas)
audio.py             dispositivos, captura de micrófono, reproductores
emisor.py            saca la señal al aire (ffmpeg -> servidor)
servidor.py          pregunta oyentes y manda el "sonando ahora"
biblioteca.py        carpeta de trabajo y listas de reproducción
config.py            ajustes portables + credenciales
estilo.py            tema visual, vúmetros y gráfico
procesos.py          red de seguridad: ningún ffmpeg sobrevive a la app
prueba_conexion.py   busca la configuración correcta del servidor
```

### Las dos decisiones que sostienen todo

**1. Un solo ffmpeg, que nunca se reinicia.** Se arranca al salir al aire y
recibe audio hasta que se corta. Cambiar de canción, disparar un jingle o abrir
el micrófono ocurre *antes*, en el mezclador. El servidor solo ve un chorro
continuo, así que no hay cortes al aire.

**2. Reloj de pared.** Si el mezclador se atrasa por lo que sea, el emisor
escribe silencio en vez de esperar. El servidor está configurado para cortar
las fuentes inactivas a los 30 segundos: quedarse callado un instante es
infinitamente mejor que quedarse quieto y perder la conexión.

---

## Archivos que genera (no van al repositorio)

| Archivo | Qué es |
|---|---|
| `ajustes.json` | Toda la configuración |
| `credenciales.env` | Las claves. **Nunca subir a ningún sitio** |
| `datos/oyentes.db` | Historial de oyentes (SQLite) |
| `datos/indice_musica.json` | Índice de la carpeta de música |
| `grabaciones/` | Los programas grabados en MP3 |

---

## Si algo falla

| Síntoma | Qué mirar |
|---|---|
| "Usuario o clave rechazados" | Es una Cuenta de DJ, no la clave del panel. Volver a correr `prueba_conexion.py` |
| No se oye el micrófono | Configuración → Audio → elegir el micrófono correcto. Cambiarlo exige volver a salir al aire |
| Se cortó y volvió solo | Normal: reconexión automática. Ver el detalle en **Ver → Registro técnico** |
| No abre y no dice nada | Mirar `error_arranque.log` en esta carpeta |
