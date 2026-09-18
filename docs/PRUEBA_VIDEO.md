# Prueba independiente de grabaciones

## Objetivo

Validar acceso a una grabación antes de construir la consola. El producto final debe permitir elegir tienda, día y cámara y navegar manualmente por las grabaciones. No requiere saltar automáticamente al horario de cada acceso.

## Entorno y selección

- Windows, SmartPSS Lite en ejecución.
- DVR identificado por etiqueta: Dahua DH-XVR1A04 (Cooper Series, 4 canales).
- Usuario confirma reproducción activa de HMV, cámara 2.
- Día solicitado: 16/09/2026; intervalo técnico de prueba: 15:52:00–15:52:30.
- Se prueba un tramo breve del día para validar el transporte; no se descarga el día completo.
- Se lee la configuración existente de `P_Qeivision/audit_config.json`. No se importan secretos a este proyecto.

## Resultado observado

1. El proceso SmartPSS Lite mantiene varios puertos TCP locales en escucha.
2. Varios puertos guardados para otras tiendas ya no aparecen en escucha. La configuración estática no demuestra una correspondencia vigente con cada DVR.
3. El puerto 24606, configurado como RTSP de HMV, pertenece a SmartPSS Lite pero restablece la conexión ante la consulta RTSP OPTIONS.
4. Una solicitud RTSP de playback mediante OpenCV/FFmpeg, con canal 2 y las fechas indicadas, devuelve `opened: false` y cero cuadros decodificados.
5. Consultas HTTP de solo lectura a los puertos actuales de SmartPSS Lite tampoco obtienen una respuesta HTTP válida dentro de los plazos de prueba.
6. Esta primera vía RTSP no generó video. Fue reemplazada por la validación P2P descrita debajo.

## Validación P2P posterior

Se implementó una conexión independiente usando `P2PDll.dll` y `dhnetsdk.dll`, ambas incluidas en la instalación local de SmartPSS Lite. La prueba contra HMV obtuvo estos resultados:

1. El servicio cloud informó que el DVR estaba conectado.
2. Se creó un túnel P2P local hacia el puerto NetSDK del grabador.
3. El inicio de sesión moderno fue rechazado por el equipo antiguo; una única prueba con el método heredado compatible funcionó.
4. El DVR informó cuatro canales.
5. La consulta de HMV, cámara 2, para el 16/09/2026 funcionó y devolvió 98 tramos grabados.

Esto demuestra acceso programático de solo lectura a las grabaciones históricas por P2P, fuera de la interfaz de SmartPSS. La falta del complemento HTML ya no bloquea la prueba.

## Descarga y reproducción validadas

Se descargó un tramo de 30 segundos de HMV, cámara 2, solicitado desde las 15:52:00 del 16/09/2026. El DVR entregó 7.948.555 bytes en formato DAV y la conversión local produjo un MP4 de 2.993.864 bytes. Un fotograma extraído muestra la cámara 2 de HMV y la marca 2026-09-16 15:52:04, coincidente con la reproducción observada en SmartPSS.

Archivos locales de la prueba:

- `recordings/HMV_cam2_2026-09-16_155200.mp4`
- `recordings/HMV_cam2_2026-09-16_155205.jpg`

No se modificó la configuración del grabador ni la base de datos.

## Medición del cambio de cámara

Se midió HMV reutilizando un único túnel P2P y una única sesión NetSDK para las cuatro cámaras, con muestras de 10 segundos desde el mismo horario:

- Preparación inicial de túnel y sesión: 12,739 s. Este costo debe pagarse una sola vez al seleccionar tienda/día, nunca en cada cambio de cámara.
- Cámara 2: descarga 3,258 s; remux DAV→MP4 0,178 s.
- Cámara 3: descarga 3,549 s; remux 0,069 s.
- Cámara 4: descarga 3,306 s; remux 0,065 s.
- Cámara 1 no entregó un tramo para ese instante concreto; debe tratarse como ausencia de grabación y no como espera indefinida.

La conversión no es el cuello de botella. La latencia visible proviene de solicitar un nuevo tramo al DVR por P2P. La implementación debe mantener la sesión abierta, dividir el día en segmentos pequeños y precargar en segundo plano el mismo intervalo de las demás cámaras. Con el segmento ya en caché, el cambio puede ser inmediato; si no está listo, la demora esperable de esta prueba es de unos 3–4 segundos.

Estos resultados invalidan considerar probado el puente RTSP utilizado por la consola anterior. No demuestran que RTSP esté deshabilitado en el DVR ni que toda integración P2P sea imposible. También quedan por validar la correspondencia de puertos, la compatibilidad de la ruta de playback y las credenciales del dispositivo concreto.

## Archivos reproducibles

- `tools/probe_smartpss.py`: identifica listeners de SmartPSS y prueba RTSP OPTIONS sin autenticación.
- `tools/probe_device_http.py`: consulta identificación HTTP por loopback; solo intenta autenticación digest si recibe el desafío correspondiente. No imprime credenciales ni números de serie.
- `tools/test_recorded_video.py`: solicita un intervalo breve, limita la ejecución a 45 segundos y suprime mensajes nativos que podrían incluir credenciales. Si obtiene imágenes, guarda una muestra local en `recordings/` para verificar visualmente cámara y fecha.
- `tools/probe_p2p_tunnel.py`: valida el túnel P2P mediante la biblioteca instalada de SmartPSS, sin imprimir el número de serie ni credenciales.
- `tools/query_p2p_recordings.py`: inicia sesión por NetSDK sobre el túnel y enumera rangos grabados de una cámara y un día.
- `tools/download_p2p_clip.py`: descarga un intervalo histórico por NetSDK y convierte DAV a MP4/H.264 apto para navegador.
- `tools/benchmark_camera_switch.py`: mide cambios de canal reutilizando una única sesión P2P/NetSDK.
- `docs/playback_probe_result.json` y `docs/http_probe_result.json`: resultados sin secretos.
- `docs/p2p_tunnel_probe_result.json` y `docs/p2p_recordings_query_result.json`: resultados P2P sin secretos.
- `docs/p2p_download_result.json`: resultado de descarga y conversión sin secretos.
- `docs/camera_switch_benchmark.json`: tiempos observados de preparación, descarga y remux por cámara.

Ejemplo desde PowerShell, usando el entorno Python que ya existe en el proyecto anterior:

```powershell
& '..\P_Qeivision\.venv\Scripts\python.exe' tools/test_recorded_video.py --store HMV --channel 2 --day 2026-09-16 --time 15:52:00
```

## Consola operativa

La prueba se convirtió en un servicio local. La consola consulta los tramos del día, dibuja la línea temporal, descarga bajo demanda el intervalo que selecciona el operador y lo entrega al navegador como MP4. También consulta los accesos y tickets de AutoShop.

La validación integral sobre HMV, cámara 2, del 16/09/2026 obtuvo 101 tramos y 21 accesos. Un clic alrededor de las 15:53 produjo y reprodujo un MP4 de 15,08 segundos en el navegador. La consulta del acceso HMV151 mostró dos renglones de ticket y un total de $5.310.

El 17/09/2026 HMV dejó de responder con `0x80000066`; se confirmó que la tienda estaba sin Internet. La misma prueba sobre HME, cámara 1, funcionó: 87 tramos, 8 accesos, reproducción web desde las 15:16 y ticket HME97 con tres renglones y total de $5.320. Esto confirma que la consola distingue un problema de conectividad de la tienda de un problema del reproductor.

## Reproducción continua

Se validó `CLIENT_PlayBackByTimeEx` con HME, cámara 2, desde las 12:51:30. El SDK inició en 3,716 segundos y entregó los primeros datos a los 4,079 segundos. Durante 45 segundos produjo 10.720 callbacks y 10.977.280 bytes; el flujo se remuxó correctamente a un MP4 de 10.927.402 bytes.

La consola integra ahora ese callback con FFmpeg y entrega MP4 fragmentado por HTTP mientras el DVR sigue transmitiendo. La prueba en Chrome superó 36 segundos continuos, permitió pausar, reanudar, saltar ±10 segundos y cambiar de horario sin conservar bloqueado el flujo anterior. La línea de tiempo amplía desde 24 horas hasta 10 minutos con marcas por minuto.

La presencia de `dhnetsdk.dll` y `P2PDll.dll` en la instalación de SmartPSS es un dato de inventario; no acredita que exista una API de integración P2P documentada y reutilizable en esta instalación.
