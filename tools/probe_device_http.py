"""Read-only device identification via current SmartPSS loopback listeners."""
import json
from pathlib import Path
import psutil
import requests
from requests.auth import HTTPDigestAuth

config = json.loads((Path.home() / 'OneDrive/Desktop/P_Qeivision/audit_config.json').read_text(encoding='utf-8-sig'))
ports = set()
for proc in psutil.process_iter(['name']):
    if (proc.info['name'] or '').lower() != 'smartpsslite.exe':
        continue
    for conn in proc.net_connections(kind='tcp'):
        if conn.status == psutil.CONN_LISTEN:
            ports.add(conn.laddr.port)
session = requests.Session()
session.trust_env = False
reports = []
for port in sorted(ports):
    row = {'port': port}
    try:
        response = session.get(f'http://127.0.0.1:{port}/cgi-bin/magicBox.cgi?action=getSystemInfo',
                               timeout=(2, 3), allow_redirects=False)
        row['http_status'] = response.status_code
        if response.status_code == 401 and response.headers.get('WWW-Authenticate', '').startswith('Digest'):
            creds = config['dvr_credentials']
            response = session.get(f'http://127.0.0.1:{port}/cgi-bin/magicBox.cgi?action=getSystemInfo',
                                   auth=HTTPDigestAuth(creds['user'], creds['pass']),
                                   timeout=(2, 5), allow_redirects=False)
            row['authenticated_status'] = response.status_code
        if response.status_code == 200:
            for line in response.text.splitlines():
                key, sep, value = line.partition('=')
                if sep and key in ('deviceType', 'hardwareVersion', 'processor'):
                    row[key] = value[:100]
                if sep and key == 'serialNumber':
                    row['matched_store'] = next((name for name, store in config['tiendas'].items()
                                                 if str(store.get('sn')) == value.strip()), None)
    except requests.RequestException as exc:
        row['error'] = type(exc).__name__
    reports.append(row)
    print(json.dumps(row), flush=True)
(Path(__file__).resolve().parents[1] / 'docs/http_probe_result.json').write_text(json.dumps(reports, indent=2))
