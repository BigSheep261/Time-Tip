"""TimeTip update service with automatic/manual package fallback and admin GUI."""
from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG = logging.getLogger("timetip-update")
DEFAULT_REPO = "https://github.com/BigSheep261/Time-Tip.git"
VERSION_RE = re.compile(r"^V?(\d+(?:\.\d+){1,3})$", re.IGNORECASE)


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


def version_tuple(value: str) -> tuple[int, ...]:
    match = VERSION_RE.fullmatch(str(value).strip())
    if not match:
        raise ValueError(f"invalid version: {value}")
    return tuple(int(part) for part in match.group(1).split("."))


class ReleaseManager:
    def __init__(self, config: Config):
        self.config = config
        self.repo_dir = config.root / "repo"
        self.automatic_dir = config.root / "automatic"
        # Backwards compatible alias used by older deployment scripts.
        self.download_dir = self.automatic_dir
        self.manual_dir = config.root / "manual"
        self.metadata_path = config.root / "metadata.json"
        self.stats_path = config.root / "stats.jsonl"
        self._lock = threading.RLock()
        self._last_sync = 0.0
        self._metadata: dict | None = None

    def current(self, client_ip: str = "") -> dict:
        with self._lock:
            if self._metadata is None or time.time() - self._last_sync >= self.config.sync_interval:
                self.sync()
            if self._metadata is None:
                raise ReleaseUnavailable("没有可用的安装包，请联系管理员")
            result = dict(self._metadata)
            result["client_ip"] = client_ip
            result["request_ip"] = client_ip
            return result

    def sync(self) -> dict:
        with self._lock:
            self.config.root.mkdir(parents=True, exist_ok=True)
            self.automatic_dir.mkdir(parents=True, exist_ok=True)
            self.manual_dir.mkdir(parents=True, exist_ok=True)
            auto = None
            try:
                self._update_checkout()
                auto = self._publish_automatic()
            except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
                LOG.warning("automatic release sync unavailable: %s", error)
            # Keep previously pulled packages usable during a temporary Git outage.
            candidates = [item for item in (auto, self._latest_automatic(), self._latest_manual()) if item]
            if not candidates:
                self._metadata = None
                self._last_sync = time.time()
                raise ReleaseUnavailable("没有可用的安装包，请联系管理员")
            metadata = max(candidates, key=lambda item: version_tuple(item["version"]))
            self.metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            self._metadata, self._last_sync = metadata, time.time()
            return dict(metadata)

    def _run_git(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, check=True,
                                capture_output=True, text=True, timeout=120)
        return result.stdout.strip()

    def _update_checkout(self) -> None:
        if not (self.repo_dir / ".git").exists():
            if self.repo_dir.exists():
                shutil.rmtree(self.repo_dir)
            self._run_git("clone", "--branch", self.config.branch, "--single-branch", "--depth", "1",
                          self.config.repo_url, str(self.repo_dir))
        else:
            self._run_git("fetch", "--depth", "1", "origin", self.config.branch, cwd=self.repo_dir)
            self._run_git("reset", "--hard", f"origin/{self.config.branch}", cwd=self.repo_dir)

    def _branch_version(self) -> tuple[str, str]:
        commit = self._run_git("rev-parse", "HEAD", cwd=self.repo_dir)
        source = (self.repo_dir / "app" / "version.py").read_text(encoding="utf-8")
        match = re.search(r"^\s*APP_VERSION\s*=\s*[\"']([^\"']+)[\"']", source, re.MULTILINE)
        if not match:
            raise ReleaseUnavailable("release 分支缺少 APP_VERSION")
        version = match.group(1).strip()
        version_tuple(version)
        return version, commit

    def _read_manifest(self) -> dict:
        for relative in ("release/update.json", "release/manifest.json", "update.json"):
            path = self.repo_dir / relative
            if path.is_file():
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(value, dict):
                        return value
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
            self.repo_dir / "release" / f"TimeTip-Setup-V{version}.exe",
            self.repo_dir / "release" / "TimeTip-Setup.exe",
            self.repo_dir / "TimeTip-Setup.exe",
        ]
        if self.config.package_path:
            candidates.insert(0, self.config.package_path)
        for path in candidates:
            if path.is_file():
                return path, expected, notes
        remote = str(manifest.get("url", manifest.get("asset_url", ""))).strip()
        if remote.startswith(("http://", "https://")):
            return Path(remote), expected, notes
        raise ReleaseUnavailable("release 分支没有安装包")

    def _publish_automatic(self) -> dict:
        version, commit = self._branch_version()
        source, expected, notes = self._resolve_package(self._read_manifest(), version)
        filename = f"TimeTip-Setup-{version}.exe"
        destination = self.automatic_dir / f"V{version}" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != destination.resolve():
            self._copy_or_download(source, destination, expected)
        digest = self._sha256(destination)
        if expected and digest.lower() != expected.lower():
            destination.unlink(missing_ok=True)
            raise ReleaseUnavailable("安装包 SHA-256 校验失败")
        return self._make_metadata(version, destination, digest, notes or f"release 分支提交：{commit[:12]}", "automatic", commit)

    def _latest_manual(self) -> dict | None:
        found = []
        for version_dir in self.manual_dir.glob("V*"):
            match = VERSION_RE.fullmatch(version_dir.name)
            if not match:
                continue
            files = sorted(version_dir.glob("*.exe"), key=lambda path: path.stat().st_mtime, reverse=True)
            if files:
                path = files[0]
                found.append(self._make_metadata(match.group(1), path, self._sha256(path), "手动上传安装包", "manual", ""))
        return max(found, key=lambda item: version_tuple(item["version"])) if found else None

    def _latest_automatic(self) -> dict | None:
        found = []
        for version_dir in self.automatic_dir.glob("V*"):
            match = VERSION_RE.fullmatch(version_dir.name)
            if not match:
                continue
            files = sorted(version_dir.glob("*.exe"), key=lambda path: path.stat().st_mtime, reverse=True)
            if files:
                path = files[0]
                found.append(self._make_metadata(match.group(1), path, self._sha256(path), "自动拉取安装包", "automatic", ""))
        return max(found, key=lambda item: version_tuple(item["version"])) if found else None

    def _make_metadata(self, version: str, path: Path, digest: str, notes: str, source: str, commit: str) -> dict:
        return {
            "product": "TimeTip",
            "version": version,
            "url": f"{self.config.public_base_url}/download/{urllib.parse.quote(path.name)}",
            "source_ip": urllib.parse.urlsplit(self.config.public_base_url).hostname or "",
            "filename": path.name,
            "sha256": digest,
            "release_notes": notes,
            "source": source,
            "source_label": "自动拉取" if source == "automatic" else "手动上传",
            "package_path": str(path),
            "commit": commit,
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

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

    def record_status(self, payload: dict, remote_ip: str) -> dict:
        event = {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "remote_ip": remote_ip, **payload}
        self.config.root.mkdir(parents=True, exist_ok=True)
        with self.stats_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def stats(self, limit: int = 100) -> list[dict]:
        if not self.stats_path.is_file():
            return []
        result = []
        for line in self.stats_path.read_text(encoding="utf-8").splitlines()[-limit:][::-1]:
            try:
                result.append(json.loads(line))
            except ValueError:
                pass
        return result

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


class UpdateHandler(BaseHTTPRequestHandler):
    manager: ReleaseManager

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if parsed.path == "/health":
                self._json({"ok": True})
            elif parsed.path == "/api/update":
                query = urllib.parse.parse_qs(parsed.query)
                client_ip = (query.get("client_ip") or [self.client_address[0]])[0]
                self._json(self.manager.current(client_ip))
            elif parsed.path == "/api/stats":
                self._json({"items": self.manager.stats()})
            elif parsed.path == "/admin":
                self._admin()
            elif parsed.path.startswith("/download/"):
                self._download(urllib.parse.unquote(parsed.path.removeprefix("/download/")))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except ReleaseUnavailable as error:
            self._json({"error": str(error), "contact_admin": True}, HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception:
            LOG.exception("request failed")
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        if urllib.parse.urlsplit(self.path).path != "/api/update/status":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            event = self.manager.record_status(payload, self.client_address[0])
            self._json({"ok": True, "event": event})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _json(self, value: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _download(self, filename: str) -> None:
        metadata = self.manager.current(self.client_address[0])
        if filename != metadata.get("filename"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path = Path(metadata["package_path"])
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/vnd.microsoft.portable-executable")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as stream:
            shutil.copyfileobj(stream, self.wfile, 1024 * 1024)

    def _admin(self) -> None:
        metadata = self.manager._metadata
        rows = "".join(
            f"<tr><td>{html.escape(str(item.get('time', '')))}</td>"
            f"<td>{html.escape(str(item.get('client_ip', item.get('remote_ip', ''))))}</td>"
            f"<td>{html.escape(str(item.get('version', '')))}</td>"
            f"<td>{html.escape(str(item.get('source_label', item.get('source', ''))))}</td>"
            f"<td>{'成功' if item.get('success') else '失败'}</td></tr>"
            for item in self.manager.stats()
        )
        current = html.escape(json.dumps(metadata or {}, ensure_ascii=False, indent=2))
        body = (
            "<!doctype html><meta charset='utf-8'><title>TimeTip 更新管理</title>"
            "<style>body{font-family:system-ui;margin:2rem}pre{background:#f4f4f4;padding:1rem}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:.5rem;text-align:left}</style>"
            f"<h1>TimeTip 更新管理</h1><h2>当前安装包</h2><pre>{current}</pre>"
            f"<h2>客户端更新记录</h2><table><tr><th>时间</th><th>客户端 IP</th><th>版本</th><th>来源</th><th>结果</th></tr>{rows}</table>"
        )
        data = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        LOG.info("%s - %s", self.address_string(), format % args)


def serve(config: Config | None = None) -> None:
    config = config or Config()
    manager = ReleaseManager(config)
    try:
        manager.sync()
    except ReleaseUnavailable as error:
        LOG.warning("initial release sync skipped: %s", error)
    handler = type("ConfiguredUpdateHandler", (UpdateHandler,), {"manager": manager})
    server = ThreadingHTTPServer((config.host, config.port), handler)
    LOG.info("listening on %s:%s", config.host, config.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("TIMETIP_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    serve()
