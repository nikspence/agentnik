import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QToolButton
from PySide6.QtGui import QColor,QImage
from agentnik.ui import MessageBubble,ImagePreview

class ChatImageControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_live_images_can_be_previewed_and_saved_without_transcoding(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root,'original.png');target=Path(root,'saved.png')
            image=QImage(12,8,QImage.Format.Format_ARGB32);image.fill(QColor('red'));self.assertTrue(image.save(str(source)))
            bubble=MessageBubble({'role':'assistant','text':'Ready'},live=True);bubble.set_images([str(source)])
            preview=bubble.findChild(QToolButton,'previewChatImage');save=bubble.findChild(QToolButton,'saveChatImage')
            self.assertIsNotNone(preview);self.assertIsNotNone(save);self.assertFalse(save.icon().isNull())
            with patch.object(ImagePreview,'exec',autospec=True,return_value=0) as shown:preview.click()
            self.assertEqual(shown.call_count,1);dialog=ImagePreview(str(source),bubble);self.assertEqual(dialog.image.size(),image.size());dialog.close()
            with patch('agentnik.ui.QFileDialog.getSaveFileName',return_value=(str(target),'')):save.click()
            self.assertEqual(target.read_bytes(),source.read_bytes());bubble.close()

    def test_saved_message_has_controls_and_cancel_is_noop(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root,'original.png');image=QImage(3,3,QImage.Format.Format_ARGB32);image.fill(QColor('blue'));image.save(str(source))
            bubble=MessageBubble({'role':'assistant','text':'Done','images':[str(source)]})
            self.assertEqual(len(bubble.findChildren(QToolButton)),2)
            with patch('agentnik.ui.QFileDialog.getSaveFileName',return_value=('','')),patch('agentnik.ui.shutil.copyfile') as copy:
                bubble.findChild(QToolButton,'saveChatImage').click();copy.assert_not_called()
            bubble.close()

    def test_persisted_chat_images_have_save_controls(self):
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(root);image=QImage(4,3,QImage.Format.Format_ARGB32);image.fill(QColor('green'));data=Path(root,'original.png');image.save(str(data));stored=store.attach(path=str(data))
            session=store.new_session('chat','test',{'url':'http://localhost:11434','model':'test'});session['messages']=[{'role':'assistant','text':'Generated','images':[stored]}];store.save(session)
            window=Window(store)
            try:
                window.open_session(store.list_sessions()[0]);self.app.processEvents();bubble=window.tabs.currentWidget().findChild(MessageBubble)
                self.assertIsNotNone(bubble.findChild(QToolButton,'previewChatImage'));self.assertIsNotNone(bubble.findChild(QToolButton,'saveChatImage'))
            finally:window.close();self.app.processEvents();store.db.close()

    def test_invalid_extension_and_missing_image_are_reported(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root,'original.png');image=QImage(3,3,QImage.Format.Format_ARGB32);image.fill(QColor('red'));image.save(str(source))
            bubble=MessageBubble({'role':'assistant','text':'Done','images':[str(source)]})
            with patch('agentnik.ui.QFileDialog.getSaveFileName',return_value=(str(Path(root,'wrong.jpg')),'')),patch('agentnik.ui.error') as error:
                bubble.findChild(QToolButton,'saveChatImage').click();error.assert_called_once();self.assertFalse(Path(root,'wrong.jpg').exists())
            source.unlink()
            with patch('agentnik.ui.error') as error:bubble.findChild(QToolButton,'previewChatImage').click();error.assert_called_once()
            bubble.close()
