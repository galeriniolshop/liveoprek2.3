from __future__ import annotations
import base64
import hashlib
import os
import re
import secrets
from cryptography.fernet import Fernet
from .config import DATA, secret


def cipher() -> Fernet:
    value = secret("APP_SECRET")
    if not value:
        DATA.mkdir(parents=True, exist_ok=True)
        p = DATA / "master.key"
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
        except FileExistsError:
            pass
        value = p.read_text().strip()
    if len(value) < 32:
        raise ValueError("APP_SECRET harus minimal 32 karakter acak.")
    key = base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest())
    return Fernet(key)


def encrypt(value: str) -> str:
    return cipher().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return cipher().decrypt(value.encode()).decode()


def token() -> str:
    return secrets.token_urlsafe(32)


def redact(text: str) -> str:
    text = re.sub(r"(?i)(bearer\s+)[a-z0-9._~+\-/=]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)([?&](?:key|api_key|access_token|refresh_token|code|upload_id|clipdrop_key)=)[^&\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(x-api-key['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", r"\1[REDACTED]", text)
    text = re.sub(r"(rtmps?://[^\s|]+/)[^\s/|?]+([?\s|]|$)", r"\1[STREAM_KEY]\2", text)
    return text