"""Qt presentation for the offline Tarot reading page."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.domain.tarot import (
    SPREADS,
    SPREAD_BY_KEY,
    TarotCard,
    TarotPosition,
    TarotSpread,
    card_meaning,
    draw,
    orientation_label,
    position_interpretation,
    reading_summary,
)
from app.presentation.widgets import Card


def _label(text: str, name: str) -> QLabel:
    label = QLabel(text, objectName=name)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


class TarotCardGrid(QWidget):
    """Reflow long readings without widening the application's minimum window."""

    def __init__(self) -> None:
        super().__init__()
        self.cards: list[TarotCardWidget] = []
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 8, 0, 0)
        self.grid.setSpacing(12)

    def set_cards(self, cards: list[TarotCardWidget]) -> None:
        for old_card in self.cards:
            self.grid.removeWidget(old_card)
            old_card.hide()
            old_card.deleteLater()
        self.cards = list(cards)
        self.columns = 0
        self._reflow()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        columns = min(len(self.cards), 3 if self.width() >= 810 else 2)
        if columns == self.columns:
            return
        self.columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for column in range(3):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
            self.grid.setColumnMinimumWidth(column, 0)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns)


class TarotCardWidget(QFrame):
    """One position in a reading; the card stays face down until clicked."""

    revealed = pyqtSignal()

    def __init__(self, number: int, position: TarotPosition, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.number = number
        self.position = position
        self.card: TarotCard | None = None
        self.is_reversed = False
        self.is_revealed = False
        self.setObjectName("tarotCard")
        self.setMinimumHeight(228)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(7)

        header = QHBoxLayout()
        self.position_label = _label(f"{number:02d}  {position.title}", "tarotPosition")
        self.position_label.setToolTip(position.prompt)
        header.addWidget(self.position_label, 1)
        self.orientation = QLabel("", objectName="tarotOrientation")
        self.orientation.hide()
        header.addWidget(self.orientation, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)
        layout.addWidget(_label(position.prompt, "cardHint"))

        self.flip_button = QPushButton("TAROT\n点击翻牌", objectName="tarotBack")
        self.flip_button.setMinimumHeight(92)
        self.flip_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.flip_button.setAccessibleName(f"翻开第{number}张牌")
        self.flip_button.clicked.connect(self.reveal)
        layout.addWidget(self.flip_button)

        self.card_name = _label("等待翻牌", "tarotCardName")
        self.card_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.card_name.setWordWrap(True)
        layout.addWidget(self.card_name)
        self.meaning = _label("", "tarotMeaning")
        self.meaning.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meaning.hide()
        layout.addWidget(self.meaning)
        layout.addStretch()

    def set_card(self, card: TarotCard, is_reversed: bool) -> None:
        self.card = card
        self.is_reversed = is_reversed
        self.is_revealed = False
        self.flip_button.setText("TAROT\n点击翻牌")
        self.flip_button.setEnabled(True)
        self.card_name.setText("等待翻牌")
        self.orientation.clear()
        self.orientation.hide()
        self.meaning.clear()
        self.meaning.hide()
        self.setProperty("revealed", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def reveal(self) -> None:
        if self.card is None or self.is_revealed:
            return
        self.is_revealed = True
        self.flip_button.setEnabled(False)
        self.flip_button.setText(f"{self.card.name}\n{orientation_label(self.is_reversed)}")
        self.flip_button.setAccessibleName(f"第{self.number}张：{self.card.name}，{orientation_label(self.is_reversed)}")
        self.card_name.setText(self.card.arcana)
        self.orientation.setText(orientation_label(self.is_reversed))
        self.orientation.show()
        self.setProperty("revealed", True)
        self.style().unpolish(self)
        self.style().polish(self)
        self.revealed.emit()

    def show_interpretation(self) -> None:
        if self.card is None or not self.is_revealed:
            return
        self.meaning.setText(
            f"牌义\n{card_meaning(self.card, self.is_reversed)}\n\n"
            f"牌位解读\n{position_interpretation(self.position, self.card, self.is_reversed)}"
        )
        self.meaning.show()


class TarotPageMixin:
    """Build and control the Tarot page in :class:`TimeTipWindow`."""

    def _tarot_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 14, 8, 8)
        outer.setSpacing(14)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.addWidget(QLabel("占卜 · 塔罗牌", objectName="pageTitle"))
        heading.addWidget(_label("静下心来，为一个问题留一点思考的空间。", "pageSubtitle"))
        header.addLayout(heading, 1)
        self.tarot_reset_button = QPushButton("重新开始", objectName="secondaryButton")
        self.tarot_reset_button.clicked.connect(self._reset_tarot)
        self.tarot_reset_button.setEnabled(False)
        header.addWidget(self.tarot_reset_button)
        outer.addLayout(header)
        self.tarot_scroll = QScrollArea()
        self.tarot_scroll.setWidgetResizable(True)
        self.tarot_scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 4, 6)
        layout.setSpacing(14)
        self.tarot_scroll.setWidget(content)
        outer.addWidget(self.tarot_scroll, 1)
        self.tarot_scroll_timer = QTimer(page)
        self.tarot_scroll_timer.setSingleShot(True)
        self.tarot_scroll_timer.setInterval(0)
        self.tarot_scroll_timer.timeout.connect(lambda: self.tarot_scroll.verticalScrollBar().setValue(0))

        intro = Card()
        self.tarot_intro = intro
        intro_layout = QVBoxLayout(intro)
        intro_layout.setContentsMargins(20, 16, 20, 16)
        intro_layout.setSpacing(10)
        intro_layout.addWidget(QLabel("先在心里明确一个问题，再选择适合的牌阵。", objectName="cardTitle"))
        self.tarot_question = QLineEdit()
        self.tarot_question.setPlaceholderText("问题（可选），例如：我该如何安排接下来的学习计划？")
        self.tarot_question.setMaxLength(200)
        self.tarot_question.setAccessibleName("占卜问题（可选）")
        intro_layout.addWidget(self.tarot_question)
        hint = _label("78 张韦特体系塔罗牌 · 每次不重复抽取 · 随机正逆位\n选择二选一牌阵时，请先在问题中约定 A、B 分别代表什么。", "cardHint")
        intro_layout.addWidget(hint)
        layout.addWidget(intro)

        spreads_card = Card()
        self.tarot_spreads_card = spreads_card
        spreads_layout = QVBoxLayout(spreads_card)
        spreads_layout.setContentsMargins(20, 16, 20, 16)
        spreads_layout.setSpacing(10)
        spreads_layout.addWidget(QLabel("选择牌阵", objectName="cardTitle"))
        spread_grid = QGridLayout()
        spread_grid.setHorizontalSpacing(10)
        spread_grid.setVerticalSpacing(10)
        self.tarot_spread_buttons: dict[str, QPushButton] = {}
        for i, spread in enumerate(SPREADS):
            button = QPushButton(f"{spread.title}  ·  {len(spread.positions)} 张\n{spread.description}", objectName="tarotSpreadButton")
            button.setToolTip("\n".join(f"{j + 1}. {position.title}：{position.prompt}" for j, position in enumerate(spread.positions)))
            button.setMinimumSize(0, 76)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, key=spread.key: self._start_tarot_reading(key))
            self.tarot_spread_buttons[spread.key] = button
            spread_grid.addWidget(button, i // 2, i % 2)
        spreads_layout.addLayout(spread_grid)
        layout.addWidget(spreads_card)

        reading_card = Card()
        self.tarot_reading_card = reading_card
        reading_layout = QVBoxLayout(reading_card)
        reading_layout.setContentsMargins(20, 16, 20, 18)
        reading_header = QHBoxLayout()
        self.tarot_reading_title = _label("尚未开始占卜", "cardTitle")
        reading_header.addWidget(self.tarot_reading_title, 1)
        self.tarot_flip_all = QPushButton("全部翻开", objectName="secondaryButton")
        self.tarot_flip_all.clicked.connect(self._reveal_all_tarot)
        self.tarot_flip_all.setVisible(False)
        reading_header.addWidget(self.tarot_flip_all)
        reading_layout.addLayout(reading_header)
        self.tarot_question_label = _label("", "tarotQuestion")
        self.tarot_question_label.setVisible(False)
        reading_layout.addWidget(self.tarot_question_label)
        self.tarot_cards_host = TarotCardGrid()
        reading_layout.addWidget(self.tarot_cards_host)
        self.tarot_summary = _label("选择上方牌阵开始。", "tarotSummary")
        self.tarot_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        reading_layout.addWidget(self.tarot_summary)
        layout.addWidget(reading_card)
        reading_card.hide()
        layout.addWidget(_label("解读采用内置中文牌义与牌位提示，问题用于聚焦思考；适合娱乐与自我观察。结果仅保留在本次运行中。", "cardHint"))
        layout.addStretch()

        self.tarot_spread: TarotSpread | None = None
        self.tarot_drawn: list[tuple[TarotCard, bool]] = []
        self.tarot_card_widgets: list[TarotCardWidget] = []
        return page

    def _start_tarot_reading(self, key: str) -> None:
        spread = SPREAD_BY_KEY.get(key)
        if spread is None or self.tarot_spread is not None:
            return
        self.tarot_spread = spread
        self.tarot_drawn = draw(spread)
        self.tarot_card_widgets = []
        for index, (card, is_reversed) in enumerate(self.tarot_drawn):
            widget = TarotCardWidget(index + 1, spread.positions[index])
            widget.set_card(card, is_reversed)
            widget.revealed.connect(self._tarot_card_revealed)
            self.tarot_card_widgets.append(widget)
        self.tarot_cards_host.set_cards(self.tarot_card_widgets)
        self.tarot_reading_title.setText(f"{spread.title} · 已翻开 0 / {len(self.tarot_drawn)} 张")
        question = self.tarot_question.text().strip()
        self.tarot_question_label.setText(f"你的问题：{question}" if question else "本次没有填写具体问题，将聚焦牌阵本身的提示。")
        self.tarot_question_label.setVisible(True)
        self.tarot_summary.setText("牌已抽好。依次点击牌背，或选择「全部翻开」。全部翻开后将显示每张牌的牌义、牌位解读与本次小结。")
        self.tarot_flip_all.setVisible(True)
        self.tarot_flip_all.setEnabled(True)
        self.tarot_reset_button.setEnabled(True)
        self.tarot_intro.hide()
        self.tarot_spreads_card.hide()
        self.tarot_reading_card.show()
        self.tarot_card_widgets[0].flip_button.setFocus()
        self.tarot_scroll_timer.start()

    def _tarot_card_revealed(self) -> None:
        if self.tarot_spread is None:
            return
        count = sum(widget.is_revealed for widget in self.tarot_card_widgets)
        self.tarot_reading_title.setText(f"{self.tarot_spread.title} · 已翻开 {count} / {len(self.tarot_drawn)} 张")
        if count == len(self.tarot_drawn):
            for widget in self.tarot_card_widgets:
                widget.show_interpretation()
            self.tarot_summary.setText("本次解读小结\n\n" + reading_summary(self.tarot_spread, self.tarot_drawn))
            self.tarot_flip_all.setEnabled(False)
            self.tarot_reading_title.setText(f"{self.tarot_spread.title} · 解读已完成")

    def _reveal_all_tarot(self) -> None:
        # Disabling each card should not send focus (and the viewport) down the grid.
        self.tarot_reset_button.setFocus()
        for widget in self.tarot_card_widgets:
            widget.reveal()

    def _reset_tarot(self) -> None:
        self.tarot_spread = None
        self.tarot_drawn = []
        self.tarot_card_widgets = []
        self.tarot_cards_host.set_cards([])
        self.tarot_reading_title.setText("尚未开始占卜")
        self.tarot_question_label.clear()
        self.tarot_question_label.setVisible(False)
        self.tarot_summary.setText("选择上方牌阵开始。")
        self.tarot_flip_all.setVisible(False)
        self.tarot_reset_button.setEnabled(False)
        self.tarot_reading_card.hide()
        self.tarot_intro.show()
        self.tarot_spreads_card.show()
        self.tarot_question.setFocus()
        self.tarot_scroll_timer.start()
