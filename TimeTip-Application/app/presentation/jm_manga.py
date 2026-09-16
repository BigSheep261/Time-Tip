"""JM漫画下载 page and its background workers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QSize, QThread, QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.infrastructure.jmcomic_service import JMComicService
from app.presentation.widgets import Card, ElidedLabel
from app.presentation.jm_widgets import JMListWidget, MarqueeLabel


class JMWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)

    def __init__(self, function: Callable[..., Any], *args: Any) -> None:
        super().__init__()
        self.function = function
        self.args = args

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            result = self.function(*self.args)
            if not self.isInterruptionRequested():
                self.completed.emit(result)
        except Exception as exc:  # noqa: BLE001 - display a friendly error in the page
            self.failed.emit(str(exc) or exc.__class__.__name__)


class JMMangaPageMixin:
    def _jm_store_root(self) -> Path:
        backend = getattr(self.store, "_backend", None)
        if backend is not None:
            return Path(backend.root)
        settings = getattr(self.store, "settings", None)
        return Path(settings.fileName()).resolve().parent if settings is not None else Path.home() / "TimeTip"

    def _jm_service(self) -> JMComicService:
        settings = {
            "image_suffix": self.store.get("jm_image_suffix", ".jpg"),
            "client_type": self.store.get("jm_client_type", "api"),
            "client_domain": self.store.get("jm_client_domain", ""),
            "retry_times": self.store.get("jm_retry_times", "0"),
            "proxy_url": self.store.get("jm_proxy_url", ""),
        }
        return JMComicService(self._jm_store_root(), settings)

    def _jm_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(QLabel("JM漫画下载", objectName="pageTitle"))
        self.jm_status = ElidedLabel("搜索、查看详情并加入下载队列。")
        self.jm_status.setObjectName("pageSubtitle")
        self.jm_status.setTextFormat(Qt.TextFormat.PlainText)
        header.addWidget(self.jm_status, 1)
        layout.addLayout(header)

        search_card = Card()
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(20, 16, 20, 16)
        search_row = QHBoxLayout()
        self.jm_search_input = QLineEdit()
        self.jm_search_input.setPlaceholderText("输入漫画关键词")
        self.jm_search_input.returnPressed.connect(self._jm_search)
        search_row.addWidget(self.jm_search_input, 1)
        self.jm_search_mode = QComboBox()
        for key, label in (("site", "综合"), ("tag", "标签"), ("author", "作者"), ("actor", "角色"), ("work", "作品")):
            self.jm_search_mode.addItem(label, key)
        search_row.addWidget(self.jm_search_mode)
        self.jm_search_page = QSpinBox()
        self.jm_search_page.setRange(1, 9999)
        self.jm_search_page.setValue(1)
        self.jm_search_page.setPrefix("第 ")
        self.jm_search_page.setSuffix(" 页")
        search_row.addWidget(self.jm_search_page)
        search = QPushButton("搜索", objectName="primaryButton")
        search.clicked.connect(self._jm_search)
        search_row.addWidget(search)
        search_layout.addLayout(search_row)
        self.jm_search_feedback = self._jm_hint("")
        search_layout.addWidget(self.jm_search_feedback)
        self.jm_results = JMListWidget(258)
        search_layout.addWidget(self.jm_results)
        layout.addWidget(search_card)

        detail_card = Card()
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(20, 16, 20, 16)
        self.jm_detail_title = MarqueeLabel("选择搜索结果查看详情", objectName="cardTitle")
        detail_layout.addWidget(self.jm_detail_title)
        self.jm_detail_text = QLabel("")
        self.jm_detail_text.setWordWrap(True)
        self.jm_detail_text.setTextFormat(Qt.TextFormat.PlainText)
        self.jm_detail_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        detail_layout.addWidget(self.jm_detail_text)
        detail_actions = QHBoxLayout()
        self.jm_chapter = QSpinBox()
        self.jm_chapter.setRange(1, 1)
        self.jm_chapter.setPrefix("第 ")
        self.jm_chapter.setSuffix(" 章")
        detail_actions.addWidget(self.jm_chapter)
        self.jm_pdf_check = QCheckBox("下载后生成 PDF")
        self.jm_pdf_check.setChecked(True)
        detail_actions.addWidget(self.jm_pdf_check)
        self.jm_album_button = QPushButton("下载整本", objectName="primaryButton")
        self.jm_album_button.setEnabled(False)
        self.jm_album_button.clicked.connect(self._jm_queue_album)
        detail_actions.addWidget(self.jm_album_button)
        self.jm_photo_button = QPushButton("下载单章", objectName="secondaryButton")
        self.jm_photo_button.setEnabled(False)
        self.jm_photo_button.clicked.connect(self._jm_queue_photo)
        detail_actions.addWidget(self.jm_photo_button)
        detail_actions.addStretch()
        detail_layout.addLayout(detail_actions)
        layout.addWidget(detail_card)

        favorites_card = Card()
        favorites_layout = QVBoxLayout(favorites_card)
        favorites_layout.setContentsMargins(20, 16, 20, 16)
        favorites_layout.addWidget(QLabel("本地收藏夹", objectName="cardTitle"))
        self.jm_favorites = JMListWidget(80)
        favorites_layout.addWidget(self.jm_favorites)
        layout.addWidget(favorites_card)

        queue_card = Card()
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(20, 16, 20, 16)
        queue_header = QHBoxLayout()
        queue_header.addWidget(QLabel("下载管理", objectName="cardTitle"), 1)
        folder = QPushButton("打开下载目录", objectName="secondaryButton")
        folder.clicked.connect(self._jm_open_download_root)
        queue_header.addWidget(folder)
        queue_layout.addLayout(queue_header)
        self.jm_queue_tabs = QTabWidget(objectName="jmQueueTabs")
        self.jm_queue_list = JMListWidget(246)
        self.jm_completed_list = JMListWidget(246)
        self.jm_queue_tabs.addTab(self.jm_queue_list, "下载队列 (0)")
        self.jm_queue_tabs.addTab(self.jm_completed_list, "完成队列 (0)")
        queue_layout.addWidget(self.jm_queue_tabs)
        layout.addWidget(queue_card)
        layout.addStretch()

        self.jm_selected_id = ""
        self.jm_selected_title = ""
        self.jm_queue: list[dict[str, Any]] = []
        self.jm_completed: list[dict[str, Any]] = []
        self.jm_queue_worker: JMWorker | None = None
        self.jm_lookup_worker: JMWorker | None = None
        self._jm_workers: set[JMWorker] = set()
        self._jm_closing = False
        self._jm_load_favorites()
        self._jm_load_completed()
        return page

    @staticmethod
    def _jm_add_row(widget: QListWidget, row: QWidget, height: int) -> None:
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, height))
        row.setFixedHeight(height)
        widget.addItem(item)
        widget.setItemWidget(item, row)

    @staticmethod
    def _jm_button(text: str, width: int, primary: bool = False) -> QPushButton:
        button = QPushButton(text, objectName="primaryButton" if primary else "secondaryButton")
        button.setFixedSize(width, 40)
        button.setStyleSheet("padding: 0px 8px;")
        return button

    @staticmethod
    def _jm_hint(text: str) -> ElidedLabel:
        label = ElidedLabel(text)
        label.setObjectName("cardHint")
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _jm_start_worker(self, worker: JMWorker, done: Callable[[Any], None], failed: Callable[[str], None]) -> None:
        # Keep ownership until QThread.finished, not merely until the result
        # signal: run() can still be unwinding when the UI receives a result.
        worker.setParent(self)
        self._jm_workers.add(worker)
        worker.completed.connect(lambda value: done(value) if not self._jm_closing else None)
        worker.failed.connect(lambda message: failed(message) if not self._jm_closing else None)
        worker.finished.connect(lambda: self._jm_worker_finished(worker))
        worker.start()

    def _jm_worker_finished(self, worker: JMWorker) -> None:
        was_queue = self.jm_queue_worker is worker
        if was_queue:
            self.jm_queue_worker = None
        if self.jm_lookup_worker is worker:
            self.jm_lookup_worker = None
        self._jm_workers.discard(worker)
        worker.deleteLater()
        if self._jm_closing:
            if not self._jm_workers:
                QTimer.singleShot(0, self.quit_app)
        elif was_queue:
            self._jm_start_next()

    def _jm_search(self) -> None:
        keyword = self.jm_search_input.text().strip()
        if not keyword:
            self.jm_search_feedback.setText("请输入搜索关键词。")
            return
        if self._jm_closing or self.jm_lookup_worker is not None:
            return
        self.jm_search_feedback.setText("正在搜索…")
        self.jm_results.clear()
        try:
            service = self._jm_service()
        except (OSError, ValueError) as exc:
            self._jm_lookup_failed(str(exc))
            return
        worker = JMWorker(service.search, keyword, self.jm_search_page.value(), self.jm_search_mode.currentData())
        self.jm_lookup_worker = worker
        self._jm_start_worker(worker, self._jm_search_done, self._jm_lookup_failed)

    def _jm_search_done(self, results: list[dict[str, Any]]) -> None:
        self.jm_results.clear()
        self.jm_search_feedback.setText(f"找到 {len(results)} 条结果。")
        for data in results:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(12, 8, 12, 8)
            line.setSpacing(8)
            text = QVBoxLayout()
            text.setSpacing(4)
            text.addWidget(MarqueeLabel(f"{data['id']}  {data['title']}"))
            text.addWidget(self._jm_hint(f"标签：{'、'.join(data.get('tags', [])) or '无'}"))
            line.addLayout(text, 1)
            detail = self._jm_button("详情", 60)
            detail.clicked.connect(lambda _=False, album_id=data["id"]: self._jm_show_detail(album_id))
            line.addWidget(detail)
            favorite = self._jm_button("取消收藏" if self._jm_is_favorite(data["id"]) else "收藏", 80)
            favorite.setProperty("jmFavoriteId", str(data["id"]))
            favorite.clicked.connect(lambda _=False, value=data, button=favorite: self._jm_toggle_favorite(value, button))
            line.addWidget(favorite)
            download = self._jm_button("加入整本", 88, True)
            download.clicked.connect(lambda _=False, value=data: self._jm_enqueue(value["id"], value.get("title", value["id"]), 0, self.jm_pdf_check.isChecked()))
            line.addWidget(download)
            self._jm_add_row(self.jm_results, row, 78)

    def _jm_lookup_failed(self, message: str) -> None:
        self.jm_search_feedback.setText(message)
        self.jm_status.setText("JM 服务暂不可用。")

    def _jm_show_detail(self, album_id: str) -> None:
        if self._jm_closing or self.jm_lookup_worker is not None:
            return
        self.jm_status.setText("正在读取详情…")
        self.jm_selected_id = ""
        self.jm_selected_title = ""
        self.jm_detail_title.setText("正在读取详情…")
        self.jm_detail_text.clear()
        self.jm_album_button.setEnabled(False)
        self.jm_photo_button.setEnabled(False)
        try:
            service = self._jm_service()
        except (OSError, ValueError) as exc:
            self._jm_lookup_failed(str(exc))
            return
        worker = JMWorker(service.detail, album_id)
        self.jm_lookup_worker = worker
        self._jm_start_worker(worker, self._jm_detail_done, self._jm_lookup_failed)

    def _jm_detail_done(self, detail: dict[str, Any]) -> None:
        self.jm_selected_id = detail["id"]
        self.jm_selected_title = detail["title"]
        total = max(1, int(detail.get("chapter_count", 1)))
        self.jm_chapter.setRange(1, total)
        self.jm_detail_title.setText(f"{detail['title']}  ·  {detail['id']}")
        self.jm_detail_text.setText(
            f"作者：{detail.get('author') or '未知'}\n"
            f"章节：{total}  ·  标签：{'、'.join(detail.get('tags', [])) or '无'}\n"
            f"{detail.get('description') or '暂无简介'}"
        )
        self.jm_album_button.setEnabled(True)
        self.jm_photo_button.setEnabled(True)
        self.jm_status.setText("详情已加载。")

    def _jm_queue_album(self) -> None:
        if self.jm_selected_id:
            self._jm_enqueue(self.jm_selected_id, self.jm_selected_title or self.jm_selected_id, 0, self.jm_pdf_check.isChecked())

    def _jm_queue_photo(self) -> None:
        if self.jm_selected_id:
            self._jm_enqueue(self.jm_selected_id, self.jm_selected_title or self.jm_selected_id, self.jm_chapter.value(), self.jm_pdf_check.isChecked())

    def _jm_enqueue(self, album_id: str, title: str, chapter: int, pdf: bool) -> None:
        if self._jm_closing:
            return
        self.jm_queue.append({"id": f"{album_id}:{chapter}", "album_id": str(album_id), "title": title, "chapter": chapter, "pdf": pdf, "state": "排队中", "done": 0, "total": 0, "unit": "图片", "output": ""})
        self._jm_refresh_queue()
        self._jm_start_next()

    def _jm_start_next(self) -> None:
        if self._jm_closing or self.jm_queue_worker is not None:
            return
        task = next((item for item in self.jm_queue if item["state"] == "排队中"), None)
        if task is None:
            return
        task["state"] = "下载中"
        self._jm_refresh_queue()
        try:
            service = self._jm_service()
        except (OSError, ValueError) as exc:
            self._jm_task_failed(task, str(exc))
            QTimer.singleShot(0, self._jm_start_next)
            return

        def run() -> Any:
            service.cancelled = worker.isInterruptionRequested
            progress = worker.progress.emit
            if task["chapter"]:
                photo_id, _name, _total = service.chapter_id(task["album_id"], task["chapter"])
                result = service.download_photo(photo_id, progress)
            else:
                result = service.download_album(task["album_id"], progress)
            output = result.directory
            if task["pdf"]:
                output = service.pack_pdf(result.directory, f"{task['album_id']}_{task['chapter'] or '全部'}")
            return result, output

        worker = JMWorker(run)
        self.jm_queue_worker = worker
        worker.progress.connect(lambda done, total, unit: self._jm_progress(task, done, total, unit))
        self._jm_start_worker(worker, lambda value: self._jm_task_done(task, value), lambda message: self._jm_task_failed(task, message))

    def _jm_progress(self, task: dict[str, Any], done: int, total: int, unit: str) -> None:
        if self._jm_closing:
            return
        task.update(done=done, total=total, unit=unit)
        self._jm_refresh_queue()

    def _jm_task_done(self, task: dict[str, Any], value: Any) -> None:
        result, output = value
        task.update(state="已完成", done=result.image_count, total=result.image_count, output=str(output), unit="图片")
        # A re-download replaces the record for the same output file.
        record = {key: task[key] for key in ("album_id", "title", "chapter", "total")}
        record["output"] = self._jm_local_path(str(output)).relative_to(self._jm_download_root()).as_posix()
        record["directory"] = self._jm_local_path(str(result.directory)).relative_to(self._jm_download_root()).as_posix()
        self.jm_completed = [item for item in self.jm_completed if item["output"] != record["output"]]
        self.jm_completed.insert(0, record)
        self.jm_queue = [item for item in self.jm_queue if item is not task]
        self._jm_save_completed()
        self.jm_status.setText(f"已完成：{task['title']}，可在完成队列中打开。")
        self._jm_refresh_queue()
        self._jm_refresh_completed()

    def _jm_task_failed(self, task: dict[str, Any], message: str) -> None:
        task.update(state="失败", output=message)
        self.jm_status.setText(message)
        self._jm_refresh_queue()

    def _jm_refresh_queue(self) -> None:
        if not hasattr(self, "jm_queue_list"):
            return
        self.jm_queue_list.clear()
        self.jm_queue_tabs.setTabText(0, f"下载队列 ({len(self.jm_queue)})")
        for task in self.jm_queue:
            row = QWidget()
            line = QVBoxLayout(row)
            line.setContentsMargins(12, 8, 12, 8)
            line.setSpacing(4)
            chapter_label = "整本" if not task["chapter"] else f"第 {task['chapter']} 章"
            label = MarqueeLabel(f"{task['title']} · {chapter_label} · {task['state']}")
            line.addWidget(label)
            bar = QProgressBar()
            total = task.get("total", 0)
            bar.setRange(0, total or (0 if task["state"] == "下载中" else 1))
            bar.setValue(min(task.get("done", 0), total or 1))
            bar.setFixedHeight(18)
            line.addWidget(bar)
            line.addWidget(self._jm_hint(task.get("output") or f"{task.get('done', 0)} / {total or '—'} 张图片"))
            self._jm_add_row(self.jm_queue_list, row, 96)
        if not self.jm_queue:
            self.jm_queue_list.addItem("暂无下载任务，从搜索结果或详情中加入下载。")

    def _jm_download_root(self) -> Path:
        return (self._jm_store_root() / "jm_downloads").resolve()

    def _jm_local_path(self, value: str) -> Path:
        root = self._jm_download_root()
        path = (root / value).resolve()
        if not value or path == root or not path.is_relative_to(root):
            raise ValueError("文件路径不在 JM 下载目录内。")
        return path

    def _jm_load_completed(self) -> None:
        saved = self.store.read_json("jm_download_history", None)
        self.jm_completed = []
        seen: set[str] = set()
        for item in saved if isinstance(saved, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                path = self._jm_local_path(str(item.get("output", "")))
                relative = path.relative_to(self._jm_download_root()).as_posix()
                chapter, total = max(0, int(item.get("chapter", 0))), max(0, int(item.get("total", 0)))
                directory = (self._jm_local_path(str(item["directory"])).relative_to(self._jm_download_root()).as_posix()
                             if item.get("directory") else "")
            except (OSError, ValueError, TypeError):
                continue
            if relative in seen:
                continue
            seen.add(relative)
            self.jm_completed.append({
                "album_id": str(item.get("album_id", "")), "title": str(item.get("title") or path.name),
                "chapter": chapter, "total": total, "output": relative, "directory": directory,
            })
        # Older versions did not save completed tasks. Recover their local PDFs
        # and image directories once, without requiring another download.
        root = self._jm_download_root()
        if saved is None and root.is_dir():
            try:
                candidates = [path for path in root.rglob("*.pdf") if path.is_file()]
                candidates += [path for path in root.iterdir() if path.is_dir()
                               and any(image.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
                                       for image in path.rglob("*") if image.is_file())]
                for path in sorted(candidates):
                    try:
                        path = self._jm_local_path(str(path))
                    except (OSError, ValueError):
                        continue
                    self.jm_completed.append({
                        "album_id": path.stem.split("_")[0] if path.is_file() else path.name,
                        "title": f"本地{'PDF' if path.is_file() else '图片'} · {path.stem}",
                        "chapter": 0, "total": 0, "output": path.relative_to(root).as_posix(),
                    })
            except OSError as exc:
                self.jm_status.setText(f"读取已有下载文件失败：{exc}")
        self._jm_save_completed()
        self._jm_refresh_queue()
        self._jm_refresh_completed()

    def _jm_save_completed(self) -> None:
        self.store.write_json("jm_download_history", self.jm_completed)

    def _jm_refresh_completed(self) -> None:
        self.jm_completed_list.clear()
        self.jm_queue_tabs.setTabText(1, f"完成队列 ({len(self.jm_completed)})")
        for record in self.jm_completed:
            row = QWidget()
            layout = QVBoxLayout(row)
            layout.setContentsMargins(12, 8, 12, 8)
            layout.setSpacing(4)
            layout.addWidget(MarqueeLabel(record["title"]))
            path = self._jm_local_path(record["output"])
            layout.addWidget(self._jm_hint(record["output"] if path.exists() else f"文件已移动或删除 · {record['output']}"))
            actions = QHBoxLayout()
            chapter = f"第 {record['chapter']} 章" if record["chapter"] else "整本"
            actions.addWidget(self._jm_hint(f"{chapter} · {record['total']} 张图片" if record["total"] else "已有本地文件"), 1)
            folder = self._jm_button("打开文件夹", 104)
            folder.clicked.connect(lambda _=False, value=record: self._jm_open_completed(value, folder=True))
            actions.addWidget(folder)
            open_button = self._jm_button("打开", 60, True)
            open_button.setToolTip("使用默认程序打开 PDF，图片下载则打开图片文件夹")
            open_button.clicked.connect(lambda _=False, value=record: self._jm_open_completed(value))
            actions.addWidget(open_button)
            delete = self._jm_button("删除", 60)
            delete.setToolTip("删除对应 PDF 文件或图片文件夹")
            delete.clicked.connect(lambda _=False, value=record: self._jm_delete_completed(value))
            actions.addWidget(delete)
            layout.addLayout(actions)
            self._jm_add_row(self.jm_completed_list, row, 112)
        if not self.jm_completed:
            self.jm_completed_list.addItem("暂无已完成的下载，下载完成后会自动显示在这里。")

    def _jm_open_download_root(self) -> None:
        try:
            root = self._jm_download_root()
            root.mkdir(parents=True, exist_ok=True)
            self._jm_open_path(root)
        except OSError as exc:
            self.jm_status.setText(f"无法打开下载目录：{exc}")

    def _jm_open_path(self, path: Path) -> None:
        if not path.exists():
            self.jm_status.setText("文件已移动或删除，无法打开；可删除失效的完成记录。")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.jm_status.setText("无法打开文件，请检查系统默认打开方式。")
        else:
            self.jm_status.setText(f"已打开：{path.name}")

    def _jm_open_completed(self, record: dict[str, Any], folder: bool = False) -> None:
        try:
            path = self._jm_local_path(record["output"])
            if folder:
                directory = self._jm_local_path(record["directory"]) if record.get("directory") else None
                path = directory if directory is not None and directory.is_dir() else (path if path.is_dir() else path.parent)
            self._jm_open_path(path)
        except (OSError, ValueError) as exc:
            self.jm_status.setText(f"无法打开：{exc}")

    def _jm_delete_completed(self, record: dict[str, Any]) -> None:
        # Chapters and full-album downloads can share image folders. Do not
        # delete a file while this album is being downloaded or packed.
        if any(task["album_id"] == record["album_id"] and task["state"] in {"排队中", "下载中"}
               for task in self.jm_queue):
            self.jm_status.setText("这本漫画仍有下载任务，请等待任务结束后再删除。")
            return
        try:
            path = self._jm_local_path(record["output"])
            if path.is_dir():
                description = "将删除此图片文件夹及其中全部文件，无法撤销。"
            elif path.exists():
                description = "将删除此 PDF 文件，无法撤销。原始图片会保留。"
            else:
                description = "文件已不存在，将移除此完成记录。"
            answer = QMessageBox.question(
                self, "删除下载文件", f"{record['title']}\n\n{description}\n{path}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            # Revalidate after the dialog, immediately before touching files.
            JMComicService.remove_path(path, self._jm_download_root())
            self.jm_completed = [item for item in self.jm_completed
                                 if not (self._jm_local_path(item["output"]) == path
                                         or self._jm_local_path(item["output"]).is_relative_to(path))]
            self._jm_save_completed()
            self._jm_refresh_completed()
            self.jm_status.setText("下载文件及对应完成记录已删除。")
        except (OSError, ValueError) as exc:
            self.jm_status.setText(f"删除失败：{exc}")

    def _jm_load_favorites(self) -> None:
        saved = self.store.read_json("jm_favorites", [])
        self.jm_favorite_items = []
        seen: set[str] = set()
        for data in saved if isinstance(saved, list) else []:
            if not isinstance(data, dict):
                continue
            album_id = str(data.get("id") or "").strip()
            if not album_id or album_id in seen:
                continue
            seen.add(album_id)
            tags = data.get("tags", [])
            self.jm_favorite_items.append({
                "id": album_id, "title": str(data.get("title") or ""),
                "tags": [str(tag) for tag in tags] if isinstance(tags, list) else [],
            })
        self._jm_refresh_favorites()

    def _jm_is_favorite(self, album_id: str) -> bool:
        return any(str(item.get("id")) == str(album_id) for item in self.jm_favorite_items if isinstance(item, dict))

    def _jm_toggle_favorite(self, data: dict[str, Any], button: QPushButton | None = None) -> None:
        if self._jm_is_favorite(data["id"]):
            self.jm_favorite_items = [item for item in self.jm_favorite_items if str(item.get("id")) != str(data["id"])]
            if button:
                button.setText("收藏")
        else:
            self.jm_favorite_items.append({"id": data["id"], "title": data.get("title", ""), "tags": data.get("tags", [])})
            if button:
                button.setText("取消收藏")
        self.store.write_json("jm_favorites", self.jm_favorite_items)
        self._jm_refresh_favorites()

    def _jm_refresh_favorites(self) -> None:
        if not hasattr(self, "jm_favorites"):
            return
        self.jm_favorites.clear()
        self.jm_favorites.setFixedHeight(150 if len(self.jm_favorite_items) > 1 else 80)
        for button in self.jm_results.findChildren(QPushButton):
            album_id = button.property("jmFavoriteId")
            if album_id is not None:
                button.setText("取消收藏" if self._jm_is_favorite(album_id) else "收藏")
        for data in self.jm_favorite_items:
            if not isinstance(data, dict):
                continue
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(12, 8, 12, 8)
            line.setSpacing(8)
            line.addWidget(MarqueeLabel(f"{data.get('id', '')}  {data.get('title', '')}"), 1)
            detail = self._jm_button("详情", 60)
            detail.clicked.connect(lambda _=False, album_id=data.get("id", ""): self._jm_show_detail(str(album_id)))
            line.addWidget(detail)
            download = self._jm_button("加入队列", 88, True)
            download.clicked.connect(lambda _=False, value=data: self._jm_enqueue(str(value.get("id", "")), str(value.get("title", "")), 0, self.jm_pdf_check.isChecked()))
            line.addWidget(download)
            remove = self._jm_button("移除", 60)
            remove.clicked.connect(lambda _=False, value=data: self._jm_toggle_favorite(value))
            line.addWidget(remove)
            self._jm_add_row(self.jm_favorites, row, 64)
        if not self.jm_favorite_items:
            self.jm_favorites.addItem("暂无收藏，可在搜索结果中收藏漫画。")

    def jm_shutdown(self) -> bool:
        self._jm_closing = True
        for task in self.jm_queue:
            if task["state"] in {"排队中", "下载中"}:
                task["state"] = "已取消"
        for worker in self._jm_workers:
            worker.requestInterruption()
        if self._jm_workers:
            self.jm_status.setText("正在停止后台任务，完成后退出…")
            return False
        return True

    def jm_wait_for_shutdown(self) -> None:
        # Fallback for OS/application shutdown that bypasses quit_app(). Normal
        # exits wait asynchronously, keeping the UI responsive until finished.
        self.jm_shutdown()
        for worker in tuple(self._jm_workers):
            worker.wait()
