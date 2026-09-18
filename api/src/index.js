const express = require('express');
const cors = require('cors');
const rateLimit = require('express-rate-limit');
const sql = require('mssql');
require('dotenv').config({ path: require('path').join(__dirname, '..', '.env') });

const app = express();
const port = Number(process.env.PORT || 6700);
const stores = JSON.parse(process.env.STORES_JSON || '{}');
const allowedOrigins = (process.env.CORS_ORIGINS || '').split(',').map(value => value.trim()).filter(Boolean);
const poolPromise = sql.connect({
  user: process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  server: process.env.DB_SERVER,
  port: Number(process.env.DB_PORT || 1433),
  database: process.env.DB_NAME || 'Autoshop',
  options: {
    encrypt: String(process.env.DB_ENCRYPT).toLowerCase() === 'true',
    trustServerCertificate: String(process.env.DB_TRUST_SERVER_CERTIFICATE).toLowerCase() === 'true',
  },
});

app.use(cors({ origin: (origin, callback) => {
  if (!origin || allowedOrigins.length === 0 || allowedOrigins.includes(origin)) return callback(null, true);
  return callback(new Error('Origen no permitido.'));
}}));
app.use(express.json());
app.use(rateLimit({ windowMs: 60 * 1000, limit: 120, standardHeaders: true, legacyHeaders: false }));

app.get('/health', (_req, res) => res.json({ status: 'ok', service: 'QeiVision-API' }));
app.get('/api/tiendas', (_req, res) => res.json({ status: 'ok', tiendas: stores }));

app.get('/api/accesos', async (req, res, next) => {
  try {
    const store = stores[req.query.tienda];
    const from = String(req.query.desde || '');
    const to = String(req.query.hasta || from);
    if (!store || !/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) {
      return res.status(400).json({ status: 'error', message: 'Tienda o rango de fechas inválido.' });
    }
    const db = await poolPromise;
    const result = await db.request()
      .input('sucursal', sql.Int, store.sucursal_id)
      .input('desde', sql.DateTime2, `${from} 00:00:00`)
      .input('hasta', sql.DateTime2, `${to} 23:59:59`)
      .query(`SELECT c.Id, c.Fecha, CONVERT(varchar(19), c.Fecha, 120) AS FechaTexto,
                     CONVERT(varchar(8), c.Fecha, 108) AS HoraTexto,
                     c.UsuarioId, u.Usuario, u.Dni, u.Celular,
                     uf.Numero AS Lote
              FROM CommLog c
              LEFT JOIN Usuarios u ON c.UsuarioId = u.Id
              LEFT JOIN UnidadesFuncionales uf ON u.UnidadFuncionalId = uf.Id
              WHERE c.SucursalId = @sucursal AND c.Tipo = 'PUERTA'
                AND c.Fecha BETWEEN @desde AND @hasta
              ORDER BY c.Fecha DESC`);
    const seenSales = new Set();
    const accesos = [];
    for (const row of result.recordset) {
      let sales = [];
      if (row.Fecha && row.UsuarioId) {
        const salesResult = await db.request().input('usuario', sql.Int, row.UsuarioId)
          .input('desde', sql.DateTime2, row.Fecha)
          .input('hasta', sql.DateTime2, new Date(row.Fecha.getTime() + 45 * 60 * 1000))
          .query('SELECT Id, Importe FROM Ventas WHERE UsuarioId = @usuario AND Fecha BETWEEN @desde AND @hasta ORDER BY Fecha, Id');
        sales = salesResult.recordset;
      }
      const saleKey = row.UsuarioId && sales.length ? `${row.UsuarioId}:${sales.map(sale => sale.Id).join(',')}` : '';
      if (saleKey && seenSales.has(saleKey)) continue;
      if (saleKey) seenSales.add(saleKey);
      const total = sales.reduce((sum, sale) => sum + Number(sale.Importe || 0), 0);
      accesos.push({
        id: row.Id,
        fecha: row.FechaTexto || '', hora: row.HoraTexto || '',
        usuario_id: row.UsuarioId,
        usuario: row.Usuario || 'Invitado',
        dni: row.Dni || '-', celular: row.Celular || '-', lote: String(row.Lote || '-'),
        compro: sales.length > 0, total_venta: total, estado: sales.length ? 'COMPRO' : 'SIN_COMPRA',
      });
    }
    return res.json({ status: 'ok', accesos });
  } catch (error) { return next(error); }
});

app.get('/api/auditoria', async (req, res, next) => {
  try {
    const userId = Number(req.query.usuario_id);
    const accessTime = String(req.query.fecha || '');
    if (!Number.isInteger(userId) || !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(accessTime)) return res.status(400).json({ status: 'error', message: 'Referencia inválida.' });
    const db = await poolPromise;
    const result = await db.request().input('usuario', sql.Int, userId).input('fecha', sql.VarChar(19), accessTime)
      .query(`SELECT v.Id AS VentaId, v.Fecha, CONVERT(varchar(8), v.Fecha, 108) AS HoraVenta,
                     v.Importe, dv.ProductoId, p.Nombre AS Producto,
                     dv.Cantidad, COALESCE(dv.Subtotal, dv.Importe, 0) AS Subtotal
              FROM Ventas v INNER JOIN DetalleVenta dv ON v.Id = dv.VentaId
              LEFT JOIN Productos p ON dv.ProductoId = p.Id
              WHERE v.UsuarioId = @usuario
                AND v.Fecha BETWEEN DATEADD(minute, -10, CONVERT(datetime2, @fecha))
                                 AND DATEADD(minute, 45, CONVERT(datetime2, @fecha))
              ORDER BY v.Fecha ASC`);
    const tickets = new Map();
    for (const row of result.recordset) {
      if (!tickets.has(row.VentaId)) tickets.set(row.VentaId, { ticket_id: row.VentaId, hora: row.HoraVenta || '', importe_total: Number(row.Importe || 0), items: [] });
      tickets.get(row.VentaId).items.push({ producto: (row.Producto || `Producto #${row.ProductoId}`).trim(), cantidad: Number(row.Cantidad || 1), subtotal: Number(row.Subtotal || 0) });
    }
    const values = [...tickets.values()];
    return res.json({ status: 'ok', auditoria: { compro: values.length > 0, tickets: values, total_abonado: values.reduce((sum, ticket) => sum + ticket.importe_total, 0) } });
  } catch (error) { return next(error); }
});

app.use((error, _req, res, _next) => { console.error('[QeiVision-API]', error.message); res.status(500).json({ status: 'error', message: 'No se pudo completar la operación.' }); });
app.listen(port, () => console.log(`QeiVision-API escuchando en puerto ${port}`));
