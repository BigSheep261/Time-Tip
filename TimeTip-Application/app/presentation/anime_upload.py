"""Modal manual video import for an anime's configured folder."""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout,
)

from app.infrastructure.anime_files import VIDEO_EXTENSIONS, move_anime_video


class VideoDropArea(QFrame):
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("animeUploadDropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(116)
        layout = QVBoxLayout(self)
        label = QLabel("将视频文件拖到这里\n或点击下方“选择视频”，支持一次添加多个文件")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(label)

    @staticmethod
    def _local_videos(mime):
        return [url.toLocalFile() for url in mime.urls()
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in VIDEO_EXTENSIONS]

    def dragEnterEvent(self, event):
        if self.isEnabled() and self._local_videos(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self._local_videos(event.mimeData())
        if self.isEnabled() and paths:
            self.filesDropped.emit(paths)
            # Queueing files does not move them; the user starts the move below.
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()


class VideoMoveWorker(QThread):
    fileFinished = pyqtSignal(str, bool, str)

    def __init__(self, paths, folder, parent=None):
        super().__init__(parent)
        self.paths = list(paths)
        self.folder = folder

    def run(self):
        for path in self.paths:
            try:
                move_anime_video(Path(path), self.folder)
            except Exception as error:
                self.fileFinished.emit(path, False, str(error))
            else:
                self.fileFinished.emit(path, True, "已移动")


class AnimeUploadDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.folder = Path(item["folder"]).resolve()
        self.worker = None
        self._pending = {}
        self._known_paths = set()
        self._completed = self._succeeded = 0
        self.moved_count = 0
        self.setObjectName("animeDialog")
        self.setWindowTitle("手动上传视频")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(660, 580)
        self.setMinimumSize(540, 480)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(14)
        title = QLabel(item.get("title", "未命名番剧"), objectName="animeDialogTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        outer.addWidget(title)
        hint = QLabel("选择视频后点击“开始移动”，文件将从原位置移入下方目录。同名文件会跳过。", objectName="animeDialogHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("目标目录"))
        self.folder_path = QLineEdit(str(self.folder))
        self.folder_path.setReadOnly(True)
        self.folder_path.setToolTip(str(self.folder))
        folder_row.addWidget(self.folder_path, 1)
        self.open_button = QPushButton("打开目录", objectName="secondaryButton")
        self.open_button.clicked.connect(self.open_folder)
        folder_row.addWidget(self.open_button)
        outer.addLayout(folder_row)

        self.drop_area = VideoDropArea()
        self.drop_area.filesDropped.connect(self.add_files)
        outer.addWidget(self.drop_area)
        self.file_list = QListWidget(objectName="cleanList")
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.setMinimumHeight(100)
        outer.addWidget(self.file_list, 1)
        actions = QHBoxLayout()
        self.choose_button = QPushButton("选择视频", objectName="secondaryButton")
        self.choose_button.clicked.connect(self.choose_files)
        actions.addWidget(self.choose_button)
        self.remove_button = QPushButton("移除所选", objectName="secondaryButton")
        self.remove_button.clicked.connect(self.remove_selected)
        actions.addWidget(self.remove_button)
        actions.addStretch()
        self.move_button = QPushButton("开始移动", objectName="primaryButton")
        self.move_button.setEnabled(False)
        self.move_button.clicked.connect(self.start_move)
        actions.addWidget(self.move_button)
        outer.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.feedback = QLabel("尚未选择视频。", objectName="animeDialogHint")
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback.setWordWrap(True)
        outer.addWidget(self.feedback)
        close_row = QHBoxLayout()
        close_row.addStretch()
        self.close_button = QPushButton("关闭", objectName="secondaryButton")
        self.close_button.clicked.connect(self.reject)
        close_row.addWidget(self.close_button)
        outer.addLayout(close_row)

    @property
    def busy(self):
        return self.worker is not None

    def choose_files(self):
        patterns = " ".join(f"*{suffix}" for suffix in sorted(VIDEO_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要移动的视频", "", f"视频文件 ({patterns})")
        self.add_files(paths)

    def add_files(self, paths):
        if self.busy:
            return
        skipped = 0
        for raw in paths:
            path = Path(raw)
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                skipped += 1
                continue
            path = path.resolve()
            key = os.path.normcase(str(path))
            if key in self._known_paths or path.parent == self.folder:
                skipped += 1
                continue
            row = QListWidgetItem(f"待移动 · {path.name}")
            row.setData(Qt.ItemDataRole.UserRole, str(path))
            row.setToolTip(str(path))
            self.file_list.addItem(row)
            self._pending[str(path)] = row
            self._known_paths.add(key)
        self.move_button.setEnabled(bool(self._pending))
        text = f"待移动 {len(self._pending)} 个视频。"
        if skipped:
            text += f" 已忽略 {skipped} 个重复、无效或已在目标目录的文件。"
        self.feedback.setText(text)

    def remove_selected(self):
        if self.busy:
            return
        for row in self.file_list.selectedItems():
            path = row.data(Qt.ItemDataRole.UserRole)
            self._pending.pop(path, None)
            self._known_paths.discard(os.path.normcase(path))
            self.file_list.takeItem(self.file_list.row(row))
        self.move_button.setEnabled(bool(self._pending))
        self.feedback.setText(f"待移动 {len(self._pending)} 个视频。")

    def open_folder(self):
        if not self.folder.is_dir():
            self.feedback.setText("目标文件夹不存在，请在番剧编辑窗口中重新设置。")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder))):
            self.feedback.setText("无法打开目录，请检查文件夹是否可访问。")

    def start_move(self):
        if self.busy or not self._pending:
            return
        if not self.folder.is_dir():
            self.feedback.setText("目标文件夹不存在，请在番剧编辑窗口中重新设置。")
            return
        self._completed = self._succeeded = 0
        self.progress.setRange(0, len(self._pending))
        self.progress.setValue(0)
        self.progress.show()
        self.worker = VideoMoveWorker(self._pending, self.folder, self)
        self.worker.fileFinished.connect(self._file_finished)
        self.worker.finished.connect(self._move_finished)
        self._set_busy(True)
        self.feedback.setText("正在移动视频，请等待完成后关闭窗口。")
        self.worker.start()

    def _set_busy(self, busy):
        for widget in (self.drop_area, self.choose_button, self.remove_button, self.close_button):
            widget.setEnabled(not busy)
        self.move_button.setEnabled(not busy and bool(self._pending))

    def _file_finished(self, path, success, message):
        row = self._pending[path]
        row.setText(f"{'已移动' if success else '未移动'} · {Path(path).name}")
        row.setToolTip(f"{path}\n{message}")
        self._completed += 1
        if success:
            self._succeeded += 1
            self.moved_count += 1
            del self._pending[path]
        else:
            row.setText(f"未移动 · {Path(path).name}（{message}）")
        self.progress.setValue(self._completed)

    def _move_finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self._set_busy(False)
        failed = self._completed - self._succeeded
        self.feedback.setText(f"移动完成：成功 {self._succeeded} 个，未移动 {failed} 个。" +
                              (" 查看文件行中的原因，处理后可重试。" if failed else "可打开目录查看，或继续添加视频。"))

    def done(self, result):
        if self.busy:
            self.feedback.setText("正在移动视频，请等待完成后关闭窗口。")
            return
        super().done(result)

    def closeEvent(self, event):
        if self.busy:
            self.feedback.setText("正在移动视频，请等待完成后关闭窗口。")
            event.ignore()
        else:
            super().closeEvent(event)
