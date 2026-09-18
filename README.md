# QeiVision

Consola local de auditoría para cotejar accesos, grabaciones Dahua y tickets de AutoShop.

## Estado actual

La versión operativa está validada con HME, cámaras 1 y 2, para el 16/09/2026:

- conexión al DVR por P2P usando su número de serie;
- consulta de las grabaciones disponibles del día;
- reproducción histórica continua mediante NetSDK y MP4 fragmentado;
- inicio del video mientras el DVR continúa enviando datos;
- consulta de accesos y tickets en AutoShop;
- cámara fija durante toda la sesión de auditoría;
- línea general de 24 horas ampliable hasta ventanas de 10 minutos;
- marcas por minuto, desplazamiento temporal y rueda del mouse para ampliar;
- pausa, reanudación, detención, velocidades y saltos de ±10 segundos.

SmartPSS Lite puede permanecer abierto como herramienta de respaldo, pero la consola no usa su interfaz ni el complemento HTML para reproducir. Utiliza las bibliotecas Dahua instaladas junto con SmartPSS Lite.

## Iniciar

1. Ejecutar `iniciar_qeivision.cmd`. El iniciador abre SmartPSS Lite si está cerrado y espera unos segundos.
2. Comprobar en SmartPSS Lite que el DVR figure **En línea**.
3. Si el navegador no se abre solo, visitar `http://127.0.0.1:8080`.
4. Elegir tienda, fecha y cámara, y pulsar **Iniciar Auditoría**.
5. Seleccionar un acceso en la columna izquierda para consultar su ticket.
6. Hacer clic en una franja amarilla para iniciar la reproducción continua desde ese horario.
7. Usar `+` o la rueda del mouse sobre la línea para ampliar; `◀` y `▶` desplazan la ventana.

La primera conexión P2P puede tardar algunos segundos. En la prueba de HME cámara 2, el flujo comenzó a entregar datos en 4,1 segundos y continuó más allá del límite anterior de 15 segundos.

## Configuración

`config.local.json` contiene la configuración privada y no se versiona. La consola sólo escucha en `127.0.0.1`, por lo que no queda expuesta a la red local.

El entorno Python se encuentra en `.venv` dentro de este proyecto. Las dependencias declaradas están en `requirements.txt`.

## Documentación técnica

- [Arquitectura](docs/ARQUITECTURA.md)
- [Prueba de video P2P](docs/PRUEBA_VIDEO.md)
