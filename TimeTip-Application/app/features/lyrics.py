"""Lyrics learning feature: import songs, browse lyric cards, and inspect words."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Iterable

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QStackedWidget,
)

from app.presentation.module_runtime import FeatureModule
from app.presentation.widgets import Card


SCHEMA_VERSION = 1
STORAGE_KEY = "lyrics_songs"

TEMPLATE = {
    "version": 1,
    "song": {
        "id": "yoru-no-uta",
        "title": "夜の歌",
        "artist": "歌手名",
        "cover": "",
    },
    "lyrics": [
        {"id": "line-001", "text": "ここに第一行の歌词"},
        {"id": "line-002", "text": "ここに第二行の歌词"},
    ],
    "vocab": [
        {
            "id": "word-001",
            "surface": "歌词",
            "reading": "かし",
            "meaning": "歌词；歌曲中的文字",
            "note": "可选的补充说明",
        }
    ],
}


def _required_text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串。")
    return value.strip()


def _optional_text(value, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label}必须是字符串。")
    return value.strip()


def validate_song_payload(payload: object) -> dict:
    """Validate the public JSON format and return the stored song record."""
    if not isinstance(payload, dict):
        raise ValueError("歌词文件必须是 JSON 对象。")
    if type(payload.get("version")) is not int or payload["version"] != SCHEMA_VERSION:
        raise ValueError(f"只支持 version 为 {SCHEMA_VERSION} 的歌词文件。")

    raw_song = payload.get("song")
    if not isinstance(raw_song, dict):
        raise ValueError("song 必须是对象。")
    song_id = _required_text(raw_song.get("id"), "song.id")
    title = _required_text(raw_song.get("title"), "song.title")
    artist = _optional_text(raw_song.get("artist", ""), "song.artist")
    cover = _optional_text(raw_song.get("cover", ""), "song.cover")

    raw_lyrics = payload.get("lyrics")
    if not isinstance(raw_lyrics, list) or not raw_lyrics:
        raise ValueError("lyrics 必须是至少包含一行的数组。")
    lyrics = []
    lyric_ids = set()
    for index, line in enumerate(raw_lyrics, 1):
        if not isinstance(line, dict):
            raise ValueError(f"lyrics[{index}] 必须是对象。")
        line_id = _required_text(line.get("id"), f"lyrics[{index}].id")
        text = _required_text(line.get("text"), f"lyrics[{index}].text")
        if line_id in lyric_ids:
            raise ValueError(f"歌词行 ID 重复：{line_id}")
        lyric_ids.add(line_id)
        lyrics.append({"id": line_id, "text": text})

    raw_vocab = payload.get("vocab")
    if not isinstance(raw_vocab, list):
        raise ValueError("vocab 必须是数组。")
    vocab = []
    vocab_ids = set()
    surfaces = set()
    for index, word in enumerate(raw_vocab, 1):
        if not isinstance(word, dict):
            raise ValueError(f"vocab[{index}] 必须是对象。")
        word_id = _required_text(word.get("id"), f"vocab[{index}].id")
        surface = _required_text(word.get("surface"), f"vocab[{index}].surface")
        reading = _optional_text(word.get("reading", ""), f"vocab[{index}].reading")
        meaning = _required_text(word.get("meaning"), f"vocab[{index}].meaning")
        note = _optional_text(word.get("note", ""), f"vocab[{index}].note")
        if word_id in vocab_ids:
            raise ValueError(f"生词 ID 重复：{word_id}")
        if surface in surfaces:
            raise ValueError(f"生词原文重复：{surface}")
        vocab_ids.add(word_id)
        surfaces.add(surface)
        vocab.append({
            "id": word_id,
            "surface": surface,
            "reading": reading,
            "meaning": meaning,
            "note": note,
        })

    return {
        "id": song_id,
        "title": title,
        "artist": artist,
        "cover": cover,
        "lyrics": lyrics,
        "vocab": vocab,
    }


def _normalize_stored_song(record: object) -> dict | None:
    """Keep malformed old records out of the page without breaking startup."""
    if not isinstance(record, dict):
        return None
    payload = {
        "version": SCHEMA_VERSION,
        "song": {
            "id": record.get("id"),
            "title": record.get("title"),
            "artist": record.get("artist", ""),
            "cover": record.get("cover", ""),
        },
        "lyrics": record.get("lyrics"),
        "vocab": record.get("vocab"),
    }
    try:
        return validate_song_payload(payload)
    except ValueError:
        return None


def highlighted_lyrics_html(
    lyrics: Iterable[dict], vocab: Iterable[dict]
) -> str:
    """Render exact surface matches as safe, clickable HTML links."""
    words = [
        word for word in vocab
        if isinstance(word, dict) and isinstance(word.get("surface"), str)
        and word.get("surface")
    ]
    words.sort(key=lambda word: len(word["surface"]), reverse=True)
    paragraphs = []
    for line in lyrics:
        text = str(line.get("text", ""))
        matches = []
        for word in words:
            surface = word["surface"]
            offset = 0
            while True:
                start = text.find(surface, offset)
                if start < 0:
                    break
                matches.append((start, len(surface), word["id"]))
                offset = start + len(surface)
        # Longest word wins when two entries begin at the same character.
        matches.sort(key=lambda item: (item[0], -item[1]))
        selected = []
        end = 0
        for start, length, word_id in matches:
            if start < end:
                continue
            selected.append((start, length, word_id))
            end = start + length

        chunks = []
        cursor = 0
        for start, length, word_id in selected:
            chunks.append(html.escape(text[cursor:start]))
            surface = html.escape(text[start:start + length])
            chunks.append(
                f'<a href="vocab:{html.escape(str(word_id), quote=True)}" '
                'style="color:#5E5CE6; font-weight:700; '
                'text-decoration:none; background:#ECE9FF; '
                'border-radius:4px; padding:1px 3px;">'
                f"{surface}</a>"
            )
            cursor = start + length
        chunks.append(html.escape(text[cursor:]))
        paragraphs.append(
            f'<p style="margin:0 0 12px 0; line-height:1.8;">{"".join(chunks)}</p>'
        )
    return "".join(paragraphs)


class LyricsSongCard(QFrame):
    opened = pyqtSignal(str)

    def __init__(self, song: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.song_id = song["id"]
        self.setObjectName("lyricsCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(6)

        title = QLabel(song["title"])
        title.setObjectName("lyricsCardTitle")
        title.setWordWrap(False)
        title.setToolTip(song["title"])
        layout.addWidget(title)

        artist = song.get("artist") or "未知歌手"
        artist_label = QLabel(artist)
        artist_label.setObjectName("lyricsCardMeta")
        layout.addWidget(artist_label)

        line_count = len(song.get("lyrics", []))
        word_count = len(song.get("vocab", []))
        meta = QLabel(f"{line_count} 行歌词 · {word_count} 个生词")
        meta.setObjectName("lyricsCardMeta")
        layout.addWidget(meta)

        hint = QLabel("双击打开歌词")
        hint.setObjectName("lyricsCardHint")
        layout.addWidget(hint)
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.opened.emit(self.song_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class LyricsModule(FeatureModule):
    def __init__(self, context):
        super().__init__(context)
        self.page = None
        self.songs: list[dict] = []
        self.current_song: dict | None = None

    def create_page(self):
        self.page = QWidget()
        root = QVBoxLayout(self.page)
        root.setContentsMargins(8, 14, 8, 8)
        root.setSpacing(14)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self._build_library_page()
        self._build_detail_page()
        self.stack.setCurrentWidget(self.library_page)
        return self.page

    def _build_library_page(self):
        self.library_page = QWidget()
        layout = QVBoxLayout(self.library_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.addWidget(QLabel("歌词学习", objectName="pageTitle"))
        subtitle = QLabel(
            "导入歌曲歌词和生词，双击卡片打开歌词；点击高亮词查看含义。"
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)

        self.import_button = QPushButton("导入歌曲 JSON", objectName="primaryButton")
        self.import_button.clicked.connect(self.import_song)
        header.addWidget(self.import_button)
        self.template_button = QPushButton("查看 JSON 模板", objectName="secondaryButton")
        self.template_button.clicked.connect(self.show_template)
        header.addWidget(self.template_button)
        layout.addLayout(header)

        self.library_status = QLabel("")
        self.library_status.setObjectName("cardHint")
        self.library_status.setWordWrap(True)
        layout.addWidget(self.library_status)

        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        cards_host = QWidget()
        self.cards_layout = QVBoxLayout(cards_host)
        self.cards_layout.setContentsMargins(0, 0, 4, 0)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch()
        self.cards_scroll.setWidget(cards_host)
        layout.addWidget(self.cards_scroll, 1)
        self.cards_host = cards_host
        self.stack.addWidget(self.library_page)

    def _build_detail_page(self):
        self.detail_page = QWidget()
        layout = QVBoxLayout(self.detail_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        self.back_button = QPushButton("← 返回歌曲列表", objectName="secondaryButton")
        self.back_button.clicked.connect(self._show_library)
        top.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.detail_title = QLabel("")
        self.detail_title.setObjectName("pageTitle")
        top.addWidget(self.detail_title, 1)
        layout.addLayout(top)

        self.detail_artist = QLabel("")
        self.detail_artist.setObjectName("pageSubtitle")
        layout.addWidget(self.detail_artist)

        lyrics_card = Card("lyricsTextCard")
        lyrics_layout = QVBoxLayout(lyrics_card)
        lyrics_layout.setContentsMargins(20, 18, 20, 18)
        self.lyrics_browser = QTextBrowser()
        self.lyrics_browser.setOpenLinks(False)
        self.lyrics_browser.setOpenExternalLinks(False)
        self.lyrics_browser.setReadOnly(True)
        self.lyrics_browser.anchorClicked.connect(self._show_word)
        lyrics_layout.addWidget(self.lyrics_browser)
        layout.addWidget(lyrics_card, 1)

        self.word_panel = Card("lyricsWordPanel")
        word_layout = QVBoxLayout(self.word_panel)
        word_layout.setContentsMargins(18, 14, 18, 14)
        self.word_title = QLabel("点击高亮词查看详情")
        self.word_title.setObjectName("lyricsWordTitle")
        word_layout.addWidget(self.word_title)
        self.word_reading = QLabel("")
        self.word_reading.setObjectName("lyricsWordReading")
        word_layout.addWidget(self.word_reading)
        self.word_meaning = QLabel("")
        self.word_meaning.setWordWrap(True)
        word_layout.addWidget(self.word_meaning)
        self.word_note = QLabel("")
        self.word_note.setObjectName("cardHint")
        self.word_note.setWordWrap(True)
        word_layout.addWidget(self.word_note)
        layout.addWidget(self.word_panel)
        self.stack.addWidget(self.detail_page)

    def start(self):
        self.context.subscribe("data.reloaded", lambda _payload=None: self._load_songs())
        self._load_songs()

    def _load_songs(self):
        raw = self.context.store.read_json(STORAGE_KEY, [])
        self.songs = [
            song for item in raw if (song := _normalize_stored_song(item)) is not None
        ] if isinstance(raw, list) else []
        if self.page is not None:
            self._render_cards()
            if self.current_song is not None:
                refreshed = self._song_by_id(self.current_song["id"])
                if refreshed is None:
                    self._show_library()
                else:
                    self._open_song(refreshed["id"])

    def _save_songs(self):
        self.context.store.write_json(STORAGE_KEY, self.songs)

    def _render_cards(self):
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self.songs:
            empty = QLabel("还没有歌曲。点击“导入歌曲 JSON”开始学习。")
            empty.setObjectName("cardHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(180)
            self.cards_layout.insertWidget(0, empty)
            self.library_status.setText("支持 version 1 的固定 JSON 格式。")
            return
        self.library_status.setText(f"已保存 {len(self.songs)} 首歌曲。双击卡片打开歌词。")
        for song in self.songs:
            card = LyricsSongCard(song)
            card.opened.connect(self._open_song)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

    def _song_by_id(self, song_id: str) -> dict | None:
        return next((song for song in self.songs if song["id"] == song_id), None)

    def _open_song(self, song_id: str):
        song = self._song_by_id(song_id)
        if song is None:
            return
        self.current_song = song
        self.detail_title.setText(song["title"])
        self.detail_artist.setText(song.get("artist") or "未知歌手")
        self.lyrics_browser.setHtml(
            '<div style="font-size:16px;">'
            + highlighted_lyrics_html(song["lyrics"], song["vocab"])
            + "</div>"
        )
        self.word_title.setText("点击高亮词查看详情")
        self.word_reading.setText("")
        self.word_meaning.setText("")
        self.word_note.setText("")
        self.stack.setCurrentWidget(self.detail_page)

    def _show_library(self):
        self.current_song = None
        self.stack.setCurrentWidget(self.library_page)

    def _show_word(self, url: QUrl):
        value = url.toString()
        if not value.startswith("vocab:") or self.current_song is None:
            return
        word_id = value.split(":", 1)[1]
        word = next(
            (item for item in self.current_song["vocab"] if item["id"] == word_id),
            None,
        )
        if word is None:
            return
        self.word_title.setText(word["surface"])
        self.word_reading.setText(f"读音：{word['reading']}" if word["reading"] else "读音：未提供")
        self.word_meaning.setText(f"含义：{word['meaning']}")
        self.word_note.setText(f"备注：{word['note']}" if word["note"] else "")

    def import_song(self):
        path, _ = QFileDialog.getOpenFileName(
            self.page,
            "导入歌曲歌词 JSON",
            "",
            "歌词 JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            song = validate_song_payload(payload)
            index = next(
                (index for index, item in enumerate(self.songs)
                 if item["id"] == song["id"]),
                None,
            )
            if index is None:
                self.songs.append(song)
                message = f"已导入《{song['title']}》。"
            else:
                self.songs[index] = song
                message = f"已更新《{song['title']}》。"
            self._save_songs()
            self._render_cards()
            self.library_status.setText(message)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            QMessageBox.warning(self.page, "导入失败", str(error))

    def show_template(self):
        dialog = QDialog(self.page)
        dialog.setWindowTitle("歌词学习 JSON 模板")
        dialog.resize(680, 620)
        layout = QVBoxLayout(dialog)
        hint = QLabel(
            "复制下面的模板，填写歌曲信息、逐行歌词和生词后保存为 .json 文件，"
            "再点击“导入歌曲 JSON”。"
        )
        hint.setObjectName("cardHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        editor = QTextEdit()
        editor.setPlainText(json.dumps(TEMPLATE, ensure_ascii=False, indent=2))
        editor.setReadOnly(True)
        layout.addWidget(editor, 1)
        actions = QHBoxLayout()
        copy_button = QPushButton("复制模板", objectName="secondaryButton")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(editor.toPlainText())
        )
        actions.addWidget(copy_button)
        actions.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        close.accepted.connect(dialog.accept)
        actions.addWidget(close)
        layout.addLayout(actions)
        dialog.exec()
