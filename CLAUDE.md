# CLAUDE.md — Filadelfia Broadcaster

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
eq.py              cadena de voz: ecualizador, compresor, puerta y limitador
grabador.py        grabación a disco con su propio botón, aparte de la emisión
monitor_aire.py    escucha el chorro real y mide su nivel (detecta silencio)
ventana_aire.py    ventanita flotante con el estado de la emisora
metadatos.py       leer y escribir las etiquetas de un archivo ya grabado
ventana_metadatos.py  el editor de metadatos (menú Metadatos)
pruebas/           465 comprobaciones automáticas (7 archivos)
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
5. **Tk manda la barra espaciadora al botón que tenga el foco ANTES que a
   la ventana.** Con el foco en el botón del micrófono, la barra lo abría (el
   botón) y lo cerraba (el atajo) en el mismo golpe: parecía que el atajo no
   funcionaba. `takefocus=False` **no basta** — un clic da el foco igual. La
   solución es interceptar la clase: `bind_class("TButton", "<space>", ...)`
   devolviendo `"break"`, y solo en la ventana principal (en los diálogos la
   barra debe seguir pulsando el botón).
6. **Drenar siempre el stderr de ffmpeg en un hilo.** Si se llenan los 64 KB de
   la tubería, ffmpeg se bloquea para siempre.
7. **Una prueba que se fía del código de salida de ffmpeg no prueba nada.**
   El campo "host" tenía pegada la dirección del panel
   (`http://cast1.asurahosting.com/start/nonefern`), la URL salía deformada,
   ffmpeg acababa hablando con un **servidor web cualquiera** por el puerto 80
   — y devolvía 0. La prueba decía "PASA" **con una clave equivocada**. Dos
   defensas: `emisor.limpiar_host()` sanea el campo siempre, y la verificación
   real es la respuesta del servidor (`OK` / `Invalid password`), no el código
   de salida. Hay prueba de no regresión en `pruebas/prueba_emisor.py`.
8. **Una función que nunca se ha probado, dala por rota.** La reconexión
   automática llevaba desde el primer día en el código, con su opción en
   Configuración y su mensaje en el registro, y **no funcionaba en absoluto**.
   Nadie la había ejercitado porque hacía falta un servidor que cortara la
   conexión a propósito. Montar ese servidor de mentira cuesta veinte líneas.
   Vale para cualquier camino de recuperación de errores: son justo los que no
   se recorren en el uso normal, y por eso se pudren sin que nadie lo note.
9. **Dos sitios que hacen la misma tarea acaban divergiendo.** Abrir los
   micrófonos estaba escrito en `arrancar()` y otra vez en el refresco de
   hardware, con una diferencia sutil (uno abría todos, el otro solo los que
   estuvieran al aire) — y esa diferencia dejó al usuario sin micrófono. Ahora
   hay una sola `sincronizar_microfonos()` por la que pasa todo el mundo.
   Antes de copiar unas líneas, preguntarse si no toca extraerlas.
10. **Un fallo intermitente no se ve corriendo la prueba una vez.** El monitor
   se quedaba mudo una de cada tres veces por una carrera entre el hilo del
   mezclador y la reapertura de la salida. Con las prisas de "las pruebas pasan"
   se habría colado. Ante cualquier cosa que huela a carrera entre hilos:
   correrla cinco u ocho veces seguidas.
11. **Un umbral de prueba tiene que salir de la arquitectura, no de la
   intuición.** Puse "3 periodos" porque sonaba razonable; flaqueaba con el
   ruido de Windows y no medía nada real. El número bueno salía del código:
   el emisor mete silencio a los 500 ms de cola vacía. Si un umbral falla a
   veces, casi siempre está mal elegido — pero **antes de relajarlo hay que
   comprobar que no está señalando un fallo de verdad** (aquí señalaba dos).
12. **Las pruebas NO deben escribir en la configuración real.** Redirigir
   `config.ARCHIVO_AJUSTES` y compañía a una carpeta temporal *antes* de
   importar la app. (En el transcriptor unas pruebas dejaron basura en los
   "recientes" del usuario.)

## 6. Estado y qué sigue

### ⚡ PARA RETOMAR EN UNA SESIÓN NUEVA — leer esto primero

**La aplicación está terminada y funcionando en producción.** Emite de verdad a
`cast1.asurahosting.com`, el usuario ya la ha usado al aire. El repositorio está
en GitHub (`artunduaga74/radio-filadelfia`, privado) y al día.

**Cómo trabajar aquí:**
1. Las pruebas son la red de seguridad: `python pruebas/prueba_*.py`, siete
   archivos, **465 comprobaciones**. Correrlas SIEMPRE antes y después de tocar
   nada, y **vigilar que el número no baje** — un descenso silencioso ha
   delatado ya tres parches que no se habían aplicado.
2. Todo lo de audio se **mide** (dB, LUFS, espectro), no se estima. Hay
   ejemplos en `pruebas/prueba_eq_grabador.py`.
3. Antes de buscar un fallo en el código, **mirar `ajustes.json`**: dos "bugs"
   reportados eran configuración del usuario, no código.
4. ⚠️ Los parches con scripts que llevan `
` dentro de cadenas **fallan en
   silencio** en este entorno (se convierte en salto de línea real). Usar
   coincidencia por líneas y comprobar el resultado.

**Lo único pendiente de decisión del usuario:**
- Poner el **volumen de emisión en +3 dB** y volver a medir con
  `ffmpeg -i <stream> -af ebur128` (iba a −18.9 LUFS; el objetivo es −16).
- El **MP3 de 4.4 MB que se coló** en los primeros commits sigue en el
  historial. Repositorio privado, sin consecuencias; limpiarlo exige reescribir
  el historial y forzar el envío. **No hacerlo sin que él lo pida.**


**Hecho y probado (2026-08-24):** los 11 módulos, **94 comprobaciones en
verde** (52 del motor, 39 del emisor/ICY, 49 del ecualizador/compresor/grabador, 13
del monitor de aire, 112 de la ventana). Todo lo de audio se mide: dB reales, no "parece que suena".

**⛔ GATE PENDIENTE — lo único que falta para darlo por bueno:** el usuario debe
correr `python prueba_conexion.py` con su usuario y clave de DJ. **Nunca se ha
transmitido de verdad al servidor**, porque hace falta esa clave. Hasta que ese
gate pase, no dar por funcionando la emisión.

**Backlog (no construir sin pedirlo):**
- Icono propio y `.exe` portable con PyInstaller.
- **Programación por horarios (parrilla) — VIABILIDAD ESTUDIADA el 2026-08-25.**
  Pregunta del usuario: "que se conecte al servidor a las 5am y transmita X".
  Técnicamente es fácil (las piezas ya existen: lista de reproducción,
  `cortar_al_terminar`, y ahora `intentar_salir_al_aire()`, que insiste hasta
  que haya internet). Lo caro NO es el código, es que **depende de que su PC
  esté encendido y despierto a las 5 de la mañana**. Comprobado en su equipo:
  admite suspensión S3 e hibernación, y el Programador de tareas de Windows
  sabe despertarlo, así que se puede montar.
  **Pero antes de construirlo hay que decidir dónde vive el 24/7:** su Centova
  tiene el **autoDJ ACTIVO** (comprobado en el servidor), y un autoDJ hace
  exactamente esto — listas programadas por hora — **sin depender de que su
  ordenador esté encendido, sin gastar su internet y sin que un apagón o una
  actualización de Windows tumben el programa**. La regla del proyecto sigue
  siendo la buena: *el 24/7 se deja en el servidor; la aplicación toma el aire
  en vivo*. La parrilla en la aplicación solo tiene sentido para bloques que
  necesiten la mesa (mezclas, cortinas, micrófono), no para "poner un MP3 a las
  5". Decisión pendiente del usuario.
- Cartwall más grande que 4 cortinas.
- Procesado tipo radio (compresor multibanda). Con `loudnorm`/`compand` se
  llega al 70-80 %; al 100 % no (eso es Stereo Tool/Omnia).
- Integrar los MP3 que genera la skill `audio-emisora`.

## 7. Bitácora

> Anotar aquí cada avance: fecha, qué se hizo, estado, qué sigue.

- [2026-08-25] **La gráfica de oyentes dejó de trabajar en balde.**
  Salía de la investigación de arriba. `_pintar_oyentes()` corre **cada
  segundo** (lo llama `_tic_lento`), pero el servidor solo se sondea **cada
  15 s**: se estaba pidiendo a SQLite las últimas dos horas y redibujando el
  lienzo **quince veces por cada dato nuevo**. Ahora los rótulos (oyentes, pico,
  título) siguen refrescándose cada segundo, que es gratis, y la consulta y el
  redibujo **solo ocurren cuando el sondeo trae un `momento` que no se ha
  pintado**.
  Medido sobre 120 tics (dos minutos de aplicación) con 8 sondeos reales:
  **8 consultas y 8 redibujos en vez de 120** — un 93 % menos — con los rótulos
  igual de al día. Ahorro: ~6 s de CPU por hora.
  La prueba comprueba las dos direcciones: que NO trabaje de más, y que con un
  dato nuevo **sí** redibuje (si no, "no dibujar nunca" también pasaría).
  ⚠️ Ojo con `prueba_ventana.py`: la comprobación "el vúmetro del micro se
  enciende" es **intermitente** — depende del micrófono real del equipo. Falló
  una vez y pasó las dos siguientes sin tocar nada. Si aparece, repetir antes de
  buscarle una causa.
  465 comprobaciones. — Estado: ✅

- [2026-08-25] **Parar/reproducir trabado, botones del reproductor y SOUNDPAD.**
  **(1) BUG: tras "Parar", el play no hacía nada.** `Pista.detener()` mata el
  ffmpeg de la pista pero **deja la ruta puesta**, y `reproducir()` empezaba con
  *"si no hay proceso, no hagas nada"*. Resultado: la pista se quedaba trabada y
  había que mover el deslizador (que por dentro recarga) o volver a elegirla en
  la lista — justo lo que describió el usuario. Ahora `reproducir()` se cura
  solo: si no hay proceso pero sí ruta, la recarga desde el principio. Medido
  con el nivel de audio real: 0.336 sonando → 0.000 al parar → 0.337 al darle
  al play otra vez.
  **(2) "Grabar" pegado al botón de parar.** Los tres de transporte no llevaban
  `width`, así que el relleno del estilo los estiraba hasta juntarse con
  "Grabar". Con `width=3` pasan de 112 a **96 px** cada uno y el hueco antes de
  "Grabar" pasa de 0 a **214 px**.
  **(3) Cortinas → SOUNDPAD**, de 4 a **8 botones**, en rejilla de 2 filas de 4
  (en una sola tira no caben sin dejarlos tan estrechos que el nombre no se lee,
  que era la queja) y más anchos: de 9 a 13 caracteres, **149 px**, y el nombre
  que se lee sube de 12 a 13 caracteres. ⚠️ La clave guardada sigue siendo
  `cortinas`, así que **no se pierde lo que ya tuviera asignado**: comprobado
  con su `ajustes.json` real, las cuatro que tenía siguen ahí.
  ⚠️ Una prueba dejó de pasar y **no era un fallo**: comparaba contra la lista
  fija `["2","3","4"]`. Ahora se compara contra el número de botones que haya.
  461 comprobaciones. — Estado: ✅

- [2026-08-25] **INVESTIGACIÓN (sin tocar nada): el PC lento tras 2 horas.**
  El usuario estuvo 2 h seguidas (1 grabando, 1 transmitiendo) y al final el
  audio salía entrecortado y **todo el ordenador iba lento, internet incluido**.
  Se le echó un vistazo al código y se midió lo barato. **NO se arregló nada**,
  por petición suya. Lo que hay hasta ahora:
  **Descartado (medido):** no hay fuga de memoria en el camino en reposo — 3
  minutos de aplicación viva dan RAM plana en 124.4 MB, 2 hilos, handles
  estables y el número de objetos de Python sin moverse. El registro técnico
  está acotado a 500 líneas. El gráfico de oyentes hace `delete("all")` antes de
  redibujar, así que no acumula objetos en el lienzo (que es la causa clásica de
  "se va poniendo lento"). El servidor se sondea cada 15 s, no cada segundo. No
  quedan procesos ffmpeg huérfanos.
  **SOSPECHOSO PRINCIPAL, y no es la aplicación: el disco está casi lleno.**
  `C:` tiene **9.2 GB libres de 139 (93 % usado)** y `D:` 10.8 de 97.7 (89 %).
  Windows se arrastra cuando al disco del sistema le queda tan poco: el archivo
  de paginación no puede crecer, y las tareas de fondo (indexado, Windows
  Update, mantenimiento) machacan el disco. Encaja con TODOS sus síntomas —
  incluido que se ralentizara *el internet* y que *reiniciar lo arreglara*, que
  es justo lo que hace un reinicio: liberar paginación y temporales. Una sesión
  de 2 h grabando escribe además ~0.3 GB, apretando más.
  **Ineficiencia real encontrada, menor — ✅ YA ARREGLADA (ver entrada de
  abajo):** `_pintar_oyentes()` corría **cada segundo** y abría una conexión
  SQLite nueva cada vez para consultar las últimas 2 horas (**1.84 ms**), más el
  redibujo del lienzo. No explica por sí solo lo que le pasó, pero sobraba.
  **Lo que NO se ha probado y haría falta para concluir:** una sesión larga con
  el camino REAL (mezclador + emisor + grabador a la vez), midiendo RAM, hilos y
  CPU. Sin eso no se puede afirmar que la aplicación esté limpia bajo carga.
  — Estado: 🔄 investigación abierta — Siguiente: que libere espacio en C: y
  vuelva a hacer un programa largo; si se repite, medir bajo carga real.

- [2026-08-25] **Rompí el micrófono con lo de arriba, y de paso salieron 3 fallos más.**
  El usuario probó lo del hardware en caliente: encontró su Maonocaster, se lo
  asignó al Micro 1, pulsó el botón y le salió **"No se pudo abrir Micro 1"**
  con el motivo VACÍO ("-"). Reproducido en dos minutos.
  **(1) Mi regresión.** `arrancar()` abre el stream de TODOS los micrófonos de
  una vez, y el botón de la mesa **solo levanta una bandera**: no sabe abrir un
  stream cerrado. Mi refresco los cerraba todos y **reabría solo los que
  estuvieran ya al aire** — y como lo normal es tenerlos cerrados mientras uno
  trastea en Configuración, quedaban todos muertos.
  **(2) Fallo de fondo que salió a la luz:** cambiar el aparato de un micrófono
  en Configuración **nunca llegaba al canal** (de ahí el letrero "los
  micrófonos se aplican al reiniciar"). Justo lo que él necesitaba. Ahora
  `aplicar_ajustes` lo sigue y el cambio surte efecto al momento.
  **(3) Los canales en blanco se abrían igual.** La ventana promete "deja el
  aparato en blanco para no usar ese canal", pero se abrían los cuatro: la
  aplicación agarraba el micrófono por defecto de Windows tres veces de más y
  luego se quejaba de canales que el usuario no quiere.
  **(4) Los auriculares se quedaban mudos una de cada tres veces, sin avisar.**
  Al sacar la reapertura del monitor fuera de la zona protegida, el bucle
  escribía en el stream recién creado, la primera escritura fallaba y el
  `except` lo dejaba en `None` **en silencio**. Encontrado corriendo la prueba
  cinco veces seguidas, no una.
  **Arreglado con una sola pieza:** `Mezclador.sincronizar_microfonos()`, que
  ahora es **el único sitio del programa que abre micrófonos** — `arrancar()`,
  `aplicar_ajustes()`, `refrescar_dispositivos()` y el propio botón de la mesa
  pasan por ella. Tener dos versiones de la misma tarea fue lo que permitió que
  se colara la diferencia. El botón además **se cura solo**: si el stream está
  cerrado lo intenta abrir ahí mismo antes de protestar, y si no puede da un
  motivo de verdad en vez de un guión.
  **Orden final del refresco, con su porqué:** soltar → cerrar → reiniciar
  PortAudio → **reabrir el monitor (dentro de la protección, o pasa el fallo 4)**
  → soltar → abrir micrófonos (fuera, que es la parte lenta). Medido: el peor
  hueco que ve el emisor bajó de 44 a **~24 ms**.
  ⚠️ **Sobre el umbral de la prueba:** tenía puesto "3 periodos = 32 ms", que
  era un número inventado por mí, y flaqueaba con el ruido de planificación de
  Windows. Ahora es **250 ms, la mitad del único límite real** (el escritor del
  emisor mete silencio a los 500 ms de cola vacía; el servidor suelta la fuente
  a los 30 s), y se mide **además la mediana**, que es lo que delata una
  regresión de verdad. Ocho pasadas seguidas en verde.
  454 comprobaciones. — Estado: ✅ — Siguiente: que vuelva a probarlo con su
  Maonocaster.

- [2026-08-25] **⚠️ FALLO GRAVE: la reconexión automática NUNCA funcionó.**
  El usuario preguntó si la aplicación vuelve sola cuando se cae internet. El
  código decía que sí desde el primer día, y **estaba roto**; nadie lo había
  probado nunca (las 39 comprobaciones del emisor no tocaban este camino).
  **Reproducido** con un servidor ICY de mentira que corta la conexión: 0
  reintentos en 12 s, la emisora en "error" para siempre.
  **La causa:** `_caida()` cerraba el socket pero **dejaba vivo ffmpeg**, y
  `arrancar()` empieza con *"si ya hay un ffmpeg vivo, no hagas nada"*. El
  reintento se creía conectado y se iba sin hacer nada. Medido: `socket=False`
  y `ffmpeg_vivo=True` durante los 12 s enteros.
  **Segundo fallo del mismo sitio:** salir al aire **sin internet** se rendía
  al primer golpe. `arrancar()` fallaba, y como no llegaba a montar los hilos
  que avisan de la caída, nadie volvía a intentarlo jamás. Justo el caso de
  "dejo el programa puesto y me voy".
  **Arreglado:** (1) `_soltar_todo()` cierra socket **y** ffmpeg antes de
  reintentar; (2) `_reintentar()` se encadena a sí mismo si tampoco puede;
  (3) `intentar_salir_al_aire()` (lo que llama el botón) programa el reintento
  cuando el fallo es de red; (4) bandera `_reintento_pendiente`, porque de una
  sola caída avisan los DOS hilos y se programaban dos reconexiones que se
  peleaban; (5) `_sin_arreglo` — **con la clave mal NO insiste**: eso no se
  arregla esperando y machacar al servidor cada dos segundos con una clave
  equivocada es la forma de acabar bloqueado.
  **Medido después:** 3 reconexiones en 12 s cuando el servidor corta; con
  internet caído entra sola a los 12.1 s de volver la línea; con la clave mala,
  1 solo golpe en 8 s. Todo ello es ahora prueba de no regresión.

- [2026-08-25] **Cambiar de micrófono sin cerrar la aplicación.**
  Pedido del usuario: enchufar otro micrófono con la aplicación abierta y que
  se entere, "sin perder latencia o que se cuelgue la transmisión".
  **El problema medido:** PortAudio se queda con la lista de aparatos que había
  al arrancar. Para releerla hay que reiniciarlo, y eso **invalida todos los
  streams abiertos** (comprobado: *Invalid stream pointer*) y tarda unos 130 ms.
  Así que preguntar "¿hay algo nuevo?" NO puede pasar por ahí — sería
  exactamente lo que él temía.
  **Solución en dos piezas.** (1) *Preguntar* es barato y no toca el audio:
  `audio.huella_hardware()` lee el registro de Windows, donde Core Audio anota
  cada entrada y salida con su estado. **3.3 ms de media**, frente a 127 ms de
  reiniciar PortAudio; comprobado que la cuenta coincide con la que ve
  PortAudio. Se mira cada 4 s y avisa en la barra de estado, una sola vez.
  (2) *Cambiar de verdad* lo decide el usuario, con el botón **"Buscar aparatos
  nuevos"** en Configuración → Audio: `Mezclador.refrescar_dispositivos()`
  levanta una bandera, **el bucle sigue girando** pero suelta micrófonos y
  monitor, se reinicia PortAudio y se vuelve a abrir solo lo que estaba abierto
  (por NOMBRE, así que si el aparato cambió de número al enchufar otro se
  reencuentra igual).
  **El aire NO se corta, y está medido:** durante el cambio el emisor siguió
  recibiendo bloques con un hueco peor de **25.6 ms** frente a los 10.7 ms
  normales — ni un solo hueco por encima del límite de 32 — y se entregó tanto
  audio como tiempo pasó (2.5 % de desfase). La música ni se entera: la
  decodifica ffmpeg, no la tarjeta de sonido. Lo único que parpadea es la voz,
  unos 250 ms. Si está al aire con el micrófono abierto, se avisa antes.
  Se hace **en otro hilo**: lo normal son 250-300 ms, pero se midió un caso de
  **30 s** con unos auriculares Bluetooth despertándose, y con la ventana
  congelada eso parece que la aplicación se colgó. Medido: la ventana nunca se
  para más de 38 ms.
  ⚠️ **Ojo con la altura de Configuración:** ya medía **1048 px en una pantalla
  de 1080**. Las dos filas que añadí la llevaron a 1122 y los botones de abajo
  se salían (lección 2, otra vez). El botón acabó en la MISMA fila del rótulo
  "MICROFONOS" y la explicación en un globo de ayuda: la ventana vuelve a medir
  1048 exactos. Hay prueba que lo vigila.
  ⚠️ **Y por tercera vez:** un parche con `

` dentro de una cadena volvió a
  romper un archivo. Ahora se usan constantes (`SALTO`, `FIN`).
  447 comprobaciones en verde (eran 415). — Estado: ✅ — Siguiente: que pruebe a
  enchufar su micrófono con la aplicación abierta.

- [2026-08-25] **El autor seguía saliendo "Unknown": lo pisaba la música.**
  El arreglo del día anterior (mandar `Autor - Título` en una sola cadena) era
  correcto pero **duraba unos segundos**. Al arrancar cada pista, `_poner_pista`
  volvía a mandar el "sonando ahora" con `biblioteca.etiqueta(pista)` — y esa
  función devuelve **solo el título** cuando el MP3 no trae etiqueta de artista.
  O sea: se pulsaba "Poner", salía bien, y a la primera canción el autor
  desaparecía. Dos senderos escribiendo el mismo dato, uno de ellos sin autor.
  **Comprobado contra el servidor real** (sin tocar la emisión): Centova parte
  la cadena por el primer " - " para separar artista y título —
  `rawmeta "Fernando Miranda - Simeón y Ana"` → `{"artist": "Fernando
  Miranda", "title": "Simeón y Ana"}` — así que sin separador el hueco del
  artista sale como "Unknown". Los dos endpoints de metadata existen y piden
  clave (401 con una falsa), o sea que el envío funcionaba; lo que fallaba era
  **el contenido**.
  **Arreglado en tres piezas:** (1) `servidor.componer_titulo()`, una sola
  función que arma la cadena, usada por los dos senderos (y que no duplica el
  separador si el título ya venía compuesto); (2) `App._texto_de_pista()`, que
  al anunciar una canción **siempre pone autor**: el del archivo y, si no lo
  trae, el nombre de la emisora; (3) `titulo_programa` — mientras haya un
  título puesto a mano con "Poner", el cambio de canción **ya no lo pisa**, que
  es lo que uno espera en una transmisión en vivo (se anuncia el programa, no
  el archivo que suene de fondo). Vaciando los dos campos y pulsando "Poner" se
  suelta y vuelve a anunciarse cada canción.
  *Lección repetida: al arreglar un dato, buscar quién MÁS lo escribe.* Es la
  misma del 24 con la grabación automática.

- [2026-08-25] **Editor de metadatos (menú Metadatos, al lado de Ver).**
  `grabador.py` pone las etiquetas mientras graba; a un programa ya guardado no
  había forma de tocarle nada. Nuevos `metadatos.py` (lógica) y
  `ventana_metadatos.py` (la ventana), con **los mismos campos y la misma
  tarjeta de vista previa** de Configuración → Transmisión, a propósito.
  Detalles que importan: **no recodifica** (`-c copy`, medido: la duración no
  se mueve ni 0.05 s), rellena `album_artist` solo (sin él, los teléfonos
  agrupan los programas en "Varios"), conserva o cambia o quita la carátula, y
  **nunca escribe encima del original**: genera un temporal completo en la
  misma carpeta y solo entonces hace `os.replace`. Probado a propósito con una
  carátula que no existe: avisa, el archivo queda con el mismo tamaño y las
  mismas etiquetas, y no deja temporales tirados.
  Se admiten mp3, m4a, aac, ogg, opus, flac, wav y wma.
  ⚠️ **Fallo mío cazado por la prueba de integración:** el hilo que escribe
  llamaba a `self.after(...)`, y eso revienta con *main thread is not in main
  loop*. Es justo la regla que este documento ya trae en §4 (tkinter no es
  seguro entre hilos). Cambiado al patrón del resto de la casa: el hilo deja el
  resultado en un atributo y la ventana lo recoge sondeando con `after`.

- [2026-08-25] **Iconos borrosos: faltaban los tamaños del escalado de pantalla.**
  El `.ico` llevaba 16/20/24/32/40/48/… pero la **barra de tareas dibuja a 24
  puntos lógicos**, que con su pantalla al 150 % son **36 px reales** — un
  tamaño que no estaba. Windows lo fabricaba encogiendo el de 48 con un filtro
  barato. Medido sobre este logo: **77.0 de definición frente a 121.5** del
  generado directo a 36. Añadidos **30 (125 %), 36 (150 %) y 60 (250 %)**;
  72 se descartó porque no compensa (76.7 frente a 75.7).
  **El .bat no puede llevar icono propio**: Windows le pone siempre el de la
  consola, se configure lo que se configure. Lo que sí admite icono es un
  acceso directo, así que hay `crear_acceso_directo.ps1` — crea "Filadelfia
  Broadcaster.lnk" en el **escritorio y en el menú Inicio** apuntando a
  `pythonw.exe app.py` (sin consola detrás) con `icono.ico`, y de paso refresca
  la caché de iconos de Windows (`ie4uinit.exe -show`), que es lo que hace que
  a veces se siga viendo el icono viejo. Si se mueve la carpeta, volver a
  ejecutarlo.
  415 comprobaciones en verde (eran 350). — Estado: ✅ — Siguiente: que el
  usuario confirme el autor al aire en su próxima transmisión.

- [2026-08-25] **La radio mostraba "Unknown": faltaba el autor en el stream.**
  El usuario vio que el título salía bien pero el autor aparecía como
  "Unknown". Causa: a `servidor.actualizar_titulo()` se le mandaba **solo el
  título**, y los reproductores esperan el formato **`Autor - Título`** en esa
  misma cadena (SHOUTcast manda un único campo de texto, no dos). Nuevo
  `_texto_al_aire()`, que junta ambos y aguanta que falte cualquiera de los dos.
  El autor se recuerda al pulsar "Poner".
  **Campo nuevo en el panel del reproductor** sin crecer hacia abajo: las dos
  filas de antes (rótulo "Título del programa:" encima, entrada debajo) se
  juntaron en **una sola** — `Al aire: [título] [autor] [Poner]`. El panel pasa
  de **305 a 270 px** *añadiendo* un campo, con lo que las cortinas ganan aire
  en vez de perderlo. Comprobado a cuatro anchos: la última cortina acaba en
  793 px con la ventana en 900, o sea 107 de margen.
  Ojo con la distinción: en el **stream** va `Autor - Título` en una sola
  cadena; en las **grabaciones** el autor va en su etiqueta ID3 propia y el
  título en la suya. Son dos sitios distintos y no hay que mezclarlos.
  350 comprobaciones en verde. — Estado: ✅ — Siguiente: probar el puerto 8026.

- [2026-08-25] **El icono se veía borroso en la barra: faltaba el tamaño 24.**
  El `.ico` se generaba con 16/32/48/64/128/256, y **la barra de tareas normal
  de Windows pide 24**. Al no encontrarlo, Windows encogía el de 32 por su
  cuenta con un filtro barato. Medido: **60.3 de definición frente a 123.2** del
  que se genera directo a 24 y se realza. Justo el doble.
  **Solución** en `estilo.generar_iconos()`: se guardan los diez tamaños que
  Windows pide de verdad (16, 20, 24, 32, 40, 48, 64, 96, 128, 256), cada uno
  generado **desde el original a su medida exacta** con LANCZOS, y con realce de
  borde (`UnsharpMask`) en los de 64 o menos — un logo con detalle fino se
  empasta al bajar de 1254 px por mucho filtro que se use. El realce va solo al
  color, nunca a la transparencia, o saldrían halos.
  ⚠️ Una prueba falló y **no era el código**: llamaba a `_icono_segun_aire(True)`
  y luego a `update()`, y el reloj de la ventana volvía a poner el estado real
  (fuera del aire), que es lo correcto en uso normal. La prueba ahora comprueba
  el mecanismo sin el reloj de por medio.
  344 comprobaciones en verde. — Estado: ✅ — Siguiente: probar el puerto 8026.

- [2026-08-25] **Imagen nueva: iconos y carátula regenerados.** El usuario
  cambió `icono.png`. Se rehicieron `icono.ico` y `icono_aire.ico` (el del
  punto rojo) y la carátula `datos/portada.jpg`. Comprobado a 16 px: 91 de 256
  píxeles cambian y 37 son rojos, así que la versión "al aire" se sigue
  distinguiendo en la barra de tareas.
  ⚠️ **Cambio de criterio en `grabador.CANDIDATAS`:** ahora `icono.png` va
  PRIMERO. Antes mandaba `filadelfia broadcaster.png`, que se había quedado en
  la carpeta con la imagen VIEJA: las grabaciones habrían seguido llevando la
  carátula antigua aunque él hubiera cambiado el icono. Lo natural es que la
  carátula sea la imagen de la aplicación.
  339 comprobaciones en verde. — Estado: ✅ — Siguiente: probar el puerto 8026.

- [2026-08-24] **Icono propio en la barra de tareas, y en rojo al aire.**
  Al usuario le salía **el icono de Python** en la barra de tareas. Causa:
  Windows agrupa las ventanas por una *AppUserModelID*, y la de un script de
  Python es la del propio Python — `iconbitmap()` cambia la ventana pero no eso.
  Se arregla con
  `shell32.SetCurrentProcessExplicitAppUserModelID("VozDeFiladelfia.Broadcaster")`
  **antes** de que aparezca la ventana, más `iconbitmap(default=...)` para que
  valga también en los diálogos.
  Su segunda queja era que, con la app de fondo, no sabía si estaba al aire.
  Ahora **el icono cambia**: se genera `icono_aire.ico` con un punto rojo
  grande abajo a la derecha, y el título pasa a **"* AL AIRE - Filadelfia
  Broadcaster"** (que es lo que se lee al pasar el ratón por la barra y en el
  conmutador de ventanas). Medido a 16 px, que es como se ve de verdad:
  **92 de 256 píxeles cambian y hay 37 rojos**, así que se distingue.
  339 comprobaciones en verde. — Estado: ✅ — Siguiente: probar el puerto 8026.

- [2026-08-24] **Metadatos configurables, vista previa y un fallo que él cazó.**
  **(1) El usuario preguntó si la casilla "Empezar a grabar sola al salir al
  aire" funcionaba. Funcionaba MAL.** Iba por el camino viejo: el emisor
  grababa con una segunda salida de su propio ffmpeg, así que esas grabaciones
  salían **sin etiquetas y sin carátula**, el botón REC no se enteraba y el
  archivo se llamaba siempre `programa_FECHA.mp3`. Quedó suelto al separar la
  grabación en `grabador.py`. **Arreglado:** el emisor ya no graba nunca; la
  casilla arranca el `Grabador`, que es el único que sabe poner los datos.
  *Lección: al mover una responsabilidad de módulo, buscar quién más la hacía.*
  **(2) Metadatos configurables por temporada o programa**, en la pestaña
  **Transmisión** (antes "Carpetas"): autor, álbum/temporada, género y
  comentario, más una **carátula propia** elegible con el explorador. Cada campo
  vacío cae en el valor de la emisora, así que nunca queda un hueco.
  **(3) Vista previa** en esa misma pestaña: una tarjeta que muestra cómo se
  verá en un reproductor (carátula, título, autor, álbum, género y fecha). Se
  calcula con **las mismas funciones** que graban el MP3
  (`grabador.etiquetas()` y `grabador.portada()`), no con una copia del texto:
  si cambia el grabador, la vista cambia sola.
  330 comprobaciones en verde. — Estado: ✅ — Siguiente: probar el puerto 8026.

- [2026-08-24] **Metadatos con carátula en las grabaciones y corte automático.**
  **(1) Las grabaciones ya no dicen "Desconocido".** `grabador.etiquetas()`
  rellena título, artista, artista del álbum, álbum, género, fecha y comentario;
  ningún campo se deja vacío (un campo vacío es justo lo que hace que los
  reproductores pongan "Desconocido"). Sin título de programa, se pone
  "Programa del DD-MM-AAAA". Autor: **Fernando Erick Miranda**, configurable en
  `autor`. **Carátula:** `grabador.portada()` busca `filadelfia broadcaster.png`
  (o `portada.png`/`icono.png`) en la carpeta de la app, la convierte **una vez**
  a JPEG de 600×600 en `datos/portada.jpg` —los reproductores tragan mejor JPEG,
  y meter 1.7 MB en cada grabación sería un desperdicio— y la incrusta como
  `attached_pic`. Verificado con ffprobe sobre un MP3 real: las nueve etiquetas
  puestas y la imagen dentro.
  **(2) Corte automático al acabar la lista.** Si "Repetir" está quitado y la
  lista se termina, se cierra la grabación, se corta la emisión y la emisora
  vuelve a su programación. Casilla **"Cortar al final"** junto a Repetir
  (`cortar_al_terminar`). Sirve para dejar un bloque programado e irse.
  **(3) autoDJ:** comprobado que sus puertos 8026/8027 vuelven a estar abiertos,
  o sea que lo tiene encendido. **No hace falta apagarlo**: emitiendo al 8026 el
  harbor de Liquidsoap toma la fuente en vivo y devuelve la programación solo al
  desconectar. Queda que él lo pruebe cambiando el puerto a 8026.
  314 comprobaciones en verde. — Estado: ✅ — Siguiente: probar el 8026.

- [2026-08-24] **Carpeta de grabaciones configurable + repositorio subido.**
  Nuevo `config.carpeta_graba()`: si el usuario elige una carpeta, esa; si la
  deja en blanco, la de junto a la aplicación (que es lo que la mantiene
  portable). **Si la carpeta elegida deja de existir** —un USB desenchufado, un
  disco de red caído— **vuelve sola a la de siempre en vez de fallar en medio
  de un programa**, que es cuando peor vendría. Campo con botón de examinar en
  Configuración → Carpetas.
  **El repositorio ya está en GitHub**: `artunduaga74/radio-filadelfia`,
  privado. ⚠️ En el primer envío **se coló un MP3 de 4.4 MB** de la carpeta
  `audios/`: música con derechos, que no pinta nada en un repositorio de
  código. Se sacó del control de versiones (el archivo sigue en el disco) y el
  `.gitignore` pasa a excluir `audios/`, `musica/`, `cortinas/` y cualquier
  mp3/wav, salvo los dos tonos de `pruebas/medios/`, que sí hacen falta para
  las comprobaciones. **Sigue en el historial de los commits anteriores**;
  limpiarlo del todo exigiría reescribir el historial y forzar el envío, y eso
  se dejó a decisión del usuario.
  302 comprobaciones en verde. — Estado: ✅ — Siguiente: lo que pida el uso real.

- [2026-08-24] **Retoques de pantalla y volumen de emisión.**
  El usuario mandó capturas anotadas. Cuatro cosas:
  **(1) La raya rara de Configuración era un choque de filas:** en la pestaña
  Audio, `base + 7` estaba usado **tres veces** y `base + 8` dos, así que se
  dibujaban textos encima de separadores. Causa de fondo: numerar filas
  sumando a mano sobre una base. **La pestaña se reescribió con un contador
  `fila` que se incrementa**, que elimina esa clase de error de raíz.
  **(2) El fader de auriculares se movió a Configuración → Audio**, como pedía,
  y con eso las cortinas dejan de quedar cortadas (comprobado a cuatro anchos).
  **(3) El título ya no se corta a lo bruto:** `_ajustar_titulo()` lo recorta al
  ancho real con puntos suspensivos y deja el completo en el globo de ayuda.
  Verificado: uno de 1077 px se queda en 674 y cabe en los 688 disponibles.
  **(4) Volumen de emisión (master), con dato medido.** Se midió su señal en
  antena con `ebur128`: **−18.9 LUFS integrados, pico real −3.5 dBFS**. Las
  radios por internet suelen ir a **−16 LUFS**, así que sonaba ~3 dB más floja
  que las demás. Nuevo `master_db` (−12…+12), aplicado ANTES del limitador para
  que el techo siga garantizado. Está en Configuración → Servidor.
  Una prueba del salto de pista falló una vez de cinco: no era el código, era
  el temporizado del relanzamiento de ffmpeg. Margen ampliado y explicado.
  295 comprobaciones en verde. — Estado: ✅ — Siguiente: subir a GitHub.

- [2026-08-24] **Volumen de los auriculares y retraso al oírse.**
  **(1) El volumen del monitor no se podía tocar.** Descuido mío: el ajuste
  `volumen_monitor` existía desde el principio pero **nunca le puse un
  control**. Los botones de volumen de Windows tampoco servían, porque cambian
  el dispositivo *predeterminado* y la aplicación abre el suyo aparte. Ahora
  hay un fader **AURICULARES** en la mesa, en dB. Probado que **no toca lo que
  sale al aire**: bajarlo de 1.0 a 0.1 deja la emisión igual (0.276 vs 0.284).
  **(2) Sí hay latencia, y era mucha: 110 ms medidos.** Desglose en su equipo:
  tarjeta de entrada 42.7 ms + tarjeta de salida 42.7 + bloque de proceso 21.3
  + mirada del limitador 3.0. Por encima de 40-50 ms ya estorba al hablar.
  **El bloque de audio pasa a ser configurable** (`bloque_audio`) y el nuevo
  valor de fábrica es **512** en vez de 1024: medido, baja el total a **59 ms**.
  Por debajo de 512 apenas se gana (256 → 54 ms, 128 → 51 ms) porque manda la
  latencia de la tarjeta, y el riesgo de cortes sube. Selector en
  Configuración → Audio, con `Mezclador.medir_retraso()` para saber el número.
  ⚠️ Lo que de verdad quita el eco al oírse es la **escucha directa por
  hardware**, si el micrófono USB trae salida de auriculares: es instantánea
  por diseño. Con software siempre habrá algo.
  295 comprobaciones en verde. — Estado: ✅ — Siguiente: subir a GitHub (el
  usuario crea el repositorio y yo enlazo y empujo).

- [2026-08-24] **Segunda ronda de calidad: zumbido de red, mono y marca.**
  El usuario dijo que había mejorado pero "algo le falta". Se midió su
  micrófono real otra vez, ahora a fondo:
  - **DC a cero y captura limpia**, descartado.
  - **Zumbido de la red eléctrica**: 60 Hz a **+9.0 dB sobre la banda de voz** y
    su armónico de 120 Hz a **+13.8 dB**. (50 Hz a −12 dB: Panamá es 60 Hz.)
    Se cuela por el cable del micrófono. El corte de graves de una sección solo
    lo bajaba 6 dB.
  - **Solución:** tipo de filtro `notch` nuevo (Q=24) en la red y sus dos
    armónicos, más corte de graves de **4º orden a 90 Hz** (antes 2º a 80).
    Medido sobre su señal real: 60 Hz pasa de +2.2 a −14.7 dB respecto a la voz
    (17 dB menos), 120 Hz baja 6 dB, y **la banda de voz no se mueve** (0.3 dB).
    Ajuste por micrófono: sin filtro / 50 Hz / 60 Hz. Se le dejó en 60.
  - **Emitir en mono**: su fuente es un micrófono mono duplicado, así que en
    estéreo se gasta la mitad del bitrate en codificar una copia. Medido a
    128 kbps con ruido rosa: estéreo llega a **16.7 kHz** y mono a **20.2 kHz**,
    mismo tamaño de archivo. Opción nueva `emitir_mono`, apagada de fábrica
    (con música estéreo no conviene).
  **Marca:** la aplicación pasa a llamarse **Filadelfia Broadcaster**, con
  logotipo sobre la lista de reproducción. Basta con dejar `icono.png` en la
  carpeta; el `.ico` multi-tamaño se genera solo al arrancar.
  ⚠️ Tres pruebas dejaron de pasar al cambiar el corte de graves y al meter el
  filtro de zumbido por defecto: **no eran fallos, eran expectativas viejas**
  (medían el filtro de 2º orden a 80 Hz, y daban por "plano" un ecualizador que
  ahora trae la muesca puesta). Actualizadas.
  285 comprobaciones en verde. — Estado: ✅ — Siguiente: subir a GitHub.

- [2026-08-24] **"No suena con calidad": era un defecto MÍO, medido y corregido.**
  El usuario dijo que el audio no sonaba bien pese a tener buen micrófono, y
  pidió mirar código de otros programas. Antes de importar nada, se midió la
  cadena. **La captura estaba sana** (0.3 % de bloques perdidos, 48 kHz
  nativos, mono duplicado bien): el problema estaba en el procesado.
  **El defecto:** `_limitar` calculaba un factor por bloque y lo aplicaba
  entero. Medido con una señal que lo hace trabajar: **salto de 0.1450 en la
  costura entre bloques, siete veces mayor que la pendiente natural de la onda
  (0.0210)**, y recortando en 68 de 93 bloques. Eso es un chasquido cada 21 ms.
  **La corrección costó tres intentos, todos medidos:**
  1. Suavizar la ganancia → PEOR: el suavizado la retrasaba, el pico se
     escapaba por encima del techo (1.0000) y había que recortarlo a lo bruto.
     Distorsión 0.22 % → 3.74 %.
  2. Con **mirada adelante** (el audio se retrasa 3 ms y la ganancia se toma
     del mínimo de esa ventana, con `minimum_filter1d`): salto 0.0283,
     distorsión 0.05 %, pico exacto 0.9700 y nunca por encima.
  3. Las pruebas cazaron un tercer fallo: **el estado inicial del filtro de un
     polo estaba mal** (`(1-a)*x` en vez de `a*x`), así que los primeros 150 ms
     salían casi mudos cada vez que arrancaba. Afectaba también al compresor y
     a la puerta. Corregido en los tres.
  **Añadido `eq.Puerta`** (puerta de ruido, por micrófono, opcional): baja la
  sala 11.6 dB sin tocar la voz. Necesaria ahora que se puede amplificar +24 dB.
  **Orden de la cadena de voz:** puerta → ecualizador → compresor → volumen.
  Al revés, el compresor levantaría el ruido y la puerta ya no sabría
  distinguirlo de la voz.
  ⚠️ **Sobre copiar de otros programas:** no se copió código. BUTT, Mixxx,
  Audacity y Liquidsoap son GPL, y meter su código aquí le impondría esa
  licencia al proyecto. Lo que se hizo fue implementar las técnicas estándar
  (biquads del recetario de Bristow-Johnson, limitador de mirada adelante,
  compresor y puerta feed-forward), que son práctica de ingeniería documentada,
  no código de nadie.
  275 comprobaciones en verde, con las medidas de calidad clavadas como prueba
  de no regresión. — Estado: ✅ — Siguiente: que lo escuche; sigue sin subir a
  GitHub.

- [2026-08-24] **Seis mejoras de uso pedidas por el usuario.**
  **(1) La barra espaciadora "no funcionaba": no era un bug.** Su `ajustes.json`
  tenía `tecla_espacio: "reproducir"`, de cuando probamos los modos. Estaba
  haciendo exactamente lo configurado. Corregido en su archivo. *Lección: antes
  de buscar el fallo en el código, mirar la configuración REAL del usuario.*
  **(2) Deslizador de posición** en el reproductor: se arrastra para ir a otro
  punto (usa `Pista.saltar_a`, que ya existía). Mientras se arrastra, el reloj
  deja de moverlo.
  **(3) Panel "SONANDO AHORA" más compacto** (313 → 305 px) para que los
  botones de cortina dejaran de quedar cortados abajo.
  **(4) Ventana de Configuración**: se abría a 60 px del borde y los botones de
  abajo quedaban fuera de pantalla. Ahora `_colocar()` la limita a la pantalla,
  el pie se empaqueta con `side="bottom"` ANTES del cuaderno (misma lección del
  `pack` de siempre) y hay botón **Aplicar** que guarda y aplica **sin cerrar**,
  para poder probar la salida de audio sin reabrir el diálogo.
  **(5) Pestañas reordenadas**: Audio primero, Servidor al final.
  **(6) Ganancia del micrófono de verdad.** El fader iba de 0 a 100 % (tope
  x1.0), así que con un micrófono lejano había que subir todo al máximo y aun
  así se oía flojo. Ahora va **en decibelios, de −40 a +24 dB** (hasta x16), con
  el valor a la vista. Y lo que de verdad lo arregla: **`eq.Compresor`**, un
  nivelador de voz (envolvente con `lfilter` en C, no un bucle de Python) que
  sube lo flojo y frena lo fuerte. Medido: +8 dB a una voz floja, −5 dB a una
  fuerte; 30 dB de diferencia entre las dos pasan a 16. Encendido de fábrica,
  con control de refuerzo por micrófono en la pestaña Micrófono.
  ⚠️ Una prueba del ecualizador empezó a fallar al meter el compresor: es que
  el compresor **nivela justo lo que medía**. Se apaga en esa prueba para medir
  solo el ecualizador. 265 comprobaciones en verde. — Estado: ✅ — Siguiente:
  el repositorio sigue sin subir a GitHub.

- [2026-08-24] **Dos bugs reportados por el usuario, los dos reproducidos.**
  **(1) El selector de auriculares no hacía nada** (siempre salía por el
  Bluetooth). Causa: el monitor solo se abría en `Mezclador.arrancar()`, así
  que cambiarlo en Configuración no reabría nada y se seguía oyendo por el
  aparato anterior; además, si el nombre guardado no coincidía, `audio.buscar()`
  devolvía None y sonaba **por la salida por defecto del sistema sin avisar**.
  Nuevo `Mezclador.cambiar_monitor()` (cierra y reabre en caliente, lo llama
  `aplicar_ajustes` al detectar el cambio) y aviso explícito cuando el aparato
  elegido ya no está.
  **(2) La barra espaciadora no abría el micrófono.** Reproducido: con el foco
  en el botón del micrófono la barra se disparaba **dos veces** (el botón la
  recibe antes que la ventana), y en modo "reproducir/pausa" el botón abría el
  micro mientras el atajo pausaba la música — exactamente lo que describió.
  Ver lección 5.
  **Además, a petición suya:** al abrir el micrófono, si "bajar música al
  hablar" está marcado la música baja (como antes) y si NO lo está la música se
  **pausa** y vuelve sola al cerrar; el modo "reproducir/pausa" fuerza el
  reproductor pase lo que pase. Y **anti-acople**: opción de callar los
  auriculares mientras haya un micrófono abierto (para cuando el monitor sale
  por altavoces o por un Bluetooth que no son audífonos), más una red de
  seguridad que corta el monitor si el limitador lleva 2 s recortando más de
  6 dB con el micro abierto, avisando en la barra de estado.
  233 comprobaciones en verde. — Estado: ✅ — Siguiente: sigue sin subir a GitHub.

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
