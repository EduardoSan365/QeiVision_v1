from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import urllib.parse

from qeivision.config import PROJECT_ROOT, load_config, public_stores
from qeivision.database import AutoShopDatabase


WEB_DIR = PROJECT_ROOT / "web"
CONFIG = load_config()
DATABASE = AutoShopDatabase(CONFIG)


class AuditHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[HTTP] {self.address_string()} - {fmt % args}")

    def do_HEAD(self):
        self._handle(head_only=True)

    def do_GET(self):
        self._handle(head_only=False)

    def _handle(self, head_only: bool) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/api/tiendas":
                self.send_json({"status": "ok", "tiendas": public_stores(CONFIG)}, head_only=head_only)
                return
            if parsed.path == "/api/accesos":
                store = params.get("tienda", [""])[0]
                start_day = params.get("desde", params.get("fecha", [""]))[0]
                end_day = params.get("hasta", [start_day])[0]
                data = DATABASE.fetch_accesses_range(store, start_day, end_day)
                self.send_json({"status": "ok", "accesos": data}, head_only=head_only)
                return
            if parsed.path == "/api/auditoria":
                user_id = int(params.get("usuario_id", ["0"])[0])
                access_time = params.get("fecha", [""])[0]
                data = DATABASE.fetch_ticket(user_id, access_time)
                self.send_json({"status": "ok", "auditoria": data}, head_only=head_only)
                return
            if parsed.path.startswith("/api/"):
                self.send_json({"status": "error", "message": "API inexistente."}, 404)
                return
            super().do_HEAD() if head_only else super().do_GET()
        except (ValueError, KeyError) as error:
            self.send_json({"status": "error", "message": str(error)}, 400)
        except Exception as error:
            print(f"[ERROR] {type(error).__name__}: {error}")
            self.send_json({"status": "error", "message": "No se pudo completar la operación."}, 500)

    def send_json(self, data: dict, status: int = 200, head_only: bool = False) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)


import socket


def run(port: int = 8080) -> None:
    server = None
    # 1. Intentar servidor Dual-Stack (IPv6 ::1 + IPv4 127.0.0.1 simultáneos para localhost)
    try:
        class DualStackServer(ThreadingHTTPServer):
            address_family = socket.AF_INET6
            allow_reuse_address = True

            def server_bind(self):
                try:
                    self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                except Exception:
                    pass
                super().server_bind()

        server = DualStackServer(("::", port), AuditHandler)
    except Exception:
        # 2. Fallback estándar a IPv4
        try:
            class IPv4Server(ThreadingHTTPServer):
                allow_reuse_address = True

            server = IPv4Server(("0.0.0.0", port), AuditHandler)
        except Exception:
            class LocalServer(ThreadingHTTPServer):
                allow_reuse_address = True

            server = LocalServer(("127.0.0.1", port), AuditHandler)

    print("==================================================")
    print(" QeiVision Auditoría iniciada exitosamente")
    print(f" Servidor activo en puerto {port}")
    print(f" Abrí en tu navegador:")
    print(f"   -> http://localhost:{port}")
    print(f"   -> http://127.0.0.1:{port}")
    print("==================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo QeiVision...")
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    run(args.port)
