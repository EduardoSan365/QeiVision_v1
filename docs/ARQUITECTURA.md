# Arquitectura y validaciones iniciales

## Conexión de video validada

La consola abre un túnel P2P con las bibliotecas instaladas de SmartPSS Lite, inicia sesión NetSDK y consulta las grabaciones históricas del canal fijo. La reproducción utiliza `CLIENT_PlayBackByTimeEx`: los datos llegan por callback y FFmpeg los remuxa en tiempo real como MP4 fragmentado para el navegador.

El navegador comienza a reproducir mientras el DVR continúa enviando datos. Un nuevo posicionamiento detiene el flujo anterior y abre otro en el segundo seleccionado. No se descarga previamente un archivo completo ni existe ya un límite fijo de 15 segundos.

Ejemplo documental, sin credenciales reales:
rtsp://USUARIO:CLAVE@HOST:554/cam/realmonitor?channel=1&subtype=1

La documentación Dahua distingue el stream principal (subtype=0) del secundario (subtype=1). La compatibilidad exacta debe comprobarse con el equipo disponible.
Fuente: https://material.dahuasecurity.com/uploads/cpq/DOR/PUM0003575/Dahua-Network-Camera-Web-3.0_OperationManual_V2.1.5.pdf

## P2P

La conexión, consulta histórica, descarga y reproducción continua fueron validadas con equipos Dahua antiguos por número de serie. SmartPSS Lite debe estar ejecutándose y la tienda debe tener Internet. Un DVR fuera de línea se informa como un problema de conectividad y no bloquea la interfaz indefinidamente.

## Línea de tiempo

La vista comienza con las 24 horas y puede ampliarse sucesivamente a 12, 8, 4, 2 y 1 hora, 30 minutos y 10 minutos. El zoom conserva el segundo señalado como foco. La regla, las franjas grabadas, los accesos y el cabezal se recalculan para la ventana visible.

## Auditoría
Entidades propuestas: tienda, equipo, canal, evento de acceso, referencia de grabación y revisión.
Conservar identificador del evento QeiSHOP, fecha UTC, zona horaria de la tienda y correspondencia con el reloj del grabador. Un stream en vivo no resuelve por sí solo la consulta histórica: validar reproducción o descarga de grabaciones del NVR, o definir grabación propia y retención.

### Cámara por sesión de auditoría

Cada sesión de la consola se vincula a una tienda, una fecha y una única cámara de auditoría. Una vez iniciada, esa cámara queda fija durante toda la sesión y es el único canal que consulta, descarga, convierte y reproduce la consola.

La cámara puede redefinirse al iniciar una nueva sesión. La selección anterior puede ofrecerse como valor predeterminado de la tienda, pero cambiarla no altera sesiones ya iniciadas. Si el operador necesita revisar otros ángulos durante una auditoría activa, utilizará SmartPSS como herramienta complementaria.

Esta decisión evita abrir o precargar varios canales, reduce el tráfico P2P y elimina el cambio de cámara como cuello de botella en la primera versión.

## Configuración
Mantener las credenciales de cámaras en el servidor; entregar al navegador únicamente sesiones autorizadas de reproducción. No versionar secretos, grabaciones ni datos de clientes.

## Datos necesarios para la primera prueba
- Modelo y firmware del DVR/NVR Dahua.
- Disponibilidad de red local, VPN o únicamente P2P.
- Canal de cámara para la prueba y códec configurado.
- Forma de consultar los eventos de acceso de QeiSHOP.
- Disponibilidad y retención de grabaciones históricas.

## Trabajo previo localizado
Existe una carpeta independiente P_Qeivision en el escritorio. Se observó su listado de archivos, pero no se importaron scripts, configuraciones ni credenciales. Evaluar su reutilización si se solicita.
