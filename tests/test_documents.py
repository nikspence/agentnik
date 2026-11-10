"""Offline document parsing, multimodal serialization and attachment persistence."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from agentnik.document_reader import read_document, pdf_images, message_text, validate_documents


class Documents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from PySide6.QtGui import QFontDatabase
        font = Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'arial.ttf'
        if font.exists(): QFontDatabase.addApplicationFont(str(font))

    def test_text_bounds_and_rejected_files(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'notes.md'; path.write_text('hello\nworld',encoding='utf-8')
            self.assertIn('[Lines 1-2]\nhello\nworld',read_document(path))
            path.write_text('x'*60000,encoding='utf-8')
            self.assertIn('content omitted',read_document(path))
            path.write_bytes(b'abc\x00def')
            with self.assertRaises(ValueError):read_document(path)
            with self.assertRaises(ValueError):read_document(Path(root)/'run.exe')

    def test_office_inert_values_and_archive_limits(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'sample.docx'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Hello document</w:t></w:r></w:p></w:document>')
            self.assertIn('[Paragraph 1]\nHello document',read_document(path))
            path = Path(root)/'sample.xlsx'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>')
            self.assertIn('sheet1 row 1]\nA1: 2',read_document(path))
            with zipfile.ZipFile(path,'w') as z:z.writestr('bomb','x'*(21*1024*1024))
            with self.assertRaises(ValueError):read_document(path)

    def test_pdf_text_and_page_images_sent_together_all_protocols(self):
        from PySide6.QtGui import QPdfWriter,QPainter,QFont
        from agentnik import core
        with tempfile.TemporaryDirectory() as root:
            pdf = Path(root)/'example.pdf'; writer=QPdfWriter(str(pdf)); painter=QPainter(writer)
            painter.setFont(QFont('Arial',18)); painter.drawText(100,300,'Document evidence'); painter.end(); del writer
            text=read_document(pdf); self.assertIn('Document evidence',text); self.assertIn('[Page 1]',text)
            pages=pdf_images(pdf);self.assertEqual(len(pages),1);self.assertTrue(pages[0].startswith(b'\x89PNG'))
            image=Path(root)/'page.png';image.write_bytes(pages[0])
            message={'role':'user','text':'Explain','images':[str(image)],'documents':[{'name':pdf.name,'text':text}]}
            for protocol in ('chat','responses','messages'):
                body=core.chat_body({'url':'https://example.com/v1','model':'vision','protocol':protocol},[message])
                content=body.get('input',body.get('messages'))[0]['content']
                self.assertIn('Document evidence',content[0]['text']);self.assertEqual(len(content),2)
            from agentnik.ollama_tools import history_messages
            native=history_messages([message])[0];self.assertIn('Document evidence',native['content']);self.assertEqual(len(native['images']),1)

    def test_chat_drafts_saved_prompts_reopen_remove_and_preview(self):
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik.document_ui import DocumentReader
        with tempfile.TemporaryDirectory() as root,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}),patch('agentnik.core.models',return_value=[]):
            store=Store(root);store.config['connections']={'local':{'url':'http://localhost:11434/v1','model':'one'}};window=Window(store)
            try:
                window.new_session('chat','local');tab=window.tabs.currentWidget()
                doc={'name':'notes.md','text':'Document: notes.md\n[Lines 1-1]\nEvidence'}
                tab.documents=[doc];tab.refresh_documents();tab.save_draft()
                loaded=next(s for s in store.list_sessions() if s['id']==tab.session['id']);self.assertEqual(loaded['draft_documents'],[doc])
                self.assertIn('documents',store.prompt_json('chat',tab.current_prompt()))
                with patch('agentnik.ui.confirm',return_value=True):tab.copy_prompt({'text':'again','images':[],'documents':[doc]})
                self.assertEqual(tab.documents,[doc]);tab.remove_document(0);self.assertFalse(tab.documents)
                dlg=DocumentReader(tab);dlg.loaded((doc,[]));self.assertTrue(dlg.insert.isEnabled());self.assertIn('Evidence',dlg.preview.toPlainText());dlg.close()
                with self.assertRaises(ValueError):validate_documents([doc]*5)
                self.assertEqual(message_text({'text':'normal'}),'normal')
            finally:window.close();self.app.processEvents();store.db.close()
