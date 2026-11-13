"""Selection dragging scrolls the appropriate Qt viewport."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QVBoxLayout, QWidget, QPlainTextEdit
from agentnik.selection_scroll import SelectionScroll
from agentnik.ui import MessageText


class SelectionScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def check_drag(self, editor, area):
        bar = area.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        self.assertGreater(bar.maximum(), 0)
        point = QPoint(10, 30)
        QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton, pos=point)
        before = bar.value()
        target = area.viewport().mapToGlobal(QPoint(10, area.viewport().height() - 1))
        with patch.object(QCursor, 'pos', return_value=target):
            editor._selection_scroll.scroll_selection()
        self.assertGreater(bar.value(), before)
        self.assertTrue(editor.textCursor().hasSelection())
        target = area.viewport().mapToGlobal(QPoint(10, 0))
        before = bar.value()
        with patch.object(QCursor, 'pos', return_value=target):
            editor._selection_scroll.scroll_selection()
        self.assertLess(bar.value(), before)
        QTest.mouseRelease(editor.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertFalse(editor._selection_scroll.timer.isActive())

    def test_coding_activity(self):
        editor = QPlainTextEdit('\n'.join('Line %d' % n for n in range(200)))
        editor.resize(400, 150); editor.show(); self.app.processEvents()
        editor._selection_scroll = SelectionScroll(editor)
        try: self.check_drag(editor, editor)
        finally: editor.close()

    def test_chat_message_outer_scroll(self):
        area = QScrollArea(); area.setWidgetResizable(True); area.resize(400, 150)
        container = QWidget(); layout = QVBoxLayout(container)
        editor = MessageText('\n'.join('Line %d' % n for n in range(200)))
        layout.addWidget(editor); area.setWidget(container); area.show()
        for _ in range(5): self.app.processEvents()
        try: self.check_drag(editor, area)
        finally: area.close()
