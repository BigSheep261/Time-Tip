"""Online release checking and installer download for the Windows build."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import socket
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QThread, QObject, pyqtSignal

from app.version import APP_VERSION, is_newer

DEFAULT_UPDATE_URL = "http://47.116.193.23:8787/api/update"


def local_ip() -> str:
    """Return the LAN address used to identify this update request."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("47.116.193.23", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class _UpdateWorker(QThread):
    checked = pyqtSignal(dict)
    downloaded = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    failed = pyqtSignal(str)

    def __init__(self, mode: str, metadata_url: str, package_url: str = "", expected_sha256: str = "", metadata: dict | None = None) -> None:
        super().__init__()
        self.mode = mode.strip().lower()
        self.metadata_url = metadata_url.strip()
        self.package_url = package_url.strip()
        self.expected_sha256 = expected_sha256.strip().lower()
        self.metadata = metadata or {}
        self.client_ip = local_ip()

    def _report(self, success: bool, error: str = "") -> None:
        """Tell the service whether a download completed and which source was used."""
        parsed = urllib.parse.urlsplit(self.metadata_url)
        endpoint = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/api/update/status", "", ""))
        payload = {
            "client_ip": self.client_ip,
            "version": str(self.metadata.get("version", "")),
            "source": str(self.metadata.get("source", "unknown")),
            "source_label": str(self.metadata.get("source_label", "")),
            "success": bool(success),
            "error": error,
        }
        try:
            request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"),
                                             headers={"Content-Type": "application/json", "User-Agent": "TimeTip/" + APP_VERSION}, method="POST")
            with urllib.request.urlopen(request, timeout=5):
                pass
        except OSError:
            # Reporting must never turn a successful local download into a failure.
            pass

    def run(self) -> None:
        try:
            if self.mode == "check":
                query = urllib.parse.urlencode({"client_ip": self.client_ip, "current_version": APP_VERSION})
                separator = "&" if "?" in self.metadata_url else "?"
                request = urllib.request.Request(
                    self.metadata_url + separator + query,
                    headers={"User-Agent": "TimeTip/" + APP_VERSION, "Accept": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=8) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict) or payload.get("product", "TimeTip") != "TimeTip":
                    raise ValueError("更新服务返回了不受支持的元数据。")
                version = str(payload.get("version", "")).strip()
                url = str(payload.get("url", "")).strip()
                digest = str(payload.get("sha256", "")).strip().lower()
                if not version or not url or len(digest) != 64:
                    raise ValueError("更新元数据缺少 version、url 或 sha256。")
                int(digest, 16)
                payload = dict(payload)
                payload["version"] = version
                payload["url"] = url
                payload["sha256"] = digest
                payload["has_update"] = is_newer(version, APP_VERSION)
                parsed = urllib.parse.urlsplit(self.metadata_url)
                payload["source_ip"] = parsed.hostname or ""
                payload.setdefault("source", "unknown")
                payload.setdefault("source_label", "未知来源")
                payload["client_ip"] = self.client_ip
                self.checked.emit(payload)
                return
            if self.mode != "download" or not self.package_url or len(self.expected_sha256) != 64:
                raise ValueError("更新下载参数不完整。")
            request = urllib.request.Request(self.package_url, headers={"User-Agent": "TimeTip-updates"})
            with urllib.request.urlopen(request, timeout=30) as response:
                total = int(response.headers.get("Content-Length", "0") or 0)
                temp_dir = Path(tempfile.gettempdir()) / "TimeTip-updates"
                temp_dir.mkdir(parents=True, exist_ok=True)
                destination = temp_dir / ("TimeTip-Setup-" + self.expected_sha256[:12] + "-download.exe")
                digest = hashlib.sha256()
                received = 0
                with destination.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        self.progress.emit(received, total)
                if digest.hexdigest().lower() != self.expected_sha256:
                    destination.unlink(missing_ok=True)
                    raise ValueError("安装包校验失败，文件可能已损坏或来源不可信。")
            self._report(True)
            self.downloaded.emit(str(destination))
        except urllib.error.HTTPError as error:
            message = f"更新服务暂不可用（HTTP {error.code}），请联系管理员。"
            try:
                payload = json.loads(error.read().decode("utf-8"))
                message = str(payload.get("error", message))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
            if self.mode == "download":
                self._report(False, message)
            self.failed.emit(message)
        except (OSError, ValueError, TypeError, urllib.error.URLError, json.JSONDecodeError) as error:
            if self.mode == "download":
                self._report(False, str(error))
            self.failed.emit(str(error))


class Updater(QObject):
    """Small asynchronous facade used by the settings page."""

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
            "download", self.metadata_url, str(self.metadata.get("url", "")), str(self.metadata.get("sha256", "")), self.metadata
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
