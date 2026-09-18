# Despliegue inicial

## Frontend en Vercel

Importar el repositorio `EduardoSan365/QeiVision_v1` en Vercel y configurar la
carpeta raíz como `web`. No se requiere build command: es una aplicación
estática.

Durante el desarrollo, `web/runtime-config.js` deja vacía la base de la API y
la consola usa las rutas relativas del servidor local. Cuando `QeiVision-API`
esté disponible, establecer allí la URL pública de la API:

```js
window.QEIVISION_API_BASE = 'https://URL-DE-LA-API';
```

Este archivo sólo contiene configuración pública; nunca debe incluir secretos.

## API

La API real se ejecutará de forma independiente en el servidor Ubuntu y será
la única capa autorizada para consultar AutoShop. El frontend no se conecta
directamente a SQL Server.
