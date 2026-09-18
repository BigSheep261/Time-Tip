"""Offline Tarot deck, reading lifecycle and Qt integration checks."""
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "TimeTip-Application"))

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.domain.tarot import (
    CARD_BY_NAME, DECK, SPREADS, SPREAD_BY_KEY, card_meaning, draw,
    position_interpretation, reading_summary,
)
from app.infrastructure.store import Store
from app.presentation.tarot import TarotPageMixin
from app.presentation.theme import apply_theme


class TarotDomainTests(unittest.TestCase):
    def test_complete_deck_has_unique_names_and_distinct_meanings(self):
        self.assertEqual(len(DECK), 78)
        self.assertEqual(len(CARD_BY_NAME), 78)
        self.assertEqual(sum(card.arcana == "大阿卡那" for card in DECK), 22)
        for suit in ("权杖", "圣杯", "宝剑", "星币"):
            self.assertEqual(sum(card.name.startswith(suit) for card in DECK), 14)
        for card in DECK:
            self.assertTrue(card.upright.strip() and card.reversed.strip())
            self.assertNotEqual(card.upright, card.reversed)

    def test_all_spreads_draw_required_count_without_replacement(self):
        self.assertEqual([len(spread.positions) for spread in SPREADS], [1, 3, 4, 5, 10])
        orientations = set()
        for spread in SPREADS:
            with self.subTest(spread=spread.key):
                cards = draw(spread, random.Random(10))
                self.assertEqual(len(cards), len(spread.positions))
                self.assertEqual(len({card.name for card, _ in cards}), len(cards))
                self.assertTrue(all(card in DECK for card, _ in cards))
                orientations.update(reversed_ for _, reversed_ in cards)
        self.assertEqual(orientations, {True, False})

    def test_every_card_orientation_and_position_has_matching_interpretation(self):
        for spread in SPREADS:
            for position in spread.positions:
                for card in DECK:
                    for reversed_ in (False, True):
                        meaning = card_meaning(card, reversed_)
                        self.assertEqual(meaning, card.reversed if reversed_ else card.upright)
                        result = position_interpretation(position, card, reversed_)
                        self.assertIn(card.name, result)
                        self.assertIn(meaning, result)
                        self.assertIn(position.title, result)
                        self.assertIn(position.reflection, result)

    def test_summary_uses_actual_cards_and_does_not_score_orientation(self):
        spread = SPREAD_BY_KEY["single"]
        card = CARD_BY_NAME["宝剑九"]
        upright = reading_summary(spread, [(card, False)])
        reversed_ = reading_summary(spread, [(card, True)])
        self.assertIn(card.upright, upright)
        self.assertIn(card.reversed, reversed_)
        self.assertNotIn("整体能量顺畅", upright)
        self.assertNotEqual(upright, reversed_)
        with self.assertRaises(ValueError):
            reading_summary(SPREAD_BY_KEY["celtic"], [(card, False)])

    def test_celtic_cross_has_ten_distinct_traditional_positions(self):
        positions = [position.title for position in SPREAD_BY_KEY["celtic"].positions]
        self.assertEqual(positions, ["现况", "挑战", "根基", "过去", "目标与意识", "近期走向", "你的态度", "外部环境", "希望与恐惧", "最终走向"])


class TarotTestWindow(TarotPageMixin, QWidget):
    def __init__(self):
        super().__init__()
        QVBoxLayout(self).addWidget(self._tarot_page())
        self.scroll = self.tarot_scroll


class TarotPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # Windows' offscreen platform does not automatically discover system fonts.
        for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
        cls.app.setStyle("Fusion")

    def setUp(self):
        apply_theme(self.app, "light")
        self.window = TarotTestWindow()
        self.window.resize(620, 600)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.hide()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_flip_once_and_reveal_all_completes_without_redrawing(self):
        self.window.tarot_spread_buttons["timeline"].click()
        drawn = list(self.window.tarot_drawn)
        first = self.window.tarot_card_widgets[0]
        first.flip_button.click()
        first.reveal()
        self.assertEqual(sum(card.is_revealed for card in self.window.tarot_card_widgets), 1)
        self.assertTrue(all(card.meaning.isHidden() for card in self.window.tarot_card_widgets))
        self.assertIn("1 / 3", self.window.tarot_reading_title.text())
        self.window.tarot_flip_all.click()
        self.assertEqual(self.window.tarot_drawn, drawn)
        self.assertTrue(all(card.is_revealed and not card.meaning.isHidden() for card in self.window.tarot_card_widgets))
        self.assertIn("解读已完成", self.window.tarot_reading_title.text())
        self.assertIn("本次解读小结", self.window.tarot_summary.text())
        self.assertFalse(self.window.tarot_flip_all.isEnabled())
        for card, reversed_ in drawn:
            self.assertIn(card_meaning(card, reversed_), self.window.tarot_summary.text())

    def test_each_mode_can_complete_reset_and_replace_the_old_reading(self):
        self.window.tarot_question.setText("A：继续学习；B：开始工作")
        for spread in SPREADS:
            self.window.tarot_spread_buttons[spread.key].click()
            self.assertEqual(len(self.window.tarot_card_widgets), len(spread.positions))
            drawn = list(self.window.tarot_drawn)
            self.window._start_tarot_reading("single")
            self.assertEqual(self.window.tarot_drawn, drawn)
            self.window._reveal_all_tarot()
            self.window.tarot_reset_button.click()
            self.app.processEvents()
            self.assertIsNone(self.window.tarot_spread)
            self.assertFalse(self.window.tarot_drawn)
            self.assertEqual(self.window.tarot_cards_host.grid.count(), 0)
            self.assertEqual(self.window.tarot_question.text(), "A：继续学习；B：开始工作")

    def test_question_is_plain_text_and_frozen_for_this_reading(self):
        self.window.tarot_question.setText("<b>我的问题</b>" + "长问题" * 70)
        question = self.window.tarot_question.text()
        self.assertEqual(len(question), 200)
        self.window._start_tarot_reading("single")
        self.assertEqual(self.window.tarot_question_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn(question, self.window.tarot_question_label.text())
        self.window.tarot_question.setText("另一个问题")
        self.assertIn(question, self.window.tarot_question_label.text())

    def test_theme_switch_preserves_partial_reading(self):
        self.window._start_tarot_reading("choice")
        self.window.tarot_card_widgets[2].reveal()
        drawn = list(self.window.tarot_drawn)
        apply_theme(self.app, "dark")
        self.app.processEvents()
        self.assertEqual(self.window.tarot_drawn, drawn)
        self.assertEqual([card.is_revealed for card in self.window.tarot_card_widgets], [False, False, True, False, False])
        self.window._reveal_all_tarot()
        self.assertIn("本次解读小结", self.window.tarot_summary.text())

    def test_narrow_and_wide_layouts_do_not_need_horizontal_scrolling(self):
        self.window.tarot_question.setText("很长的问题" * 40)
        for width, columns in ((620, 2), (1000, 3), (620, 2)):
            self.window.resize(width, 600)
            self.window._reset_tarot()
            self.app.processEvents()
            self.assertEqual(self.window.scroll.horizontalScrollBar().maximum(), 0)
            for button in self.window.tarot_spread_buttons.values():
                for line in button.text().splitlines():
                    self.assertLessEqual(button.fontMetrics().horizontalAdvance(line), button.width() - 26)
            self.window._start_tarot_reading("celtic")
            self.window._reveal_all_tarot()
            for _ in range(3):
                self.app.processEvents()
            self.assertEqual(self.window.tarot_cards_host.columns, columns)
            self.assertEqual(self.window.scroll.horizontalScrollBar().maximum(), 0)
            for card in self.window.tarot_card_widgets:
                self.assertTrue(self.window.tarot_cards_host.rect().contains(card.geometry()))
            self.window.scroll.verticalScrollBar().setValue(self.window.scroll.verticalScrollBar().maximum())
            self.assertTrue(self.window.rect().contains(self.window.tarot_reset_button.mapTo(self.window, self.window.tarot_reset_button.rect().center())))
            self.window.tarot_reset_button.click()
            self.app.processEvents()
            self.assertEqual(self.window.scroll.verticalScrollBar().value(), 0)

    def test_navigation_integration_keeps_legacy_indices_and_session(self):
        from app.presentation.window import TimeTipWindow

        with tempfile.TemporaryDirectory() as directory:
            store = Store(str(Path(directory) / "settings.ini"))
            with patch.object(TimeTipWindow, "_start_timers"), patch("app.presentation.window.QSystemTrayIcon.isSystemTrayAvailable", return_value=False):
                main = TimeTipWindow(store)
            try:
                main.show()
                main.resize(860, 620)
                main.tarot_nav_button.click()
                self.assertEqual(main.pages.currentIndex(), 9)
                self.assertEqual(len(main.nav_buttons), 8)
                self.assertTrue(main.tarot_nav_button.isChecked())
                main._start_tarot_reading("single")
                main._reveal_all_tarot()
                drawn = list(main.tarot_drawn)
                main.nav_buttons[0].click()
                self.assertFalse(main.tarot_nav_button.isChecked())
                main.tarot_nav_button.click()
                main.set_theme("dark")
                for _ in range(3):
                    self.app.processEvents()
                self.assertEqual(main.tarot_drawn, drawn)
                self.assertEqual(main.tarot_scroll.horizontalScrollBar().maximum(), 0)
                for _ in range(5):
                    main._unlock_jm_mode()
                self.assertEqual(main.pages.currentIndex(), 8)
                self.assertTrue(main.jm_nav_button.isChecked())
                main._leave_jm_mode()
                self.assertEqual(main.pages.currentIndex(), 5)
            finally:
                main.jm_wait_for_shutdown()
                main.tray.hide()
                main.hide()
                main.deleteLater()
                self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
