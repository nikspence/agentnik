"""Render safe, offline baseline screenshots using temporary application data."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from agentnik.storage import Store
from agentnik.ui import Window


def main():
    app=QApplication([]); app.setStyle('Fusion')
    fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    for name in ('segoeui.ttf','segoeuib.ttf','seguisym.ttf'):
        if (fonts/name).exists(): QFontDatabase.addApplicationFont(str(fonts/name))
    app.setFont(QFont('Segoe UI',9))
    out=Path(__file__).resolve().parents[1]/'assets'
    with tempfile.TemporaryDirectory() as root, patch('agentnik.core.discover',return_value={}), patch('agentnik.core.environment_connections',return_value={}):
        store=Store(root); w=Window(store); w.show()
        try:
            for theme in ('Light','Dark'):
                w.theme.setCurrentText(theme)
                for _ in range(20): app.processEvents()
                if not w.grab().save(str(out/f'agentnik-{theme.lower()}-welcome.png')): raise RuntimeError('Screenshot failed')
        finally:
            w.close(); app.processEvents(); store.db.close()


if __name__=='__main__': main()
