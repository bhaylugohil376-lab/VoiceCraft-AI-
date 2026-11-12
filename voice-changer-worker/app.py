from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

APP_DIR = Path(__file__).resolve().parent
APPLIO_ROOT = Path(os.environ.get("APPLIO_ROOT", "/opt/Applio")).resolve()
# Applio may use a separate virtual environment with its own ML dependencies.
APPLIO_PYTHON = Path(os.environ.get("APPLIO_PYTHON", sys.executable)).expanduser().resolve()
MODELS_DIR = Path(os.environ.get("VOICE_MODELS_DIR", str(APPLIO_ROOT / "logs"))).resolve()
MODELS_FILE = Path(os.environ.get("VOICE_MODELS_JSON", str(APP_DIR / "models.json")))
WORKER_TOKEN = os.environ.get("VOICE_WORKER_TOKEN", "")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
CONVERSION_TIMEOUT = int(os.environ.get("CONVERSION_TIMEOUT_SECONDS", "900"))
ALLOWED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".mp4", ".aac"}
conversion_lock = threading.Lock()

app = FastAPI(title="VoiceCraft AI CPU Voice Conversion Worker", version="0.1.0")
origins = [item.strip() for item in os.environ.get("VOICE_WORKER_CORS_ORIGINS", "").split(",") if item.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


def load_models() -> dict[str, dict[str, Any]]:
    if not MODELS_FILE.is_file():
        return {}
    try:
        raw = json.loads(MODELS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, dict)}


def safe_model_file(value: str) -> Path:
    candidate = (MODELS_DIR / value).resolve()
    if not candidate.is_relative_to(MODELS_DIR):
        raise HTTPException(status_code=500, detail="Invalid model file configuration.")
    return candidate


def require_worker_token(authorization: str | None = Header(default=None)) -> None:
    if not WORKER_TOKEN:
        raise HTTPException(status_code=503, detail="Worker authentication is not configured.")
    expected = "Bearer " + WORKER_TOKEN
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized.")


def applio_cli() -> Path:
    cli = APPLIO_ROOT / "core.py"
    if not cli.is_file():
        raise HTTPException(status_code=503, detail="Applio is not installed at APPLIO_ROOT.")
    if not APPLIO_PYTHON.is_file():
        raise HTTPException(status_code=503, detail="APPLIO_PYTHON does not point to a Python executable.")
    return cli


@app.get("/health")
def health() -> dict[str, Any]:
    cli_ready = (APPLIO_ROOT / "core.py").is_file()
    models = load_models()
    ready_models = []
    for model_id, item in models.items():
        try:
            pth = safe_model_file(str(item.get("pth", "")))
            if pth.is_file() and pth.suffix.lower() == ".pth":
                ready_models.append(model_id)
        except HTTPException:
            continue
    return {
        "ok": cli_ready and bool(ready_models),
        "engine": "applio-rvc",
        "compute": "cpu",
        "applio_installed": cli_ready,
        "configured_models": len(models),
        "available_models": len(ready_models),
    }


@app.get("/voices", dependencies=[Depends(require_worker_token)])
def voices() -> list[dict[str, str]]:
    result = []
    for model_id, item in load_models().items():
        try:
            pth = safe_model_file(str(item.get("pth", "")))
            index_value = str(item.get("index", "")).strip()
            index_path = safe_model_file(index_value) if index_value else None
            if not pth.is_file() or pth.suffix.lower() != ".pth":
                continue
            if index_path and not index_path.is_file():
                continue
            result.append({
                "id": model_id,
                "name": str(item.get("name", model_id)),
                "language": str(item.get("language", "und")),
            })
        except HTTPException:
            continue
    return result


@app.post("/convert", dependencies=[Depends(require_worker_token)])
def convert(
    model_id: str,
    audio: UploadFile = File(...),
) -> FileResponse:
    suffix = Path(audio.filename or "recording.wav").suffix.lower()
    if suffix not in ALLOWED_AUDIO_SUFFIXES:
        raise HTTPException(status_code=415, detail="Unsupported audio file type.")
    if audio.content_type and not audio.content_type.startswith("audio/") and audio.content_type != "video/mp4":
        raise HTTPException(status_code=415, detail="Please upload an audio file.")
    models = load_models()
    item = models.get(model_id)
    if not item:
        raise HTTPException(status_code=404, detail="Voice model not found.")
    pth = safe_model_file(str(item.get("pth", "")))
    index_value = str(item.get("index", "")).strip()
    index_path = safe_model_file(index_value) if index_value else None
    if not pth.is_file() or pth.suffix.lower() != ".pth":
        raise HTTPException(status_code=503, detail="The selected inference model is not installed.")
    if index_path and not index_path.is_file():
        raise HTTPException(status_code=503, detail="The selected model's matching index file is missing.")

    temp_dir = Path(tempfile.mkdtemp(prefix="voicecraft-convert-"))
    input_path = temp_dir / ("input" + suffix)
    output_path = temp_dir / "converted.wav"
    try:
        total = 0
        with input_path.open("wb") as destination:
            while True:
                chunk = audio.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Audio file exceeds the 20 MB limit.")
                destination.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="The uploaded audio file is empty.")

        cli = applio_cli()
        command = [
            str(APPLIO_PYTHON), str(cli), "infer",
            "--input-path", str(input_path),
            "--output-path", str(output_path),
            "--pth-path", str(pth),
            "--index-path", str(index_path) if index_path else "",
            "--pitch", "0",
            "--index-rate", "0.5",
            "--f0-method", "rmvpe",
        ]
        environment = os.environ.copy()
        # Hide CUDA devices so PyTorch/Applio runs on CPU on this worker.
        environment["CUDA_VISIBLE_DEVICES"] = ""
        environment["PYTHONUNBUFFERED"] = "1"
        with conversion_lock:
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(APPLIO_ROOT),
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=CONVERSION_TIMEOUT,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(status_code=504, detail="CPU conversion timed out. Try a shorter recording.") from exc
        if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            detail = (completed.stderr or completed.stdout or "Applio conversion failed.")[-1800:]
            raise HTTPException(status_code=502, detail="Conversion failed: " + detail)
        return FileResponse(
            path=output_path,
            media_type="audio/wav",
            filename="voicecraft-converted.wav",
            background=BackgroundTask(lambda: __import__("shutil").rmtree(temp_dir, ignore_errors=True)),
        )
    except Exception:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    finally:
        audio.file.close()
