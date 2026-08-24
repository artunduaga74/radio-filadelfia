# Pruebas

Se ejecutan solas y **no tocan la configuración real**: cada prueba redirige
`config` a una carpeta temporal antes de importar la aplicación. Tampoco tocan
el servidor: no transmiten nada.

```bash
python pruebas/prueba_motor.py     # 28 comprobaciones del audio
python pruebas/prueba_ventana.py   # 33 comprobaciones de la interfaz
```

`prueba_motor.py` mide el audio de verdad (niveles en dBFS, el ducking, el
limitador, los fundidos) en vez de comprobar que "no dio error".

`prueba_ventana.py` abre la ventana real y verifica, entre otras cosas, que
**todo siga visible al tamaño mínimo** — dos fallos de maquetación aparecieron
justo ahí.

`medios/` son dos tonos generados con amplitud conocida. Si hay que
regenerarlos:

```bash
ffmpeg -y -f lavfi -i "aevalsrc=0.7*sin(2*PI*440*t):s=48000:d=5" -ac 2 pruebas/medios/tono.wav
ffmpeg -y -f lavfi -i "aevalsrc=0.5*sin(2*PI*880*t):s=48000:d=2" -ac 2 pruebas/medios/jingle.wav
```

> Ojo: el filtro `sine` de ffmpeg genera a **−21 dB**, no a fondo de escala. Por
> eso se usa `aevalsrc`, con la amplitud escrita explícitamente.
