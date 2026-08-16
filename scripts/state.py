from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _fernet(client_secret: str) -> Fernet:
    if not client_secret:
        raise ValueError("STRAVA_CLIENT_SECRET is empty")
    key = base64.urlsafe_b64encode(hashlib.sha256(client_secret.encode()).digest())
    return Fernet(key)


def encrypt_refresh_token(token: str, client_secret: str) -> bytes:
    if not token:
        raise ValueError("refresh token is empty")
    return _fernet(client_secret).encrypt(token.encode())


def decrypt_refresh_token(payload: bytes, client_secret: str) -> str:
    try:
        return _fernet(client_secret).decrypt(payload).decode()
    except InvalidToken as exc:
        raise ValueError("Encrypted refresh token cannot be decrypted with this client secret") from exc


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
