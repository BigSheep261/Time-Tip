"""Native Qt rich-text controls shared by the memo page."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QAction, QColor, QFont, QFontInfo, QKeySequence, QTextCharFormat, QTextCursor,
    QTextFrameFormat, QTextLength, QTextListFormat, QTextTableFormat,
)
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFontComboBox, QFormLayout, QHBoxLayout,
    QLabel, QMenu, QSizePolicy, QSpinBox, QToolBar, QToolButton, QWidget,
)


class MemoFormatBar(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.font_family = QFontComboBox(objectName="memoFontCombo")
        self.font_family.setMinimumWidth(82)
        self.font_family.setMaximumWidth(104)
        self.font_family.setFixedHeight(36)
        self.font_family.setAccessibleName("备忘录字体")
        self.font_family.setToolTip("字体：应用于选中文字或接下来输入的文字")
        self.font_family.currentFontChanged.connect(self.set_family)
        layout.addWidget(self.font_family)
        self.font_size = QSpinBox(objectName="memoFontSize")
        self.font_size.setRange(6, 96)
        self.font_size.setSuffix(" pt")
        self.font_size.setFixedSize(58, 36)
        self.font_size.setKeyboardTracking(False)
        self.font_size.setAccessibleName("备忘录字号")
        self.font_size.setToolTip("字号：应用于选中文字或接下来输入的文字")
        self.font_size.valueChanged.connect(self.set_size)
        layout.addWidget(self.font_size)
        self.toolbar = QToolBar(objectName="memoFormatToolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.toolbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toolbar.setFixedHeight(38)
        self.bold_action = self.format_action("B", "加粗 (Ctrl+B)", "Ctrl+B", self.set_bold)
        self.italic_action = self.format_action("I", "斜体 (Ctrl+I)", "Ctrl+I", self.set_italic)
        self.underline_action = self.format_action("U", "下划线 (Ctrl+U)", "Ctrl+U", self.set_underline)
        self.strike_action = self.format_action("S", "删除线", None, self.set_strike)
        for action, property_name in ((self.bold_action, "bold"), (self.italic_action, "italic"),
                                      (self.underline_action, "underline"), (self.strike_action, "strike")):
            font = QFont()
            {"bold": font.setBold, "italic": font.setItalic, "underline": font.setUnderline,
             "strike": font.setStrikeOut}[property_name](True)
            action.setFont(font)
        self.toolbar.addSeparator()
        lists = self.menu_button("列")
        lists.parentWidget().setToolTip("列表：项目符号、编号或取消列表")
        lists.addAction("项目符号列表", lambda: self.set_list(QTextListFormat.Style.ListDisc))
        lists.addAction("编号列表", lambda: self.set_list(QTextListFormat.Style.ListDecimal))
        lists.addAction("取消列表", self.remove_list)
        tables = self.menu_button("表")
        tables.parentWidget().setToolTip("表格：插入或编辑表格")
        tables.addAction("插入表格…", self.choose_table)
        tables.addSeparator()
        self.table_actions = []
        for label, operation in (("在下方插入行", "row_add"), ("在右侧插入列", "column_add"),
                                 ("删除当前行", "row_remove"), ("删除当前列", "column_remove"),
                                 ("删除整个表格", "remove")):
            self.table_actions.append(tables.addAction(label, lambda checked=False, op=operation: self.edit_table(op)))
        tables.aboutToShow.connect(self.sync_table_actions)
        clear = self.toolbar.addAction("×")
        clear.setToolTip("清除选中文字的字体样式")
        clear.triggered.connect(self.clear_format)
        layout.addWidget(self.toolbar, 1)
        editor.currentCharFormatChanged.connect(self.sync_format)
        self.sync_format(editor.currentCharFormat())

    def format_action(self, label, hint, shortcut, slot):
        action = QAction(label, self)
        action.setToolTip(hint)
        action.setCheckable(True)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.editor.addAction(action)
        action.triggered.connect(slot)
        self.toolbar.addAction(action)
        return action

    def menu_button(self, label):
        button = QToolButton()
        button.setText(label)
        button.setAccessibleName("备忘录" + label)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setAutoRaise(True)
        button.setMinimumWidth(28)
        button.setMinimumHeight(36)
        menu = QMenu(button)
        button.setMenu(menu)
        self.toolbar.addWidget(button)
        return menu

    def apply_format(self, fmt):
        self.editor.mergeCurrentCharFormat(fmt)
        self.editor.setFocus()

    def set_family(self, font):
        fmt = QTextCharFormat()
        fmt.setFontFamilies([font.family()])
        self.apply_format(fmt)

    def set_size(self, size):
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        self.apply_format(fmt)

    def set_bold(self, enabled):
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Bold if enabled else QFont.Weight.Normal)
        self.apply_format(fmt)

    def set_italic(self, enabled):
        fmt = QTextCharFormat()
        fmt.setFontItalic(enabled)
        self.apply_format(fmt)

    def set_underline(self, enabled):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(enabled)
        self.apply_format(fmt)

    def set_strike(self, enabled):
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(enabled)
        self.apply_format(fmt)

    def clear_format(self):
        fmt = QTextCharFormat()
        fmt.setFont(self.editor.document().defaultFont())
        self.editor.setCurrentCharFormat(fmt)
        self.editor.setFocus()

    def sync_format(self, fmt):
        for action, checked in ((self.bold_action, fmt.fontWeight() >= QFont.Weight.Bold),
                                (self.italic_action, fmt.fontItalic()),
                                (self.underline_action, fmt.fontUnderline()),
                                (self.strike_action, fmt.fontStrikeOut())):
            action.setChecked(checked)
        self.font_family.blockSignals(True)
        self.font_family.setCurrentFont(fmt.font())
        self.font_family.blockSignals(False)
        self.font_size.blockSignals(True)
        points = fmt.fontPointSize()
        if points <= 0:
            font = fmt.font()
            points = QFontInfo(font).pointSizeF()
        if points <= 0:
            points = self.editor.document().defaultFont().pointSizeF()
        self.font_size.setValue(max(6, min(96, round(points or 11))))
        self.font_size.blockSignals(False)

    def set_list(self, style):
        cursor = self.editor.textCursor()
        fmt = QTextListFormat()
        fmt.setStyle(style)
        fmt.setIndent(1)
        cursor.createList(fmt)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def remove_list(self):
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        block = self.editor.document().findBlock(start)
        while block.isValid() and block.position() <= end:
            if block.textList():
                block.textList().remove(block)
                block_cursor = QTextCursor(block)
                fmt = block.blockFormat()
                fmt.setIndent(0)
                block_cursor.setBlockFormat(fmt)
            block = block.next()
        cursor.endEditBlock()
        self.editor.setFocus()

    def choose_table(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("插入表格")
        layout = QFormLayout(dialog)
        rows, columns = QSpinBox(), QSpinBox()
        for spin in (rows, columns):
            spin.setRange(1, 20)
            spin.setValue(3)
        layout.addRow("行数", rows)
        layout.addRow("列数", columns)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("插入")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.insert_table(rows.value(), columns.value())

    def insert_table(self, rows, columns):
        fmt = QTextTableFormat()
        fmt.setBorder(1)
        fmt.setBorderBrush(QColor("#8E91A1"))
        fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
        fmt.setCellPadding(6)
        fmt.setCellSpacing(0)
        fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        cursor = self.editor.textCursor()
        table = cursor.insertTable(rows, columns, fmt)
        self.editor.setTextCursor(table.cellAt(0, 0).firstCursorPosition())
        self.editor.setFocus()
        return table

    def sync_table_actions(self):
        for action in self.table_actions:
            action.setEnabled(self.editor.textCursor().currentTable() is not None)

    def edit_table(self, operation):
        cursor = self.editor.textCursor()
        table = cursor.currentTable()
        if table is None:
            return
        cell = table.cellAt(cursor)
        if operation == "row_add":
            table.insertRows(cell.row() + 1, 1)
        elif operation == "column_add":
            table.insertColumns(cell.column() + 1, 1)
        elif operation == "row_remove":
            if table.rows() > 1:
                row, column = cell.row(), cell.column()
                table.removeRows(row, 1)
                cell = table.cellAt(min(row, table.rows() - 1), min(column, table.columns() - 1))
        elif operation == "column_remove":
            if table.columns() > 1:
                row, column = cell.row(), cell.column()
                table.removeColumns(column, 1)
                cell = table.cellAt(min(row, table.rows() - 1), min(column, table.columns() - 1))
        elif operation == "remove":
            start = QTextCursor(table.firstCursorPosition())
            start.setPosition(table.lastCursorPosition().position() + 1, QTextCursor.MoveMode.KeepAnchor)
            start.removeSelectedText()
            self.editor.setFocus()
            return
        self.editor.setTextCursor(cell.firstCursorPosition())
        self.editor.setFocus()
