"""Prueba local de YOLO11 sobre MEUG Channel 8 vía RTSP de SmartPSS.

Uso: ejecutar con SmartPSS abierto y el túnel RTSP activo. El puerto se pasa
por argumento para no guardar credenciales ni puertos del equipo en código.
"""
from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path

import cv2
from ultralytics import YOLO


class FreshRTSPStream:
    def __init__(self, url: str):
        self.capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def _read_loop(self):
        while self.running:
            ok, frame = self.capture.read()
            if ok and frame is not None:
                with self.lock:
                    self.frame = frame
            else:
                time.sleep(0.02)

    def read(self):
        with self.lock:
            return (self.frame is not None, None if self.frame is None else self.frame.copy())

    def close(self):
        self.running = False
        self.capture.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True, help='Puerto RTSP local de SmartPSS')
    parser.add_argument('--user', default='admin')
    parser.add_argument('--password', required=True)
    parser.add_argument('--channel', type=int, default=8)
    args = parser.parse_args()

    model_path = Path(__file__).resolve().parents[1] / 'models' / 'yolo11n.pt'
    model = YOLO(str(model_path))
    url = f'rtsp://{args.user}:{args.password}@127.0.0.1:{args.port}/cam/realmonitor?channel={args.channel}&subtype=0'
    stream = FreshRTSPStream(url)
    persons, pets = {}, {}
    last_time = time.time()
    print(f'Analizando MEUG Channel {args.channel} con YOLO11n. Presioná Q para salir.')

    try:
        while True:
            ok, frame = stream.read()
            if not ok:
                time.sleep(0.05)
                continue
            now = time.time()
            result = model.track(frame, persist=True, classes=[0, 15, 16], conf=0.25, verbose=False)[0]
            if result.boxes is not None:
                ids = result.boxes.id
                for index, cls in enumerate(result.boxes.cls):
                    key = int(ids[index]) if ids is not None else f'temp-{index}'
                    (persons if int(cls) == 0 else pets)[key] = now
            persons = {key: stamp for key, stamp in persons.items() if now - stamp < 1.2}
            pets = {key: stamp for key, stamp in pets.items() if now - stamp < 1.2}
            frame = result.plot()
            cv2.putText(frame, f'Personas: {len(persons)} | Mascotas: {len(pets)}', (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
            cv2.imshow('QeiVision - MEUG Channel 8 - YOLO11', frame)
            if cv2.waitKey(1) & 0xFF in (ord('q'), ord('Q')):
                break
            last_time = now
    finally:
        stream.close()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
