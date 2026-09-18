"""Prueba acotada de reproducción histórica progresiva por NetSDK.

Captura el callback de CLIENT_PlayBackByTimeEx durante un período de pared,
sin imprimir números de serie ni credenciales, y remuxa el flujo recibido a MP4.
"""
from __future__ import annotations

import argparse
import ctypes as C
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import imageio_ffmpeg

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from qeivision.config import PROJECT_ROOT, load_config
from qeivision.dahua import BYTE, DWORD, LLONG, LDWORD, BOOL, NET_TIME, DahuaSession, _net_time


PLAY_POS = C.WINFUNCTYPE(None, LLONG, DWORD, DWORD, LDWORD)
PLAY_DATA = C.WINFUNCTYPE(C.c_int, LLONG, DWORD, C.POINTER(BYTE), DWORD, LDWORD)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default="HME")
    parser.add_argument("--channel", type=int, default=2)
    parser.add_argument("--start", default="2026-09-16 12:51:30")
    parser.add_argument("--capture-seconds", type=int, default=45)
    args = parser.parse_args()

    config = load_config()
    store = config["tiendas"][args.store]
    credentials = config["dvr_credentials"]
    start = dt.datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S")
    requested_end = start + dt.timedelta(minutes=5)
    output_dir = PROJECT_ROOT / "recordings"
    output_dir.mkdir(exist_ok=True)
    stem = f"{args.store}_cam{args.channel}_{start:%Y-%m-%d_%H%M%S}_continuous"
    dav_path = output_dir / f"{stem}.dav"
    mp4_path = output_dir / f"{stem}.mp4"
    for path in (dav_path, mp4_path):
        path.unlink(missing_ok=True)

    session = DahuaSession(
        store=args.store,
        serial=str(store["sn"]),
        username=str(credentials["user"]),
        password=str(credentials["pass"]),
        channel=args.channel,
        day=start.strftime("%Y-%m-%d"),
        cache_dir=PROJECT_ROOT / "clips_cache",
    )
    result: dict = {
        "store": args.store,
        "channel": args.channel,
        "start": args.start,
        "capture_wall_seconds": args.capture_seconds,
    }
    play_handle = 0
    file_lock = threading.Lock()
    first_data_at: float | None = None
    callback_count = 0
    received_bytes = 0
    data_types: set[int] = set()
    started_at = time.perf_counter()

    try:
        session.connect()
        sdk = session.sdk
        sdk.CLIENT_PlayBackByTimeEx.restype = LLONG
        sdk.CLIENT_PlayBackByTimeEx.argtypes = [
            LLONG, C.c_int, C.POINTER(NET_TIME), C.POINTER(NET_TIME),
            C.c_void_p, PLAY_POS, LDWORD, PLAY_DATA, LDWORD,
        ]
        sdk.CLIENT_StopPlayBack.restype = BOOL
        sdk.CLIENT_StopPlayBack.argtypes = [LLONG]

        @PLAY_POS
        def on_position(_handle, _total, _played, _user):
            return None

        with dav_path.open("wb") as stream:
            @PLAY_DATA
            def on_data(_handle, data_type, buffer, size, _user):
                nonlocal first_data_at, callback_count, received_bytes
                if size:
                    now = time.perf_counter()
                    if first_data_at is None:
                        first_data_at = now
                    chunk = C.string_at(buffer, size)
                    with file_lock:
                        stream.write(chunk)
                    callback_count += 1
                    received_bytes += int(size)
                    data_types.add(int(data_type))
                return 1

            start_net, end_net = _net_time(start), _net_time(requested_end)
            play_handle = sdk.CLIENT_PlayBackByTimeEx(
                session.login_handle,
                args.channel - 1,
                C.byref(start_net),
                C.byref(end_net),
                None,
                on_position,
                0,
                on_data,
                0,
            )
            if not play_handle:
                result["sdk_error"] = int(sdk.CLIENT_GetLastError())
                raise RuntimeError("CLIENT_PlayBackByTimeEx no inició la reproducción.")
            result["playback_started_seconds"] = round(time.perf_counter() - started_at, 3)
            deadline = time.monotonic() + max(10, min(args.capture_seconds, 180))
            while time.monotonic() < deadline:
                time.sleep(0.25)
            sdk.CLIENT_StopPlayBack(play_handle)
            play_handle = 0
            stream.flush()

        result.update({
            "first_data_seconds": None if first_data_at is None else round(first_data_at - started_at, 3),
            "callback_count": callback_count,
            "received_bytes": received_bytes,
            "data_types": sorted(data_types),
        })
        if received_bytes <= 0:
            raise RuntimeError("El SDK inició, pero no entregó datos de reproducción.")

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        conversion = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(dav_path),
             "-map", "0:v:0", "-c:v", "copy", "-movflags", "+faststart", "-an", str(mp4_path)],
            capture_output=True, text=True, timeout=120,
        )
        result["conversion_succeeded"] = conversion.returncode == 0 and mp4_path.exists()
        result["mp4_bytes"] = mp4_path.stat().st_size if mp4_path.exists() else 0
        result["mp4_path"] = str(mp4_path) if mp4_path.exists() else None
        if conversion.returncode != 0:
            result["conversion_error"] = conversion.stderr[-600:]
    except Exception as error:
        result["error"] = str(error)
    finally:
        if play_handle and session.sdk:
            session.sdk.CLIENT_StopPlayBack(play_handle)
        session.close()

    report = PROJECT_ROOT / "docs" / "continuous_playback_probe_result.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("conversion_succeeded") else 1


if __name__ == "__main__":
    raise SystemExit(main())
