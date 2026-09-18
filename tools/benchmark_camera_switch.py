"""Measure historical camera switching while reusing one P2P/NetSDK session."""
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

from download_p2p_clip import DISCONNECT, DOWNLOAD_POS, load_sdk, open_tunnel
from query_p2p_recordings import (
    CONFIG, ROOT, SMARTPSS, NET_DEVICEINFO_EX, NET_IN_LOGIN, NET_OUT_LOGIN,
    configure_p2p, net_time,
)


def login(sdk, local_port: int, username: bytes, password: bytes):
    modern_in = NET_IN_LOGIN()
    modern_in.dwSize = C.sizeof(NET_IN_LOGIN)
    modern_in.szIP = b"127.0.0.1"
    modern_in.nPort = local_port
    modern_in.szUserName = username
    modern_in.szPassword = password
    modern_out = NET_OUT_LOGIN()
    modern_out.dwSize = C.sizeof(NET_OUT_LOGIN)
    handle = sdk.CLIENT_LoginWithHighLevelSecurity(C.byref(modern_in), C.byref(modern_out))
    if handle:
        return handle
    info = NET_DEVICEINFO_EX()
    error = C.c_int(0)
    return sdk.CLIENT_LoginEx2(
        b"127.0.0.1", local_port, username, password, 0, None,
        C.byref(info), C.byref(error),
    )


def download_one(sdk, login_handle, channel: int, start: dt.datetime,
                 seconds: int, output_dir: Path) -> dict:
    end = start + dt.timedelta(seconds=seconds)
    stem = f"switch_cam{channel}_{start:%Y-%m-%d_%H%M%S}"
    dav_path = output_dir / f"{stem}.dav"
    mp4_path = output_dir / f"{stem}.mp4"
    done = threading.Event()

    @DOWNLOAD_POS
    def on_progress(_handle, total, downloaded, _index, _record, _user):
        if downloaded == 0xFFFFFFFF or (total > 0 and downloaded >= total):
            done.set()

    start_net, end_net = net_time(start), net_time(end)
    began = time.perf_counter()
    handle = sdk.CLIENT_DownloadByTimeEx(
        login_handle, channel - 1, 0, C.byref(start_net), C.byref(end_net),
        os.fsencode(dav_path), on_progress, 0, None, 0, None,
    )
    if not handle:
        return {"channel": channel, "started": False,
                "sdk_error": int(sdk.CLIENT_GetLastError())}
    finished = done.wait(timeout=60)
    sdk.CLIENT_StopDownload(handle)
    download_seconds = time.perf_counter() - began
    dav_bytes = dav_path.stat().st_size if dav_path.exists() else 0
    row = {"channel": channel, "started": True, "completed": finished,
           "download_seconds": round(download_seconds, 3), "dav_bytes": dav_bytes}
    if not dav_bytes:
        return row

    convert_began = time.perf_counter()
    conversion = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
         "-y", "-i", str(dav_path), "-map", "0:v:0", "-c:v", "copy",
         "-movflags", "+faststart", "-an", str(mp4_path)],
        capture_output=True, text=True, timeout=30,
    )
    row["remux_seconds"] = round(time.perf_counter() - convert_began, 3)
    row["mp4_ready"] = conversion.returncode == 0 and mp4_path.exists()
    row["mp4_bytes"] = mp4_path.stat().st_size if mp4_path.exists() else 0
    return row


def worker(store_name: str, start_text: str, seconds: int) -> dict:
    config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    store = config["tiendas"][store_name]
    creds = config["dvr_credentials"]
    serial = str(store["sn"]).encode("ascii")
    username = str(creds["user"]).encode("utf-8")
    password = str(creds["pass"]).encode("utf-8")
    start = dt.datetime.fromisoformat(start_text)
    output_dir = ROOT / "recordings" / "switch_benchmark"
    output_dir.mkdir(parents=True, exist_ok=True)

    os.chdir(SMARTPSS)
    os.add_dll_directory(str(SMARTPSS))
    setup_began = time.perf_counter()
    p2p = configure_p2p()
    p2p_handle, local_port = open_tunnel(p2p, serial)
    result = {"store": store_name, "start": str(start), "clip_seconds": seconds,
              "tunnel_created": bool(local_port), "cameras": []}
    if not local_port:
        return result
    sdk = load_sdk()
    disconnect_cb = DISCONNECT(lambda *_: None)
    login_handle = 0
    try:
        sdk.CLIENT_Init(disconnect_cb, 0)
        sdk.CLIENT_SetConnectTime(10000, 2)
        time.sleep(2)
        login_attempts = 0
        for login_attempts in range(1, 4):
            login_handle = login(sdk, local_port, username, password)
            if login_handle:
                break
            time.sleep(2)
        result["login_attempts"] = login_attempts
        result["login_succeeded"] = bool(login_handle)
        result["session_setup_seconds"] = round(time.perf_counter() - setup_began, 3)
        if not login_handle:
            result["sdk_error"] = int(sdk.CLIENT_GetLastError())
            return result
        for channel in (1, 2, 3, 4):
            result["cameras"].append(
                download_one(sdk, login_handle, channel, start, seconds, output_dir)
            )
        return result
    finally:
        if login_handle:
            sdk.CLIENT_Logout(login_handle)
        sdk.CLIENT_Cleanup()
        p2p.P2P_UnInit(0, p2p_handle)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default="HMV")
    parser.add_argument("--start", default="2026-09-16 15:52:00")
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.store, args.start, args.seconds)), flush=True)
        return
    try:
        process = subprocess.run(
            [sys.executable, __file__, "--store", args.store, "--start", args.start,
             "--seconds", str(args.seconds), "--worker"],
            capture_output=True, text=True, timeout=240,
        )
        results = []
        for line in process.stdout.splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict) and "cameras" in item:
                    results.append(item)
            except ValueError:
                pass
        report = {"exit_code": process.returncode, "results": results,
                  "native_diagnostics_suppressed": bool(process.stderr)}
        if not results:
            report["error"] = "Benchmark worker returned no structured result"
    except subprocess.TimeoutExpired:
        report = {"error": "Camera switch benchmark exceeded 240 seconds"}
    (ROOT / "docs/camera_switch_benchmark.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
