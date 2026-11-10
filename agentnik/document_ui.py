"""Local preview before explicitly inserting document text into a Chat draft."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QPlainTextEdit, QFileDialog, QDialogButtonBox, QCheckBox
from pathlib import Path
from .document_reader import read_document, pdf_images, MAX_FILE


class DocumentReader(QDialog):
    def __init__(self, parent=None, path=None):
        super().__init__(parent)
        from .ui import Job
        self.Job = Job; self.job = None
        self.setWindowTitle(self.tr('Document Reader')); self.resize(740, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr('Read locally, review, then attach to your draft. Sending shares this text with the selected model.')))
        self.pdf_visual = QCheckBox(self.tr('PDF: attach page images alongside extracted text (multimodal model required; up to 12 pages)')); self.pdf_visual.setChecked(True); layout.addWidget(self.pdf_visual)
        self.open_button = QPushButton(self.tr('Open document…')); layout.addWidget(self.open_button)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True); layout.addWidget(self.preview, 1)
        self.status = QLabel(self.tr('Text, PDF, DOCX, XLSX · 10 MB file / 48,000 characters / 100 PDF pages. No OCR.'))
        self.status.setWordWrap(True); layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.insert = buttons.addButton(self.tr('Attach document'), QDialogButtonBox.ButtonRole.AcceptRole)
        self.insert.setEnabled(False); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons); self.open_button.clicked.connect(self.open_document)
        if path: QTimer.singleShot(0,lambda:self.open_document(path))

    def open_document(self, path=None):
        if not path: path, _ = QFileDialog.getOpenFileName(self, self.tr('Open document'), '', 'Documents (*.txt *.md *.csv *.json *.log *.rst *.pdf *.docx *.xlsx)')
        if not path: return
        self.pdf_visual.setEnabled(False)
        self.preview.clear(); self.insert.setEnabled(False); self.open_button.setEnabled(False)
        self.status.setText(self.tr('Reading locally…'))
        visual = self.pdf_visual.isChecked() and Path(path).suffix.lower() == '.pdf'
        def extract(progress, cancel):
            with open(path, 'rb') as stream: data = stream.read(MAX_FILE + 1)
            pages = pdf_images(path, data) if visual else []
            try: text = read_document(path, data)
            except ValueError as exc:
                if pages and str(exc).startswith('No readable text'):
                    text = 'Document: ' + Path(path).name + '\nNo extractable text; see attached page images in page order.'
                else: raise
            return {'name':Path(path).name, 'text':text}, pages
        self.job = self.Job(extract, self.loaded, self.failed)

    def loaded(self, result):
        self.document, self.pages = result
        text = self.document['text']
        self.job = None; self.open_button.setEnabled(True); self.pdf_visual.setEnabled(True)
        self.preview.setPlainText(text); self.insert.setEnabled(True)
        self.status.setText(self.tr('Review the extracted text. PDF page images: {count}. Formulas are not evaluated.').format(count=len(self.pages)))

    def failed(self, message):
        self.job = None; self.open_button.setEnabled(True); self.pdf_visual.setEnabled(True); self.status.setText(message)
