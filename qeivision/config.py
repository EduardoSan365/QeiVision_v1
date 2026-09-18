from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.local.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            "Falta config.local.json. Copiá la configuración local autorizada "
            "antes de iniciar QeiVision."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def public_stores(config: dict) -> dict:
    result = {}
    for key, value in config.get("tiendas", {}).items():
        cameras = value.get("camaras") or []
        default_camera = value.get("audit_camera")
        if default_camera is None:
            default_camera = 2 if key == "HMV" else (cameras[0]["id"] if cameras else 1)
        result[key] = {
            "nombre": value.get("nombre", key),
            "camaras": cameras,
            "audit_camera": int(default_camera),
        }
    return result
