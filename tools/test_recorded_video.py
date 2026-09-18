"""Bounded playback test using existing local config; no secrets in output.

Example: python tools/test_recorded_video.py --store HMV --channel 2
Only requests a short interval on the selected day to validate transport first.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path.home() / 'OneDrive/Desktop/P_Qeivision/audit_config.json'


def worker(args):
    os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'
    import cv2
    config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    store = config['tiendas'][args.store]
    creds = config['dvr_credentials']
    start = dt.datetime.fromisoformat(f'{args.day}T{args.time}')
    end = start + dt.timedelta(seconds=30)
    port = args.port or int(store['rtsp_port'])
    url = (f"rtsp://{quote(creds['user'], safe='')}:{quote(creds['pass'], safe='')}"
           f"@127.0.0.1:{port}/cam/playback?channel={args.channel}&subtype=0"
           f"&starttime={start:%Y_%m_%d_%H_%M_%S}&endtime={end:%Y_%m_%d_%H_%M_%S}")
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 12000,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 12000])
    result = {'store': args.store, 'channel': args.channel, 'day': args.day,
              'start_requested': str(start), 'port': port, 'opened': cap.isOpened(),
              'decoded_frames': 0, 'visual_timestamp_verified': False}
    writer = None
    try:
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            if not 1 <= fps <= 60:
                fps = 20
            for index in range(60):
                ok, frame = cap.read()
                if not ok:
                    break
                if writer is None:
                    outdir = ROOT / 'recordings'
                    outdir.mkdir(exist_ok=True)
                    output = outdir / f'probe_{args.store}_cam{args.channel}_{args.day}.mp4'
                    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*'mp4v'), fps,
                                             (frame.shape[1], frame.shape[0]))
                    if not writer.isOpened():
                        raise RuntimeError('VideoWriter failed')
                    cv2.imwrite(str(output.with_suffix('.jpg')), frame)
                    result['output'] = str(output)
                writer.write(frame)
                result['decoded_frames'] += 1
    finally:
        cap.release()
        if writer is not None:
            writer.release()
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', default='HMV')
    parser.add_argument('--channel', type=int, default=2)
    parser.add_argument('--day', default='2026-09-16')
    parser.add_argument('--time', default='15:52:00')
    parser.add_argument('--port', type=int)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    try:
        proc = subprocess.run([sys.executable, __file__, *sys.argv[1:], '--worker'],
                              capture_output=True, text=True, timeout=45)
        # Native multimedia errors may contain credential-bearing URLs: never echo them.
        records = []
        for line in proc.stdout.splitlines():
            try:
                record = json.loads(line)
                if isinstance(record, dict) and 'decoded_frames' in record:
                    records.append(record)
            except ValueError:
                pass
        report = {'exit_code': proc.returncode, 'results': records,
                  'native_diagnostics_suppressed': bool(proc.stderr)}
        if not records:
            report['error'] = 'No playback result returned; raw diagnostics withheld to protect credentials.'
    except subprocess.TimeoutExpired:
        report = {'error': 'Playback exceeded 45 second deadline'}
    (ROOT / 'docs/playback_probe_result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
