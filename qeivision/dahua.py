from __future__ import annotations

import ctypes as C
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from collections.abc import Iterator

import imageio_ffmpeg


SMARTPSS = Path(r"C:\Program Files\SmartPSSLite")
P2P_USERNAME = b"cba1b29e32cb17aa46b8ff9e73c7f40b"
P2P_GUESS = b"996103384cdf19179e19243e959bbf8b"
P2P_SERVERS = (b"www.easy4ipcloud.com", b"www.dahuap2pcloud.com")

BYTE = C.c_ubyte
DWORD = C.c_uint32
LLONG = C.c_int64
LDWORD = C.c_uint64
BOOL = C.c_int


class NET_DEVICEINFO_EX(C.Structure):
    _fields_ = [
        ("sSerialNumber", BYTE * 48),
        ("nAlarmInPortNum", C.c_int),
        ("nAlarmOutPortNum", C.c_int),
        ("nDiskNum", C.c_int),
        ("nDVRType", C.c_int),
        ("nChanNum", C.c_int),
        ("byLimitLoginTime", BYTE),
        ("byLeftLogTimes", BYTE),
        ("bReserved", BYTE * 2),
        ("nLockLeftTime", C.c_int),
        ("Reserved", C.c_char * 4),
        ("nNTlsPort", C.c_int),
        ("Reserved2", C.c_char * 16),
    ]


class NET_IN_LOGIN(C.Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("szIP", C.c_char * 64),
        ("nPort", C.c_int),
        ("szUserName", C.c_char * 64),
        ("szPassword", C.c_char * 64),
        ("emSpecCap", C.c_int),
        ("byReserved", BYTE * 4),
        ("pCapParam", C.c_void_p),
        ("emTLSCap", C.c_int),
    ]


class NET_OUT_LOGIN(C.Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("stuDeviceInfo", NET_DEVICEINFO_EX),
        ("nError", C.c_int),
        ("byReserved", BYTE * 132),
    ]


class NET_TIME(C.Structure):
    _fields_ = [
        ("dwYear", DWORD), ("dwMonth", DWORD), ("dwDay", DWORD),
        ("dwHour", DWORD), ("dwMinute", DWORD), ("dwSecond", DWORD),
    ]


class NET_RECORDFILE_INFO(C.Structure):
    _fields_ = [
        ("ch", DWORD),
        ("filename", C.c_char * 128),
        ("size", DWORD),
        ("starttime", NET_TIME),
        ("endtime", NET_TIME),
        ("driveno", DWORD),
        ("startcluster", DWORD),
        ("nRecordFileType", BYTE),
        ("bImportantRecID", BYTE),
        ("bHint", BYTE),
        ("bRecType", BYTE),
    ]


DISCONNECT = C.WINFUNCTYPE(None, LLONG, C.c_char_p, C.c_int, LDWORD)
DOWNLOAD_POS = C.WINFUNCTYPE(
    None, LLONG, DWORD, DWORD, C.c_int, NET_RECORDFILE_INFO, LDWORD
)
PLAY_POS = C.WINFUNCTYPE(None, LLONG, DWORD, DWORD, LDWORD)
PLAY_DATA = C.WINFUNCTYPE(C.c_int, LLONG, DWORD, C.POINTER(BYTE), DWORD, LDWORD)


def _net_time(value: dt.datetime) -> NET_TIME:
    return NET_TIME(value.year, value.month, value.day, value.hour, value.minute, value.second)


def _python_time(value: NET_TIME) -> dt.datetime:
    return dt.datetime(
        value.dwYear, value.dwMonth, value.dwDay,
        value.dwHour, value.dwMinute, value.dwSecond,
    )


class DahuaError(RuntimeError):
    pass


class DahuaSession:
    def __init__(self, store: str, serial: str, username: str, password: str,
                 channel: int, day: str, cache_dir: Path):
        self.store = store
        self.serial = serial.encode("ascii")
        self.username = username.encode("utf-8")
        self.password = password.encode("utf-8")
        self.channel = int(channel)
        self.day = day
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.playback_lock = threading.RLock()
        self.active_play_handle = 0
        self.active_play_process: subprocess.Popen | None = None
        self.p2p = None
        self.sdk = None
        self.p2p_handle = C.c_void_p()
        self.login_handle = 0
        self.local_port = 0
        self.channel_count = 0
        self._dll_dir = None
        self._disconnect_cb = DISCONNECT(lambda *_: None)

    def connect(self) -> None:
        with self.lock:
            if self.login_handle:
                return
            if not SMARTPSS.exists():
                raise DahuaError("SmartPSS Lite no está instalado en esta computadora.")
            if not self._smartpss_is_running():
                raise DahuaError(
                    "SmartPSS Lite está cerrado. Abrilo, esperá a que el DVR figure "
                    "En línea y volvé a iniciar la auditoría."
                )
            os.chdir(SMARTPSS)
            self._dll_dir = os.add_dll_directory(str(SMARTPSS))
            self._load_p2p()
            self._open_tunnel()
            self._load_sdk()
            if not self.sdk.CLIENT_Init(self._disconnect_cb, 0):
                raise DahuaError("No se pudo inicializar NetSDK.")
            self.sdk.CLIENT_SetConnectTime(10000, 2)
            time.sleep(2)
            for attempt in range(3):
                if self._login_once():
                    return
                if attempt < 2:
                    time.sleep(2)
            code = int(self.sdk.CLIENT_GetLastError())
            if code == 0x80000066:
                raise DahuaError(
                    "El DVR no respondió por P2P. Comprobá en SmartPSS Lite que el "
                    "equipo figure En línea y que pueda reproducir una grabación; "
                    "después volvé a intentarlo."
                )
            raise DahuaError(f"El DVR no aceptó la sesión P2P (código {code:#x}).")

    @staticmethod
    def _smartpss_is_running() -> bool:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq SmartPSSLite.exe", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=flags,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return "smartpsslite.exe" in result.stdout.lower()

    def _load_p2p(self) -> None:
        self.p2p = C.CDLL(str(SMARTPSS / "P2PDll.dll"))
        self.p2p.P2P_Init.restype = C.c_int
        self.p2p.P2P_Init.argtypes = [
            C.c_int, C.c_char_p, C.c_int, C.c_char_p, C.c_char_p,
            C.POINTER(C.c_void_p),
        ]
        self.p2p.P2P_GetDeviceInfo.restype = C.c_int
        self.p2p.P2P_GetDeviceInfo.argtypes = [
            C.c_int, C.c_void_p, C.c_char_p, C.c_int, C.c_char_p,
        ]
        self.p2p.P2P_Connect.restype = C.c_int
        self.p2p.P2P_Connect.argtypes = [
            C.c_int, C.c_void_p, C.c_char_p, C.c_int, C.POINTER(C.c_int),
            C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p,
        ]
        self.p2p.P2P_UnInit.restype = C.c_int
        self.p2p.P2P_UnInit.argtypes = [C.c_int, C.c_void_p]

    def _open_tunnel(self) -> None:
        for server in P2P_SERVERS:
            handle = C.c_void_p()
            initialized = self.p2p.P2P_Init(
                0, server, 8800, P2P_GUESS, P2P_USERNAME, C.byref(handle)
            )
            if initialized != 0 or not handle.value:
                continue
            info_buffer = C.create_string_buffer(2048)
            self.p2p.P2P_GetDeviceInfo(
                0, handle, self.serial, len(info_buffer), info_buffer
            )
            device_version = b"6.6.5"
            raw_info = info_buffer.raw.split(b"\x00", 1)[0]
            if raw_info:
                try:
                    info = json.loads(raw_info.decode("utf-8", errors="replace"))
                    if info.get("devp2pver"):
                        device_version = str(info["devp2pver"]).encode("ascii")
                except ValueError:
                    pass
            local_port = C.c_int(0)
            self.p2p.P2P_Connect(
                0, handle, self.serial, 37777, C.byref(local_port),
                b"", device_version, b"", b"",
            )
            if local_port.value:
                self.p2p_handle = handle
                self.local_port = local_port.value
                return
            self.p2p.P2P_UnInit(0, handle)
        raise DahuaError("No se pudo abrir el túnel P2P hacia el DVR.")

    def _load_sdk(self) -> None:
        C.CDLL(str(SMARTPSS / "dhconfigsdk.dll"))
        self.sdk = C.CDLL(str(SMARTPSS / "dhnetsdk.dll"))
        self.sdk.CLIENT_Init.restype = BOOL
        self.sdk.CLIENT_Init.argtypes = [DISCONNECT, LDWORD]
        self.sdk.CLIENT_SetConnectTime.argtypes = [C.c_int, C.c_int]
        self.sdk.CLIENT_LoginWithHighLevelSecurity.restype = LLONG
        self.sdk.CLIENT_LoginWithHighLevelSecurity.argtypes = [C.c_void_p, C.c_void_p]
        self.sdk.CLIENT_LoginEx2.restype = LLONG
        self.sdk.CLIENT_LoginEx2.argtypes = [
            C.c_char_p, C.c_ushort, C.c_char_p, C.c_char_p, C.c_int,
            C.c_void_p, C.POINTER(NET_DEVICEINFO_EX), C.POINTER(C.c_int),
        ]
        self.sdk.CLIENT_QueryRecordFile.restype = BOOL
        self.sdk.CLIENT_QueryRecordFile.argtypes = [
            LLONG, C.c_int, C.c_int, C.POINTER(NET_TIME), C.POINTER(NET_TIME),
            C.c_char_p, C.c_void_p, C.c_int, C.POINTER(C.c_int), C.c_int, BOOL,
        ]
        self.sdk.CLIENT_DownloadByTimeEx.restype = LLONG
        self.sdk.CLIENT_DownloadByTimeEx.argtypes = [
            LLONG, C.c_int, C.c_int, C.POINTER(NET_TIME), C.POINTER(NET_TIME),
            C.c_char_p, DOWNLOAD_POS, LDWORD, C.c_void_p, LDWORD, C.c_void_p,
        ]
        self.sdk.CLIENT_StopDownload.argtypes = [LLONG]
        self.sdk.CLIENT_PlayBackByTimeEx.restype = LLONG
        self.sdk.CLIENT_PlayBackByTimeEx.argtypes = [
            LLONG, C.c_int, C.POINTER(NET_TIME), C.POINTER(NET_TIME),
            C.c_void_p, PLAY_POS, LDWORD, PLAY_DATA, LDWORD,
        ]
        self.sdk.CLIENT_StopPlayBack.restype = BOOL
        self.sdk.CLIENT_StopPlayBack.argtypes = [LLONG]
        self.sdk.CLIENT_GetLastError.restype = DWORD
        self.sdk.CLIENT_Logout.argtypes = [LLONG]
        self.sdk.CLIENT_Cleanup.argtypes = []

    def _login_once(self) -> bool:
        login_in = NET_IN_LOGIN()
        login_in.dwSize = C.sizeof(NET_IN_LOGIN)
        login_in.szIP = b"127.0.0.1"
        login_in.nPort = self.local_port
        login_in.szUserName = self.username
        login_in.szPassword = self.password
        login_in.emSpecCap = 0
        login_out = NET_OUT_LOGIN()
        login_out.dwSize = C.sizeof(NET_OUT_LOGIN)
        handle = self.sdk.CLIENT_LoginWithHighLevelSecurity(
            C.byref(login_in), C.byref(login_out)
        )
        device_info = login_out.stuDeviceInfo
        if not handle:
            legacy_info = NET_DEVICEINFO_EX()
            legacy_error = C.c_int(0)
            handle = self.sdk.CLIENT_LoginEx2(
                b"127.0.0.1", self.local_port, self.username, self.password,
                0, None, C.byref(legacy_info), C.byref(legacy_error),
            )
            device_info = legacy_info
        if handle:
            self.login_handle = handle
            self.channel_count = int(device_info.nChanNum)
            return True
        return False

    def query_recordings(self) -> list[dict]:
        with self.lock:
            self.connect()
            start = dt.datetime.fromisoformat(self.day + "T00:00:00")
            end = start + dt.timedelta(days=1) - dt.timedelta(seconds=1)
            start_net, end_net = _net_time(start), _net_time(end)
            capacity = 2000
            records = (NET_RECORDFILE_INFO * capacity)()
            count = C.c_int(0)
            ok = self.sdk.CLIENT_QueryRecordFile(
                self.login_handle, self.channel - 1, 0,
                C.byref(start_net), C.byref(end_net), None,
                C.cast(records, C.c_void_p), C.sizeof(records), C.byref(count),
                15000, 1,
            )
            if not ok:
                code = int(self.sdk.CLIENT_GetLastError())
                raise DahuaError(f"No se pudieron consultar las grabaciones ({code:#x}).")
            result = []
            for index in range(min(count.value, capacity)):
                record = records[index]
                try:
                    record_start = _python_time(record.starttime)
                    record_end = _python_time(record.endtime)
                except ValueError:
                    continue
                result.append(
                    {
                        "start": record_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "end": record_end.strftime("%Y-%m-%d %H:%M:%S"),
                        "start_time": record_start.strftime("%H:%M:%S"),
                        "end_time": record_end.strftime("%H:%M:%S"),
                        "size_bytes": int(record.size),
                    }
                )
            return result

    def download_clip(self, start: dt.datetime, seconds: int = 15) -> Path:
        with self.lock:
            self.connect()
            if start.strftime("%Y-%m-%d") != self.day:
                raise DahuaError("El horario solicitado no pertenece a la sesión activa.")
            seconds = max(5, min(int(seconds), 60))
            cache_name = (
                f"{self.store}_cam{self.channel}_{start:%Y-%m-%d_%H%M%S}_{seconds}s"
            )
            mp4_path = self.cache_dir / f"{cache_name}.mp4"
            if mp4_path.exists() and mp4_path.stat().st_size > 1000:
                return mp4_path
            dav_path = self.cache_dir / f"{cache_name}.dav"
            end = start + dt.timedelta(seconds=seconds)
            done = threading.Event()

            @DOWNLOAD_POS
            def on_progress(_handle, total, downloaded, _index, _record, _user):
                if downloaded == 0xFFFFFFFF or (total > 0 and downloaded >= total):
                    done.set()

            start_net, end_net = _net_time(start), _net_time(end)
            download_handle = self.sdk.CLIENT_DownloadByTimeEx(
                self.login_handle, self.channel - 1, 0,
                C.byref(start_net), C.byref(end_net), os.fsencode(dav_path),
                on_progress, 0, None, 0, None,
            )
            if not download_handle:
                code = int(self.sdk.CLIENT_GetLastError())
                raise DahuaError(f"No hay video disponible en ese horario ({code:#x}).")
            try:
                done.wait(timeout=75)
            finally:
                self.sdk.CLIENT_StopDownload(download_handle)
            if not dav_path.exists() or dav_path.stat().st_size == 0:
                raise DahuaError("El DVR no entregó imágenes para ese horario.")
            self._remux(dav_path, mp4_path)
            try:
                dav_path.unlink()
            except OSError:
                pass
            return mp4_path

    def stream_mp4(self, start: dt.datetime, minutes: int = 30) -> Iterator[bytes]:
        """Entrega playback histórico como MP4 fragmentado mientras llega del DVR."""
        with self.lock:
            self.connect()
            if start.strftime("%Y-%m-%d") != self.day:
                raise DahuaError("El horario solicitado no pertenece a la sesión activa.")
            end_of_day = dt.datetime.combine(start.date(), dt.time(23, 59, 59))
            end = min(start + dt.timedelta(minutes=max(5, min(minutes, 240))), end_of_day)
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            process = subprocess.Popen(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                 "-map", "0:v:0", "-c:v", "copy", "-an", "-f", "mp4",
                 "-movflags", "frag_keyframe+empty_moov+default_base_moof", "pipe:1"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            finished = threading.Event()
            play_handle = 0

            with self.playback_lock:
                self._stop_stream_unlocked()
                self.active_play_process = process

            @PLAY_POS
            def on_position(_handle, _total, played, _user):
                if played == 0xFFFFFFFF:
                    finished.set()

            @PLAY_DATA
            def on_data(_handle, _data_type, buffer, size, _user):
                if not size or not process.stdin:
                    return 1
                try:
                    process.stdin.write(C.string_at(buffer, size))
                    process.stdin.flush()
                    return 1
                except (BrokenPipeError, OSError, ValueError):
                    finished.set()
                    return 0

            try:
                start_net, end_net = _net_time(start), _net_time(end)
                play_handle = self.sdk.CLIENT_PlayBackByTimeEx(
                    self.login_handle, self.channel - 1,
                    C.byref(start_net), C.byref(end_net), None,
                    on_position, 0, on_data, 0,
                )
                if not play_handle:
                    code = int(self.sdk.CLIENT_GetLastError())
                    raise DahuaError(f"No se pudo iniciar la reproducción continua ({code:#x}).")
                with self.playback_lock:
                    self.active_play_handle = play_handle
                assert process.stdout is not None
                while True:
                    chunk = process.stdout.read(64 * 1024)
                    if chunk:
                        yield chunk
                        continue
                    if finished.is_set() or process.poll() is not None:
                        break
            finally:
                with self.playback_lock:
                    if self.active_play_handle == play_handle and play_handle:
                        self.sdk.CLIENT_StopPlayBack(play_handle)
                        self.active_play_handle = 0
                    if self.active_play_process is process:
                        self._close_play_process(process)
                        self.active_play_process = None

    def stop_stream(self) -> None:
        with self.playback_lock:
            self._stop_stream_unlocked()

    def _stop_stream_unlocked(self) -> None:
        if self.active_play_handle and self.sdk:
            self.sdk.CLIENT_StopPlayBack(self.active_play_handle)
            self.active_play_handle = 0
        if self.active_play_process:
            self._close_play_process(self.active_play_process)
            self.active_play_process = None

    @staticmethod
    def _close_play_process(process: subprocess.Popen) -> None:
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()

    @staticmethod
    def _remux(dav_path: Path, mp4_path: Path) -> None:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        copy = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(dav_path), "-map", "0:v:0", "-c:v", "copy",
             "-movflags", "+faststart", "-an", str(mp4_path)],
            capture_output=True, text=True, timeout=90,
        )
        if copy.returncode == 0 and mp4_path.exists() and mp4_path.stat().st_size > 0:
            return
        encode = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(dav_path), "-map", "0:v:0", "-c:v", "libx264",
             "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-an", str(mp4_path)],
            capture_output=True, text=True, timeout=120,
        )
        if encode.returncode != 0 or not mp4_path.exists() or mp4_path.stat().st_size == 0:
            raise DahuaError("No se pudo preparar el video para el navegador.")

    def close(self) -> None:
        self.stop_stream()
        with self.lock:
            if self.sdk:
                if self.login_handle:
                    self.sdk.CLIENT_Logout(self.login_handle)
                    self.login_handle = 0
                self.sdk.CLIENT_Cleanup()
                self.sdk = None
            if self.p2p and self.p2p_handle.value:
                self.p2p.P2P_UnInit(0, self.p2p_handle)
                self.p2p_handle = C.c_void_p()
            self.local_port = 0
            if self._dll_dir:
                self._dll_dir.close()
                self._dll_dir = None
