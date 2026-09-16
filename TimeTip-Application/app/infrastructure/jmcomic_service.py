"""Local JM comic service used by the optional TimeTip JM module.

The UI deliberately talks to this small adapter instead of importing the
AstrBot plugin.  jmcomic is loaded lazily so the normal TimeTip application
continues to work when the optional downloader dependencies are unavailable.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


def _load_jmcomic():
    try:
        import jmcomic  # type: ignore
    except ImportError:
        return None
    return jmcomic


def dependency_error() -> str:
    return "JM 下载功能需要先安装 jmcomic、PyMuPDF 和 pyzipper 依赖。"


def _natural_key(path: Path, root: Path) -> list[tuple[int, int | str]]:
    relative = str(path.relative_to(root))
    return [
        (0, int(token)) if token.isdigit() else (1, token.lower())
        for token in re.split(r"(\d+)", relative)
    ]


def _image_files(root: Path) -> list[Path]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    ]
    return sorted(files, key=lambda path: _natural_key(path, root))


@dataclass(frozen=True)
class JMDownloadResult:
    album_id: str
    title: str
    chapter_count: int
    image_count: int
    directory: Path


class JMComicService:
    """Synchronous jmcomic facade; callers should run it off the UI thread."""

    def __init__(self, root: Path, settings: dict[str, Any] | None = None) -> None:
        self.root = root
        self.settings = settings or {}
        self.download_root = root / "jm_downloads"
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.cover_root = root / "jm_covers"
        self.cover_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def available() -> bool:
        return _load_jmcomic() is not None

    def _option(self):
        jmcomic = _load_jmcomic()
        if jmcomic is None:
            raise RuntimeError(dependency_error())
        option_dict: dict[str, Any] = {
            "dir_rule": {"base_dir": str(self.download_root), "rule": "Bd/Aid/Pindex"},
            "download": {
                "image": {"suffix": str(self.settings.get("image_suffix", ".jpg"))},
                "threading": {"photo": 3, "image": 5},
            },
            "client": {"impl": str(self.settings.get("client_type", "api"))},
        }
        domain = str(self.settings.get("client_domain", "")).strip()
        if domain:
            option_dict["client"]["domain"] = [item.strip() for item in domain.split(",") if item.strip()]
        retry_times = int(self.settings.get("retry_times", 0) or 0)
        if retry_times > 0:
            option_dict["client"]["retry_times"] = retry_times
        proxy = str(self.settings.get("proxy_url", "")).strip()
        option_dict["client"]["postman"] = {"meta_data": {"proxies": proxy if proxy else {}}}
        return jmcomic.JmModuleConfig.option_class().construct(option_dict)

    def _client(self, option):
        return option.new_jm_client()

    def search(self, keyword: str, page: int = 1, mode: str = "site") -> list[dict[str, Any]]:
        jmcomic = _load_jmcomic()
        if jmcomic is None:
            raise RuntimeError(dependency_error())
        client = self._client(self._option())
        method = {
            "site": client.search_site,
            "tag": client.search_tag,
            "author": client.search_author,
            "actor": client.search_actor,
            "work": client.search_work,
        }.get(mode, client.search_site)
        result = []
        for album_id, title, tags in method(keyword.strip(), max(1, int(page))).iter_id_title_tag():
            result.append({"id": str(album_id), "title": str(title), "tags": list(tags or [])})
        return result

    def detail(self, album_id: str) -> dict[str, Any]:
        jmcomic = _load_jmcomic()
        if jmcomic is None:
            raise RuntimeError(dependency_error())
        parsed = jmcomic.JmcomicText.parse_to_jm_id(album_id)
        album = self._client(self._option()).get_album_detail(parsed)
        return {
            "id": str(album.id),
            "title": str(album.title),
            "author": str(getattr(album, "author", "") or ""),
            "tags": list(getattr(album, "tags", []) or []),
            "chapter_count": len(album),
            "description": str(getattr(album, "description", "") or ""),
            "pub_date": str(getattr(album, "pub_date", "") or ""),
            "update_date": str(getattr(album, "update_date", "") or ""),
            "views": int(getattr(album, "views", 0) or 0),
            "likes": int(getattr(album, "likes", 0) or 0),
        }

    def chapter_id(self, album_id: str, chapter: int) -> tuple[str, str, int]:
        jmcomic = _load_jmcomic()
        if jmcomic is None:
            raise RuntimeError(dependency_error())
        album = self._client(self._option()).get_album_detail(jmcomic.JmcomicText.parse_to_jm_id(album_id))
        total = len(album.episode_list)
        if chapter < 1 or chapter > total:
            raise ValueError(f"章节序号必须在 1 到 {total} 之间")
        photo_id, _index, title = album.episode_list[chapter - 1]
        return str(photo_id), str(title), total

    def download_album(self, album_id: str, progress: Callable[[int, int, str], None] | None = None) -> JMDownloadResult:
        jmcomic = _load_jmcomic()
        if jmcomic is None:
            raise RuntimeError(dependency_error())
        option = self._option()
        downloader_cls = self._progress_downloader(jmcomic)
        downloader = downloader_cls(option, progress)
        with downloader:
            album = downloader.download_album(jmcomic.JmcomicText.parse_to_jm_id(album_id))
        directory = Path(option.dir_rule.decide_album_root_dir(album))
        return JMDownloadResult(str(album.id), str(album.title), len(album), downloader.downloaded_images, directory)

    def download_photo(self, photo_id: str, progress: Callable[[int, int, str], None] | None = None) -> JMDownloadResult:
        jmcomic = _load_jmcomic()
        if jmcomic is None:
            raise RuntimeError(dependency_error())
        option = self._option()
        downloader_cls = self._progress_downloader(jmcomic)
        downloader = downloader_cls(option, progress)
        with downloader:
            photo = downloader.download_photo(jmcomic.JmcomicText.parse_to_jm_id(photo_id))
        directory = Path(option.decide_image_save_dir(photo))
        return JMDownloadResult(str(getattr(photo, "album_id", photo_id)), str(getattr(photo, "title", "") or ""), 1, downloader.downloaded_images, directory)

    @staticmethod
    def _progress_downloader(jmcomic):
        class ProgressDownloader(jmcomic.JmDownloader):
            def __init__(self, option, callback=None):
                super().__init__(option)
                self.callback = callback
                self.downloaded_images = 0
                self.total_images = 0

            def before_photo(self, photo):
                super().before_photo(photo)
                try:
                    self.total_images = len(photo)
                except Exception:
                    self.total_images = 0
                self._emit()

            def after_image(self, image, img_save_path):
                super().after_image(image, img_save_path)
                self.downloaded_images += 1
                self._emit()

            def _emit(self):
                if self.callback and self.total_images > 0:
                    self.callback(self.downloaded_images, self.total_images, "图片")

        return ProgressDownloader

    def pack_pdf(self, source_dir: Path, output_name: str) -> Path:
        try:
            import fitz  # type: ignore
        except ImportError as exc:
            raise RuntimeError("PDF 打包需要安装 PyMuPDF。") from exc
        images = _image_files(source_dir)
        if not images:
            raise RuntimeError("下载目录中没有可打包的图片。")
        output = source_dir.parent / f"{output_name}.pdf"
        document = fitz.open()
        try:
            for image in images:
                try:
                    image_doc = fitz.open(image)
                    pdf_bytes = image_doc.convert_to_pdf()
                    image_doc.close()
                    page_doc = fitz.open("pdf", pdf_bytes)
                    document.insert_pdf(page_doc)
                    page_doc.close()
                except Exception:
                    continue
            if document.page_count == 0:
                raise RuntimeError("无法从图片创建 PDF。")
            document.save(output)
        finally:
            document.close()
        return output

    @staticmethod
    def remove_path(path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()
