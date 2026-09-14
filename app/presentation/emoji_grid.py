"""Image-only grid with file drops in and file drags out."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, QMimeData, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDrag, QIcon, QMovie, QPixmap
from PyQt6.QtWidgets import QListWidget, QListWidgetItem


class EmojiGrid(QListWidget):
    filesDropped = pyqtSignal(list)
    imageDropped = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._movies: dict[int, QMovie] = {}
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setIconSize(QSize(116, 116))
        self.setGridSize(QSize(136, 136))
        self.setSpacing(8)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        # DragOnly keeps internal items from being rearranged; re-enable external file drops.
        self.setAcceptDrops(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setMinimumHeight(260)
        self.setAccessibleName("表情包图片网格，可拖入图片或拖出到聊天窗口")

    def add_image(self, path: str, record: dict) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        item = QListWidgetItem(QIcon(pixmap), "")
        item.setData(Qt.ItemDataRole.UserRole, record)
        item.setSizeHint(QSize(136, 136))
        # The image itself is the complete visual content; no filename or tooltip is shown.
        item.setToolTip("")
        self.addItem(item)
        if Path(path).suffix.lower() == ".gif":
            try:
                gif_data = Path(path).read_bytes()
            except OSError:
                return
            movie = QMovie(parent=self)
            # Keep compressed GIF bytes only; no decoded-frame cache or persistent file lock.
            source = QBuffer(movie)
            source.setData(gif_data)
            source.open(QIODevice.OpenModeFlag.ReadOnly)
            movie.setDevice(source)
            if not movie.isValid():
                movie.setFileName("")
                movie.deleteLater()
                return
            movie.setScaledSize(pixmap.size().scaled(self.iconSize(), Qt.AspectRatioMode.KeepAspectRatio))
            movie.frameChanged.connect(lambda frame, target=item, player=movie: target.setIcon(QIcon(player.currentPixmap())))
            self._movies[id(item)] = movie
            movie.jumpToFrame(0)
            if self.isVisible():
                movie.start()

    def _release_movie(self, item_key: int) -> None:
        movie = self._movies.pop(item_key, None)
        if movie is not None:
            movie.frameChanged.disconnect()
            movie.stop()
            source = movie.device()
            movie.setDevice(None)
            if source is not None:
                source.close()
            movie.deleteLater()

    def clear(self) -> None:
        for item_key in list(self._movies):
            self._release_movie(item_key)
        super().clear()

    def clear_images(self) -> None:
        self.clear()

    def takeItem(self, row):
        item = self.item(row)
        if item is not None:
            self._release_movie(id(item))
        return super().takeItem(row)

    def showEvent(self, event):
        super().showEvent(event)
        for movie in self._movies.values():
            if movie.state() == QMovie.MovieState.Paused:
                movie.setPaused(False)
            elif movie.state() == QMovie.MovieState.NotRunning:
                movie.start()

    def hideEvent(self, event):
        for movie in self._movies.values():
            if movie.state() == QMovie.MovieState.Running:
                movie.setPaused(True)
        super().hideEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
        elif event.mimeData().hasImage():
            self.imageDropped.emit(event.mimeData().imageData())
            event.acceptProposedAction()
        else:
            event.ignore()

    def startDrag(self, supported_actions):
        items = self.selectedItems()
        paths = []
        for item in items:
            record = item.data(Qt.ItemDataRole.UserRole) or {}
            path = record.get("absolute_path")
            if path and Path(path).is_file():
                paths.append(Path(path).resolve())
        if not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        # A static image MIME fallback would flatten GIFs in apps that prefer it to file URLs.
        # For GIFs and multi-selection, send the original files only.
        if len(paths) == 1 and paths[0].suffix.lower() != ".gif":
            mime.setImageData(QPixmap(str(paths[0])).toImage())
        drag = QDrag(self)
        drag.setMimeData(mime)
        pixmap = self.selectedItems()[0].icon().pixmap(72, 72)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.CopyAction)
