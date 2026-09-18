from __future__ import annotations

import datetime as dt

import pymssql


class AutoShopDatabase:
    def __init__(self, config: dict):
        self.config = config

    def connect(self):
        db = self.config["db"]
        return pymssql.connect(
            server=db["server"],
            user=db["user"],
            password=db["password"],
            database=db["database"],
            port=int(db.get("port", 1433)),
            login_timeout=10,
            timeout=20,
        )

    def fetch_accesses(self, store_key: str, day: str) -> list[dict]:
        return self.fetch_accesses_range(store_key, day, day)

    def fetch_accesses_range(self, store_key: str, start_day: str, end_day: str) -> list[dict]:
        store = self.config["tiendas"].get(store_key)
        if not store:
            raise ValueError(f"Tienda desconocida: {store_key}")
        start_date = dt.date.fromisoformat(start_day)
        end_date = dt.date.fromisoformat(end_day)
        if end_date < start_date:
            raise ValueError("La fecha hasta no puede ser anterior a la fecha desde.")
        if (end_date - start_date).days > 31:
            raise ValueError("El rango máximo de auditoría es de 31 días.")
        start = f"{start_day} 00:00:00"
        end = f"{end_day} 23:59:59"
        connection = self.connect()
        try:
            cursor = connection.cursor(as_dict=True)
            cursor.execute(
                """
                SELECT c.Id, c.Fecha, c.UsuarioId, c.Tipo, c.MensajeVuelta,
                       u.Usuario, u.Dni, u.Celular, uf.Numero AS Lote
                FROM CommLog c
                LEFT JOIN Usuarios u ON c.UsuarioId = u.Id
                LEFT JOIN UnidadesFuncionales uf ON u.UnidadFuncionalId = uf.Id
                WHERE c.SucursalId = %s
                  AND c.Tipo = 'PUERTA'
                  AND c.Fecha BETWEEN %s AND %s
                ORDER BY c.Fecha DESC
                """,
                (store["sucursal_id"], start, end),
            )
            rows = cursor.fetchall()
            result = []
            seen_sale_accesses: set[tuple[int, tuple[int, ...]]] = set()
            for row in rows:
                event_time = row["Fecha"]
                user_id = row["UsuarioId"]
                has_sale = False
                total = 0.0
                sale_ids: tuple[int, ...] = ()
                if event_time and user_id:
                    window_end = event_time + dt.timedelta(minutes=45)
                    cursor.execute(
                        """
                        SELECT Id, Importe
                        FROM Ventas
                        WHERE UsuarioId = %s AND Fecha BETWEEN %s AND %s
                        ORDER BY Fecha, Id
                        """,
                        (user_id, event_time, window_end),
                    )
                    sales = cursor.fetchall()
                    sale_ids = tuple(int(sale["Id"]) for sale in sales)
                    has_sale = bool(sales)
                    total = sum(float(sale["Importe"] or 0) for sale in sales)

                # El DVR puede registrar dos aperturas consecutivas para un mismo
                # ingreso. Si ambas encuentran exactamente las mismas ventas, es
                # el mismo ticket y no deben aparecer como dos compras.
                sale_key = (int(user_id), sale_ids) if user_id and sale_ids else None
                if sale_key and sale_key in seen_sale_accesses:
                    continue
                if sale_key:
                    seen_sale_accesses.add(sale_key)
                result.append(
                    {
                        "id": row["Id"],
                        "fecha": event_time.strftime("%Y-%m-%d %H:%M:%S") if event_time else "",
                        "hora": event_time.strftime("%H:%M:%S") if event_time else "",
                        "usuario_id": user_id,
                        "usuario": row["Usuario"] or "Invitado",
                        "dni": row["Dni"] or "-",
                        "celular": row["Celular"] or "-",
                        "lote": str(row["Lote"] or "-"),
                        "compro": has_sale,
                        "total_venta": total,
                        "estado": "COMPRO" if has_sale else "SIN_COMPRA",
                    }
                )
            return result
        finally:
            connection.close()

    def fetch_ticket(self, user_id: int, access_time: str) -> dict:
        access = dt.datetime.strptime(access_time, "%Y-%m-%d %H:%M:%S")
        start = access - dt.timedelta(minutes=10)
        end = access + dt.timedelta(minutes=45)
        connection = self.connect()
        try:
            cursor = connection.cursor(as_dict=True)
            cursor.execute(
                """
                SELECT v.Id AS VentaId, v.Fecha, v.Importe, dv.ProductoId,
                       p.Nombre AS Producto, dv.Cantidad,
                       COALESCE(dv.Subtotal, dv.Importe, 0) AS Subtotal
                FROM Ventas v
                INNER JOIN DetalleVenta dv ON v.Id = dv.VentaId
                LEFT JOIN Productos p ON dv.ProductoId = p.Id
                WHERE v.UsuarioId = %s AND v.Fecha BETWEEN %s AND %s
                ORDER BY v.Fecha ASC
                """,
                (user_id, start, end),
            )
            tickets: dict[int, dict] = {}
            for row in cursor.fetchall():
                ticket_id = row["VentaId"]
                ticket = tickets.setdefault(
                    ticket_id,
                    {
                        "ticket_id": ticket_id,
                        "hora": row["Fecha"].strftime("%H:%M:%S") if row["Fecha"] else "",
                        "importe_total": float(row["Importe"] or 0),
                        "items": [],
                    },
                )
                ticket["items"].append(
                    {
                        "producto": (row["Producto"] or f"Producto #{row['ProductoId']}").strip(),
                        "cantidad": float(row["Cantidad"] or 1),
                        "subtotal": float(row["Subtotal"] or 0),
                    }
                )
            values = list(tickets.values())
            return {
                "compro": bool(values),
                "tickets": values,
                "total_abonado": sum(ticket["importe_total"] for ticket in values),
            }
        finally:
            connection.close()
