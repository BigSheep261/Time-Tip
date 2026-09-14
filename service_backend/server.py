"""TimeTip update service.

The service is intentionally implemented with the Python standard library so it
can run on a small Linux VPS without installing a web framework.  It fetches the
latest commit from the ``relese`` branch, reads ``app/version.py`` and serves a
validated installer through the same metadata contract used by the desktop app.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG = logging.getLogger("timetip-update")
VERSION_RE = re.compile(r"^\s*APP_VERSION\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
DEFAULT_REPO = "https://github.com/BigSheep261/Time-Tip.git"


class ReleaseUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    repo_url: str = os.environ.get("TIMETIP_REPO_URL", DEFAULT_REPO)
    branch: str = os.environ.get("TIMETIP_RELEASE_BRANCH", "release")
    root: Path = Path(os.environ.get("TIMETIP_UPDATE_ROOT", ".timetip-updates"))
    host: str = os.environ.get("TIMETIP_HOST", "0.0.0.0")
    port: int = int(os.environ.get("TIMETIP_PORT", "8787"))
    public_base_url: str = os.environ.get("TIMETIP_PUBLIC_BASE_URL", "http://47.116.193.23:8787").rstrip("/")
    sync_interval: int = int(os.environ.get("TIMETIP_SYNC_INTERVAL", "300"))
    package_path: Path | None = Path(os.environ["TIMETIP_PACKAGE_PATH"]) if os.environ.get("TIMETIP_PACKAGE_PATH") else None


class ReleaseManager:
    def __init__(self, config: Config):
        self.config = config
        self.repo_dir = config.root / "repo"
        self.download_dir = config.root / "downloads"
        self.metadata_path = config.root / "metadata.json"
        self._lock = threading.RLock()
        self._last_sync = 0.0
        self._metadata: dict | None = None

    def current(self) -> dict:
        with self._lock:
            if self._metadata is None or time.time() - self._last_sync >= self.config.sync_interval:
                self.sync()
            if self._metadata is None:
                raise ReleaseUnavailable("暂无可用的安装包")
            return dict(self._metadata)

    def sync(self) -> dict:
        with self._lock:
            self.config.root.mkdir(parents=True, exist_ok=True)
            self.download_dir.mkdir(parents=True, exist_ok=True)
            self._update_checkout()
            version, commit = self._branch_version()
            manifest = self._read_manifest()
            source, expected_hash, notes = self._resolve_package(manifest, version)
            filename = f"TimeTip-Setup-{version}.exe"
            destination = self.download_dir / filename
            if source.resolve() != destination.resolve():
                self._copy_or_download(source, destination, expected_hash)
            digest = self._sha256(destination)
            if expected_hash and digest.lower() != expected_hash.lower():
                destination.unlink(missing_ok=True)
                raise ReleaseUnavailable("安装包 SHA-256 校验失败")
            metadata = {
                "product": "TimeTip",
                "version": version,
                "url": f"{self.config.public_base_url}/download/{urllib.parse.quote(filename)}",
                "sha256": digest,
                "release_notes": notes or f"relese 分支提交：{commit[:12]}",
                "commit": commit,
                "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            self.metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            self._metadata = metadata
            self._last_sync = time.time()
            LOG.info("published %s (%s)", version, commit[:12])
            return dict(metadata)

    def _run_git(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *args], cwd=str(cwd) if cwd else None, check=True,
            capture_output=True, text=True, timeout=120,
        )
        return result.stdout.strip()

    def _update_checkout(self) -> None:
        if not (self.repo_dir / ".git").exists():
            if self.repo_dir.exists(): shutil.rmtree(self.repo_dir)
            self._run_git("clone", "--branch", self.config.branch, "--single-branch", "--depth", "1", self.config.repo_url, str(self.repo_dir))
        else:
            self._run_git("fetch", "--depth", "1", "origin", self.config.branch, cwd=self.repo_dir)
            self._run_git("reset", "--hard", f"origin/{self.config.branch}", cwd=self.repo_dir)

    def _branch_version(self) -> tuple[str, str]:
        commit = self._run_git("rev-parse", "HEAD", cwd=self.repo_dir)
        source = (self.repo_dir / "app" / "version.py").read_text(encoding="utf-8")
        match = VERSION_RE.search(source)
        if not match:
            raise ReleaseUnavailable("relese 分支缺少 app/version.py 或 APP_VERSION")
        version = match.group(1).strip()
        if not re.fullmatch(r"\d+(?:\.\d+){1,3}", version):
            raise ReleaseUnavailable("APP_VERSION 格式无效")
        return version, commit

    def _read_manifest(self) -> dict:
        for relative in ("release/update.json", "release/manifest.json", "update.json"):
            path = self.repo_dir / relative
            if path.is_file():
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(value, dict): return value
                except (OSError, ValueError):
                    LOG.warning("invalid release manifest: %s", path)
        return {}

    def _resolve_package(self, manifest: dict, version: str) -> tuple[Path, str, str]:
        expected = str(manifest.get("sha256", "")).strip().lower()
        if expected and not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ReleaseUnavailable("发布清单中的 sha256 无效")
        notes = str(manifest.get("release_notes", manifest.get("notes", "")))
        candidates = [
            self.repo_dir / "release" / f"TimeTip-Setup-{version}.exe",
            self.repo_dir / "release" / "TimeTip-Setup.exe",
            self.repo_dir / "TimeTip-Setup.exe",
        ]
        if self.config.package_path:
            candidates.insert(0, self.config.package_path)
        for path in candidates:
            if path.is_file(): return path, expected, notes
        remote = str(manifest.get("url", manifest.get("asset_url", ""))).strip()
        if remote.startswith(("http://", "https://")):
            return Path(remote), expected, notes
        raise ReleaseUnavailable("relese 分支没有安装包；请提交 release/TimeTip-Setup.exe 或 release/update.json")

    def _copy_or_download(self, source: Path, destination: Path, expected_hash: str) -> None:
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.unlink(missing_ok=True)
        try:
            if str(source).startswith(("http://", "https://")):
                with urllib.request.urlopen(str(source), timeout=120) as response, temporary.open("wb") as output:
                    shutil.copyfileobj(response, output, 1024 * 1024)
            else:
                shutil.copy2(source, temporary)
            if expected_hash and self._sha256(temporary).lower() != expected_hash.lower():
                raise ReleaseUnavailable("远程安装包 SHA-256 校验失败")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


class UpdateHandler(BaseHTTPRequestHandler):
    manager: ReleaseManager
    config: Config

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if parsed.path == "/health":
                self._json({"ok": True})
            elif parsed.path == "/api/update":
                self._json(self.manager.current())
            elif parsed.path.startswith("/download/"):
                self._download(urllib.parse.unquote(parsed.path.removeprefix("/download/")))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except ReleaseUnavailable as error:
            LOG.warning("release unavailable: %s", error)
            self._json({"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception:
            LOG.exception("request failed")
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def _json(self, value: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _download(self, filename: str) -> None:
        metadata = self.manager.current()
        if filename != metadata.get("url", "").rsplit("/", 1)[-1]:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path = self.manager.download_dir / filename
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        size = path.stat().st_size
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/vnd.microsoft.portable-executable")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with path.open("rb") as stream:
            shutil.copyfileobj(stream, self.wfile, 1024 * 1024)

    def log_message(self, format: str, *args) -> None:
        LOG.info("%s - %s", self.address_string(), format % args)


def serve(config: Config | None = None) -> None:
    config = config or Config()
    manager = ReleaseManager(config)
    try:
        manager.sync()
    except ReleaseUnavailable as error:
        # Keep the HTTP service up so a package can be published after deployment;
        # the next metadata request will retry synchronization.
        LOG.warning("initial release sync skipped: %s", error)
    handler = type("ConfiguredUpdateHandler", (UpdateHandler,), {"manager": manager, "config": config})
    server = ThreadingHTTPServer((config.host, config.port), handler)
    LOG.info("listening on %s:%s", config.host, config.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("TIMETIP_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    serve()
