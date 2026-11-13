"""Scroll a text selection while dragging near a view's vertical edges."""
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QCursor, QTextCursor


class SelectionScroll(QObject):
    def __init__(self, editor, outer=None):
        super().__init__(editor)
        self.editor = editor
        self.outer = outer or editor
        self.dragging = False
        self.timer = QTimer(self)
        self.timer.setInterval(35)
        self.timer.timeout.connect(self.scroll_selection)
        editor.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.timer.start()
        elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.timer.stop()
        elif event.type() in (QEvent.Type.Hide, QEvent.Type.WindowDeactivate):
            self.dragging = False
            self.timer.stop()
        return False

    def scroll_selection(self):
        if not self.dragging:
            return
        viewport = self.outer.viewport()
        point = viewport.mapFromGlobal(QCursor.pos())
        edge = min(28, max(1, viewport.height() // 4))
        direction = -1 if point.y() < edge else 1 if point.y() >= viewport.height() - edge else 0
        if not direction:
            return
        bar = self.outer.verticalScrollBar()
        before = bar.value()
        bar.setValue(before + direction * max(1, bar.singleStep() * 2))
        if bar.value() == before:
            return
        # Keep the original selection anchor as the visible content moves.
        local = self.editor.viewport().mapFromGlobal(QCursor.pos())
        local.setX(max(0, min(local.x(), self.editor.viewport().width() - 1)))
        local.setY(max(0, min(local.y(), self.editor.viewport().height() - 1)))
        cursor = self.editor.textCursor()
        cursor.setPosition(self.editor.cursorForPosition(local).position(), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
