"""Image-only grid with file drops in and file drags out."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, QMimeData, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QIcon, QMovie, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QStyledItemDelegate


DUPLICATE_ROLE = Qt.ItemDataRole.UserRole + 1


class EmojiItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.data(DUPLICATE_ROLE):
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#e59d36"), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(option.rect.adjusted(3, 3, -3, -3), 10, 10)
            painter.restore()


class EmojiGrid(QListWidget):
    filesDropped = pyqtSignal(list)
    imageDropped = pyqtSignal(object)
    reordered = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._movies: dict[int, QMovie] = {}
        self._reordering = False
        self.setItemDelegate(EmojiItemDelegate(self))
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

    def highlight_duplicates(self, record_ids: set[str]) -> None:
        first = None
        for row in range(self.count()):
            item = self.item(row)
            duplicate = item.data(Qt.ItemDataRole.UserRole)["id"] in record_ids
            item.setData(DUPLICATE_ROLE, duplicate)
            item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, "重复图片，已跳过添加" if duplicate else "")
            if duplicate and first is None:
                first = item
        if first is not None:
            self.scrollToItem(first)
        self.viewport().update()

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
        try:
            image_data = Path(path).read_bytes()
        except OSError:
            return
        movie = QMovie(parent=self)
        # Detect animation from the file bytes instead of trusting the filename extension.
        # Some chat clients save animated content with a .jpg suffix.
        source = QBuffer(movie)
        source.setData(image_data)
        source.open(QIODevice.OpenModeFlag.ReadOnly)
        movie.setDevice(source)
        if not movie.isValid() or movie.frameCount() <= 1:
            movie.setDevice(None)
            source.close()
            movie.deleteLater()
            return
        # Remember animation based on content, even for animated files with a .jpg suffix.
        record["animated"] = True
        item.setData(Qt.ItemDataRole.UserRole, record)
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

    def set_reordering(self, enabled: bool) -> None:
        self._reordering = bool(enabled)
        self.setMovement(QListWidget.Movement.Snap if self._reordering else QListWidget.Movement.Static)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove if self._reordering else QListWidget.DragDropMode.DragOnly)
        # Qt changes this when the drag mode changes; external file drops stay enabled.
        self.setAcceptDrops(True)

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
        if event.mimeData().hasUrls() or event.mimeData().hasImage() or (self._reordering and event.source() is self):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage() or (self._reordering and event.source() is self):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self._reordering and not event.mimeData().hasUrls() and not event.mimeData().hasImage():
            super().dropEvent(event)
            self.reordered.emit([self.item(row).data(Qt.ItemDataRole.UserRole).get("id")
                                 for row in range(self.count())])
            event.acceptProposedAction()
            return
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
        if self._reordering:
            super().startDrag(Qt.DropAction.MoveAction)
            return
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
        animated = any(bool((item.data(Qt.ItemDataRole.UserRole) or {}).get("animated"))
                       for item in items)
        if len(paths) == 1 and not animated:
            mime.setImageData(QPixmap(str(paths[0])).toImage())
        drag = QDrag(self)
        drag.setMimeData(mime)
        pixmap = self.selectedItems()[0].icon().pixmap(72, 72)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.CopyAction)
