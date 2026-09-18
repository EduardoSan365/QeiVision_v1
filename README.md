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

## Despliegue

La consola web se trabaja mediante Git, Vercel y la API oficial de QeiVision.
No se utiliza un servidor web local ni un puerto `localhost` para la aplicación.

La primera conexión P2P puede tardar algunos segundos. En la prueba de HME cámara 2, el flujo comenzó a entregar datos en 4,1 segundos y continuó más allá del límite anterior de 15 segundos.

## Configuración

Las credenciales y variables de despliegue se administran fuera del repositorio, en la configuración del proyecto de Vercel y de la API.

## Documentación técnica

- [Arquitectura](docs/ARQUITECTURA.md)
- [Prueba de video P2P](docs/PRUEBA_VIDEO.md)
