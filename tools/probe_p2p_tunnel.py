"""Probe a Dahua P2P tunnel on Windows using SmartPSS Lite's installed DLL.

The script reads serial/credentials from the existing local configuration and
never prints them. It does not change DVR settings or download video.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SMARTPSS = Path(r"C:\Program Files\SmartPSSLite")
CONFIG = Path.home() / "OneDrive/Desktop/P_Qeivision/audit_config.json"
SERVERS = (b"www.easy4ipcloud.com", b"www.dahuap2pcloud.com")
SERVER_PORT = 8800
# Application-level constants used by SmartPSS-family P2P clients. These are
# not DVR credentials and are identical across installations.
P2P_USERNAME = b"cba1b29e32cb17aa46b8ff9e73c7f40b"
P2P_GUESS = b"996103384cdf19179e19243e959bbf8b"


def worker(store_name: str) -> dict:
    config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    store = config["tiendas"][store_name]
    serial = str(store["sn"]).encode("ascii")

    os.chdir(SMARTPSS)
    os.add_dll_directory(str(SMARTPSS))
    p2p = C.CDLL(str(SMARTPSS / "P2PDll.dll"))

    p2p.P2P_Init.restype = C.c_int
    p2p.P2P_Init.argtypes = [
        C.c_int, C.c_char_p, C.c_int, C.c_char_p, C.c_char_p,
        C.POINTER(C.c_void_p),
    ]
    p2p.P2P_DeviceStatus.restype = C.c_int
    p2p.P2P_DeviceStatus.argtypes = [C.c_int, C.c_void_p, C.c_char_p]
    p2p.P2P_GetDeviceInfo.restype = C.c_int
    p2p.P2P_GetDeviceInfo.argtypes = [
        C.c_int, C.c_void_p, C.c_char_p, C.c_int, C.c_char_p,
    ]
    p2p.P2P_Connect.restype = C.c_int
    p2p.P2P_Connect.argtypes = [
        C.c_int, C.c_void_p, C.c_char_p, C.c_int, C.POINTER(C.c_int),
        C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p,
    ]
    p2p.P2P_UnInit.restype = C.c_int
    p2p.P2P_UnInit.argtypes = [C.c_int, C.c_void_p]

    attempts = []
    for server in SERVERS:
        handle = C.c_void_p()
        init_result = p2p.P2P_Init(
            0, server, SERVER_PORT, P2P_GUESS, P2P_USERNAME, C.byref(handle)
        )
        row = {
            "server": server.decode(),
            "init_result": init_result,
            "handle_created": bool(handle.value),
        }
        if not handle.value:
            attempts.append(row)
            continue
        try:
            row["device_status"] = p2p.P2P_DeviceStatus(0, handle, serial)
            buffer = C.create_string_buffer(2048)
            row["device_info_result"] = p2p.P2P_GetDeviceInfo(
                0, handle, serial, len(buffer), buffer
            )
            raw_info = buffer.raw.split(b"\x00", 1)[0]
            device_version = b"6.6.5"
            if raw_info:
                try:
                    info = json.loads(raw_info.decode("utf-8", errors="replace"))
                    row["device_info_received"] = True
                    row["device_p2p_version"] = info.get("devp2pver")
                    if info.get("devp2pver"):
                        device_version = str(info["devp2pver"]).encode("ascii")
                except (ValueError, TypeError):
                    row["device_info_received"] = True
            else:
                row["device_info_received"] = False

            local_port = C.c_int(0)
            row["connect_result"] = p2p.P2P_Connect(
                0, handle, serial, 37777, C.byref(local_port),
                b"", device_version, b"", b""
            )
            row["tunnel_created"] = local_port.value > 0
            row["local_port"] = local_port.value or None
        finally:
            # The probe only validates tunnel establishment. A later test will
            # keep it alive while NetSDK queries recordings.
            p2p.P2P_UnInit(0, handle)
        attempts.append(row)
        if row.get("tunnel_created"):
            break
    return {"store": store_name, "attempts": attempts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default="HMV")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.store)), flush=True)
        return

    try:
        completed = subprocess.run(
            [sys.executable, __file__, "--store", args.store, "--worker"],
            capture_output=True,
            text=True,
            timeout=75,
        )
        records = []
        for line in completed.stdout.splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict) and "attempts" in item:
                    records.append(item)
            except ValueError:
                continue
        report = {
            "exit_code": completed.returncode,
            "results": records,
            "native_diagnostics_suppressed": bool(completed.stderr),
        }
        if not records:
            report["error"] = "P2P worker returned no structured result"
    except subprocess.TimeoutExpired:
        report = {"error": "P2P probe exceeded 75 second deadline"}

    output = ROOT / "docs/p2p_tunnel_probe_result.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
