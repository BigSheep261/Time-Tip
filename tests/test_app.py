import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QDate, QDateTime, QTime, Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from timetip import Store, TimeTipWindow, STYLESHEET


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # The offscreen Windows plugin does not enumerate system fonts.
        for path in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/msyhbd.ttc'):
            if Path(path).exists():
                QFontDatabase.addApplicationFont(path)
        cls.app.setStyle('Fusion')
        cls.app.setStyleSheet(STYLESHEET)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.folder.name) / 'settings.ini'))
        self.window = TimeTipWindow(self.store)
        self.window.timer.stop()
        self.notifications = []
        self.window.notify = self.notifications.append

    def dispose(self):
        self.window.quitting = True
        self.window.geometry_timer.stop()
        self.window.close()
        self.window.tray.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def tearDown(self):
        self.dispose()
        self.folder.cleanup()

    def restart(self):
        self.dispose()
        self.window = TimeTipWindow(Store(self.store.settings.fileName()))
        self.window.timer.stop()
        self.window.notify = self.notifications.append

    def add_countdown(self, title, days=2):
        self.window.new_countdown()
        self.window.countdown_name.setText(title)
        self.window.target_edit.setDateTime(QDateTime(datetime.now() + timedelta(days=days)))
        self.window.save_target()
        return self.window.active_countdown_id

    def test_multiple_countdowns_edit_delete_and_restart(self):
        first = self.add_countdown('周末旅行')
        second = self.add_countdown('项目交付', 4)
        saved = self.window.countdowns[1]['target']
        self.window.target_edit.setDateTime(QDateTime(datetime.now() + timedelta(days=8)))
        self.assertEqual(self.window.countdowns[1]['target'], saved)
        self.window._select_list_id(self.window.countdown_list, first)
        self.window.countdown_name.setText('新的旅行')
        self.window.save_target()
        self.restart()
        self.assertEqual([c['title'] for c in self.window.countdowns], ['新的旅行', '项目交付'])
        self.assertIn('countdown:' + first, self.window.tiles)
        self.assertIn('countdown:' + second, self.window.tiles)
        self.window._select_list_id(self.window.countdown_list, first)
        self.window.delete_countdown()
        self.restart()
        self.assertEqual([c['id'] for c in self.window.countdowns], [second])

    def test_countdown_notifications_independent_and_persisted(self):
        self.add_countdown('同一时间 A')
        self.add_countdown('同一时间 B')
        past = (datetime.now() - timedelta(seconds=2)).replace(microsecond=0).isoformat()
        for item in self.window.countdowns:
            item['target'] = past
        self.window._update_countdown()
        self.window._update_countdown()
        self.assertEqual(self.notifications, ['倒计时结束：同一时间 A、同一时间 B'])
        self.assertTrue(all(c['notified'] for c in self.store.read_json('countdowns', [])))
        self.restart()
        self.window._update_countdown()
        self.assertEqual(len(self.notifications), 1)
        self.window._select_list_id(self.window.countdown_list, self.window.countdowns[0]['id'])
        self.window.countdown_name.setText('仅修改标题')
        self.window.save_target()
        self.window._update_countdown()
        self.assertEqual(len(self.notifications), 1)
        self.window.target_edit.setDateTime(QDateTime(datetime.now() + timedelta(seconds=30)))
        self.window.save_target()
        self.window._update_countdown(datetime.now() + timedelta(seconds=31))
        self.assertEqual(len(self.notifications), 2)

    def test_countdown_validation(self):
        self.window.save_target()
        self.assertEqual(self.window.countdowns, [])
        self.window.countdown_name.setText('过去')
        self.window.target_edit.setDateTime(QDateTime(datetime.now() - timedelta(days=1)))
        self.window.save_target()
        self.assertEqual(self.window.countdowns, [])
        self.assertIn('晚于', self.window.countdown_feedback.text())

    def test_cyclic_form_persistence_notifications_and_layout(self):
        self.window.countdown_name.setText('每日下班')
        self.window.countdown_mode.setCurrentIndex(1)
        self.window.cycle_frequency.setCurrentIndex(2)
        self.window.save_target()
        item_id = self.window.active_countdown_id
        self.assertEqual(self.window.countdowns[0]['cycle_start'], '09:30')
        self.assertEqual(self.window.countdowns[0]['cycle_weekdays'], [0, 1, 2, 3, 4])
        self.restart()
        self.window._select_list_id(self.window.countdown_list, item_id)
        self.assertEqual(self.window.countdown_mode.currentData(), 'cyclic')
        self.assertEqual(self.window.cycle_frequency.currentData(), 'weekly')
        self.window.countdowns[0]['notified_cycle'] = '2026-09-07T17:30:00'
        self.window._update_countdown(datetime(2026, 9, 8, 17, 30, 5))
        self.window._update_countdown(datetime(2026, 9, 8, 17, 31))
        self.assertEqual(self.notifications, ['倒计时结束：每日下班'])
        self.window.countdown_name.setText('下班提醒')
        self.window.save_target()
        self.assertEqual(self.window.countdowns[0]['notified_cycle'], '2026-09-08T17:30:00')
        self.window.show()
        self.window.resize(860, 620)
        self.window._switch_page(4)
        self.app.processEvents()
        self.assertEqual(self.window.size().height(), 620)
        self.assertGreaterEqual(self.window.cycle_start.height(), 40)
        output = Path(__file__).resolve().parents[1] / 'screenshots'
        output.mkdir(exist_ok=True)
        self.window.pages.currentWidget().verticalScrollBar().setValue(10000)
        self.app.processEvents()
        self.window.grab().save(str(output / 'countdowns-cyclic-860.png'))

    def test_legacy_data_migrates_once_including_notification(self):
        legacy = Store(str(Path(self.folder.name) / 'legacy.ini'))
        target = datetime.now().replace(microsecond=0) - timedelta(days=1)
        legacy.set('target', target.isoformat())
        legacy.set('target_notified', target.isoformat())
        legacy.set('memo', '旧笔记\n第二行')
        legacy.migrate_collections()
        items = legacy.read_json('countdowns', [])
        self.assertTrue(items[0]['notified'])
        self.assertEqual(legacy.read_json('memos', [])[0]['text'], '旧笔记\n第二行')
        legacy.migrate_collections()
        self.assertEqual(legacy.read_json('countdowns', []), items)
        legacy.write_json('countdowns', [])
        legacy.write_json('memos', [])
        legacy.migrate_collections()
        self.assertEqual(legacy.read_json('countdowns', []), [])
        self.assertEqual(legacy.read_json('memos', []), [])

    def test_multiple_memos_autosave_switch_delete_and_restart(self):
        self.window.add_memo()
        first = self.window.active_memo_id
        self.window.memo_title.setText('读书')
        self.window.memo_edit.setPlainText('明天读一本书\n保留中文与换行。')
        self.window.add_memo()
        second = self.window.active_memo_id
        self.window.memo_title.setText('购物')
        self.window.memo_edit.setPlainText('咖啡豆')
        self.window._select_list_id(self.window.memo_list, first)
        self.assertEqual(self.window.memo_title.text(), '读书')
        self.window.memo_edit.insertPlainText('自动保存。')
        QTest.qWait(600)
        self.assertIn('自动保存', self.store.read_json('memos', [])[0]['text'])
        self.restart()
        self.assertEqual(len(self.window.memos), 2)
        self.assertEqual(self.window.memos[1]['text'], '咖啡豆')
        self.window._select_list_id(self.window.memo_list, second)
        self.window.memo_edit.setPlainText('待保存但将删除')
        self.window.delete_memo()
        QTest.qWait(600)
        self.restart()
        self.assertEqual([m['id'] for m in self.window.memos], [first])
        self.window.delete_memo()
        self.restart()
        self.assertEqual(self.window.memos, [])
        self.assertFalse(self.window.memo_edit.isEnabled())

    def test_widget_layout_and_visibility_survive_resize_and_restart(self):
        self.add_countdown('目标')
        self.window.show()
        self.app.processEvents()
        self.assertEqual(self.window.grid.columns, 4)
        self.window._change_widget('salary', 'size', (4, 2))
        self.window._change_widget('focus', 'visible', False)
        self.window._change_widget('salary', 'move', -1)
        self.window.resize(860, 620)
        self.app.processEvents()
        self.assertEqual(self.window.grid.columns, 2)
        self.assertEqual(self.window.tiles['salary'].span, (4, 2))
        for tile in self.window.grid.tiles:
            self.assertLessEqual(tile.geometry().right(), self.window.grid.width())
        self.restart()
        self.assertEqual(self.window.size().width(), 860)
        self.assertNotIn('focus', self.window.tiles)
        self.assertEqual(next(iter(self.window.tiles)), 'salary')
        self.assertEqual(self.window.tiles['salary'].span, (4, 2))
        self.window._change_widget('focus', 'visible', True)
        self.assertIn('focus', self.window.tiles)

    def test_salary_settings_validation_and_persistence(self):
        self.assertFalse(self.window.save_salary_settings())
        self.window.monthly_salary.setValue(22000)
        self.window.shift_end.setTime(self.window.shift_start.time())
        self.assertFalse(self.window.save_salary_settings())
        self.window.shift_end.setTime(QTime(18, 0))
        self.assertTrue(self.window.save_salary_settings())
        self.restart()
        self.assertEqual(self.window.monthly_salary.value(), 22000)
        self.assertEqual(self.window.salary_config['weekdays'], [0, 1, 2, 3, 4])
        self.window._render_dashboard(datetime(2026, 9, 7, 10))
        tile = self.window.tiles['salary']
        first = tile.value_label.full_text
        self.window._render_dashboard(datetime(2026, 9, 7, 10, 0, 1))
        self.assertNotEqual(first, tile.value_label.full_text)
        self.assertIn('上班', tile.hint_label.full_text)
        self.window._render_dashboard(datetime(2026, 9, 7, 18))
        amount = tile.value_label.full_text
        self.window._render_dashboard(datetime(2026, 9, 7, 20))
        self.assertEqual(tile.value_label.full_text, amount)
        self.assertIn('下班', tile.hint_label.full_text)

    def test_overdue_reminder_is_delivered_once_and_persisted(self):
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        self.store.save_reminders([{'date': yesterday, 'time': '09:00', 'text': '测试提醒'}])
        self.window._check_reminders(datetime.now())
        self.window._check_reminders(datetime.now())
        self.assertEqual(self.notifications, ['日历提醒：测试提醒'])
        self.assertTrue(Store(self.store.settings.fileName()).reminders()[0]['notified'])

    def test_pomodoro_catches_up_after_delayed_tick_and_pauses(self):
        self.window.toggle_focus()
        self.window.pomodoro_deadline = datetime.now() - timedelta(seconds=40)
        self.window._tick()
        self.assertEqual(self.window.pomodoro_mode, 'break')
        self.assertEqual(self.window.pomodoro_remaining, 300)
        self.window.toggle_focus()
        remaining = self.window.pomodoro_remaining
        self.window._tick()
        self.assertEqual(self.window.pomodoro_remaining, remaining)
        self.assertFalse(self.window.pomodoro_running)

    def test_calendar_reminder_modes_and_date_format(self):
        self.window.reminder_mode.setCurrentIndex(1)
        self.window.reminder_input.setText('仅日历事项')
        self.window.add_reminder()
        self.assertEqual(self.store.reminders()[0]['mode'], 'calendar')
        self.window._check_reminders(datetime.now() + timedelta(days=3))
        self.assertEqual(self.notifications, [])
        self.window.date_format_combo.setCurrentIndex(self.window.date_format_combo.findData('japanese'))
        self.assertEqual(self.store.get('date_format'), 'japanese')
        self.window._tick()
        self.assertIn('曜日', self.window.day_label.text())

    def test_anime_schedule_persists_and_marks_calendar_without_notification(self):
        self.window._switch_page(6)
        self.window.anime_name.setText('测试番剧')
        self.window.anime_update.setTime(QTime(21, 30))
        self.window.anime_day_checks[1].setChecked(True)
        self.window.anime_folder.setText('D:/Anime')
        self.window.anime_progress.setText('第 3 集')
        self.assertTrue(self.window.save_anime())
        anime_id = self.window.active_anime_id
        self.assertIn('anime', self.window.tiles)
        self.restart()
        self.assertEqual(self.window.anime[0]['id'], anime_id)
        self.assertEqual(self.window.anime[0]['progress'], '第 3 集')
        self.window._calendar_selected(QDate(2026, 9, 8))
        self.assertGreaterEqual(self.window.reminder_list.count(), 1)
        self.assertEqual(self.window.reminder_list.item(0).data(Qt.ItemDataRole.UserRole)['kind'], 'anime')
        self.window._check_reminders(datetime(2026, 9, 8, 23))
        self.assertEqual(self.notifications, [])

    def test_calendar_reminder_add_and_delete(self):
        self.window.reminder_input.setText('指定日期事项')
        self.window.add_reminder()
        self.assertEqual(len(self.store.reminders()), 1)
        self.window.reminder_list.setCurrentRow(0)
        self.window.remove_reminder()
        self.assertEqual(self.store.reminders(), [])

    def test_delete_undo_restores_content_and_widget_preferences(self):
        item_id = self.add_countdown('撤销测试')
        key = 'countdown:' + item_id
        self.window._change_widget(key, 'size', (1, 1))
        self.window.delete_countdown()
        self.window.undo_delete_countdown()
        self.assertEqual(self.window.countdowns[0]['id'], item_id)
        self.assertEqual(self.window.tiles[key].span, (1, 1))
        self.window.add_memo()
        self.window.memo_edit.setPlainText('删除前尚未自动保存的内容')
        self.window.delete_memo()
        self.window.undo_delete_memo()
        self.assertEqual(self.window.memo_edit.toPlainText(), '删除前尚未自动保存的内容')
        self.restart()
        self.assertEqual(len(self.window.countdowns), 1)
        self.assertEqual(self.window.memos[0]['text'], '删除前尚未自动保存的内容')

    def test_render_all_pages_at_two_window_sizes(self):
        self.add_countdown('下一站，去看海', 10)
        self.add_countdown('项目交付', 3)
        self.window.add_memo()
        self.window.memo_title.setText('今天的小计划')
        self.window.memo_edit.setPlainText('读完手边的书\n整理旅行清单\n记得给家人打电话')
        self.window.save_memo()
        self.window.monthly_salary.setValue(22000)
        self.window.save_salary_settings()
        self.window.show()
        self.app.processEvents()
        output = Path(__file__).resolve().parents[1] / 'screenshots'
        output.mkdir(exist_ok=True)
        for width, height in [(1220, 830), (860, 620)]:
            self.window.resize(width, height)
            for index, name in enumerate(['overview', 'calendar', 'pomodoro', 'memo', 'countdowns', 'settings']):
                self.window._switch_page(index)
                self.app.processEvents()
                self.assertEqual(self.window.width(), width, f'{name} unexpectedly expands the window')
                self.assertTrue(self.window.grab().save(str(output / f'{name}-{width}.png')))
        self.window._switch_page(5)
        self.window.pages.currentWidget().verticalScrollBar().setValue(440)
        self.app.processEvents()
        self.window.grab().save(str(output / 'salary-settings-860.png'))
        self.window.pages.currentWidget().verticalScrollBar().setValue(100000)
        self.app.processEvents()
        self.window.grab().save(str(output / 'widget-settings-860.png'))
        self.window._switch_page(0)
        for key in list(self.window.tiles):
            self.window._change_widget(key, 'size', (1, 1))
        self.window.edit_layout_button.setChecked(True)
        self.window.resize(1220, 830)
        self.app.processEvents()
        self.window._render_dashboard(datetime.now())
        self.window.grab().save(str(output / 'widgets-1x1.png'))

    def test_settings_navigation_highlights_settings_button(self):
        self.assertEqual([button.text() for button in self.window.nav_buttons],
                         ['概览', '日历提醒', '番茄钟', '备忘录', '倒计时', '设置', '看番提醒'])
        self.window._switch_page(5)
        self.assertEqual(self.window.pages.currentIndex(), 5)
        self.assertTrue(self.window.nav_buttons[5].isChecked())
        self.assertFalse(self.window.nav_buttons[6].isChecked())

        self.window._switch_page(6)
        self.assertTrue(self.window.nav_buttons[6].isChecked())
        self.assertFalse(self.window.nav_buttons[5].isChecked())


if __name__ == '__main__':
    unittest.main()
