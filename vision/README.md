# Visión QeiVision

Módulo local para analizar video de los DVR Dahua antes de integrarlo con la
consola y `QeiVision-API`.

Se reutiliza del proyecto anterior la idea de lector RTSP de frame fresco y el
tracking persistente con YOLO. Las credenciales y puertos se leen desde la
configuración local y no se escriben en los scripts.

La primera prueba apunta a MEUG, Channel 8, y detecta las clases COCO:

- `0`: persona
- `15`: gato
- `16`: perro

La línea de ingreso todavía se definirá después de observar varios clips.
