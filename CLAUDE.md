# CLAUDE.md — Estudio de transmisión "Voz de Filadelfia"

> Memoria del proyecto. Leer completo antes de tocar código.

## 1. Qué es

Aplicación de escritorio (Windows) para que Erick transmita **en vivo** a su
emisora web. Sustituye a tener que usar BUTT/Mixxx: mezcla micrófono, música y
cortinas, saca la señal al servidor, graba el programa y muestra los oyentes.

**Usuario único:** Erick. **Objetivo declarado:** publicar la emisora la semana
del 2026-08-24.

Referencia de estilo pedida por el usuario: **RadioBOSS** ("esa me encanta").
Elegante, con todo a la vista, sin cosas de DJ que no usa.

## 2. El servidor (medido, no supuesto — 2026-08-23)

Proveedor: **asurahosting**, panel **Centova Cast**, plan Starter.
Host: `cast1.asurahosting.com` · cuenta `nonefern`

| Puerto | Qué es realmente |
|---|---|
| 8024 | DNAS **2.6.1.777** — oyentes. 128 kbps, **44100 Hz**, tope 120 |
| 8025 | fuente v1 del DNAS (sin autoDJ) |
| 8026 | `Liquidsoap source harbor` — el autoDJ, por HTTP (pero **sin montaje válido**) |
| **8027** | el mismo harbor hablando ICY — sale al aire **a través del autoDJ** |

**La regla del +1 (importante).** En SHOUTcast v1 el número que muestran los
paneles —y el que se escribe en BUTT, SAM o RadioBOSS— es el de los **oyentes**;
el codificador le suma 1 para hablar con la fuente. Por eso una captura de un
broadcaster que funciona pone `8024` aunque por dentro conecte al `8025`. La
aplicación hace lo mismo (`emisor.puerto_fuente`, opción `sumar_uno_v1`), para
que se escriba **exactamente lo que dice el panel**.

| Se escribe | Conecta a | Camino |
|---|---|---|
| **8024** | 8025 | directo al DNAS, sin pasar por el autoDJ |
| 8026 | 8027 | por el autoDJ (al colgar, la programación vuelve sola) |

`cast1.my-control-panel.com` es **el mismo servidor** (misma IP, 65.108.105.26).
En esa máquina hay más puertos abiertos (8020, 8021, 8028, 8031): son de **otros
clientes** del hosting compartido. No tocarlos.

**Consecuencia clave (corregida el 2026-08-24):** el harbor **NO acepta
Icecast**. Se probaron 13 montajes (`/`, `/stream`, `/live`, `/nonefern`,
`/source`, …) y **todos dan 404**. Lo que sí acepta, en el 8027, es el
protocolo **ICY de SHOUTcast v1** — y eso **ffmpeg no sabe hablarlo**. Por eso
existe `icy.py`: hace el saludo por socket y nosotros le empujamos el MP3 que
produce ffmpeg.

> La primera versión de este documento afirmaba lo contrario (que el harbor
> hablaba Icecast). Era una deducción a partir del banner `Liquidsoap source
> harbor`, no una comprobación. Se corrigió al probar de verdad.

**Estadísticas SIN contraseña** (esto abarató todo el monitoreo):
```
http://cast1.asurahosting.com:8024/stats?sid=1&json=1
  -> currentlisteners, peaklisteners, maxlisteners, songtitle, streamuptime...
```
Metadata ("sonando ahora"): `/admin/metadata` (Icecast) o `/admin.cgi?mode=updinfo`.

**Ajustes del panel que condicionan el diseño:**
- "Desconectar fuentes inactivas después de: **30 segundos**" → de ahí el
  reloj de pared (ver §3).
- "Desconectar a los oyentes si se desconecta la fuente: **No**" → si se cae
  el internet, los oyentes se quedan y el autoDJ retoma. Está bien así.

**Credenciales:** usuario y clave de una **Cuenta de DJ** (Centova →
Configuración → Cuentas de DJ), NO la clave del panel. Para el autoDJ, la
"clave" del protocolo es **`usuario:contraseña`** (el panel lo dice con el
ejemplo `jsmith:secret`) — de eso se encarga `clave_con_usuario`. Van en
`credenciales.env`, que está en `.gitignore`. **Nunca pedirlas por chat ni
escribirlas en ningún archivo versionado.**

## 3. Las dos decisiones que sostienen el diseño

**1. Un solo ffmpeg, que nunca se reinicia.** Arranca al salir al aire y recibe
audio hasta que se corta. Cambiar de canción, disparar un jingle o abrir el
micrófono ocurre *antes*, en el mezclador. El servidor solo ve un chorro
continuo → no hay cortes al aire. **No romper esto nunca**: cualquier diseño
que reinicie ffmpeg al cambiar de pista corta la emisión.

**2. Reloj de pared.** Si el mezclador se atrasa, `emisor._escritor` escribe
silencio en vez de esperar. Con el corte a los 30 s del servidor, quedarse
callado un instante es infinitamente mejor que quedarse quieto.

Corolario: `Emisor.enviar()` **tira el bloque más viejo** si la cola se llena.
Preferimos perder 20 ms de audio antes que frenar el hilo del mezclador.

## 4. Arquitectura

```
app.py             ventana: lista, mezclador, oyentes + diálogo de configuración
motor.py           Mezclador: suma micrófono + música + cortinas, ducking, limitador
audio.py           dispositivos, Microfono (sounddevice), Pista (decodifica por ffmpeg)
emisor.py          Emisor: ffmpeg -> socket ICY, reconexión, grabación simultánea
icy.py             cliente de fuente SHOUTcast v1 (el saludo por socket)
servidor.py        estado(), actualizar_titulo(), Historial (SQLite), Vigilante
biblioteca.py      Biblioteca (índice de carpeta) y Lista (reproducción)
config.py          ajustes PORTABLES (junto a la app) + credenciales aparte
estilo.py          tema, px() para DPI, Vumetro y Grafico propios
procesos.py        job object de Windows: ningún ffmpeg sobrevive a la app
prueba_conexion.py busca solo el puerto y la forma de clave correctos
eq.py              ecualizador de voz (biquads + scipy), con ajustes de fábrica
grabador.py        grabación a disco con su propio botón, aparte de la emisión
monitor_aire.py    escucha el chorro real y mide su nivel (detecta silencio)
ventana_aire.py    ventanita flotante con el estado de la emisora
pruebas/           213 comprobaciones automáticas
```

**Formato interno:** float32, 2 canales, **48000 Hz** (lo que usa WASAPI en
Windows). ffmpeg convierte a 44100 Hz en la misma pasada con soxr, gratis. No
resamplear en Python.

**Hilos:** el mezclador corre en su propio hilo; el reloj lo marca la tarjeta
de sonido cuando el monitor está encendido (`OutputStream.write` bloquea justo
el tiempo del bloque) y por tiempo cuando no lo está.
**tkinter no es seguro entre hilos**: la ventana consulta `mezclador.niveles`
con `after(60ms)`; el hilo de audio nunca toca un widget.

## 5. Lecciones ya pagadas (no repetir)

1. **`pack` reparte el espacio por ORDEN.** La barra de estado debe
   empaquetarse ANTES que el cuerpo con `expand=True`, o se queda de 1 píxel.
   *Ya pasó en el editor de video del transcriptor y volvió a pasar aquí.*
2. **`px()` cuenta el escalado de Windows.** Al 150 %, una ventana "de 1180"
   mide 1770 px reales y no cabe en 1920×1080. Siempre recortar al tamaño de
   pantalla disponible.
3. **Los estilos derivados de `ttk.Scale` necesitan la orientación en el
   nombre**: `Caja.Horizontal.TScale`, no `Caja.TScale` (si no: *Layout not
   found*).
4. **El filtro `sine` de ffmpeg genera a −21 dB**, no a fondo de escala. Una
   tanda de pruebas "falló" por esto con el código correcto. Usar `aevalsrc`
   con amplitud explícita.
5. **Drenar siempre el stderr de ffmpeg en un hilo.** Si se llenan los 64 KB de
   la tubería, ffmpeg se bloquea para siempre.
6. **Una prueba que se fía del código de salida de ffmpeg no prueba nada.**
   El campo "host" tenía pegada la dirección del panel
   (`http://cast1.asurahosting.com/start/nonefern`), la URL salía deformada,
   ffmpeg acababa hablando con un **servidor web cualquiera** por el puerto 80
   — y devolvía 0. La prueba decía "PASA" **con una clave equivocada**. Dos
   defensas: `emisor.limpiar_host()` sanea el campo siempre, y la verificación
   real es la respuesta del servidor (`OK` / `Invalid password`), no el código
   de salida. Hay prueba de no regresión en `pruebas/prueba_emisor.py`.
7. **Las pruebas NO deben escribir en la configuración real.** Redirigir
   `config.ARCHIVO_AJUSTES` y compañía a una carpeta temporal *antes* de
   importar la app. (En el transcriptor unas pruebas dejaron basura en los
   "recientes" del usuario.)

## 6. Estado y qué sigue

**Hecho y probado (2026-08-24):** los 11 módulos, **94 comprobaciones en
verde** (50 del motor, 39 del emisor/ICY, 34 del ecualizador y el grabador, 13 del
monitor de aire, 77 de la ventana). Todo lo de audio se mide: dB reales, no "parece que suena".

**⛔ GATE PENDIENTE — lo único que falta para darlo por bueno:** el usuario debe
correr `python prueba_conexion.py` con su usuario y clave de DJ. **Nunca se ha
transmitido de verdad al servidor**, porque hace falta esa clave. Hasta que ese
gate pase, no dar por funcionando la emisión.

**Backlog (no construir sin pedirlo):**
- Icono propio y `.exe` portable con PyInstaller.
- Programación por horarios (parrilla) — ojo: el 24/7 conviene dejarlo en el
  servidor; la app solo toma el aire en vivo.
- Cartwall más grande que 4 cortinas.
- Compresor de voz (el ecualizador ya está; falta el control de dinámica).
- Procesado tipo radio (compresor multibanda). Con `loudnorm`/`compand` se
  llega al 70-80 %; al 100 % no (eso es Stereo Tool/Omnia).
- Integrar los MP3 que genera la skill `audio-emisora`.

## 7. Bitácora

> Anotar aquí cada avance: fecha, qué se hizo, estado, qué sigue.

- [2026-08-24] **Varios micrófonos (invitados) y monitor de aire.**
  **(1) Mesa con varios micrófonos.** Nuevo `motor.CanalMicro`: cada micrófono
  tiene su aparato, su nombre, su volumen y **su propio ecualizador** (la voz
  de un invitado no necesita el mismo ajuste que la del locutor). Hasta 4
  (`config.MAX_MICROS`), 2 de fábrica. En la mesa hay una fila por micrófono
  (botón que se pone rojo + vúmetro + fader) y atajos `Ctrl+1..4`. El ducking
  ahora se dispara si habla **cualquiera** de ellos. `Mezclador.micro`,
  `.eq` y `.micro_abierto` quedan como atajos al canal 0 (con setter) para no
  romper el código ni las pruebas existentes.
  ⚠️ **Trampa de la migración:** `microfonos()` debe leer el ARCHIVO
  (`_crudo()`), no `cargar()` — como los valores de fábrica ya traen la clave
  `microfonos`, preguntársela a `cargar()` nunca detectaría una configuración
  antigua y se habría perdido el micrófono que el usuario ya tenía puesto.
  **(2) Monitor de aire** (`monitor_aire.py` + `ventana_aire.py`): escucha el
  chorro público con ffmpeg y **mide el nivel real**, porque el panel del
  servidor puede decir "en línea" mientras se manda silencio — la avería más
  peligrosa. Ventana pequeña, opcionalmente siempre visible, con luz de estado,
  vúmetro, título, oyentes y contador de silencio (rojo a los 15 s). Se abre en
  **Ver → Monitor de aire**. ⚠️ Mientras está abierta **cuenta como un oyente**
  y gasta su ancho de banda; por eso solo escucha con la ventana abierta y se
  cierra sola al salir de la aplicación. Verificado contra la emisora real:
  midió -4.2 dB de un programa en curso.
  213 comprobaciones en verde. — Estado: ✅ — Siguiente: nada pendiente; sigue
  sin subir a GitHub.

- [2026-08-24] **La barra espaciadora abre el micrófono (configurable).**
  Pedido del usuario: que la barra sea el botón del micrófono, con opción de
  desactivarla, pero activa de fábrica. Nuevo ajuste `tecla_espacio` con tres
  valores — `microfono` (por defecto), `reproducir` y `nada` — elegible en
  Configuración → Audio. `_atajo_espacio()` lee el ajuste en cada pulsación,
  así que el cambio surte efecto sin reiniciar. **F1 (micrófono) y F2
  (grabar) siguen valiendo siempre**, como red de seguridad. `_atajo()` ahora
  también ignora Combobox y Spinbox además de Entry y Text: escribir el título
  del programa no puede abrir el micrófono a cada espacio. 170 comprobaciones
  en verde. — Estado: ✅ — Siguiente: nada pendiente por parte del usuario;
  queda subir el repositorio a GitHub y la decisión del autoDJ.

- [2026-08-24] **FIX: el monitor no sonaba por los auriculares Bluetooth.**
  El usuario preguntó si el monitoreo estaba habilitado. Estaba, pero **fallaba
  en silencio**: sus auriculares `BDM3P` trabajan a 44100 Hz y el mezclador va
  a 48000, así que `sd.OutputStream` reventaba con *Invalid sample rate* y
  `motor.arrancar()` se limitaba a apagar el monitor y seguir. Se quedaba sin
  auriculares sin enterarse. **Solución:** `audio.ajustes_wasapi()` devuelve
  `sd.WasapiSettings(auto_convert=True)` para los aparatos WASAPI y deja que
  Windows convierta el muestreo; se aplica al monitor **y al micrófono** (mismo
  problema con uno inalámbrico), con reserva a abrirlo directo. Verificado:
  antes fallaba, ahora los dos aparatos abren a 48 kHz. Nuevo botón **"Probar
  los auriculares"** en Configuración → Audio (pitido corto con entrada y
  salida suaves, sin salir al aire) y el error del monitor ya se ve.
  También: **cortinas con nombre propio** — clic derecho abre un menú (asignar
  audio / cambiar el nombre / quitar), el nombre se ve en el botón, se puede
  cambiar cuando se quiera y queda guardado en `cortinas_nombres`; sin nombre
  el botón muestra su número. Confirmado que el **historial de oyentes ya
  funcionaba** (306 registros en 12 h en `datos/oyentes.db`).
  161 comprobaciones en verde. — Estado: ✅ — Siguiente: decisión sobre el
  autoDJ; subir el repositorio a GitHub sigue pendiente (no hay remoto ni `gh`).

- [2026-08-24] **✅ GATE SUPERADO: la emisora salió al aire de verdad.** El
  usuario confirmó que funciona con puerto 8024 (→8025), SHOUTcast v1, cuenta
  de DJ. Tras eso pidió cuatro cosas, todas hechas:
  **(1) Botón de grabar** (`grabador.py`): la grabación era una segunda salida
  del ffmpeg que emitía, así que empezaba y acababa con la transmisión — obliga
  a grabar la música de relleno previa. Ahora es un proceso aparte alimentado
  por el mezclador: se puede estar al aire sin grabar, grabar sin estar al aire
  y parar la grabación siguiendo al aire. Atajo F2. Verificado abriendo el MP3
  con ffprobe (duración real y que no sea silencio).
  **(2) Ecualizador de voz** (`eq.py`): 4 bandas (100 Hz, 400 Hz, 3 kHz, 9 kHz)
  con biquads del recetario RBJ + corte de graves a 80 Hz, filtrado con
  `scipy.sosfilt` guardando el estado entre bloques. Cinco ajustes de fábrica
  más "A mi gusto". Pestaña propia con curva dibujada. Medido: subir presencia
  +6 dB da +6.0 dB exactos a 3 kHz, el corte grave da −3.0 dB justo en 80 Hz, y
  procesar por bloques es **idéntico** a procesar de golpe (0.0e+00) → sin
  chasquidos.
  **(3) Botones de transporte con iconos grandes** (▶ ⏸ ⏹ ⏭ ⏺, Segoe UI
  Symbol) + globos de ayuda (`estilo.Consejo`), porque un icono sin explicación
  no se entiende.
  **(4) Rótulo en las cortinas** diciendo para qué son.
  ⚠️ **Hallazgo del servidor:** con el autoDJ APAGADO, los puertos 8026/8027
  **se cierran** y la emisora queda fuera del aire cuando él no transmite.
  Es el argumento de peso para volver a encender el autoDJ y emitir por el 8026.
  ⚠️ **Aclaración importante:** el silencio NO devuelve el aire al autoDJ; solo
  lo hace una desconexión real. La app manda datos continuamente (silencio
  incluido), así que un silencio en el programa no la echa.
  **Lección de método:** parchear con scripts que llevan `
` dentro de cadenas
  **falla en silencio** en este entorno (se convierte en salto real). Tres
  inserciones se perdieron sin avisar y el contador de pruebas lo delató. Usar
  siempre coincidencia por líneas y comprobar el número de comprobaciones.
  148 comprobaciones en verde. — Estado: ✅ al aire y grabando — Siguiente:
  decisión autoDJ sí/no; compresor de voz si lo pide.

- [2026-08-24] **El protocolo era ICY, no Icecast. Falso positivo corregido.**
  El usuario reportó que "Probar conexión" decía que todo bien pero al aire no
  pasaba nada: conectaba, el reloj corría y a los segundos "se perdió la señal".
  **Causa 1:** en el campo *Servidor* estaba pegada la dirección de la página
  del panel (`http://cast1.asurahosting.com/start/nonefern`), así que la URL
  salía como `...com/start/nonefern:8024/stream`; ffmpeg hablaba con un servidor
  web por el puerto 80, este devolvía 0 y **la prueba daba "PASA" incluso con
  una clave falsa** (reproducido). **Causa 2:** el harbor no acepta Icecast —
  13 montajes probados, todos 404 — sino **ICY de SHOUTcast v1 en el 8027**,
  que ffmpeg no habla. **Hecho:** nuevo módulo `icy.py` (saludo por socket) +
  `emisor` reestructurado (ffmpeg comprime a `pipe:1` y un hilo empuja los
  bytes al socket; la grabación en disco sigue igual) + `limpiar_host()` +
  la verificación pasa a ser la respuesta del servidor, no el código de salida
  de ffmpeg + selector de protocolo en la interfaz. También se corrigió la
  configuración guardada del usuario: tenía puerto **8023, que ni siquiera está
  abierto**. **Probado: 94 comprobaciones en verde** (28 motor + 33 ventana +
  33 nuevas de emisor/ICY, estas contra el servidor real con clave falsa, sin
  interrumpir la emisión). — Estado: 🔄 sigue faltando el gate real (hace falta
  la clave verdadera) — Siguiente: `python prueba_conexion.py`.
- [2026-08-24] **La regla del +1.** El usuario mandó la captura de un
  broadcaster que SÍ conecta: pone puerto **8024** con "Shoutcast 1". Eso
  confirmó que el número del panel es el de oyentes y que el codificador suma 1
  (por eso el 8025 respondía al saludo ICY). La aplicación pedía el puerto ya
  sumado, que no es como funciona ningún otro programa: ahora se escribe el
  del panel y `emisor.puerto_fuente()` hace la suma, con la pista en pantalla.
  Una prueba nueva detectó de paso que apuntar al 8027 "a pelo" acababa en el
  8028, **que es de otro cliente del hosting compartido**. 100 comprobaciones
  en verde. — Estado: 🔄 falta la clave real — Siguiente: el gate.

- [2026-08-23] **Proyecto creado, código completo y probado.** Estudio de
  factibilidad → investigación del servidor midiendo puertos (ver §2) → 10
  módulos → 61 comprobaciones en verde. Dos fallos reales encontrados por las
  pruebas y corregidos: barra de estado de 1 px por el orden del `pack`, y
  ventana por defecto más alta que la pantalla (se reorganizó el panel de
  oyentes a la columna izquierda porque la derecha pedía 917 px de 749). El
  proyecto vivió un rato dentro del repo `biblioteca-semantica` y se movió a
  repositorio propio a petición del usuario. — Estado: 🔄 falta el gate de
  conexión real — Siguiente: `python prueba_conexion.py` y publicar la emisora.
