"""Query Dahua recordings through a P2P tunnel using SmartPSS Lite DLLs.

Reads serial and DVR credentials from the existing local configuration. Output
contains no credentials, serial number, or recorder-side filenames.
"""
from __future__ import annotations

import argparse
import ctypes as C
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SMARTPSS = Path(r"C:\Program Files\SmartPSSLite")
CONFIG = Path.home() / "OneDrive/Desktop/P_Qeivision/audit_config.json"
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


def net_time(value: dt.datetime) -> NET_TIME:
    return NET_TIME(value.year, value.month, value.day, value.hour, value.minute, value.second)


def format_time(value: NET_TIME) -> str:
    return (f"{value.dwYear:04d}-{value.dwMonth:02d}-{value.dwDay:02d} "
            f"{value.dwHour:02d}:{value.dwMinute:02d}:{value.dwSecond:02d}")


def configure_p2p():
    p2p = C.CDLL(str(SMARTPSS / "P2PDll.dll"))
    p2p.P2P_Init.restype = C.c_int
    p2p.P2P_Init.argtypes = [C.c_int, C.c_char_p, C.c_int, C.c_char_p,
                             C.c_char_p, C.POINTER(C.c_void_p)]
    p2p.P2P_GetDeviceInfo.restype = C.c_int
    p2p.P2P_GetDeviceInfo.argtypes = [C.c_int, C.c_void_p, C.c_char_p,
                                      C.c_int, C.c_char_p]
    p2p.P2P_Connect.restype = C.c_int
    p2p.P2P_Connect.argtypes = [C.c_int, C.c_void_p, C.c_char_p, C.c_int,
                                C.POINTER(C.c_int), C.c_char_p, C.c_char_p,
                                C.c_char_p, C.c_char_p]
    p2p.P2P_UnInit.restype = C.c_int
    p2p.P2P_UnInit.argtypes = [C.c_int, C.c_void_p]
    return p2p


def configure_sdk():
    C.CDLL(str(SMARTPSS / "dhconfigsdk.dll"))
    sdk = C.CDLL(str(SMARTPSS / "dhnetsdk.dll"))
    disconnect_type = C.WINFUNCTYPE(None, LLONG, C.c_char_p, C.c_int, LDWORD)
    sdk.CLIENT_Init.restype = BOOL
    sdk.CLIENT_Init.argtypes = [disconnect_type, LDWORD]
    sdk.CLIENT_SetConnectTime.argtypes = [C.c_int, C.c_int]
    sdk.CLIENT_LoginWithHighLevelSecurity.restype = LLONG
    sdk.CLIENT_LoginWithHighLevelSecurity.argtypes = [C.c_void_p, C.c_void_p]
    sdk.CLIENT_LoginEx2.restype = LLONG
    sdk.CLIENT_LoginEx2.argtypes = [
        C.c_char_p, C.c_ushort, C.c_char_p, C.c_char_p, C.c_int,
        C.c_void_p, C.POINTER(NET_DEVICEINFO_EX), C.POINTER(C.c_int),
    ]
    sdk.CLIENT_QueryRecordFile.restype = BOOL
    sdk.CLIENT_QueryRecordFile.argtypes = [
        LLONG, C.c_int, C.c_int, C.POINTER(NET_TIME), C.POINTER(NET_TIME),
        C.c_char_p, C.c_void_p, C.c_int, C.POINTER(C.c_int), C.c_int, BOOL,
    ]
    sdk.CLIENT_GetLastError.restype = DWORD
    sdk.CLIENT_Logout.argtypes = [LLONG]
    sdk.CLIENT_Cleanup.argtypes = []
    return sdk, disconnect_type


def worker(store_name: str, channel: int, day: str) -> dict:
    config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    store = config["tiendas"][store_name]
    credentials = config["dvr_credentials"]
    serial = str(store["sn"]).encode("ascii")
    username = str(credentials["user"]).encode("utf-8")
    password = str(credentials["pass"]).encode("utf-8")

    os.chdir(SMARTPSS)
    os.add_dll_directory(str(SMARTPSS))
    p2p = configure_p2p()
    p2p_handle = C.c_void_p()
    local_port = C.c_int(0)
    tunnel_server = None
    for server in P2P_SERVERS:
        if p2p.P2P_Init(0, server, 8800, P2P_GUESS, P2P_USERNAME,
                        C.byref(p2p_handle)) != 0 or not p2p_handle.value:
            continue
        info_buffer = C.create_string_buffer(2048)
        p2p.P2P_GetDeviceInfo(0, p2p_handle, serial, len(info_buffer), info_buffer)
        device_version = b"6.6.5"
        raw_info = info_buffer.raw.split(b"\x00", 1)[0]
        if raw_info:
            try:
                parsed = json.loads(raw_info.decode("utf-8", errors="replace"))
                if parsed.get("devp2pver"):
                    device_version = str(parsed["devp2pver"]).encode("ascii")
            except ValueError:
                pass
        p2p.P2P_Connect(0, p2p_handle, serial, 37777, C.byref(local_port),
                        b"", device_version, b"", b"")
        if local_port.value:
            tunnel_server = server.decode()
            break
        p2p.P2P_UnInit(0, p2p_handle)
        p2p_handle = C.c_void_p()

    result = {"store": store_name, "channel": channel, "day": day,
              "tunnel_created": bool(local_port.value), "server": tunnel_server}
    if not local_port.value:
        return result

    sdk, disconnect_type = configure_sdk()
    disconnect_cb = disconnect_type(lambda *_: None)
    login_handle = 0
    try:
        result["sdk_initialized"] = bool(sdk.CLIENT_Init(disconnect_cb, 0))
        sdk.CLIENT_SetConnectTime(10000, 2)
        login_in = NET_IN_LOGIN()
        login_in.dwSize = C.sizeof(NET_IN_LOGIN)
        login_in.szIP = b"127.0.0.1"
        login_in.nPort = local_port.value
        login_in.szUserName = username
        login_in.szPassword = password
        login_in.emSpecCap = 0
        login_out = NET_OUT_LOGIN()
        login_out.dwSize = C.sizeof(NET_OUT_LOGIN)
        login_handle = sdk.CLIENT_LoginWithHighLevelSecurity(
            C.byref(login_in), C.byref(login_out)
        )
        result["modern_login_succeeded"] = bool(login_handle)
        result["modern_login_error"] = login_out.nError
        device_info = login_out.stuDeviceInfo
        if not login_handle:
            # XVR1A04 is an older platform and may not implement the newer
            # high-level-security RPC. Make one legacy TCP login attempt.
            legacy_error = C.c_int(0)
            legacy_info = NET_DEVICEINFO_EX()
            login_handle = sdk.CLIENT_LoginEx2(
                b"127.0.0.1", local_port.value, username, password, 0, None,
                C.byref(legacy_info), C.byref(legacy_error),
            )
            result["legacy_login_attempted"] = True
            result["legacy_login_error"] = legacy_error.value
            if login_handle:
                device_info = legacy_info
        result["login_succeeded"] = bool(login_handle)
        if not login_handle:
            result["sdk_error"] = int(sdk.CLIENT_GetLastError())
            return result
        result["reported_channels"] = device_info.nChanNum

        start = dt.datetime.fromisoformat(day + "T00:00:00")
        end = start + dt.timedelta(days=1) - dt.timedelta(seconds=1)
        start_net, end_net = net_time(start), net_time(end)
        capacity = 512
        records = (NET_RECORDFILE_INFO * capacity)()
        count = C.c_int(0)
        ok = sdk.CLIENT_QueryRecordFile(
            login_handle, channel - 1, 0, C.byref(start_net), C.byref(end_net),
            None, C.cast(records, C.c_void_p), C.sizeof(records), C.byref(count),
            15000, 1,
        )
        result["query_succeeded"] = bool(ok)
        result["record_count"] = count.value if ok else 0
        if not ok:
            result["sdk_error"] = int(sdk.CLIENT_GetLastError())
        else:
            result["sample_ranges"] = [
                {"start": format_time(records[i].starttime),
                 "end": format_time(records[i].endtime),
                 "size_bytes": int(records[i].size)}
                for i in range(min(count.value, 5))
            ]
        return result
    finally:
        if login_handle:
            sdk.CLIENT_Logout(login_handle)
        sdk.CLIENT_Cleanup()
        p2p.P2P_UnInit(0, p2p_handle)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default="HMV")
    parser.add_argument("--channel", type=int, default=2)
    parser.add_argument("--day", default="2026-09-16")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.store, args.channel, args.day)), flush=True)
        return
    try:
        completed = subprocess.run(
            [sys.executable, __file__, "--store", args.store, "--channel",
             str(args.channel), "--day", args.day, "--worker"],
            capture_output=True, text=True, timeout=90,
        )
        records = []
        for line in completed.stdout.splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict) and "tunnel_created" in item:
                    records.append(item)
            except ValueError:
                continue
        report = {"exit_code": completed.returncode, "results": records,
                  "native_diagnostics_suppressed": bool(completed.stderr)}
        if not records:
            report["error"] = "NetSDK worker returned no structured result"
    except subprocess.TimeoutExpired:
        report = {"error": "NetSDK query exceeded 90 second deadline"}
    output = ROOT / "docs/p2p_recordings_query_result.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
