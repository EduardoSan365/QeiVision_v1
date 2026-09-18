"""Read-only local SmartPSS service probe. Never prints credentials or SNs."""
import json
import socket
from pathlib import Path

import psutil

CONFIG = Path.home() / 'OneDrive/Desktop/P_Qeivision/audit_config.json'


def main():
    config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    configured = {}
    for store, item in config['tiendas'].items():
        for kind in ('http_port', 'rtsp_port'):
            if item.get(kind):
                configured.setdefault(int(item[kind]), []).append(f'{store}:{kind}')
    listeners = {}
    processes = []
    for process in psutil.process_iter(['pid', 'name']):
        if 'smartpss' not in (process.info['name'] or '').lower():
            continue
        processes.append(process.info)
        try:
            for connection in process.net_connections(kind='tcp'):
                if connection.status == psutil.CONN_LISTEN:
                    listeners[connection.laddr.port] = process.info['name']
        except (psutil.AccessDenied, psutil.NoSuchProcess) as exc:
            print(json.dumps({'process': process.info['name'], 'error': type(exc).__name__}))
    print(json.dumps({'processes': processes, 'listeners': listeners}))
    for port in sorted(set(configured) | set(listeners)):
        result = {'port': port, 'configured_for': configured.get(port, []),
                  'owner': listeners.get(port)}
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=2) as sock:
                sock.settimeout(2)
                sock.sendall(f'OPTIONS rtsp://127.0.0.1:{port}/ RTSP/1.0\r\nCSeq: 1\r\n\r\n'.encode())
                data = sock.recv(2048)
                first = data.split(b'\r\n', 1)[0]
                result['status'] = first.decode('ascii', errors='replace')[:100] if first.startswith((b'RTSP/', b'HTTP/')) else 'non-RTSP/HTTP reply'
                result['rtsp'] = data.startswith(b'RTSP/')
        except OSError as exc:
            result['error'] = type(exc).__name__
            result['errno'] = exc.errno
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
