"""Download and convert a short historical Dahua clip over P2P on Windows."""
from __future__ import annotations

import argparse
import ctypes as C
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import imageio_ffmpeg

from query_p2p_recordings import (
    CONFIG, ROOT, SMARTPSS, P2P_GUESS, P2P_SERVERS, P2P_USERNAME,
    DWORD, LDWORD, LLONG, NET_DEVICEINFO_EX, NET_IN_LOGIN, NET_OUT_LOGIN,
    NET_RECORDFILE_INFO, NET_TIME,
    configure_p2p, net_time,
)


DOWNLOAD_POS = C.WINFUNCTYPE(
    None, LLONG, DWORD, DWORD, C.c_int, NET_RECORDFILE_INFO, LDWORD
)
DISCONNECT = C.WINFUNCTYPE(None, LLONG, C.c_char_p, C.c_int, LDWORD)


def load_sdk():
    C.CDLL(str(SMARTPSS / "dhconfigsdk.dll"))
    sdk = C.CDLL(str(SMARTPSS / "dhnetsdk.dll"))
    sdk.CLIENT_Init.restype = C.c_int
    sdk.CLIENT_Init.argtypes = [DISCONNECT, LDWORD]
    sdk.CLIENT_SetConnectTime.argtypes = [C.c_int, C.c_int]
    sdk.CLIENT_LoginWithHighLevelSecurity.restype = LLONG
    sdk.CLIENT_LoginWithHighLevelSecurity.argtypes = [C.c_void_p, C.c_void_p]
    sdk.CLIENT_LoginEx2.restype = LLONG
    sdk.CLIENT_LoginEx2.argtypes = [
        C.c_char_p, C.c_ushort, C.c_char_p, C.c_char_p, C.c_int,
        C.c_void_p, C.POINTER(NET_DEVICEINFO_EX), C.POINTER(C.c_int),
    ]
    sdk.CLIENT_DownloadByTimeEx.restype = LLONG
    sdk.CLIENT_DownloadByTimeEx.argtypes = [
        LLONG, C.c_int, C.c_int, C.POINTER(NET_TIME), C.POINTER(NET_TIME),
        C.c_char_p, DOWNLOAD_POS, LDWORD, C.c_void_p, LDWORD, C.c_void_p,
    ]
    sdk.CLIENT_StopDownload.argtypes = [LLONG]
    sdk.CLIENT_GetLastError.restype = DWORD
    sdk.CLIENT_Logout.argtypes = [LLONG]
    sdk.CLIENT_Cleanup.argtypes = []
    return sdk


def open_tunnel(p2p, serial: bytes):
    for server in P2P_SERVERS:
        handle = C.c_void_p()
        if p2p.P2P_Init(0, server, 8800, P2P_GUESS, P2P_USERNAME,
                        C.byref(handle)) != 0 or not handle.value:
            continue
        info_buffer = C.create_string_buffer(2048)
        p2p.P2P_GetDeviceInfo(0, handle, serial, len(info_buffer), info_buffer)
        device_version = b"6.6.5"
        raw = info_buffer.raw.split(b"\x00", 1)[0]
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8", errors="replace"))
                if parsed.get("devp2pver"):
                    device_version = str(parsed["devp2pver"]).encode("ascii")
            except ValueError:
                pass
        local_port = C.c_int(0)
        p2p.P2P_Connect(0, handle, serial, 37777, C.byref(local_port),
                        b"", device_version, b"", b"")
        if local_port.value:
            return handle, local_port.value
        p2p.P2P_UnInit(0, handle)
    return None, 0


def worker(store_name: str, channel: int, start_text: str, seconds: int) -> dict:
    config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    store = config["tiendas"][store_name]
    creds = config["dvr_credentials"]
    serial = str(store["sn"]).encode("ascii")
    username = str(creds["user"]).encode("utf-8")
    password = str(creds["pass"]).encode("utf-8")
    start = dt.datetime.fromisoformat(start_text)
    end = start + dt.timedelta(seconds=seconds)

    os.chdir(SMARTPSS)
    os.add_dll_directory(str(SMARTPSS))
    p2p = configure_p2p()
    p2p_handle, local_port = open_tunnel(p2p, serial)
    result = {"store": store_name, "channel": channel,
              "start": str(start), "end": str(end),
              "tunnel_created": bool(local_port)}
    if not local_port:
        return result

    sdk = load_sdk()
    disconnect_cb = DISCONNECT(lambda *_: None)
    login_handle = 0
    download_handle = 0
    try:
        result["sdk_initialized"] = bool(sdk.CLIENT_Init(disconnect_cb, 0))
        sdk.CLIENT_SetConnectTime(10000, 2)
        time.sleep(2)
        modern_in = NET_IN_LOGIN()
        modern_in.dwSize = C.sizeof(NET_IN_LOGIN)
        modern_in.szIP = b"127.0.0.1"
        modern_in.nPort = local_port
        modern_in.szUserName = username
        modern_in.szPassword = password
        modern_in.emSpecCap = 0
        modern_out = NET_OUT_LOGIN()
        modern_out.dwSize = C.sizeof(NET_OUT_LOGIN)
        login_handle = sdk.CLIENT_LoginWithHighLevelSecurity(
            C.byref(modern_in), C.byref(modern_out)
        )
        result["modern_login_succeeded"] = bool(login_handle)
        result["modern_login_error"] = modern_out.nError
        info = NET_DEVICEINFO_EX()
        login_error = C.c_int(0)
        if not login_handle:
            login_handle = sdk.CLIENT_LoginEx2(
                b"127.0.0.1", local_port, username, password, 0, None,
                C.byref(info), C.byref(login_error),
            )
        result["login_succeeded"] = bool(login_handle)
        result["login_error"] = login_error.value
        if not login_handle:
            result["sdk_error"] = int(sdk.CLIENT_GetLastError())
            return result

        output_dir = ROOT / "recordings"
        output_dir.mkdir(exist_ok=True)
        stem = f"{store_name}_cam{channel}_{start:%Y-%m-%d_%H%M%S}"
        dav_path = output_dir / f"{stem}.dav"
        mp4_path = output_dir / f"{stem}.mp4"
        completed = threading.Event()

        @DOWNLOAD_POS
        def on_progress(_handle, total, downloaded, _index, _record, _user):
            if downloaded == 0xFFFFFFFF or (total > 0 and downloaded >= total):
                completed.set()

        callback_ref = on_progress
        start_net, end_net = net_time(start), net_time(end)
        download_handle = sdk.CLIENT_DownloadByTimeEx(
            login_handle, channel - 1, 0, C.byref(start_net), C.byref(end_net),
            os.fsencode(dav_path), callback_ref, 0, None, 0, None,
        )
        result["download_started"] = bool(download_handle)
        if not download_handle:
            result["sdk_error"] = int(sdk.CLIENT_GetLastError())
            return result
        result["download_completed"] = completed.wait(timeout=75)
        sdk.CLIENT_StopDownload(download_handle)
        download_handle = 0
        result["dav_bytes"] = dav_path.stat().st_size if dav_path.exists() else 0
        if not result["dav_bytes"]:
            return result

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        converted = subprocess.run(
            [ffmpeg, "-y", "-i", str(dav_path), "-map", "0:v:0",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-an", str(mp4_path)],
            capture_output=True, text=True, timeout=90,
        )
        result["conversion_succeeded"] = (
            converted.returncode == 0 and mp4_path.exists() and mp4_path.stat().st_size > 0
        )
        result["mp4_bytes"] = mp4_path.stat().st_size if mp4_path.exists() else 0
        if result["conversion_succeeded"]:
            result["mp4_path"] = str(mp4_path)
        else:
            result["conversion_error_tail"] = converted.stderr[-300:]
        return result
    finally:
        if download_handle:
            sdk.CLIENT_StopDownload(download_handle)
        if login_handle:
            sdk.CLIENT_Logout(login_handle)
        sdk.CLIENT_Cleanup()
        p2p.P2P_UnInit(0, p2p_handle)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default="HMV")
    parser.add_argument("--channel", type=int, default=2)
    parser.add_argument("--start", default="2026-09-16 15:52:00")
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.store, args.channel, args.start, args.seconds)), flush=True)
        return
    try:
        process = subprocess.run(
            [sys.executable, __file__, "--store", args.store, "--channel",
             str(args.channel), "--start", args.start, "--seconds",
             str(args.seconds), "--worker"],
            capture_output=True, text=True, timeout=180,
        )
        results = []
        for line in process.stdout.splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict) and "tunnel_created" in item:
                    results.append(item)
            except ValueError:
                continue
        report = {"exit_code": process.returncode, "results": results,
                  "native_diagnostics_suppressed": bool(process.stderr)}
        if not results:
            report["error"] = "Download worker returned no structured result"
    except subprocess.TimeoutExpired:
        report = {"error": "Download probe exceeded 180 second deadline"}
    (ROOT / "docs/p2p_download_result.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
