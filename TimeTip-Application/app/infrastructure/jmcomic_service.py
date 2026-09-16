"""Local JM comic service used by the optional TimeTip JM module.

The UI deliberately talks to this small adapter instead of importing the
AstrBot plugin.  jmcomic is loaded lazily so the normal TimeTip application
continues to work when the optional downloader dependencies are unavailable.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from threading import RLock
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
    return "JM 下载组件加载失败，请重新安装完整版 TimeTip。"


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


def _display_count(value: Any) -> int:
    text = str(value or "0").strip().replace(",", "").upper()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([KMB万萬亿億]?)", text)
    if not match:
        return 0
    scale = {"": 1, "K": 1000, "M": 1000000, "B": 1000000000,
             "万": 10000, "萬": 10000, "亿": 100000000, "億": 100000000}
    return int(float(match[1]) * scale[match[2]])


class JMDownloadCancelled(RuntimeError):
    pass


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
        self.cancelled: Callable[[], bool] = lambda: False
        self.download_root = root / "jm_downloads"
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.cover_root = root / "jm_covers"
        self.cover_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def available() -> bool:
        return _load_jmcomic() is not None

    def _check_cancelled(self) -> None:
        if self.cancelled():
            raise JMDownloadCancelled("任务已取消。")

    def _option(self):
        self._check_cancelled()
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
            "views": _display_count(getattr(album, "views", 0)),
            "likes": _display_count(getattr(album, "likes", 0)),
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
        downloader_cls = self._progress_downloader(jmcomic, self._check_cancelled)
        downloader = downloader_cls(option, progress)
        with downloader:
            album = downloader.download_album(jmcomic.JmcomicText.parse_to_jm_id(album_id))
        self._verify_download(downloader)
        directory = Path(option.dir_rule.decide_album_root_dir(album))
        return JMDownloadResult(str(album.id), str(album.title), len(album), downloader.downloaded_images, directory)

    def download_photo(self, photo_id: str, progress: Callable[[int, int, str], None] | None = None) -> JMDownloadResult:
        jmcomic = _load_jmcomic()
        if jmcomic is None:
            raise RuntimeError(dependency_error())
        option = self._option()
        downloader_cls = self._progress_downloader(jmcomic, self._check_cancelled)
        downloader = downloader_cls(option, progress)
        with downloader:
            photo = downloader.download_photo(jmcomic.JmcomicText.parse_to_jm_id(photo_id))
        self._verify_download(downloader)
        directory = Path(option.decide_image_save_dir(photo))
        return JMDownloadResult(str(getattr(photo, "album_id", photo_id)), str(getattr(photo, "title", "") or ""), 1, downloader.downloaded_images, directory)

    def _verify_download(self, downloader) -> None:
        self._check_cancelled()
        failed_images = len(downloader.download_failed_image)
        failed_photos = len(downloader.download_failed_photo)
        if failed_images or failed_photos:
            raise RuntimeError(f"下载不完整：{failed_photos} 个章节、{failed_images} 张图片失败，请重试。")
        if downloader.downloaded_images == 0:
            raise RuntimeError("没有下载到图片，请重试。")
        downloader.finish_progress()

    @staticmethod
    def _progress_downloader(jmcomic, check_cancelled: Callable[[], None] = lambda: None):
        class ProgressDownloader(jmcomic.JmDownloader):
            def __init__(self, option, callback=None):
                super().__init__(option)
                self.callback = callback
                self.downloaded_images = 0
                self.total_images = 0
                self.photo_sizes: dict[str, int] = {}
                self.completed_paths: set[str] = set()
                self.progress_lock = RLock()

            def before_album(self, album):
                check_cancelled()
                super().before_album(album)
                with self.progress_lock:
                    self.total_images = _display_count(getattr(album, "page_count", 0))
                    self._emit()

            def before_photo(self, photo):
                check_cancelled()
                super().before_photo(photo)
                with self.progress_lock:
                    self.photo_sizes[str(photo.id)] = len(photo)
                    self.total_images = max(self.total_images, sum(self.photo_sizes.values()))
                    self._emit()

            def before_image(self, image, img_save_path):
                check_cancelled()
                super().before_image(image, img_save_path)

            def download_by_image_detail(self, image):
                super().download_by_image_detail(image)
                # jmcomic 2.7.0 skips after_image for cached files; later
                # versions call it. Count each saved path once in either case.
                if image.cache and image.exists and not image.skip:
                    self._record_image(image.save_path)

            def after_image(self, image, img_save_path):
                super().after_image(image, img_save_path)
                self._record_image(img_save_path)

            def _record_image(self, img_save_path):
                with self.progress_lock:
                    key = str(img_save_path)
                    if key in self.completed_paths:
                        return
                    self.completed_paths.add(key)
                    self.downloaded_images += 1
                    self.total_images = max(self.total_images, self.downloaded_images)
                    self._emit()

            def finish_progress(self):
                with self.progress_lock:
                    self.total_images = self.downloaded_images
                    self._emit()

            def _emit(self):
                if self.callback and self.total_images > 0:
                    self.callback(self.downloaded_images, self.total_images, "图片")

        return ProgressDownloader

    def pack_pdf(self, source_dir: Path, output_name: str) -> Path:
        try:
            import fitz  # type: ignore
        except ImportError as exc:
            raise RuntimeError("PDF 组件加载失败，请重新安装完整版 TimeTip。") from exc
        images = _image_files(source_dir)
        if not images:
            raise RuntimeError("下载目录中没有可打包的图片。")
        output = source_dir.parent / f"{output_name}.pdf"
        temporary: Path | None = None
        try:
            with fitz.open() as document:
                for image in images:
                    self._check_cancelled()
                    try:
                        with fitz.open(image) as image_doc:
                            pdf_bytes = image_doc.convert_to_pdf()
                        with fitz.open("pdf", pdf_bytes) as page_doc:
                            document.insert_pdf(page_doc)
                    except Exception as exc:
                        raise RuntimeError(f"无法读取图片 {image.name}，PDF 未生成。") from exc
                self._check_cancelled()
                with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".pdf", delete=False) as handle:
                    temporary = Path(handle.name)
                document.save(temporary)
            self._check_cancelled()
            temporary.replace(output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return output

    @staticmethod
    def remove_path(path: Path, download_root: Path) -> None:
        path, download_root = path.resolve(), download_root.resolve()
        if path == download_root or not path.is_relative_to(download_root):
            raise ValueError("只能删除 JM 下载目录内的文件或文件夹。")
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()
