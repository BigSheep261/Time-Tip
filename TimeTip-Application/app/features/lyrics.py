"""Lyrics learning feature: import songs, browse lyric cards, and inspect words."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Iterable

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QShortcut, QTextCursor, QTextFormat
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
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
    QTabBar,
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
SPLITS_STORAGE_KEY = "lyrics_splits"

TEMPLATE = {
    "version": 1,
    "song": {
        "id": "yoru-no-uta",
        "title": "夜の歌",
        "artist": "歌手名",
        "cover": "",
        "language": "ja",
    },
    "lyrics": [
        {
            "id": "line-001",
            "romaji": "koko ni daiichi gyou no kashi",
            "text": "ここに第一行の歌詞",
            "translation": "这里填写第一行歌词的翻译",
        },
        {
            "id": "line-002",
            "romaji": "koko ni daini gyou no kashi",
            "text": "ここに第二行の歌詞",
            "translation": "这里填写第二行歌词的翻译",
        },
    ],
    "vocab": [
        {
            "id": "word-001",
            "surface": "歌詞",
            "reading": "かし",
            "meaning": "歌词；歌曲中的文字",
            "note": "可选的补充说明",
        }
    ],
}


ENGLISH_TEMPLATE = {
    "version": 1,
    "song": {
        "id": "morning-light",
        "title": "Morning Light",
        "artist": "歌手名",
        "cover": "",
        "language": "en",
    },
    "lyrics": [
        {
            "id": "line-001",
            "text": "Morning light comes through my window.",
            "translation": "晨光透过我的窗户。",
        },
        {
            "id": "line-002",
            "text": "I welcome a new day.",
            "translation": "我迎接新的一天。",
        },
    ],
    "vocab": [
        {
            "id": "word-001",
            "surface": "window",
            "reading": "/ˈwɪndəʊ/",
            "meaning": "窗户",
            "note": "可选的补充说明",
        }
    ],
}


LYRICS_HINT = "选中单词后可添加分割点；清除时先点按钮，再点歌词行。"


LANGUAGE_FILTERS = (("all", "全部"), ("ja", "日语"), ("en", "英语"), ("other", "其他"))


_LANGUAGE_ALIASES = {
    "zh": "zh", "cn": "zh", "chinese": "zh", "中文": "zh", "汉语": "zh",
    "ja": "ja", "jp": "ja", "japanese": "ja", "日本語": "ja", "日语": "ja", "日文": "ja",
    "en": "en", "英语": "en", "英文": "en", "english": "en",
    "ko": "ko", "kr": "ko", "韩语": "ko", "한국어": "ko", "korean": "ko",
}


def _language(value, label: str = "song.language") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串。")
    normalized_value = value.strip().lower()
    # Keep the format open to other languages alongside Japanese and English.
    return _LANGUAGE_ALIASES.get(normalized_value, normalized_value)


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
    # Old imports did not have a language field and are treated as Chinese.
    language = _language(raw_song.get("language", payload.get("language", "zh")))

    raw_lyrics = payload.get("lyrics")
    if not isinstance(raw_lyrics, list) or not raw_lyrics:
        raise ValueError("lyrics 必须是至少包含一行的数组。")
    lyrics = []
    lyric_ids = set()
    for index, line in enumerate(raw_lyrics, 1):
        if not isinstance(line, dict):
            raise ValueError(f"lyrics[{index}] 必须是对象。")
        line_id = _required_text(line.get("id"), f"lyrics[{index}].id")
        raw_text = line.get("text", line.get("original"))
        text = _required_text(raw_text, f"lyrics[{index}].text")
        line_language = _language(line.get("language", language), f"lyrics[{index}].language")
        if line_id in lyric_ids:
            raise ValueError(f"歌词行 ID 重复：{line_id}")
        lyric_ids.add(line_id)
        normalized_line = {"id": line_id}
        if "language" in line:
            normalized_line["language"] = line_language
        if line_language == "ja":
            romaji = line.get(
                "romaji",
                line.get("romanization", line.get("romanized", line.get("roman", ""))),
            )
            romaji = _required_text(romaji, f"lyrics[{index}].romaji")
            translation = _required_text(
                line.get("translation", ""), f"lyrics[{index}].translation"
            )
            normalized_line.update({"romaji": romaji, "text": text, "translation": translation})
        else:
            normalized_line["text"] = text
            if "translation" in line:
                normalized_line["translation"] = _optional_text(
                    line.get("translation"), f"lyrics[{index}].translation"
                )
        # Split points are a local learning preference. They are deliberately
        # ignored here so imported song JSON never owns this UI state.
        lyrics.append(normalized_line)

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
        "language": language,
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
            "language": record.get("language", "zh"),
        },
        "lyrics": record.get("lyrics"),
        "vocab": record.get("vocab"),
    }
    try:
        return validate_song_payload(payload)
    except ValueError:
        return None


def _language_for_line(line: dict, language: str | None) -> str:
    value = line.get("language", language or "zh")
    try:
        return _language(value)
    except ValueError:
        return "zh"


def _split_positions(value, text_length: int) -> list[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        value = [value]
    elif isinstance(value, (str, bytes)):
        return []
    else:
        try:
            value = list(value)
        except TypeError:
            return []
    return sorted({
        position for position in value
        if type(position) is int and 0 < position < text_length
    })


def _highlight_text_html(
    text: str,
    words: list[dict],
    split_at: int | Iterable[int] | None = None,
    text_color: str = "inherit",
) -> str:
    """Escape a line, bold exact vocabulary matches, and show split dividers."""
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

    splits = _split_positions(split_at, len(text))
    boundaries = {0, len(text), *splits}
    for start, length, _word_id in selected:
        boundaries.add(start)
        boundaries.add(start + length)
    ordered_boundaries = sorted(boundaries)
    chunks = []
    for left, right in zip(ordered_boundaries, ordered_boundaries[1:]):
        if left in splits:
            chunks.append(
                f'<span class="lyricsSplit" style="padding:0 8px; color:{text_color}; '
                'font-weight:400;">│</span>'
            )
        piece = html.escape(text[left:right])
        match = next(
            (item for item in selected if item[0] <= left and right <= item[0] + item[1]),
            None,
        )
        if match is None:
            chunks.append(piece)
            continue
        word_id = html.escape(str(match[2]), quote=True)
        chunks.append(
            f'<a href="vocab:{word_id}" style="color:{text_color}; '
            f'font-weight:700; text-decoration:none;"><strong>{piece}</strong></a>'
        )
    return "".join(chunks)


def highlighted_lyrics_html(
    lyrics: Iterable[dict], vocab: Iterable[dict], language: str | None = None,
    split_points: dict[str, Iterable[int]] | None = None,
    colors: dict | None = None,
) -> str:
    """Render lyrics safely with vocabulary links and language-specific rows."""
    words = [
        word for word in vocab
        if isinstance(word, dict) and isinstance(word.get("surface"), str)
        and word.get("surface")
    ]
    words.sort(key=lambda word: len(word["surface"]), reverse=True)
    palette = {
        "text": "#1D1D1F",
        "muted": "#6E6E73",
        "primary": "#5E5CE6",
    }
    if colors:
        palette.update({key: colors[key] for key in palette if key in colors})
    text_color = html.escape(str(palette["text"]), quote=True)
    muted_color = html.escape(str(palette["muted"]), quote=True)
    primary_color = html.escape(str(palette["primary"]), quote=True)
    paragraphs = []
    for line_index, line in enumerate(lyrics):
        if not isinstance(line, dict):
            continue
        text = str(line.get("text", ""))
        split_at = line.get("split_at")
        if split_points is not None:
            split_at = split_points.get(str(line.get("id")), [])
        rendered_text = _highlight_text_html(text, words, split_at, text_color)
        line_language = _language_for_line(line, language)
        line_marker = f'<a name="lyrics-line-{line_index}"></a>'
        if line_language == "ja":
            romaji = html.escape(
                str(line.get("romaji", line.get("romanization", line.get("roman", ""))))
            )
            translation = html.escape(str(line.get("translation", "")))
            paragraphs.append(
                '<div style="margin:0 0 32px 0; padding:0; line-height:1.35;">'
                f'<div style="margin:0; padding:0; color:{muted_color}; '
                f'font-size:13px; line-height:1.25;">{line_marker}{romaji}</div>'
                f'<div style="margin:2px 0 3px 0; padding:0; color:{text_color}; '
                f'font-size:17px; line-height:1.45;">{rendered_text}</div>'
                f'<div style="margin:0; padding:0; color:{primary_color}; '
                f'font-size:13px; line-height:1.25;">{translation}</div>'
                '</div>'
            )
        elif line_language == "en":
            translation = html.escape(str(line.get("translation", "")))
            translation_row = (
                f'<div style="margin:3px 0 0 0; color:{primary_color}; '
                f'font-size:13px; line-height:1.4;">{translation}</div>'
                if translation else ""
            )
            paragraphs.append(
                '<div style="margin:0 0 24px 0; padding:0;">'
                f'<div style="margin:0; color:{text_color}; '
                f'font-size:17px; line-height:1.5;">{line_marker}{rendered_text}</div>'
                f'{translation_row}</div>'
            )
        else:
            paragraphs.append(
                f'<div style="margin:0 0 12px 0; color:{text_color}; '
                f'line-height:1.8;">{line_marker}{rendered_text}</div>'
            )
    return "".join(paragraphs)


class LyricsTextBrowser(QTextBrowser):
    line_clicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_selection_mode = False

    def mousePressEvent(self, event):
        if self.line_selection_mode and event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.line_selection_mode and event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if self.line_selection_mode and event.button() == Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            cursor = self.cursorForPosition(point)
            rect = self.cursorRect(cursor)
            # Reject empty space below the document instead of selecting the last line.
            index = cursor.block().userState() if rect.top() <= point.y() <= rect.bottom() else -1
            self.line_clicked.emit(index)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class LyricsSongCard(QFrame):
    opened = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

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

        title_row = QHBoxLayout()
        title = QLabel(song["title"])
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("lyricsCardTitle")
        title.setWordWrap(False)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title.setToolTip(song["title"])
        title_row.addWidget(title, 1)
        self.delete_button = QPushButton("删除歌曲", objectName="lyricsDeleteButton")
        self.delete_button.setAccessibleName(f"删除歌曲：{song['title']}")
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self.song_id))
        title_row.addWidget(self.delete_button)
        layout.addLayout(title_row)

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
        self.split_points: dict[str, dict[str, list[int]]] = {}
        self.current_song: dict | None = None
        self._clear_split_mode = False
        self._clear_split_line_id: str | None = None
        self._selected_lyric_text = ""
        self._selected_lyric_block_text = ""
        self._selected_lyric_offset = 0

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
            "导入歌曲歌词和生词，双击卡片打开歌词；点击加粗词查看含义。"
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

        self.language_tabs = QTabBar()
        self.language_tabs.setObjectName("lyricsLanguageTabs")
        self.language_tabs.setExpanding(False)
        self.language_tabs.setDrawBase(False)
        self.language_tabs.setAccessibleName("歌词语言分类")
        for key, label in LANGUAGE_FILTERS:
            index = self.language_tabs.addTab(label)
            self.language_tabs.setTabData(index, key)
        layout.addWidget(self.language_tabs)

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
        self.language_tabs.currentChanged.connect(self._render_cards)
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
        self.detail_title.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_title.setWordWrap(True)
        self.detail_title.setObjectName("pageTitle")
        top.addWidget(self.detail_title, 1)
        self.delete_button = QPushButton("删除歌曲", objectName="lyricsDeleteButton")
        self.delete_button.clicked.connect(self._delete_current_song)
        top.addWidget(self.delete_button)
        layout.addLayout(top)

        self.detail_artist = QLabel("")
        self.detail_artist.setObjectName("pageSubtitle")
        layout.addWidget(self.detail_artist)

        lyrics_card = Card("lyricsTextCard")
        lyrics_layout = QVBoxLayout(lyrics_card)
        lyrics_layout.setContentsMargins(20, 18, 20, 18)
        lyrics_actions = QHBoxLayout()
        self.lyrics_hint = QLabel(LYRICS_HINT)
        self.lyrics_hint.setObjectName("cardHint")
        self.lyrics_hint.setWordWrap(True)
        lyrics_actions.addWidget(self.lyrics_hint, 1)
        self.split_button = QPushButton("添加分割点", objectName="secondaryButton")
        self.split_button.clicked.connect(self._split_selected_line)
        lyrics_actions.addWidget(self.split_button)
        self.clear_split_button = QPushButton("清除本行分割", objectName="secondaryButton")
        self.clear_split_button.clicked.connect(self._clear_selected_line_split)
        self.clear_split_button.setMinimumWidth(self.clear_split_button.sizeHint().width())
        lyrics_actions.addWidget(self.clear_split_button)
        lyrics_layout.addLayout(lyrics_actions)
        self.lyrics_browser = LyricsTextBrowser()
        self.lyrics_browser.line_clicked.connect(self._select_clear_split_line)
        self.cancel_clear_shortcut = QShortcut(QKeySequence("Escape"), self.detail_page)
        self.cancel_clear_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.cancel_clear_shortcut.activated.connect(self._cancel_clear_split)
        self.lyrics_browser.setOpenLinks(False)
        self.lyrics_browser.setOpenExternalLinks(False)
        self.lyrics_browser.setReadOnly(True)
        self.lyrics_browser.anchorClicked.connect(self._show_word)
        self.lyrics_browser.selectionChanged.connect(self._remember_lyric_selection)
        lyrics_layout.addWidget(self.lyrics_browser)
        layout.addWidget(lyrics_card, 1)

        self.word_panel = Card("lyricsWordPanel")
        word_layout = QVBoxLayout(self.word_panel)
        word_layout.setContentsMargins(18, 14, 18, 14)
        self.word_title = QLabel("点击加粗词查看详情")
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
        self.context.subscribe("data.reloaded", lambda _payload=None: self._reload_data())
        self.context.subscribe("theme.changed", lambda _theme_id=None: self._refresh_current_lyrics())
        self._load_splits()
        self._load_songs()

    def _reload_data(self):
        self._load_splits()
        self._load_songs()

    def _load_splits(self):
        raw = self.context.store.read_json(SPLITS_STORAGE_KEY, [])
        loaded: dict[str, dict[str, list[int]]] = {}
        if isinstance(raw, list):
            entries = []
            for item in raw:
                if isinstance(item, dict):
                    entries.append((item.get("song_id"), item.get("line_id"), item.get("positions")))
        elif isinstance(raw, dict):
            # Accept the first local representation for a seamless upgrade.
            entries = [
                (song_id, line_id, positions)
                for song_id, song_points in raw.items()
                if isinstance(song_points, dict)
                for line_id, positions in song_points.items()
            ]
        else:
            entries = []
        for song_id, line_id, positions in entries:
            if not isinstance(song_id, str) or not isinstance(line_id, str):
                continue
            values = positions if isinstance(positions, (list, tuple, set)) else [positions]
            valid = sorted({
                value for value in values
                if type(value) is int and value > 0
            })
            if valid:
                loaded.setdefault(song_id, {})[line_id] = valid
        self.split_points = loaded

    def _save_splits(self):
        records = [
            {"song_id": song_id, "line_id": line_id, "positions": positions}
            for song_id, lines in self.split_points.items()
            for line_id, positions in lines.items()
            if positions
        ]
        self.context.store.write_json(SPLITS_STORAGE_KEY, records)

    def _legacy_splits(self, raw: object) -> dict[str, dict[str, list[int]]]:
        """Migrate split points written by the previous lyrics implementation."""
        migrated: dict[str, dict[str, list[int]]] = {}
        if not isinstance(raw, list):
            return migrated
        for song in raw:
            if not isinstance(song, dict) or not isinstance(song.get("id"), str):
                continue
            lines = song.get("lyrics")
            if not isinstance(lines, list):
                continue
            for line in lines:
                if not isinstance(line, dict) or not isinstance(line.get("id"), str):
                    continue
                text = line.get("text", line.get("original", ""))
                if not isinstance(text, str):
                    continue
                positions = _split_positions(line.get("split_at"), len(text))
                if positions:
                    migrated.setdefault(song["id"], {})[line["id"]] = positions
        return migrated

    def _load_songs(self):
        raw = self.context.store.read_json(STORAGE_KEY, [])
        legacy_splits = self._legacy_splits(raw)
        for song_id, lines in legacy_splits.items():
            for line_id, positions in lines.items():
                existing = self.split_points.setdefault(song_id, {}).setdefault(line_id, [])
                self.split_points[song_id][line_id] = sorted(set(existing) | set(positions))
        self.songs = [
            song for item in raw if (song := _normalize_stored_song(item)) is not None
        ] if isinstance(raw, list) else []
        if legacy_splits:
            # Strip legacy split fields from the song collection after migration.
            self._save_songs()
            self._save_splits()
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
                widget.hide()
                widget.deleteLater()
        language_filter = self.language_tabs.tabData(self.language_tabs.currentIndex())
        songs = [song for song in self.songs if self._matches_filter(song, language_filter)]
        if not songs:
            label = self.language_tabs.tabText(self.language_tabs.currentIndex())
            message = (
                "还没有歌曲。点击“导入歌曲 JSON”开始学习。"
                if language_filter == "all"
                else f"还没有{label}歌曲。点击“导入歌曲 JSON”添加。"
            )
            empty = QLabel(message)
            empty.setObjectName("cardHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(180)
            self.cards_layout.insertWidget(0, empty)
            self.library_status.setText(
                f"共保存 {len(self.songs)} 首歌曲。可在“查看 JSON 模板”中选择日语或英语模板。"
            )
            return
        self.library_status.setText(
            f"共保存 {len(self.songs)} 首歌曲，当前显示 {len(songs)} 首。双击卡片打开歌词。"
        )
        for song in songs:
            card = LyricsSongCard(song)
            card.opened.connect(self._open_song)
            card.delete_requested.connect(self._delete_song)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

    @staticmethod
    def _matches_filter(song: dict, language_filter: str) -> bool:
        language = song.get("language", "zh")
        return (
            language_filter == "all"
            or language == language_filter
            or (language_filter == "other" and language not in {"ja", "en"})
        )

    def _delete_current_song(self):
        if self.current_song is not None:
            self._delete_song(self.current_song["id"])

    def _delete_song(self, song_id: str):
        song = self._song_by_id(song_id)
        if song is None:
            return
        confirmation = QMessageBox(self.page)
        confirmation.setWindowTitle("删除歌曲")
        confirmation.setIcon(QMessageBox.Icon.Question)
        confirmation.setTextFormat(Qt.TextFormat.PlainText)
        confirmation.setText(f"确定删除《{song['title']}》吗？")
        confirmation.setInformativeText(
            "将删除这首歌曲的歌词、生词和分割点记录，无法撤销。原始 JSON 文件会保留。"
        )
        confirmation.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        confirmation.button(QMessageBox.StandardButton.Yes).setText("删除")
        confirmation.button(QMessageBox.StandardButton.No).setText("取消")
        confirmation.setDefaultButton(QMessageBox.StandardButton.No)
        if confirmation.exec() != QMessageBox.StandardButton.Yes:
            return
        self.songs = [item for item in self.songs if item["id"] != song_id]
        self.split_points.pop(song_id, None)
        self._save_songs()
        self._save_splits()
        if self.current_song is not None and self.current_song["id"] == song_id:
            self._show_library()
        self._render_cards()
        self.library_status.setText(f"已删除《{song['title']}》。共保存 {len(self.songs)} 首歌曲。")

    def _song_by_id(self, song_id: str) -> dict | None:
        return next((song for song in self.songs if song["id"] == song_id), None)

    def _open_song(self, song_id: str):
        song = self._song_by_id(song_id)
        if song is None:
            return
        self._cancel_clear_split()
        self.current_song = song
        self.detail_title.setText(song["title"])
        language_label = {"ja": "日语", "zh": "中文", "en": "英语", "ko": "韩语"}.get(
            song.get("language", "zh"), song.get("language", "zh")
        )
        artist = song.get("artist") or "未知歌手"
        self.detail_artist.setText(f"{artist} · {language_label}")
        self._render_current_lyrics()
        self._selected_lyric_text = ""
        self._selected_lyric_block_text = ""
        self._selected_lyric_offset = 0
        self.word_title.setText("点击加粗词查看详情")
        self.word_reading.setText("")
        self.word_meaning.setText("")
        self.word_note.setText("")
        self.stack.setCurrentWidget(self.detail_page)

    def _theme_colors(self):
        theme = getattr(self.context.parent, "theme", None)
        return getattr(theme, "colors", None)

    def _refresh_current_lyrics(self):
        if self.current_song is None:
            return
        # setHtml resets the scrollbars; in-place edits should keep the reading position.
        scrollbars = (
            self.lyrics_browser.verticalScrollBar(),
            self.lyrics_browser.horizontalScrollBar(),
        )
        positions = [bar.value() for bar in scrollbars]
        self._render_current_lyrics()
        for bar, position in zip(scrollbars, positions):
            bar.setValue(position)

    def _render_current_lyrics(self):
        if self.current_song is None:
            return
        song = self.current_song
        points = self.split_points.get(song["id"], {})
        self.lyrics_browser.setHtml(
            '<div style="font-size:16px;">'
            + highlighted_lyrics_html(
                song["lyrics"], song["vocab"], song.get("language", "zh"),
                split_points=points, colors=self._theme_colors(),
            )
            + "</div>"
        )
        # Named anchors identify logical lyric rows even when their text repeats.
        # Original text, translation and romaji blocks share the same row index.
        line_index = -1
        block = self.lyrics_browser.document().begin()
        while block.isValid():
            fragments = block.begin()
            while not fragments.atEnd():
                fragment = fragments.fragment()
                if fragment.isValid():
                    for name in fragment.charFormat().anchorNames():
                        if name.startswith("lyrics-line-"):
                            line_index = int(name.removeprefix("lyrics-line-"))
                fragments += 1
            block.setUserState(line_index)
            block = block.next()
        self._highlight_clear_split_line()

    def _show_library(self):
        self._cancel_clear_split()
        self.current_song = None
        self._selected_lyric_text = ""
        self._selected_lyric_block_text = ""
        self._selected_lyric_offset = 0
        self.lyrics_browser.clear()
        self.detail_title.clear()
        self.detail_artist.clear()
        self.word_title.setText("点击加粗词查看详情")
        self.word_reading.clear()
        self.word_meaning.clear()
        self.word_note.clear()
        self.stack.setCurrentWidget(self.library_page)

    def _remember_lyric_selection(self):
        cursor = self.lyrics_browser.textCursor()
        selected = cursor.selectedText().replace("\u2029", "").strip()
        self._selected_lyric_text = selected
        self._selected_lyric_block_text = cursor.block().text().strip()
        self._selected_lyric_offset = max(0, cursor.selectionStart() - cursor.block().position())

    def _selected_line_and_position(self):
        if self.current_song is None or not self._selected_lyric_text:
            return None, None
        selected = self._selected_lyric_text
        block_text = self._selected_lyric_block_text
        normalized_block_text = block_text.replace("│", "")
        candidates = []
        for line in self.current_song.get("lyrics", []):
            text = str(line.get("text", ""))
            if block_text and block_text != text and normalized_block_text != text:
                continue
            search_offset = self._selected_lyric_offset
            if normalized_block_text == text:
                points = self.split_points.get(self.current_song["id"], {}).get(line["id"], [])
                search_offset = max(
                    0, search_offset - sum(1 for point in points if point <= search_offset)
                )
            start = text.find(selected, search_offset)
            if start < 0 and search_offset:
                start = text.find(selected)
            if start >= 0:
                candidates.append((line, start + len(selected)))
        if not candidates:
            for line in self.current_song.get("lyrics", []):
                text = str(line.get("text", ""))
                start = text.find(selected)
                if start >= 0:
                    candidates.append((line, start + len(selected)))
        if len(candidates) != 1:
            return None, None
        return candidates[0]

    def _split_selected_line(self):
        line, split_at = self._selected_line_and_position()
        if line is None:
            self.library_status.setText("请先在一条歌词中选中要添加分割点的单词。")
            return
        if split_at <= 0 or split_at >= len(line["text"]):
            self.library_status.setText("分割位置不能位于歌词开头或结尾。")
            return
        song_points = self.split_points.setdefault(self.current_song["id"], {})
        positions = song_points.setdefault(line["id"], [])
        if split_at not in positions:
            positions.append(split_at)
            positions.sort()
            self._save_splits()
        self._refresh_current_lyrics()

    def _cancel_clear_split(self):
        self._clear_split_mode = False
        self._clear_split_line_id = None
        self.lyrics_browser.line_selection_mode = False
        self.lyrics_browser.viewport().unsetCursor()
        self.lyrics_browser.setExtraSelections([])
        self.clear_split_button.setText("清除本行分割")
        self.split_button.setEnabled(True)
        self.lyrics_hint.setText(LYRICS_HINT)

    def _select_clear_split_line(self, line_index: int):
        if not self._clear_split_mode or self.current_song is None:
            return
        lines = self.current_song["lyrics"]
        if not 0 <= line_index < len(lines):
            self._clear_split_line_id = None
            self.lyrics_hint.setText("请点击目标歌词行，再次点击按钮清除。Esc 取消。")
        else:
            self._clear_split_line_id = lines[line_index]["id"]
            count = len(self.split_points.get(self.current_song["id"], {}).get(self._clear_split_line_id, []))
            self.lyrics_hint.setText(
                f"已选第 {line_index + 1} 行（{count} 个分割点），再次点击确认。Esc 取消。"
            )
        self._highlight_clear_split_line()

    def _highlight_clear_split_line(self):
        selections = []
        if self._clear_split_mode and self.current_song is not None and self._clear_split_line_id:
            target_index = next(
                (index for index, line in enumerate(self.current_song["lyrics"])
                 if line["id"] == self._clear_split_line_id),
                -1,
            )
            colors = self._theme_colors() or {}
            block = self.lyrics_browser.document().begin()
            while block.isValid():
                if target_index >= 0 and block.userState() == target_index:
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = QTextCursor(block)
                    selection.cursor.setPosition(block.position())
                    selection.cursor.setPosition(
                        block.position() + block.length() - 1,
                        QTextCursor.MoveMode.KeepAnchor,
                    )
                    selection.format.setBackground(QColor(colors.get("accent_soft", "#ECE9FF")))
                    selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                    selections.append(selection)
                block = block.next()
        self.lyrics_browser.setExtraSelections(selections)

    def _clear_selected_line_split(self):
        if self.current_song is None:
            return
        if not self._clear_split_mode:
            self._clear_split_mode = True
            self._clear_split_line_id = None
            self.lyrics_browser.line_selection_mode = True
            self.lyrics_browser.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            self.clear_split_button.setText("确认清除")
            self.split_button.setEnabled(False)
            self.lyrics_hint.setText("请点击目标歌词行，再次点击按钮清除。Esc 取消。")
            # Old text selections must not become an implicit target.
            scrollbar = self.lyrics_browser.verticalScrollBar()
            position = scrollbar.value()
            cursor = self.lyrics_browser.textCursor()
            cursor.clearSelection()
            self.lyrics_browser.setTextCursor(cursor)
            scrollbar.setValue(position)
            return
        if self._clear_split_line_id is None:
            self.lyrics_hint.setText("尚未选择歌词行，请先点击目标行。Esc 取消。")
            return
        line_id = self._clear_split_line_id
        line_number = next(
            index + 1 for index, line in enumerate(self.current_song["lyrics"])
            if line["id"] == line_id
        )
        song_points = self.split_points.get(self.current_song["id"], {})
        removed = song_points.pop(line_id, [])
        if not song_points:
            self.split_points.pop(self.current_song["id"], None)
        if removed:
            self._save_splits()
        self._cancel_clear_split()
        if removed:
            self._refresh_current_lyrics()
            self.lyrics_hint.setText(f"已清除第 {line_number} 行的 {len(removed)} 个分割点。")
        else:
            self.lyrics_hint.setText(f"第 {line_number} 行没有分割点，无需清除。")

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
            language_filter = self.language_tabs.tabData(self.language_tabs.currentIndex())
            if not self._matches_filter(song, language_filter):
                target_filter = song["language"] if song["language"] in {"ja", "en"} else "other"
                self.language_tabs.setCurrentIndex(
                    next(index for index, (key, _) in enumerate(LANGUAGE_FILTERS) if key == target_filter)
                )
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
            "再点击“导入歌曲 JSON”。song.language 使用语言代码（例如 zh、ja、en 或 ko）；"
            "日语歌曲每行需要填写 romaji、text 和 translation；"
            "英语歌曲每行填写 text，可选填 translation（中文翻译），生词 reading 可填写音标。"
        )
        hint.setObjectName("cardHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        template_selector = QComboBox()
        template_selector.setAccessibleName("模板语言")
        template_selector.addItem("日语模板", "ja")
        template_selector.addItem("英语模板", "en")
        template_selector.setCurrentIndex(
            1 if self.language_tabs.tabData(self.language_tabs.currentIndex()) == "en" else 0
        )
        layout.addWidget(template_selector)
        editor = QTextEdit()

        def update_template():
            template = ENGLISH_TEMPLATE if template_selector.currentData() == "en" else TEMPLATE
            editor.setPlainText(json.dumps(template, ensure_ascii=False, indent=2))

        template_selector.currentIndexChanged.connect(update_template)
        update_template()
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
