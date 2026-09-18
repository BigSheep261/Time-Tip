"""Pure validation helpers for the online update boundary."""
from __future__ import annotations

from pathlib import Path
import re
import urllib.parse


def safe_update_filename(filename: object) -> str:
    name = Path(str(filename)).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name if name.lower().endswith(".exe") else "TimeTip-Update.exe"


def validated_http_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("更新地址必须使用有效的 HTTP(S) URL。")
    return url


def expected_sha256(metadata: dict) -> str:
    value = str(metadata.get("sha256", metadata.get("checksumSha256", ""))).strip().lower()
    if value and not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("更新服务返回了无效的 SHA-256 校验值。")
    return value
