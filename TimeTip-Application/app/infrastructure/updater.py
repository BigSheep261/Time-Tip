"""Online update checking and installer download for the Windows build."""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QThread, QObject, pyqtSignal

from app.application.update_security import (
    expected_sha256 as _expected_sha256,
    safe_update_filename as _safe_filename,
    validated_http_url as _validated_http_url,
)
from app.version import APP_VERSION, is_newer

DEFAULT_UPDATE_URL = "http://47.116.193.23:8787/api/client/update/check"


def _source_label(source: str) -> str:
    return {"github": "GitHub 自动获取", "manual": "管理员手动上传"}.get(source, "未知来源")

class _UpdateWorker(QThread):
    checked = pyqtSignal(dict)
    downloaded = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    failed = pyqtSignal(str)

    def __init__(self, mode: str, metadata_url: str, package_url: str = "", metadata: dict | None = None) -> None:
        super().__init__()
        self.mode = mode.strip().lower()
        self.metadata_url = metadata_url.strip()
        self.package_url = package_url.strip()
        self.metadata = metadata or {}

    def _request_json(self, url: str) -> dict:
        request = urllib.request.Request(
            _validated_http_url(url),
            headers={"User-Agent": "TimeTip/" + APP_VERSION, "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("更新服务返回了无效数据。")
        return payload

    def _check(self) -> None:
        query = urllib.parse.urlencode({"version": APP_VERSION})
        separator = "&" if "?" in self.metadata_url else "?"
        payload = self._request_json(self.metadata_url + separator + query)
        current = str(payload.get("currentVersion", APP_VERSION)).strip() or APP_VERSION
        version = str(payload.get("version", current)).strip().lstrip("vV")
        source = str(payload.get("source", "unknown")).strip().lower() or "unknown"
        raw_download_url = str(payload.get("downloadUrl", "")).strip()
        if raw_download_url:
            download_url = _validated_http_url(
                urllib.parse.urljoin(self.metadata_url, raw_download_url)
            )
        else:
            download_url = ""
        has_package = bool(version and download_url)
        has_update = bool(payload.get("latest") is False and has_package and is_newer(version, APP_VERSION))
        normalized = dict(payload)
        normalized.update(
            {
                "version": version,
                "currentVersion": current,
                "downloadUrl": download_url,
                "url": download_url,
                "source": source,
                "source_label": _source_label(source),
                "release_notes": str(payload.get("releaseNotes", payload.get("release_notes", ""))).strip(),
                "filename": _safe_filename(payload.get("filename", "TimeTip-Update.exe")),
                "has_update": has_update,
            }
        )
        self.checked.emit(normalized)

    def _download(self) -> None:
        if not self.package_url:
            raise ValueError("更新服务没有提供安装包下载地址。")
        request = urllib.request.Request(
            _validated_http_url(self.package_url),
            headers={"User-Agent": "TimeTip/" + APP_VERSION, "Accept": "application/octet-stream"},
        )
        expected_hash = _expected_sha256(self.metadata)
        temp_dir = Path(tempfile.gettempdir()) / "TimeTip-updates"
        temp_dir.mkdir(parents=True, exist_ok=True)
        destination = temp_dir / _safe_filename(
            self.metadata.get("filename", "TimeTip-Update.exe")
        )
        partial = destination.with_suffix(destination.suffix + ".part")
        digest = hashlib.sha256()
        received = 0
        try:
            with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
                total = int(response.headers.get("Content-Length", "0") or 0)
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    self.progress.emit(received, total)
            if total and received != total:
                raise ValueError("更新包下载不完整，请重试。")
            if expected_hash and digest.hexdigest() != expected_hash:
                raise ValueError("更新包完整性校验失败，请勿安装。")
            os.replace(partial, destination)
        finally:
            partial.unlink(missing_ok=True)
        self.downloaded.emit(str(destination))

    def run(self) -> None:
        try:
            if self.mode == "check":
                self._check()
            elif self.mode == "download":
                self._download()
            else:
                raise ValueError("不支持的更新操作。")
        except urllib.error.HTTPError as error:
            message = f"更新服务暂不可用（HTTP {error.code}），请联系管理员。"
            try:
                payload = json.loads(error.read().decode("utf-8"))
                message = str(payload.get("error", payload.get("message", message)))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
            self.failed.emit(message)
        except (OSError, ValueError, TypeError, urllib.error.URLError, json.JSONDecodeError) as error:
            self.failed.emit(str(error))


class Updater(QObject):
    """Asynchronous client for service_core's public update API."""

    update_available = pyqtSignal(dict)
    no_update = pyqtSignal(dict)
    download_progress = pyqtSignal(int, int)
    download_ready = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None, metadata_url: str | None = None) -> None:
        super().__init__(parent)
        self.metadata_url = metadata_url or os.environ.get("TIMETIP_UPDATE_URL", DEFAULT_UPDATE_URL)
        self._worker: _UpdateWorker | None = None
        self.metadata: dict = {}

    def check(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = _UpdateWorker("check", self.metadata_url)
        self._worker.checked.connect(self._on_checked)
        self._worker.failed.connect(self.failed)
        self._worker.finished.connect(self._clear_worker)
        self._worker.start()

    def _on_checked(self, metadata: dict) -> None:
        self.metadata = metadata
        (self.update_available if metadata.get("has_update") else self.no_update).emit(metadata)

    def download(self) -> None:
        if not self.metadata.get("has_update"):
            self.failed.emit("当前没有可下载的新版本。")
            return
        self._worker = _UpdateWorker(
            "download", self.metadata_url, str(self.metadata.get("downloadUrl", "")), self.metadata
        )
        self._worker.progress.connect(self.download_progress)
        self._worker.downloaded.connect(self.download_ready)
        self._worker.failed.connect(self.failed)
        self._worker.finished.connect(self._clear_worker)
        self._worker.start()

    def _clear_worker(self) -> None:
        worker = self._worker
        if worker is not None and not worker.isRunning():
            worker.deleteLater()
            self._worker = None

    @staticmethod
    def launch_installer(path: str) -> None:
        installer = Path(path).resolve()
        if not installer.is_file():
            raise FileNotFoundError(path)
        subprocess.Popen([str(installer), "/update"], cwd=str(installer.parent), close_fds=True)
