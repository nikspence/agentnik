"""Qt desktop interface. Network jobs never run on the GUI thread."""
import copy
import json
import os
import shutil
from pathlib import Path
import sys
import threading
import uuid
import argparse
import datetime
import math
import time

from PySide6.QtCore import Qt, Signal, QObject, QTimer, QByteArray, QBuffer, QIODevice, QEvent, QCoreApplication, QSize, QRectF
from PySide6.QtGui import QAction, QColor, QPainter, QPixmap, QIcon, QDesktopServices, QPalette, QShortcut, QKeySequence, QTextCursor, QCursor, QGuiApplication
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox, QCheckBox,
    QSpinBox, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QTabWidget, QSplitter,
    QScrollArea, QFrame, QFileDialog, QMessageBox, QInputDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QStackedWidget, QAbstractItemView, QSizePolicy, QToolButton, QStyle)

from . import core, research, routing, tls
from .citations import cited_markdown
from .research_ui import WebSettings, ResearchDetails, ResearchLimitsDialog, policy_label
from .tools import chat_limits
from .storage import Store
from .repositories import RepositoryRegistry
from .code_ui import RepositoryPicker, CodeTab
from . import localization
from .selection_scroll import SelectionScroll

class WebAccessSwitch(QCheckBox):
    """Keyboard-accessible checkable control drawn as an on/off switch."""
    def sizeHint(self):
        height=max(22,self.fontMetrics().height()+6)
        return QSize(height*2+self.fontMetrics().horizontalAdvance(self.text())+12,height)
    def minimumSizeHint(self):return self.sizeHint()
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        height=min(self.height()-4,max(18,self.fontMetrics().height()+2));width=height*2;y=(self.height()-height)/2
        label_width=self.fontMetrics().horizontalAdvance(self.text());track_x=label_width+10
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText));painter.drawText(QRectF(0,0,label_width,self.height()),int(Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft),self.text())
        track=QRectF(track_x,y,width,height)
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor('#c83545') if self.isChecked() else self.palette().color(QPalette.ColorRole.Mid));painter.drawRoundedRect(track,height/2,height/2)
        painter.setBrush(QColor('white'));knob=height-4;x=track_x+width-knob-2 if self.isChecked() else track_x+2;painter.drawEllipse(QRectF(x,y+2,knob,knob))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(self.palette().color(QPalette.ColorRole.Highlight));painter.drawRoundedRect(QRectF(.5,.5,self.width()-1,self.height()-1),3,3)

class Signals(QObject):
    progress = Signal(object)
    done = Signal(object)
    error = Signal(str)

class Job:
    def __init__(self, fn, done, error, progress=None):
        self.signals = Signals(); self.cancel = threading.Event()
        self.signals.done.connect(done); self.signals.error.connect(error)
        if progress: self.signals.progress.connect(progress)
        def work():
            try: result = fn(self.signals.progress.emit, self.cancel)
            except Exception as exc:
                try: self.signals.error.emit(str(exc))
                except RuntimeError: pass
            else:
                try: self.signals.done.emit(result)
                except RuntimeError: pass
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

def button(text, fn, layout=None):
    b = QPushButton(text); b.clicked.connect(fn)
    if layout: layout.addWidget(b)
    return b

def error(parent, message): QMessageBox.warning(parent, 'Agentnik', str(message))

def confirm(parent, text):
    return QMessageBox.question(parent, 'Agentnik', text, QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget(): item.widget().deleteLater()
        elif item.layout(): clear_layout(item.layout())

def number(value, suffix=''):
    return '—' if value is None else f'{value:,.2f}{suffix}' if isinstance(value, float) else f'{value:,}{suffix}'

def metrics_text(m):
    parts = [QCoreApplication.translate('Metrics','Prompt {value} tokens').format(value=number(m.get('input_tokens'))),QCoreApplication.translate('Metrics','Generation {value} tokens').format(value=number(m.get('output_tokens')))]
    for template, key in [(QCoreApplication.translate('Metrics','Prompt {value} tok/s'), 'prompt_tps'), (QCoreApplication.translate('Metrics','Generation {value} tok/s'), 'generation_tps')]:
        if m.get(key) is not None: parts.append(template.format(value=number(m[key])))
    if m.get('prompt_tps') is None or m.get('generation_tps') is None:
        total_rate = core.total_token_rate(m)
        parts.append(QCoreApplication.translate('Metrics','Overall {value} tok/s (input + output / elapsed)').format(value=number(total_rate)))
    parts.extend([QCoreApplication.translate('Metrics','Thinking {value} s (arrival estimate)').format(value=number(m.get('thinking_seconds_estimate'))),QCoreApplication.translate('Metrics','Total {value} s').format(value=number(m.get('total_seconds')))])
    if 'model_requests' in m:
        parts.extend([QCoreApplication.translate('Metrics','{count} model request(s)').format(count=m['model_requests']),QCoreApplication.translate('Metrics','Managed tools {value} s').format(value=number(m.get('tool_seconds')))])
        if not m.get('usage_complete',False): parts.append(QCoreApplication.translate('Metrics','Known usage only'))
    return ' · '.join(parts)

class MessageText(QTextBrowser):
    """A selectable rich-text document sized to its full wrapped content."""
    def __init__(self, text='', markdown=False):
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet('QTextBrowser { background: transparent; border: none; padding: 0px; }')
        self.setOpenLinks(False); self.setOpenExternalLinks(False)
        self.anchorClicked.connect(lambda url:QDesktopServices.openUrl(url) if url.scheme() in ('https','http') else None)
        self.document().setDocumentMargin(2)
        self.document().setDefaultStyleSheet('pre { white-space: pre-wrap; }')
        self._fit_timer = QTimer(self); self._fit_timer.setSingleShot(True); self._fit_timer.timeout.connect(self.fit_content)
        self.document().documentLayout().documentSizeChanged.connect(self.schedule_fit)
        self.set_content(text,markdown)
    def set_content(self,text,markdown=False):
        if markdown:
            self.setMarkdown(text)
            # Qt imports fenced code as unbreakable preformatted lines. Allow
            # wrapping so long code stays visible without an inner scrollbar.
            block = self.document().begin()
            while block.isValid():
                format = block.blockFormat()
                if format.nonBreakableLines():
                    format.setNonBreakableLines(False); QTextCursor(block).setBlockFormat(format)
                block = block.next()
        else: self.setPlainText(text)
        self.schedule_fit()
    def schedule_fit(self,*_): self._fit_timer.start(0)
    def fit_content(self):
        width = max(1,self.viewport().width())
        if self.document().textWidth() != width: self.document().setTextWidth(width)
        margins = self.contentsMargins()
        height = math.ceil(self.document().size().height())+margins.top()+margins.bottom()+2*self.frameWidth()+2
        if self.height() != height: self.setFixedHeight(height)
    def showEvent(self,event):
        super().showEvent(event)
        if not hasattr(self, '_selection_scroll'):
            parent = self.parentWidget()
            while parent is not None and not isinstance(parent, QScrollArea): parent = parent.parentWidget()
            if parent is not None: self._selection_scroll = SelectionScroll(self, parent)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'_fit_timer'): self.schedule_fit()
    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and hasattr(self,'_fit_timer'):
            self.document().setDefaultFont(self.font()); self.schedule_fit()

class ImagePreview(QDialog):
    """Resizable, aspect-preserving preview of an image stored with a message."""
    def __init__(self,path,parent=None):
        super().__init__(parent); self.setWindowTitle(self.tr('Image preview'))
        self.image=QPixmap(path)
        if self.image.isNull():raise ValueError(self.tr('The image could not be opened.'))
        layout=QVBoxLayout(self); self.preview=QLabel(); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setAccessibleName(self.tr('Image preview')); self.preview.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        self.preview.setMinimumSize(1,1);layout.addWidget(self.preview,1)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);controls.rejected.connect(self.reject);layout.addWidget(controls)
        screen=self.screen() or QApplication.primaryScreen()
        available=screen.availableGeometry() if screen else None
        self.resize(min(900,round(available.width()*.9)) if available else 900,min(700,round(available.height()*.9)) if available else 700)
        self.update_image()
    def update_image(self):
        size=self.preview.size()
        if size.width()>1 and size.height()>1:
            self.preview.setPixmap(self.image.scaled(size,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    def resizeEvent(self,event):
        super().resizeEvent(event);self.update_image()


class MessageBubble(QFrame):
    def __init__(self,message,live=False):
        super().__init__(); self.research_data=message.get('research',{}); self.role = message['role']; self.live = live; self._thinking_seen = False
        self._initial_thinking_visible = message.get('thinking_visible',live)
        self.setObjectName('userBubble' if self.role == 'user' else 'assistantBubble')
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self); layout.setContentsMargins(14,10,14,10); layout.setSpacing(6)
        heading = QLabel(self.tr('You') if self.role == 'user' else self.tr('Assistant')); heading.setStyleSheet('font-weight: bold;')
        self.header = QHBoxLayout(); self.header.addWidget(heading); self.header.addStretch(); layout.addLayout(self.header)
        if self.role == 'assistant':
            self.copy_button = QPushButton('⧉'); self.copy_button.setAccessibleName(self.tr('Copy response')); self.copy_button.setToolTip(self.tr('Copy response'))
            self.copy_button.clicked.connect(lambda:QApplication.clipboard().setText(self.response_text)); self.header.addWidget(self.copy_button)
        self.thinking_toggle = QPushButton(self.tr('Show thinking')); self.thinking_toggle.setCheckable(True)
        self.thinking_toggle.setSizePolicy(QSizePolicy.Policy.Maximum,QSizePolicy.Policy.Fixed)
        self.thinking_toggle.toggled.connect(self.toggle_thinking); layout.addWidget(self.thinking_toggle)
        self.thinking_view = MessageText(); self.thinking_view.setObjectName('thinkingText'); layout.addWidget(self.thinking_view)
        self.text = MessageText(); layout.addWidget(self.text)
        self.image_layout=QVBoxLayout(); layout.addLayout(self.image_layout); self.image_paths=[]
        self.set_images(message.get('images',[]))
        if message.get('metrics'):
            label = QLabel(metrics_text(message['metrics'])); label.setObjectName('metrics'); label.setWordWrap(True); layout.addWidget(label)
        self.set_stream(message.get('text',''),message.get('thinking',''))
        self.restyle()
    def set_images(self,paths):
        if list(paths)==self.image_paths:return
        clear_layout(self.image_layout); self.image_paths=list(paths)
        for index,path in enumerate(paths,1):
            frame=QWidget();column=QVBoxLayout(frame);column.setContentsMargins(0,0,0,0);column.setSpacing(3)
            label=QLabel();label.setPixmap(QPixmap(path).scaled(280,180,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation));column.addWidget(label)
            controls=QHBoxLayout();column.addLayout(controls)
            preview=QToolButton();preview.setObjectName('previewChatImage');preview.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView));preview.setToolTip(self.tr('Preview image'));preview.setAccessibleName(self.tr('Preview image'));preview.clicked.connect(lambda checked=False,p=path:self.preview_image(p));controls.addWidget(preview)
            save=QToolButton();save.setObjectName('saveChatImage');save.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton));save.setToolTip(self.tr('Save image'));save.setAccessibleName(self.tr('Save image'));save.clicked.connect(lambda checked=False,p=path,n=index:self.save_image(p,n));controls.addWidget(save)
            controls.addStretch();self.image_layout.addWidget(frame)
    def preview_image(self,path):
        try:ImagePreview(path,self).exec()
        except (ValueError,OSError) as exc:error(self,exc)
    def save_image(self,path,index=1):
        suffix=Path(path).suffix.lower()
        formats={'.png':('PNG image (*.png)',('.png',)),'.jpg':('JPEG image (*.jpg *.jpeg)',('.jpg','.jpeg')),'.jpeg':('JPEG image (*.jpg *.jpeg)',('.jpg','.jpeg')),'.webp':('WebP image (*.webp)',('.webp',)),'.gif':('GIF image (*.gif)',('.gif',))}
        file_filter,extensions=formats.get(suffix,('Images (*)',(suffix,)))
        target,_=QFileDialog.getSaveFileName(self,self.tr('Save image'),f'agentnik-image-{index}{suffix}',file_filter)
        if not target:return
        destination=Path(target)
        if not destination.suffix and suffix:destination=destination.with_suffix(suffix)
        if destination.suffix.lower() not in extensions:
            return error(self,self.tr('Choose a filename matching the original image format.'))
        try:shutil.copyfile(path,destination)
        except (OSError,shutil.Error) as exc:error(self,self.tr('Could not save image: {reason}').format(reason=str(exc)))
    def toggle_thinking(self,visible):
        self.thinking_view.setVisible(visible); self.thinking_toggle.setText(self.tr('Hide thinking') if visible else self.tr('Show thinking'))
    def set_stream(self,text,thinking,research_data=None):
        self.response_text=text
        if self.role == 'assistant': self.copy_button.setEnabled(bool(text))
        if research_data is not None: self.research_data=research_data
        has_thinking = bool(thinking)
        self.thinking_toggle.setVisible(has_thinking)
        self.thinking_view.set_content(thinking)
        if has_thinking and not self._thinking_seen:
            self._thinking_seen = True; self.thinking_toggle.setChecked(self._initial_thinking_visible)
        self.thinking_view.setVisible(has_thinking and self.thinking_toggle.isChecked())
        display=cited_markdown(text,self.research_data) if self.role=='assistant' and self.research_data else text
        self.text.set_content(display,self.role == 'assistant')
        self.text.setVisible(bool(text))
    def restyle(self):
        if getattr(self,'_restyling',False): return
        palette = QApplication.palette()
        base = palette.color(QPalette.ColorRole.Base)
        tint = palette.color(QPalette.ColorRole.Highlight if self.role == 'user' else QPalette.ColorRole.Text)
        weight = .15 if self.role == 'user' else .055
        color = QColor(*[round((1-weight)*a+weight*b) for a,b in zip(base.getRgb()[:3],tint.getRgb()[:3])])
        text_color=palette.color(QPalette.ColorRole.Text); subdued=QColor(*[round(.7*a+.3*b) for a,b in zip(text_color.getRgb()[:3],color.getRgb()[:3])])
        style = f'QFrame#{self.objectName()} {{ background-color: {color.name()}; border: 1px solid palette(mid); border-radius: 12px; }} QTextEdit#thinkingText {{ color: {subdued.name()}; font-size: {max(1, QApplication.font().pointSizeF() * .9):.1f}pt; }}'
        if self.styleSheet() != style:
            self._restyling = True
            try: self.setStyleSheet(style)
            finally: self._restyling = False
    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange,QEvent.Type.ApplicationPaletteChange,QEvent.Type.ApplicationFontChange) and hasattr(self,'role'): self.restyle()

class AttachmentBox(QWidget):
    changed = Signal()
    def __init__(self, store):
        super().__init__(); self.store = store; self.paths = []; self.setAcceptDrops(True)
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0)
        self.list = QListWidget(); self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(__import__('PySide6.QtCore', fromlist=['QSize']).QSize(70,55)); self.list.setMaximumHeight(88)
        self.list.itemDoubleClicked.connect(lambda item: QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole))))
        outer.addWidget(self.list); row = QHBoxLayout(); self.controls = row; outer.addLayout(row)
        button(self.tr('Attach images…'), self.choose, row); button(self.tr('Paste image'), self.paste, row); button(self.tr('Remove selected'), self.remove, row)
        row.addStretch(); self.refresh()
    def refresh(self):
        self.list.clear(); self.list.setVisible(bool(self.paths))
        for i, p in enumerate(self.paths):
            item = QListWidgetItem(QIcon(p), self.tr('Image {number}').format(number=i+1)); item.setToolTip(p); item.setData(Qt.ItemDataRole.UserRole, p); self.list.addItem(item)
    def set_paths(self, paths): self.paths = list(paths); self.refresh()
    def add(self, paths):
        try:
            for path in paths:
                image = QPixmap(path)
                if image.isNull(): raise ValueError(self.tr('Cannot read image: {name}').format(name=Path(path).name))
                core.image_block(path, 'chat')
                stored = self.store.attach(path)
                if stored not in self.paths: self.paths.append(stored)
            self.refresh(); self.changed.emit()
        except Exception as exc: error(self, exc)
    def choose(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.tr('Attach images'), '', self.tr('Images (*.png *.jpg *.jpeg *.webp *.gif)')); self.add(paths)
    def paste(self):
        image = QApplication.clipboard().image()
        if image.isNull(): return error(self, self.tr('The clipboard does not contain an image.'))
        self.add_image(image)
    def add_image(self, image):
        if isinstance(image, QPixmap): image = image.toImage()
        if image.isNull(): return error(self, self.tr('The supplied image could not be read.'))
        buf = QBuffer(); buf.open(QIODevice.OpenModeFlag.WriteOnly); image.save(buf, 'PNG')
        self.paths.append(self.store.attach(data=bytes(buf.data()))); self.refresh(); self.changed.emit()
    def remove(self):
        selected = {x.data(Qt.ItemDataRole.UserRole) for x in self.list.selectedItems()}
        self.paths = [p for p in self.paths if p not in selected]; self.refresh(); self.changed.emit()
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dropEvent(self, event): self.add([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

class Composer(QPlainTextEdit):
    send = Signal()
    attach = Signal(object)
    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.send.emit(); return
        super().keyPressEvent(e)
    def insertFromMimeData(self, source):
        if source.hasUrls(): self.attach.emit([u.toLocalFile() for u in source.urls() if u.isLocalFile()])
        elif source.hasImage(): self.attach.emit(source.imageData())
        else: super().insertFromMimeData(source)

class Pie(QWidget):
    colors = ['#e34b59','#20b9a0','#f4ae55','#ec7597','#aa83ed','#54b4e5','#a7c957']
    def __init__(self, values):
        super().__init__(); self.values = values; self.setMinimumHeight(220)
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(190, self.height()-20); x = 10; y = 10; start = 90*16
        for i, (label, value) in enumerate(self.values.items()):
            painter.setBrush(QColor(self.colors[i % len(self.colors)])); painter.setPen(Qt.PenStyle.NoPen)
            span = round(-value*360*16); painter.drawPie(x,y,size,size,start,span); start += span
            painter.setPen(self.palette().color(QPalette.ColorRole.Text))
            painter.drawText(size+30, 25+i*23, f'{label}  {value:.1%}')
        painter.end()

class DecisionResult(QWidget):
    def __init__(self, raw):
        super().__init__(); layout = QVBoxLayout(self)
        for name, answer in raw.get('answers', {}).items():
            title = answer.get('choice', answer.get('score', answer.get('noul', '')))
            heading = QLabel(f'{name} · {title}'); heading.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(heading)
            values = answer.get('probabilities', {})
            if 'noul' in answer: values = {'No':1-answer['noul'], 'Yes':answer['noul']}
            if isinstance(values, list): values = {str(i):v for i,v in enumerate(values)}
            if isinstance(values, dict) and values:
                safe = {str(k):float(v) for k,v in values.items() if isinstance(v, (int,float)) and 0 <= v <= 1}
                legend = answer.get('legend',{})
                if isinstance(legend,dict): safe = {str(legend.get(k,k)):v for k,v in safe.items()}
                if 'noul' in answer:
                    safe = {(self.tr('No') if k=='No' else self.tr('Yes') if k=='Yes' else k):v for k,v in safe.items()}
                stack = QStackedWidget(); bars = QWidget(); bar_layout = QVBoxLayout(bars)
                for label, probability in safe.items():
                    row = QHBoxLayout(); row.addWidget(QLabel(label)); bar = QProgressBar(); bar.setRange(0,10000); bar.setValue(round(probability*10000)); bar.setFormat(f'{probability:.2%}'); row.addWidget(bar, 1); bar_layout.addLayout(row)
                stack.addWidget(bars)
                if answer.get('type') == 'choice' and abs(sum(safe.values())-1) < .02 and len(safe) <= 26:
                    pie = Pie(safe); pie.setMinimumHeight(max(220, len(safe)*23+20)); stack.addWidget(pie)
                    toggle = QPushButton(self.tr('Show pie chart')); toggle.setCheckable(True)
                    def switch(checked, stack=stack, toggle=toggle):
                        stack.setCurrentIndex(1 if checked else 0); toggle.setText(self.tr('Show probability bars') if checked else self.tr('Show pie chart'))
                    toggle.toggled.connect(switch); layout.addWidget(toggle)
                layout.addWidget(stack)
            if 'confidence' in answer: layout.addWidget(QLabel(self.tr('Confidence: {value}').format(value=f'{answer["confidence"]:.2%}')))

class WheelGuardCombo(QComboBox):
    def wheelEvent(self,event):
        if self.hasFocus(): super().wheelEvent(event)
        else: event.ignore()

class QuestionEditor(QFrame):
    changed = Signal()
    removed = Signal(object)
    def __init__(self, data=None):
        super().__init__(); self.setObjectName('questionCard'); outer = QVBoxLayout(self)
        row = QHBoxLayout(); outer.addLayout(row)
        self.name = QLineEdit(); self.name.setPlaceholderText(self.tr('Question name, e.g. urgency')); row.addWidget(self.name)
        self.kind = WheelGuardCombo(); self.kind.setFocusPolicy(Qt.FocusPolicy.ClickFocus); self.kind.addItem(self.tr('Yes / No'), 'noul'); self.kind.addItem(self.tr('Multiple choice'), 'choice'); self.kind.addItem(self.tr('Ordered score'), 'score'); row.addWidget(self.kind)
        button(self.tr('Remove question'), lambda: self.removed.emit(self), row)
        self.instructions = QPlainTextEdit(); self.instructions.setPlaceholderText(self.tr('What should the model decide?')); self.instructions.setMaximumHeight(75); outer.addWidget(self.instructions)
        self.criteria = QWidget(); criteria_layout = QVBoxLayout(self.criteria); criteria_layout.setContentsMargins(0,0,0,0)
        self.table = QTableWidget(0,2); self.table.setHorizontalHeaderLabels([self.tr('Label'), self.tr('Description / scoring level (lowest first)')]); self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch); self.table.setMaximumHeight(180); criteria_layout.addWidget(self.table)
        buttons = QHBoxLayout(); criteria_layout.addLayout(buttons); button(self.tr('Add option'), self.add_option, buttons); button(self.tr('Remove option'), self.remove_option, buttons); buttons.addStretch(); outer.addWidget(self.criteria)
        self.kind.currentIndexChanged.connect(self.type_changed)
        self.name.textChanged.connect(self.changed); self.instructions.textChanged.connect(self.changed); self.table.itemChanged.connect(self.changed)
        if data:
            self.name.setText(data['name']); self.instructions.setPlainText(data['instructions']); self.kind.setCurrentIndex(max(0, self.kind.findData(data['type'])))
            for pair in data.get('choices', []): self.add_option(pair)
        self.type_changed()
    def type_changed(self):
        self.criteria.setVisible(self.kind.currentData() != 'noul'); self.table.setColumnHidden(0, self.kind.currentData() == 'score'); self.changed.emit()
    def add_option(self, pair=None):
        if not isinstance(pair, (list,tuple)): pair = ('','')
        i = self.table.rowCount(); self.table.insertRow(i)
        for j, value in enumerate(pair): self.table.setItem(i,j,QTableWidgetItem(value))
        self.changed.emit()
    def remove_option(self):
        if self.table.currentRow() >= 0: self.table.removeRow(self.table.currentRow()); self.changed.emit()
    def value(self):
        return dict(name=self.name.text().strip(), instructions=self.instructions.toPlainText(), type=self.kind.currentData(), choices=[[(self.table.item(i,j).text() if self.table.item(i,j) else '') for j in range(2)] for i in range(self.table.rowCount())])

class ConnectionDialog(QDialog):
    def __init__(self, parent, name='', data=None):
        super().__init__(parent); self.setWindowTitle(self.tr('Connection')); self.resize(560,420); c = data or {}; layout = QFormLayout(self)
        self.fields = {}
        for key, label in [('name',self.tr('Name')),('url',self.tr('Endpoint URL')),('api_key',self.tr('API key')),('model',self.tr('Default model')),('reasoning',self.tr('Reasoning effort (optional)'))]:
            edit = QLineEdit(name if key == 'name' else c.get(key, '')); self.fields[key] = edit; layout.addRow(label, edit)
        self.fields['api_key'].setEchoMode(QLineEdit.EchoMode.Password)
        self.protocol = QComboBox(); self.protocol.addItems(core.PROTOCOLS); self.protocol.setCurrentText(c.get('protocol','responses')); layout.addRow(self.tr('Chat protocol'),self.protocol)
        self.route_hint=QLabel();self.route_hint.setWordWrap(True);self.route_hint.setTextFormat(Qt.TextFormat.PlainText);layout.addRow(self.route_hint)
        self.fields['url'].textChanged.connect(self.update_route_hint);self.protocol.currentTextChanged.connect(self.update_route_hint);self.update_route_hint()
        self.service_tier=QComboBox();self.service_tier.setObjectName('connectionServiceTier');self.service_tier.addItem(self.tr('Not specified'),'')
        for tier in ('auto','default','flex','priority','fast','ultrafast','scale'):self.service_tier.addItem(tier,tier)
        self.service_tier.setCurrentIndex(max(0,self.service_tier.findData(c.get('service_tier',''))))
        self.service_tier.setToolTip(self.tr('Optional OpenRouter-compatible request setting. Availability and pricing depend on the model and provider; gateways may not forward it.'))
        layout.addRow(self.tr('Service tier (optional)'),self.service_tier)
        self.context = QSpinBox(); self.context.setRange(0,100000000); self.context.setSpecialValueText(self.tr('Unknown')); self.context.setValue(c.get('context_limit',0)); layout.addRow(self.tr('Context limit (tokens)'),self.context)
        self.stream = QCheckBox(self.tr('Stream chat responses')); self.stream.setChecked(c.get('stream',True)); layout.addRow(self.stream)
        self.plain = QCheckBox(self.tr('Store API key in plaintext instead of OS credential store')); layout.addRow(self.plain)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addRow(buttons)
    def update_route_hint(self,*_):
        connection={'url':self.fields['url'].text(),'protocol':self.protocol.currentText()}
        try:
            mantle=core.direct_mantle(connection)
            text=self.tr('Model catalog: {catalog}\nInference: {inference}\nMantle catalog entries do not establish the model’s inference route. Copy the base URL and select the protocol shown on its AWS model card; routes can use /v1, /openai/v1, or /anthropic/v1. Save separate connections for different routes.').format(catalog=core.models_endpoint(connection),inference=core.endpoint(connection)) if mantle else ''
        except ValueError:mantle=False;text=''
        self.route_hint.setText(text);self.route_hint.setVisible(mantle)

    def value(self):
        c = {k:e.text().strip() for k,e in self.fields.items()}; name = c.pop('name')
        if not name: raise ValueError('Enter a connection name.')
        c.update(protocol=self.protocol.currentText(), context_limit=self.context.value(), stream=self.stream.isChecked())
        if self.service_tier.currentData():c['service_tier']=self.service_tier.currentData()
        core.validate_connections({'connections':{name:c}})
        return name,c

class Connections(QDialog):
    changed = Signal()
    def __init__(self, window):
        super().__init__(window); self.window = window; self.setWindowTitle(self.tr('Connections')); self.resize(800,520)
        layout = QVBoxLayout(self); layout.addWidget(QLabel(self.tr('Saved, environment, and local connections · select an entry to edit or save a copy')))
        self.list = QListWidget(); self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); layout.addWidget(self.list)
        row = QHBoxLayout(); layout.addLayout(row)
        button(self.tr('Add…'), lambda:self.edit(False),row); button(self.tr('Edit / Save copy…'),lambda:self.edit(True),row); button(self.tr('Delete saved'),self.delete,row)
        self.refresh_button = button(self.tr('Refresh discovery'),self.scan,row); button(self.tr('Import…'),self.import_file,row); button(self.tr('Export…'),self.export_file,row)
        self.status = QLabel(''); layout.addWidget(self.status); button(self.tr('Close'),self.accept,layout)
        self.populate()
    def populate(self):
        selected = {x.data(Qt.ItemDataRole.UserRole) for x in self.list.selectedItems()}; self.list.clear()
        for name,c in self.window.connections.items():
            item = QListWidgetItem(f'{name}\n{c.get("url", "")}  ·  {c.get("model") or self.tr("choose a model")}'); item.setData(Qt.ItemDataRole.UserRole,name); item.setToolTip(c.get("discovery_status","")); self.list.addItem(item); item.setSelected(name in selected)
    def scan(self):
        self.refresh_button.setEnabled(False); self.status.setText(self.tr('Checking loopback endpoints…'))
        def done(found):
            self.window.local = found; self.window.reload_connections(); self.populate(); self.refresh_button.setEnabled(True); self.status.setText(self.tr('{count} local endpoint(s) found.').format(count=len(found)))
        self.job = Job(lambda *_,discover=core.discover:discover(),done,lambda e:(self.refresh_button.setEnabled(True),self.status.setText(e)))
    def edit(self, selected):
        item = self.list.currentItem(); name = item.data(Qt.ItemDataRole.UserRole) if selected and item else ''
        data = self.window.connections.get(name,{})
        if name.startswith(('env:','local:')): name = name.split(':',1)[1]
        dlg = ConnectionDialog(self,name,data)
        while dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                new,c = dlg.value()
                if new in self.window.store.config['connections'] and not confirm(self,self.tr('Replace saved connection “{name}”?').format(name=new)): continue
                self.window.store.save_connection(new,c,dlg.plain.isChecked()); self.window.reload_connections(); self.populate(); return
            except Exception as exc: error(self,exc)
    def delete(self):
        names = [x.data(Qt.ItemDataRole.UserRole) for x in self.list.selectedItems()]
        names = [n for n in names if n in self.window.store.config['connections']]
        if names and confirm(self,self.tr('Delete {count} saved connection(s)?').format(count=len(names))):
            for n in names: self.window.store.delete_connection(n)
            self.window.reload_connections(); self.populate()
    def import_file(self):
        path,_ = QFileDialog.getOpenFileName(self,self.tr('Import connections'),'','JSON (*.json)')
        if not path: return
        try:
            incoming = core.validate_connections(json.loads(Path(path).read_text('utf-8-sig')))
            preview = '\n'.join(f'{n}: {c["url"]}' for n,c in incoming.items())
            if not confirm(self,self.tr('Import these connections?')+'\n\n'+preview): return
            for name,c in incoming.items():
                if name in self.window.store.config['connections']:
                    labels=[self.tr('Skip'),self.tr('Replace'),self.tr('Rename')]
                    if len(set(labels))!=len(labels): raise ValueError(self.tr('Duplicate translated actions; import stopped.'))
                    choice,ok = QInputDialog.getItem(self,self.tr('Duplicate connection'),name,labels,0,False)
                    if not ok or choice not in labels or choice == labels[0]: continue
                    if choice == labels[2]:
                        name,ok = QInputDialog.getText(self,self.tr('Rename connection'),self.tr('New name:'))
                        if not ok: continue
                        if not name.strip() or name in self.window.store.config['connections']: raise ValueError(self.tr('New name must be unique and nonempty.'))
                try: self.window.store.save_connection(name,c)
                except Exception as exc:
                    if not confirm(self,self.tr('Credential store unavailable: {error}\nStore “{name}” with a plaintext key?').format(error=exc,name=name)): continue
                    self.window.store.save_connection(name,c,True)
            self.window.reload_connections(); self.populate()
        except Exception as exc: error(self,exc)

    def export_file(self):
        names = [x.data(Qt.ItemDataRole.UserRole) for x in self.list.selectedItems()]
        if not names: names = list(self.window.connections)
        include = confirm(self,self.tr('Include API keys in the export?\nChoose No to export connection settings without keys.'))
        path,_ = QFileDialog.getSaveFileName(self,self.tr('Export connections'),'connections.json','JSON (*.json)')
        if not path: return
        try:
            result = {n:{k:v for k,v in self.window.connections[n].items() if k != 'credential_id' and (include or k != 'api_key')} for n in names}
            Path(path).write_text(json.dumps({'connections':result},indent=2)+'\n',encoding='utf-8')
        except Exception as exc: error(self,exc)

class SessionStatus(QLabel):
    def __init__(self, tab):
        super().__init__('', tab); self.tab = tab; self.hide()
    def setText(self, text):
        super().setText(text)
        window = self.tab.window
        if hasattr(window, 'tabs') and window.tabs.currentWidget() is self.tab: window.stats()

class SessionTab(QWidget):
    updated = Signal()
    def __init__(self, window, session):
        if session.get('mode')!='chat':raise ValueError('Only chat sessions can be opened as editable conversations')
        super().__init__(); self.window = window; self.store = window.store; self.session = session; self.job = None; self.loading = True; self._closed = False
        self.credentials = {}; self.questions = []; self.partial = None
        interrupted = session.pop('research_pending',None)
        if interrupted:
            value = interrupted['result']; value['status'] = 'failed'
            value['research']['status'] = 'interrupted'
            value['research'].setdefault('events',[]).append({'kind':'interrupted','detail':'Application closed during research; restart explicitly.'})
            session['messages'].extend([dict(interrupted['user'],status='failed'),dict(role='assistant',**value)])
            self.store.save(session)
        self.research_running = False;self.chat_mcp=None

        layout = QVBoxLayout(self); layout.setContentsMargins(18,12,18,12)
        top = QHBoxLayout(); layout.addLayout(top)
        self.connection = QComboBox(); top.addWidget(self.connection,2)
        self.model = QComboBox(); self.model.setEditable(True); self.model.setMinimumWidth(180); top.addWidget(self.model,2)
        self.models_button = button('↻',self.load_models,top); self.models_button.setToolTip(self.tr('Refresh models')); self.models_button.setAccessibleName(self.tr('Refresh models'))
        self.reasoning = QLineEdit(session['connection'].get('reasoning','')); self.reasoning.setPlaceholderText(self.tr('Reasoning effort')); self.reasoning.setMaximumWidth(150)
        if session['mode'] == 'chat': top.addWidget(self.reasoning)
        self.stream = QCheckBox(self.tr('Stream')); self.stream.setChecked(session['connection'].get('stream',True))
        if session['mode'] == 'chat': top.addWidget(self.stream)
        self.info = SessionStatus(self); self.info.setTextFormat(Qt.TextFormat.PlainText)
        if session['mode'] == 'chat':
            web_row = QHBoxLayout()
            self.web_access = window.web_search
            web_row.addStretch()
            mcp_row=QHBoxLayout();mcp_row.addWidget(QLabel(self.tr('MCP server:')))
            self.mcp_choice=QComboBox();self.mcp_choice.setAccessibleName(self.tr('Chat MCP server'));self.mcp_choice.setToolTip(self.tr('Optional server for this chat. MCP tools run without approval and may write data or perform other actions. Tool results are sent to the selected model.'));mcp_row.addWidget(self.mcp_choice,1)
            self.mcp_refresh=button(self.tr('Refresh MCP'),self.refresh_chat_mcp,mcp_row)
            self.mcp_extra_refs=copy.deepcopy(session.get('research_options',{}).get('mcp_extra',[]))
            self.mcp_servers_button=button(self.tr('MCP servers…'),self.choose_chat_mcp_servers,mcp_row)
            self.refresh_chat_mcp();self.mcp_choice.currentIndexChanged.connect(self.chat_mcp_changed)

        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.results_widget = QWidget(); self.results = QVBoxLayout(self.results_widget); self.results.addStretch(); self.scroll.setWidget(self.results_widget)
        self.results.setSpacing(10)
        self._follow_stream = True
        self.results_widget.installEventFilter(self)
        self.scroll.verticalScrollBar().valueChanged.connect(self.track_scroll)
        if session['mode'] == 'chat':
            self.chat_split = QSplitter(Qt.Orientation.Vertical); self.chat_split.setChildrenCollapsible(False); self.chat_split.setHandleWidth(7); layout.addWidget(self.chat_split,1)
            self.chat_split.addWidget(self.scroll)
            self.composer = Composer(); self.composer.setPlaceholderText(self.tr('Message · Ctrl+Enter to send · paste or drop images')); self.composer.setMinimumHeight(48); self.composer.setPlainText(session.get('draft','')); self.chat_split.addWidget(self.composer)
            self.chat_split.setStretchFactor(0,1); self.chat_split.setStretchFactor(1,0)
            self.chat_split.setSizes([600,self.store.config['settings'].get('composer_height',64)])
            self.chat_split.splitterMoved.connect(self.save_composer_height)
            self.attachments = AttachmentBox(self.store); self.attachments.set_paths(session.get('draft_images',[])); layout.addWidget(self.attachments)
            self.composer.send.connect(self.submit); self.composer.attach.connect(self.attach_mime)
            self.documents = copy.deepcopy(session.get('draft_documents', []))
            self.document_row = QHBoxLayout(); layout.addLayout(self.document_row); self.refresh_documents()
            self.composer.textChanged.connect(self.save_draft)
        else:
            split = QSplitter(Qt.Orientation.Horizontal); layout.addWidget(split,1)
            form_scroll = QScrollArea(); form_scroll.setWidgetResizable(True); form_widget = QWidget(); form_layout = QVBoxLayout(form_widget); form_scroll.setWidget(form_widget); split.addWidget(form_scroll); split.addWidget(self.scroll); split.setSizes([520,460])
            form_layout.addWidget(QLabel(self.tr('State / context')))
            self.state = Composer(); self.state.setPlaceholderText(self.tr('Describe the situation, paste JSON, or drop images…')); self.state.setMinimumHeight(100); self.state.setMaximumHeight(200); self.state.setPlainText(session['form'].get('state','')); form_layout.addWidget(self.state)
            self.json_state = QCheckBox(self.tr('Interpret state as JSON')); self.json_state.setChecked(session['form'].get('json_state',False)); form_layout.addWidget(self.json_state)
            self.attachments = AttachmentBox(self.store); self.attachments.set_paths(session['form'].get('images',[])); form_layout.addWidget(self.attachments)
            self.state.attach.connect(self.attach_mime)
            form_layout.addWidget(QLabel(self.tr('Questions · evaluated against the same state')))
            self.question_layout = QVBoxLayout(); form_layout.addLayout(self.question_layout)
            for q in session['form'].get('questions',[]): self.add_question(q)
            if not self.questions: self.add_question({'name':'question_1','instructions':'','type':'noul','choices':[]})
            button(self.tr('＋ Add question'),lambda:self.add_question(),form_layout); form_layout.addStretch()
            self.state.textChanged.connect(self.save_draft); self.json_state.toggled.connect(self.save_draft)
        self.attachments.changed.connect(self.save_draft)
        bottom = QHBoxLayout(); layout.addLayout(bottom)
        self.star_current = button(self.tr('☆ Save prompt'),self.star_draft,bottom); self.star_current.setToolTip(self.tr('Save the current prompt to Prompts'))
        self.send_button = button(self.tr('Run decision') if session['mode'] == 'decision' else self.tr('Send'),self.submit,bottom); self.send_button.setObjectName('primary')
        self.cancel_button = button(self.tr('Cancel'),self.cancel,bottom); self.cancel_button.setEnabled(False); bottom.addStretch()
        if session['mode'] == 'chat':
            self.continue_button=button(self.tr('Continue'),self.continue_chat,bottom);self.continue_button.setObjectName('continueChatRun');self.continue_button.setToolTip(self.tr('Continue the limited run with fresh limits and saved context. Incomplete tool calls are not replayed.'))
            self.context_button=button(self.tr('Context…'),self.edit_chat_context,bottom)
            self.auto_compact=QCheckBox(self.tr('Auto compact'));self.auto_compact.setChecked(session.get('chat_auto_compact',True));self.auto_compact.setToolTip(self.tr('Before sending, summarize older chat when the estimated context approaches the configured model window. Uses an additional model request.'));bottom.addWidget(self.auto_compact)
            self.auto_compact.toggled.connect(self.save_chat_compaction_setting)
            self.documents_button = QPushButton(self.tr('Documents…')); self.documents_button.clicked.connect(self.read_documents); self.attachments.controls.insertWidget(1,self.documents_button)
        button(self.tr('Export session…'),self.export_session,bottom)
        if session['mode'] == 'chat':layout.addLayout(web_row);layout.addLayout(mcp_row)
        self.refresh_connections(); self.model.setEditText(session['connection'].get('model',''))
        self.connection.currentIndexChanged.connect(self.change_connection)
        self.model.currentTextChanged.connect(self.save_draft); self.reasoning.textChanged.connect(self.save_draft); self.stream.toggled.connect(self.save_draft)
        self.loading = False; self.render(); self.update_current_star(); QTimer.singleShot(0,self.load_models)
    def save_chat_compaction_setting(self,enabled):
        if not self.loading:self.session['chat_auto_compact']=bool(enabled);self.store.save(self.session);self.updated.emit()

    def edit_chat_context(self):
        from .context_compaction import validate_snapshot,MAX_SUMMARY_CHARS
        if self.job:return
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Chat context'));dialog.resize(700,480)
        layout=QVBoxLayout(dialog);snapshot=self.session.get('chat_compaction')
        label=QLabel(self.tr('The saved conversation remains intact. The summary replaces earlier messages in future requests and may omit details. The selected model receives the prior conversation when you compact.'));label.setWordWrap(True);layout.addWidget(label)
        editor=QPlainTextEdit(snapshot['summary'] if snapshot else '');editor.setPlaceholderText(self.tr('No compacted summary'));layout.addWidget(editor)
        actions=QHBoxLayout();layout.addLayout(actions)
        compact=QPushButton(self.tr('Compact now'));save=QPushButton(self.tr('Save summary'));reset=QPushButton(self.tr('Use full history'))
        for control in (compact,save,reset):actions.addWidget(control)
        save.setEnabled(bool(snapshot));reset.setEnabled(bool(snapshot))
        def save_summary():
            try:
                value=dict(snapshot,summary=editor.toPlainText());validate_snapshot(value,self.session['messages'])
            except ValueError as exc:QMessageBox.warning(dialog,self.tr('Chat context'),str(exc));return
            self.session['chat_compaction']=value;self.store.save(self.session);self.updated.emit();dialog.accept()
        def restore():
            self.session.pop('chat_compaction',None);self.store.save(self.session);self.updated.emit();dialog.accept()
        def start():
            dialog.accept();self.compact_chat_context()
        save.clicked.connect(save_summary);reset.clicked.connect(restore);compact.clicked.connect(start);dialog.exec()

    def compact_chat_context(self,auto_send=False):
        from .context_compaction import summary_input,make_snapshot
        if self.job:return
        try:
            connection=self.active_connection()
            if not connection.get('model'):raise ValueError(self.tr('Choose or enter a model first.'))
            messages=copy.deepcopy(self.session['messages']);previous=copy.deepcopy(self.session.get('chat_compaction'))
            candidates=[i+1 for i,m in enumerate(messages) if m.get('role')=='assistant' and core.history_eligible(m)]
            through=candidates[-1] if candidates else 0
            inputs=summary_input(messages,through,previous)
            body=core.chat_body(connection,inputs)
        except (ValueError,OSError) as exc:QMessageBox.warning(self,self.tr('Chat context'),str(exc));return
        self.busy(True);self._compacting=True;self.info.setText(self.tr('Compacting context…'))
        token=uuid.uuid4().hex;self.request_token=token
        def done(result):
            if self._closed or self.request_token!=token:return
            self.job=None;self._compacting=False;self.request_token=None;self.busy(False)
            try:
                summary=research.scrub(result.get('text',''),[connection.get('api_key','')]).strip()
                snapshot=make_snapshot(messages,through,summary)
                from .context_compaction import validate_snapshot
                validate_snapshot(snapshot,self.session['messages'])
                self.session['chat_compaction']=snapshot;self.store.save(self.session);self.updated.emit();self.info.setText(self.tr('Context compacted. Review it with Context…'))
                if auto_send:self._skip_auto_compact_once=True;self.submit()
            except (ValueError,OSError) as exc:self.info.setText(self.tr('Context compaction failed: {reason}').format(reason=str(exc)))
        def failed(message):
            if self._closed or self.request_token!=token:return
            self.job=None;self._compacting=False;self.request_token=None;self.busy(False);self.info.setText(self.tr('Context compaction failed: {reason}').format(reason=message))
        self.job=Job(lambda emit,cancel:core.run_request(connection,'chat',body,lambda _:None,cancel),done,failed)

    def read_documents(self, path=None):
        from .document_ui import DocumentReader
        if self.job: return
        if len(self.documents) >= 4: return error(self,self.tr('Attach up to four documents per prompt.'))
        dlg = DocumentReader(self, path=path if isinstance(path,str) else None)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            paths = [self.store.attach(data=page) for page in dlg.pages]
            if paths: dlg.document['images'] = paths
            self.documents.append(dlg.document)
            self.attachments.paths.extend(paths)
            self.attachments.refresh(); self.refresh_documents(); self.save_draft()

    def refresh_documents(self):
        clear_layout(self.document_row)
        for index, doc in enumerate(self.documents):
            b = button(doc['name'],lambda checked=False,d=doc:self.preview_document(d),self.document_row)
            b.setToolTip(self.tr('Preview document text'))
            button('×',lambda checked=False,i=index:self.remove_document(i),self.document_row)
        self.document_row.addStretch()

    def preview_document(self, doc):
        dlg = QDialog(self); dlg.setWindowTitle(doc['name']); dlg.resize(700,500)
        layout = QVBoxLayout(dlg); text = QPlainTextEdit(); text.setReadOnly(True); text.setPlainText(doc['text']); layout.addWidget(text); dlg.exec()

    def remove_document(self, index):
        if self.job: return
        doc = self.documents.pop(index)
        self.attachments.set_paths([p for p in self.attachments.paths if p not in doc.get('images', [])])
        self.refresh_documents(); self.save_draft()

    def configure_research_limits(self):
        settings=self.store.config['settings'];dialog=ResearchLimitsDialog(self,settings.get('chat_research_limits'))
        if dialog.exec()==QDialog.DialogCode.Accepted:
            settings['chat_research_limits']=dialog.values();self.store.flush()

    def refresh_chat_mcp(self):
        from .mcp_support import server_fingerprint
        ref=self.mcp_choice.currentData() if self.mcp_choice.count() else self.session.get('research_options',{}).get('mcp')
        self.mcp_choice.blockSignals(True);self.mcp_choice.clear();self.mcp_choice.addItem(self.tr('No MCP server'),None)
        for server in self.store.config.get('mcp_servers',[]):
            if server.get('enabled'):
                entry={'name':server['name'],'sha256':server_fingerprint(server)}
                self.mcp_choice.addItem(server['name']+(' · HTTPS' if server.get('transport')=='http' else ' · local'),entry)
        if isinstance(ref,dict):
            index=self.mcp_choice.findData(ref)
            if index<0:self.mcp_choice.addItem(ref.get('name','')+self.tr(' (changed or unavailable; reselect)'),ref);index=self.mcp_choice.count()-1
            self.mcp_choice.setCurrentIndex(index)
        self.mcp_choice.blockSignals(False)

    def chat_mcp_changed(self):
        ref=self.mcp_choice.currentData()
        self.mcp_extra_refs=[item for item in self.mcp_extra_refs if ref and item['name'].casefold()!=ref['name'].casefold()]
        self.save_draft()

    def choose_chat_mcp_servers(self):
        from .mcp_support import server_fingerprint
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('MCP servers'));dialog.resize(560,440);layout=QVBoxLayout(dialog)
        note=QLabel(self.tr('Select up to five servers. The top server takes precedence when tool names conflict. Changes apply to the next run.'));note.setWordWrap(True);layout.addWidget(note)
        items=QListWidget();items.setObjectName('chatMcpOrder');layout.addWidget(items)
        primary=self.mcp_choice.currentData();old=([primary] if primary else [])+list(self.mcp_extra_refs)
        entries={item['name']:item for item in self.store.config.get('mcp_servers',[]) if item.get('enabled')}
        ordered=[ref['name'] for ref in old]+[name for name in entries if name not in {ref['name'] for ref in old}]
        for name in ordered:
            current=entries.get(name);previous=next((ref for ref in old if ref['name']==name),None)
            changed=bool(current and previous and previous['sha256']!=server_fingerprint(current))
            item=QListWidgetItem(name+(self.tr(' (changed; confirm selection)') if changed else self.tr(' (unavailable; uncheck to remove)') if not current else ''))
            item.setData(Qt.ItemDataRole.UserRole,name);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if previous else Qt.CheckState.Unchecked);items.addItem(item)
        actions=QHBoxLayout();layout.addLayout(actions)
        def move(offset):
            row=items.currentRow();target=row+offset
            if 0<=row<items.count() and 0<=target<items.count():items.insertItem(target,items.takeItem(row));items.setCurrentRow(target)
        up=QPushButton(self.tr('Move up'));up.setObjectName('chatMcpMoveUp');up.clicked.connect(lambda:move(-1));actions.addWidget(up)
        down=QPushButton(self.tr('Move down'));down.setObjectName('chatMcpMoveDown');down.clicked.connect(lambda:move(1));actions.addWidget(down);actions.addStretch()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        names=[items.item(i).data(Qt.ItemDataRole.UserRole) for i in range(items.count()) if items.item(i).checkState()==Qt.CheckState.Checked]
        if len(names)>5:QMessageBox.warning(self,self.tr('MCP servers'),self.tr('Select at most five servers total.'));return
        refs=[{'name':name,'sha256':server_fingerprint(entries[name])} if name in entries else next(ref for ref in old if ref['name']==name) for name in names]
        self.mcp_choice.blockSignals(True)
        if refs:
            index=self.mcp_choice.findData(refs[0])
            if index<0:self.mcp_choice.addItem(refs[0]['name']+self.tr(' (changed or unavailable; reselect)'),refs[0]);index=self.mcp_choice.count()-1
            self.mcp_choice.setCurrentIndex(index)
        else:self.mcp_choice.setCurrentIndex(0)
        self.mcp_choice.blockSignals(False);self.mcp_extra_refs=refs[1:];self.save_draft()

    def review_chat_mcp(self,request):
        try:
            if self._closed or request['cancelled'].is_set() or not self.job or self.job.cancel.is_set():return
            dialog=QDialog(self);dialog.setWindowTitle(self.tr('Review MCP request'));dialog.resize(720,500)
            layout=QVBoxLayout(dialog);label=QLabel(self.tr('This server can access data and perform actions. Review the complete request. Tool results may be sent to your selected model.'));label.setWordWrap(True);layout.addWidget(label)
            preview=QPlainTextEdit();preview.setReadOnly(True);preview.setPlainText(json.dumps({'model':self.research_connection.get('model',''),'model_endpoint':self.research_connection.get('url',''),'request':request['proposal']},ensure_ascii=True,indent=2));layout.addWidget(preview)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
            request['approved']=dialog.exec()==QDialog.DialogCode.Accepted and not request['cancelled'].is_set() and bool(self.job) and not self.job.cancel.is_set()
        finally:request['done'].set()

    def complete_research(self,result):
        if hasattr(self,'live_bubble'):
            result=dict(result,thinking_visible=self.live_bubble.thinking_toggle.isChecked())
        if self.chat_mcp:self.chat_mcp.close();self.chat_mcp=None
        self.request_token = None; self.job = None; self.busy(False); self.partial = None; self.research_running = False
        self.session.pop('research_pending',None)
        ok = result.get('status')=='ok'
        user = dict(self.pending,status='ok' if ok else 'failed')
        self.session['messages'].extend([user,dict(role='assistant',**result)])
        if self.session['title']=='New chat': self.session['title']=(self.pending['text'] or 'Web research')[:60]
        capability_state = result['research'].get('capability_state')
        updates=result['research'].get('capability_updates')
        if updates is None and capability_state in ('verified','unsupported'):
            updates=[{'field':'managed_tools','state':capability_state,'evidence':'Structured managed request observed '+capability_state}]
        current=self.active_connection()
        same_context=all(current.get(k)==self.research_connection.get(k) for k in ('url','protocol','model','api_key','reasoning','stream','context_limit','service_tier','_capability_scope'))
        if updates and same_context and self.research_connection.get('_capability_scope'):
            saved=self.store.config.get('connections',{}).get(self.session['connection_name'])
            if saved is not None:saved.setdefault('_capability_scope',self.research_connection['_capability_scope'])
        for update in (updates or []) if same_context else []:
            research.set_capability(self.store.config,self.research_connection,update['state'],update['evidence'],update['field'])
        if updates: self.store.flush()
        if ok and not getattr(self,'_continuing_chat',False): self.composer.clear(); self.attachments.set_paths([]); self.documents = []; self.refresh_documents(); self.save_draft()
        route_label=self.tr('Provider hosted') if result['research'].get('route')=='hosted' else self.tr('Agentnik managed')
        switched=any(e.get('kind')=='route_switch' for e in result['research'].get('events',[]))
        self.info.setText((self.tr('Research completed · {route}').format(route=route_label)+(self.tr(' · Route switched; see Research activity') if switched else '')) if ok else result.get('error',self.tr('Research stopped'))+self.tr(' · Partial work saved; restart explicitly.'))
        if ok and result['research'].get('local_only'): self.info.setText(self.tr('Local tools completed'))
        if ok and result['research'].get('mcp_only'): self.info.setText(self.tr('MCP chat completed'))
        if result['research'].get('retention',{}).get('truncated'):
            self.info.setText(self.info.text()+self.tr(' · Saved research detail limited; start a new chat to continue research.'))
        self.save_draft(); self.render(); self.updated.emit()

    def continue_chat(self):
        if self.job or not self.session['messages']:return
        last=self.session['messages'][-1]
        if last.get('research',{}).get('status')!='limited':return
        self.submit(continuation=True)

    def add_question(self,data=None):
        q = QuestionEditor(data if isinstance(data,dict) else {'name':f'question_{len(self.questions)+1}','instructions':'','type':'noul','choices':[]})
        self.questions.append(q); self.question_layout.addWidget(q); q.changed.connect(self.save_draft); q.removed.connect(self.remove_question); self.save_draft()
    def attach_mime(self, data):
        if isinstance(data, list):
            from .document_reader import SUPPORTED
            images = []
            for path in data:
                if self.session['mode'] == 'chat' and Path(path).suffix.lower() in SUPPORTED:
                    self.read_documents(path)
                else: images.append(path)
            if images: self.attachments.add(images)
        else: self.attachments.add_image(data)
    def remove_question(self,q):
        self.questions.remove(q); self.question_layout.removeWidget(q); q.deleteLater(); self.save_draft()
    def refresh_connections(self):
        self.connection.blockSignals(True); self.connection.clear()
        names = list(self.window.connections)
        name = self.session['connection_name']
        if name not in names: names.insert(0,name)
        for n in names: self.connection.addItem(n,n)
        self.connection.setCurrentIndex(self.connection.findData(name)); self.connection.blockSignals(False)
    def change_connection(self):
        name = self.connection.currentData()
        if name == self.session['connection_name']: return
        self.connection.blockSignals(True); self.connection.setCurrentIndex(self.connection.findData(self.session['connection_name'])); self.connection.blockSignals(False)
        self.window.new_session(self.session['mode'],name)
    def active_connection(self):
        c = dict(self.session['connection']); name = self.session['connection_name']
        saved = self.window.connections.get(name,{})
        # Do not silently attach a key from a renamed/repointed saved connection.
        try: same = core.base_url(saved.get('url','')) == core.base_url(c['url'])
        except ValueError: same = False
        c['api_key'] = self.credentials.get('api_key', saved.get('api_key','') if same else '')
        if same:
            if saved.get('service_tier'):c['service_tier']=saved['service_tier']
            else:c.pop('service_tier',None)
        if 'api_key' in self.credentials:
            c['_capability_scope']=self.credentials.setdefault('_capability_scope',uuid.uuid4().hex)
        elif same and saved.get('_capability_scope'):
            c['_capability_scope']=saved['_capability_scope']
        c.update(model=self.model.currentText().strip(),reasoning=self.reasoning.text().strip(),stream=self.stream.isChecked())
        return c
    def load_models(self):
        if self._closed: return
        c = self.active_connection(); self.models_button.setEnabled(False); self.info.setText(self.tr('Loading models…'))
        def done(names):
            from shiboken6 import isValid
            if not isValid(self) or self._closed: return
            current = self.model.currentText(); self.model.blockSignals(True); self.model.clear(); self.model.addItems(names); self.model.setEditText(current or (names[0] if names else '')); self.model.blockSignals(False); self.save_draft(); self.models_button.setEnabled(True); self.info.setText(self.tr('{count} model(s) available.').format(count=len(names)))
        def failed(e):
            from shiboken6 import isValid
            if isValid(self) and not self._closed: self.models_button.setEnabled(True); self.info.setText(e)
        self.model_job = Job(lambda *_,models=core.models:models(c),done,failed)
    def form_value(self):
        return dict(state=self.state.toPlainText(),json_state=self.json_state.isChecked(),images=list(self.attachments.paths),questions=[q.value() for q in self.questions])
    def current_prompt(self):
        if self.session['mode'] == 'decision': return self.form_value()
        return {'text':self.composer.toPlainText(), 'images':list(self.attachments.paths), 'documents':copy.deepcopy(self.documents)}
    def star_draft(self):
        payload = self.current_prompt()
        if self.session['mode'] == 'chat' and not payload['text'].strip() and not payload['images'] and not payload.get('documents'):
            return error(self,self.tr('Enter a prompt or attach an image first.'))
        if self.session['mode'] == 'decision' and not payload['state'].strip() and not payload['images'] and not any(q['instructions'].strip() for q in payload['questions']):
            return error(self,self.tr('Enter decision context, a question, or attach an image first.'))
        self.window.toggle_prompt(self.session['mode'],payload)
    def copy_prompt(self,payload):
        if self.job: return error(self,self.tr('Wait for the current request to finish before replacing the prompt.'))
        current = self.current_prompt()
        if self.session['mode'] == 'chat':
            occupied = bool(current['text'].strip() or current['images'] or current.get('documents'))
        else:
            occupied = bool(current['state'].strip() or current['images'] or any(q['instructions'].strip() for q in current['questions']))
        if occupied and self.store.prompt_json(self.session['mode'],current) != self.store.prompt_json(self.session['mode'],payload):
            if not confirm(self,self.tr('Replace the current prompt and attachments?')): return
        if self.session['mode'] == 'chat':
            self.loading = True; self.composer.setPlainText(payload['text']); self.attachments.set_paths(payload.get('images',[])); self.documents = copy.deepcopy(payload.get('documents',[])); self.refresh_documents(); self.loading = False; self.save_draft()
            self.composer.setFocus()
        else: self.restore(copy.deepcopy(payload)); self.state.setFocus()
    def save_draft(self,*_):
        if self.loading: return
        self.session['connection'].update(model=self.model.currentText(),reasoning=self.reasoning.text(),stream=self.stream.isChecked())
        if self.session['mode'] == 'chat':
            options=self.session.get('research_options',{})
            self.session.update(draft=self.composer.toPlainText(),draft_images=list(self.attachments.paths),draft_documents=copy.deepcopy(self.documents),research_options={**options,'mcp':copy.deepcopy(self.mcp_choice.currentData()),'mcp_extra':copy.deepcopy(self.mcp_extra_refs)})
        else: self.session['form'] = self.form_value()
        self.store.save(self.session); self.update_current_star(); self.updated.emit()
    def update_current_star(self):
        if not hasattr(self,'star_current'): return
        saved = bool(self.store.prompt_id(self.session['mode'],self.current_prompt()))
        self.star_current.setText(self.tr('★ Saved prompt') if saved else self.tr('☆ Save prompt'))
        self.star_current.setToolTip(self.tr('Remove from Prompts') if saved else self.tr('Save the current prompt to Prompts'))
    def busy(self, value):
        self.send_button.setEnabled(not value); self.cancel_button.setEnabled(value)
        for widget in (self.model,self.reasoning,self.stream,self.models_button,self.attachments): widget.setEnabled(not value)
        if self.session['mode'] == 'chat':
                self.context_button.setEnabled(not value);self.auto_compact.setEnabled(not value); self.documents_button.setEnabled(not value); self.composer.setReadOnly(value); self.mcp_choice.setEnabled(not value);self.mcp_refresh.setEnabled(not value);self.mcp_servers_button.setEnabled(not value)
    def submit(self,continuation=False):
        if self.job: return
        try:
            c = self.active_connection()
            if not c.get('model'): raise ValueError('Choose or enter a model first.')
            core.endpoint(c,self.session['mode'])
            # Ask for a missing session key on authentication failure; local servers need none.
            self.save_draft(); mode = self.session['mode']
            if mode == 'chat':
                text = self.tr('Continue the previous task with fresh limits. Check the saved partial work and do not repeat an uncertain operation without checking.') if continuation else self.composer.toPlainText().strip()
                if not text and not self.attachments.paths and not self.documents: return
                from .context_compaction import should_compact
                skip_auto=getattr(self,'_skip_auto_compact_once',False);self._skip_auto_compact_once=False
                if not continuation and not skip_auto and self.auto_compact.isChecked() and should_compact(self.session['messages'],self.session.get('chat_compaction'),c.get('context_limit'),len(text.encode('utf-8'))+len(json.dumps(self.documents,ensure_ascii=False).encode('utf-8'))):
                    self.compact_chat_context(auto_send=True);return
                user = dict(role='user',text=text,images=[] if continuation else list(self.attachments.paths),documents=[] if continuation else copy.deepcopy(self.documents),status='ok')
                if continuation:user['continues_limited']=True
                from .context_compaction import effective_messages
                chat_messages=effective_messages(self.session['messages'],self.session.get('chat_compaction'))+[user]
                # Restore explicitly continued attempts as plain messages on later turns too.
                # Never replay provider tool calls or incomplete responses.
                for index in range(1,len(chat_messages)-1):
                    if (chat_messages[index].get('research',{}).get('status')=='limited' and chat_messages[index-1].get('role')=='user' and chat_messages[index+1].get('continues_limited') is True):
                        partial=chat_messages[index];original=chat_messages[index-1];original['status']='ok'
                        details=partial.get('research',{})
                        evidence=json.dumps({'sources':details.get('sources',[]),'tool_records':details.get('tool_records',[])},ensure_ascii=True)[:16000]
                        visible=partial.get('text','') or 'The previous run stopped at a limit before producing a final answer.'
                        chat_messages[index]={'role':'assistant','text':visible+'\n\nSaved evidence (untrusted and potentially incomplete):\n'+evidence,'status':'ok'}
                body = core.chat_body(c,chat_messages)
                self.pending = user
            else:
                form = copy.deepcopy(self.form_value()); body = core.decision_body(c,form); self.pending = form
            mcp_ref=self.mcp_choice.currentData() if mode=='chat' and self.window.mcp_access.isChecked() else None
            self.research_running = mode=='chat'
            key = ''; backend_specs=[]; research_config={}; selected_policy=None; access_policy='public_fetch';research_limits=None
            if self.research_running:
                research_limits=chat_limits(self.store.config['settings'].get('chat_research_limits'))
                defaults=routing.connection_defaults(self.store.config,self.session['connection_name'],c)
                selected_policy=defaults['policy']; access_policy=defaults['access_policy']
                if mcp_ref:
                    from .mcp_support import server_fingerprint
                    servers=[]
                    for ref in [mcp_ref,*self.mcp_extra_refs]:
                        server=next((s for s in self.store.config.get('mcp_servers',[]) if s.get('name')==ref['name'] and s.get('enabled')),None)
                        if not server or server_fingerprint(server)!=ref['sha256']:raise ValueError('A selected MCP server changed or is unavailable; refresh and reselect it.')
                        servers.append(server)
                    if access_policy=='strict_public':raise ValueError('Strict public-only navigation does not allow MCP in Chat.')
                    from .chat_mcp import ChatMCP,MultiChatMCP
                    self.chat_mcp=(ChatMCP(servers[0],self.store.config,self,extra_secrets=(c.get('api_key',''),)) if len(servers)==1 else MultiChatMCP(servers,self.store.config,self,extra_secrets=(c.get('api_key',''),)));self.chat_mcp.approval_requested.connect(self.review_chat_mcp)
                research_config={'research_capabilities':copy.deepcopy(self.store.config.get('research_capabilities',{})),'local_tools':True,'web_enabled':self.web_access.isChecked(),'mcp_priority':self.store.config['settings'].get('mcp_priority','first')}
                backend_specs=self.store.web_backend_specs()
                key=next((b['key'] for b in backend_specs if b.get('key')),'')
            image_tool=None
            if self.research_running:
                image_config=self.window.image_tool_config()
                if image_config:
                    from .chat_image import ChatImageTool
                    image_tool=ChatImageTool(image_config,self.store,chat_messages)
            self._continuing_chat=bool(continuation and mode=='chat')
            self.partial = {'text':'','thinking':''}
            self.busy(True); self.info.setText(self.tr('Running…')); self.render()
            token = uuid.uuid4().hex; self.request_token = token
            if self.research_running:
                self.partial['research'] = {'version':1,'run_id':token,'status':'running','sources':[],'events':[],'exchanges':[]}
                self.session['research_pending'] = {'user':self.pending,'result':dict(self.partial,metrics={})}
                self.store.save(self.session)
            research_enabled = self.research_running
            request_messages = copy.deepcopy(chat_messages) if research_enabled else []
            self.research_connection = c
            self.last_research_save = 0
            chat_mcp=self.chat_mcp if mcp_ref else None
            def work(emit,cancel):
                try:
                    return research.run(c,request_messages,key,emit,cancel,limits=research_limits,run_id=token,config=research_config,policy=selected_policy,backends=backend_specs,access_policy=access_policy,mcp=chat_mcp,image_tool=image_tool) if research_enabled else core.run_request(c,mode,body,emit,cancel)
                finally:
                    if chat_mcp:chat_mcp.close()
            self.job = Job(work,
                           lambda value:self.finished(value) if self.request_token == token else None,
                           lambda message:self.failed(message) if self.request_token == token else None,
                           lambda value:self.progress(value) if self.request_token == token else None)
        except Exception as exc: error(self,exc)
    def progress(self,value):
        if self.job and not self.job.cancel.is_set():
            self.partial = value
            if self.research_running and 'research' in value:
                self.session['research_pending'] = {'user':self.pending,'result':value}
                if value['research'].get('events'):
                    latest=value['research']['events'][-1]; self.info.setText(latest.get('kind','Research')+': '+latest.get('detail','')[:180])
                # Save bounded activity snapshots, including partial output, for interrupted sessions.
                signature = (len(value['research'].get('events',[])),len(value['research'].get('sources',[])))
                if signature != getattr(self,'last_research_signature',None) or time.monotonic()-self.last_research_save > .4:
                    self.store.save(self.session); self.last_research_save = time.monotonic(); self.last_research_signature = signature
                if hasattr(self,'live_bubble'):
                    if not hasattr(self.live_bubble,'research_details'):
                        self.live_bubble.research_details = ResearchDetails(); self.live_bubble.layout().addWidget(self.live_bubble.research_details)
                    self.live_bubble.research_details.set_data(value['research'])
            if hasattr(self,'live_bubble'):
                self.live_bubble.set_stream(value['text'],value['thinking'],value.get('research'))
                self.live_bubble.set_images(value.get('images',[]))
            self.follow_stream()
    def finished(self,result):
        if self.research_running: return self.complete_research(result)
        if self.job and self.job.cancel.is_set(): return self.failed('Request cancelled')
        self.job = None; self.busy(False); self.partial = None
        if self.session['mode'] == 'chat':
            thinking_visible = self.live_bubble.thinking_toggle.isChecked()
            self.session['messages'].extend([self.pending,dict(role='assistant',text=result['text'],thinking=result['thinking'],thinking_visible=thinking_visible,metrics=result['metrics'],status='ok')])
            if self.session['title'] == 'New chat': self.session['title'] = (self.pending['text'] or 'Image conversation')[:60]
            if not getattr(self,'_continuing_chat',False):
                self.composer.clear(); self.attachments.set_paths([]); self.documents = []; self.refresh_documents(); self.save_draft()
        else:
            self.session['runs'].append(dict(form=self.pending,result=result))
            if self.session['title'] == 'New decision': self.session['title'] = str(self.pending['state'])[:60]
        self.info.setText(self.tr('Completed')); self.save_draft(); self.render(); self.updated.emit()
    def failed(self,message):
        if self.research_running:
            value = copy.deepcopy(self.partial or {'text':'','thinking':''})
            value.setdefault('research',{'version':1,'sources':[],'events':[],'exchanges':[]})
            value['research']['status'] = 'cancelled' if self.job and self.job.cancel.is_set() else 'failed'
            value['research'].setdefault('events',[]).append({'kind':value['research']['status'],'detail':message})
            value.update(status='failed',error=message,metrics=value.get('metrics',{}))
            return self.complete_research(value)
        cancelled = self.job and self.job.cancel.is_set(); self.job = None; self.busy(False); self.partial = None
        self.info.setText(self.tr('Cancelled. The server may still finish processing.') if cancelled else message)
        if not cancelled and ('401' in message or '403' in message):
            key,ok = QInputDialog.getText(self,self.tr('Endpoint authentication'),self.tr('API key for this tab (not saved):'),QLineEdit.EchoMode.Password)
            if ok:
                self.credentials['api_key'] = key
                self.credentials['_capability_scope'] = uuid.uuid4().hex
        self.render()
    def cancel(self):
        if self.job:
            if getattr(self,'_compacting',False):
                self.job.cancel.set();self.job=None;self._compacting=False;self.request_token=None;self.busy(False);self.info.setText(self.tr('Context compaction cancelled.'));return
            if self.chat_mcp:self.chat_mcp.close();self.chat_mcp=None
            self.job.cancel.set(); self.request_token = None; self.failed('Request cancelled')
    def save_composer_height(self,*_):
        if not self.loading:
            self.store.config['settings']['composer_height'] = self.chat_split.sizes()[1]; self.store.flush()
    def track_scroll(self,value):
        self._follow_stream = self.scroll.verticalScrollBar().maximum()-value < 32
    def follow_stream(self):
        if self._follow_stream:
            self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
    def eventFilter(self,watched,event):
        if watched is self.results_widget and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0,self.follow_stream)
        return super().eventFilter(watched,event)
    def add_bubble(self,message,live=False):
        row = QWidget(); line = QHBoxLayout(row)
        line.setContentsMargins(64 if message['role']=='user' else 4,0,4 if message['role']=='user' else 64,0)
        bubble = MessageBubble(message,live); line.addWidget(bubble); self.results.addWidget(row)
        if message['role'] == 'user':
            edit = QPushButton('✎'); edit.setAccessibleName(self.tr('Edit and resend prompt')); edit.setToolTip(self.tr('Edit this prompt and its images in the composer, then send again'))
            bubble.header.addWidget(edit)
            edit.clicked.connect(lambda checked=False,m=message:self.copy_prompt(m))
            saved = bool(self.store.prompt_id('chat',message))
            star = QPushButton('★' if saved else '☆'); star.setAccessibleName(self.tr('Remove saved prompt') if saved else self.tr('Save prompt')); star.setToolTip(self.tr('Remove from Prompts') if saved else self.tr('Save to Prompts'))
            bubble.header.addWidget(star)
            star.clicked.connect(lambda checked=False,m=message:self.window.toggle_prompt('chat',m)); self.prompt_stars.append((star,'chat',message,True))
        for doc in message.get('documents',[]):
            button(doc['name'],lambda checked=False,d=doc:self.preview_document(d),bubble.layout())
        if message.get('research'):
            bubble.research_details = ResearchDetails(message['research']); bubble.layout().addWidget(bubble.research_details)
        if not live and message['role'] == 'assistant':
            def remember_thinking(visible):
                message['thinking_visible'] = visible; self.store.save(self.session)
            bubble.thinking_toggle.toggled.connect(remember_thinking)
        return bubble
    def render(self):
        clear_layout(self.results)
        self.prompt_stars = []
        if self.session['mode'] == 'chat':
            self.continue_button.setEnabled(not self.job and bool(self.session['messages']) and self.session['messages'][-1].get('research',{}).get('status')=='limited')
            for m in self.session['messages']:
                self.add_bubble(m)
        else:
            for i,run in enumerate(self.session['runs']):
                self.results.addWidget(QLabel(self.tr('Run {number}').format(number=i+1)))
                saved = bool(self.store.prompt_id('decision',run['form']))
                star = button(self.tr('★ Saved prompt') if saved else self.tr('☆ Save prompt'),lambda checked=False,r=run:self.window.toggle_prompt('decision',r['form']),self.results)
                self.prompt_stars.append((star,'decision',run['form'],False))
                button(self.tr('Restore query to form'),lambda checked=False,r=run:self.restore(r['form']),self.results)
                self.results.addWidget(DecisionResult(run['result']['raw']))
                label = QLabel(metrics_text(run['result']['metrics'])); label.setObjectName('metrics'); label.setWordWrap(True); self.results.addWidget(label)
                button(self.tr('Inspect query and response'),lambda checked=False,r=run:self.show_text(self.tr('Decision run'),json.dumps(r,indent=2)),self.results)
        if self.partial is not None:
            if self.session['mode'] == 'chat':
                self.add_bubble(self.pending)
                self.live_bubble = self.add_bubble(dict(role='assistant',**self.partial),live=True)
            else: self.results.addWidget(QLabel(self.tr('Running…')))
        elif not self.session['messages'] and not self.session['runs']:
            hint = QLabel(self.tr('Build a decision query on the left.') if self.session['mode']=='decision' else self.tr('Start a conversation. Attach images or paste them into the composer.')); hint.setWordWrap(True); self.results.addWidget(hint)
        self.results.addStretch(); self._follow_stream = True; QTimer.singleShot(0,self.follow_stream)
    def refresh_prompt_stars(self):
        self.update_current_star()
        for star,mode,payload,compact in self.prompt_stars:
            saved = bool(self.store.prompt_id(mode,payload))
            star.setText(('★' if saved else '☆') if compact else (self.tr('★ Saved prompt') if saved else self.tr('☆ Save prompt')))
            star.setToolTip(self.tr('Remove from Prompts') if saved else self.tr('Save to Prompts'))
            star.setAccessibleName(self.tr('Remove saved prompt') if saved else self.tr('Save prompt'))
    def restore(self,form):
        self.loading = True; self.state.setPlainText(form['state']); self.json_state.setChecked(form.get('json_state',False)); self.attachments.set_paths(form.get('images',[])); clear_layout(self.question_layout); self.questions = []
        for q in form['questions']: self.add_question(q)
        self.loading = False; self.save_draft()
    def show_text(self,title,text):
        dlg = QDialog(self); dlg.setWindowTitle(title); dlg.resize(720,520); layout = QVBoxLayout(dlg); view = QPlainTextEdit(); view.setReadOnly(True); view.setPlainText(text); layout.addWidget(view); button(self.tr('Close'),dlg.accept,layout); dlg.exec()
    def export_session(self):
        path,_ = QFileDialog.getSaveFileName(self,self.tr('Export session'),'conversation.json','JSON (*.json)')
        if path:
            try:
                self.save_draft(); Path(path).write_text(json.dumps(self.session,indent=2)+'\n',encoding='utf-8')
            except Exception as exc: error(self,exc)

class LegacyDecisionTab(QWidget):
    """Read-only access to decision history saved by earlier releases."""
    updated=Signal()
    def __init__(self,window,session):
        super().__init__();self.session=session;self.job=None;self._closed=False
        layout=QVBoxLayout(self);label=QLabel(self.tr('This saved Decision session is read-only. Use Promptnik to create and test System One queries.'));label.setWordWrap(True);layout.addWidget(label)
        self.view=QPlainTextEdit();self.view.setObjectName('legacyDecisionHistory');self.view.setReadOnly(True)
        self.view.setPlainText(json.dumps({'form':session.get('form'),'runs':session.get('runs',[]),'saved_prompts':window.store.list_prompts('decision')},ensure_ascii=False,indent=2));layout.addWidget(self.view)
    def save_draft(self):pass
    def cancel(self):pass

class SettingsDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.store=window.store;self.setWindowTitle(self.tr('Settings'));self.resize(700,550)
        settings=self.store.config['settings'];outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);outer.addWidget(scroll);content=QWidget();scroll.setWidget(content);layout=QVBoxLayout(content)
        notice=QLabel(self.tr('Settings apply to new Chat and Code runs. Existing runs keep their original settings. Search provider changes are saved immediately.'));notice.setWordWrap(True);layout.addWidget(notice)
        legacy=QLabel(self.tr('Previous per-tab web, limits and Decision settings remain in history but are no longer used. Configure global settings here; Web starts off.'));legacy.setWordWrap(True);layout.addWidget(legacy)
        self.relaxed=QCheckBox(self.tr('Relax TLS verification globally'));self.relaxed.setChecked(settings.get('relaxed_tls',False));layout.addWidget(self.relaxed)
        tls_notice=QLabel(self.tr('Relaxing TLS disables certificate and hostname verification for Agentnik network connections. Intermediaries can read or change traffic. Restart Agentnik to apply this setting.'));tls_notice.setWordWrap(True);layout.addWidget(tls_notice)
        appearance=QFormLayout();layout.addLayout(appearance);self.theme=QComboBox()
        for label,value in ((self.tr('System'),'System'),(self.tr('Light'),'Light'),(self.tr('Dark'),'Dark')):self.theme.addItem(label,value)
        self.theme.setCurrentIndex(max(0,self.theme.findData(settings.get('theme','System'))));appearance.addRow(self.tr('Theme'),self.theme)
        self.language=QComboBox();self.language.setToolTip(self.tr('Language changes take effect after restarting Agentnik.'))
        for code,name in localization.choices():self.language.addItem(self.tr('System default') if code=='system' else name,code)
        saved_language=settings.get('language','system')
        if self.language.findData(saved_language)<0:self.language.addItem(saved_language+self.tr(' (unavailable)'),saved_language)
        self.language.setCurrentIndex(self.language.findData(saved_language));appearance.addRow(self.tr('Language'),self.language)
        from .code_limits import coding_limits,goal_limits
        self.coding_limits=coding_limits(settings.get('coding_limits'));self.goal_limits=goal_limits(settings.get('coding_goal_limits'))
        self.chat_limits=copy.deepcopy(settings.get('chat_research_limits'))
        research_form=QFormLayout();layout.addLayout(research_form);self.research_policy=QComboBox()
        for policy in ('Provider first','Agentnik first'):self.research_policy.addItem(policy_label(policy),policy)
        self.research_policy.setCurrentIndex(max(0,self.research_policy.findData(settings.get('research_policy','Provider first'))));research_form.addRow(self.tr('Search priority'),self.research_policy)
        self.research_access=QComboBox();self.research_access.addItem(self.tr('Public page reads; external search navigation disclosed'),'public_fetch');self.research_access.addItem(self.tr('Enforce public-only navigation everywhere'),'strict_public');self.research_access.setCurrentIndex(max(0,self.research_access.findData(settings.get('research_access_policy','public_fetch'))));research_form.addRow(self.tr('Navigation policy'),self.research_access)
        self.mcp_priority=QComboBox();self.mcp_priority.addItem(self.tr('MCP First'),'first');self.mcp_priority.addItem(self.tr('MCP Last'),'last');self.mcp_priority.setCurrentIndex(max(0,self.mcp_priority.findData(settings.get('mcp_priority','first'))));research_form.addRow(self.tr('Conflicting MCP tools'),self.mcp_priority)
        self.git_authors={row['id']:window.repositories.git_author(row['id']) for row in window.repositories.list()}
        git_form=QFormLayout();layout.addLayout(git_form);self.git_repository=QComboBox();self.git_repository.setObjectName('gitAuthorRepository')
        for row in window.repositories.list():self.git_repository.addItem(row['name']+' — '+row['path'],row['id'])
        git_form.addRow(self.tr('Git author repository'),self.git_repository)
        self.git_author_name=QLineEdit();self.git_author_name.setObjectName('gitAuthorName');git_form.addRow(self.tr('Git author name'),self.git_author_name)
        self.git_author_email=QLineEdit();self.git_author_email.setObjectName('gitAuthorEmail');git_form.addRow(self.tr('Git author email'),self.git_author_email)
        git_hint=QLabel(self.tr('Leave both fields blank to use the repository Git configuration. Changes apply to new Code runs.'));git_hint.setWordWrap(True);layout.addWidget(git_hint)
        self._git_author_id=None;self.git_repository.currentIndexChanged.connect(self.change_git_author_repository);self.change_git_author_repository()
        button(self.tr('Search providers…'),self.search_providers,layout)
        button(self.tr('Code and goal limits…'),self.code_limits,layout)
        button(self.tr('Chat research limits…'),self.research_limits,layout)
        button(self.tr('Forget remembered subagent tool support'),self.forget_subagents,layout)
        from .image_settings import validate_image_settings
        image_settings=validate_image_settings(settings.get('image_generation'));self.image_job=None
        self.image_enabled=QCheckBox(self.tr('Enable image generation tool'));self.image_enabled.setObjectName('imageGenerationEnabled');self.image_enabled.setChecked(image_settings['enabled']);layout.addWidget(self.image_enabled)
        image_form=QFormLayout();layout.addLayout(image_form);self.image_connection=QComboBox();self.image_connection.setObjectName('imageGenerationConnection');self.image_connection.addItem(self.tr('Not configured'),'')
        for name in window.connections:self.image_connection.addItem(name,name)
        name=image_settings['connection']
        if name and self.image_connection.findData(name)<0:self.image_connection.addItem(name+self.tr(' (unavailable)'),name)
        self.image_connection.setCurrentIndex(max(0,self.image_connection.findData(name)));image_form.addRow(self.tr('Image connection'),self.image_connection)
        self.image_model=QLineEdit(image_settings['model']);self.image_model.setObjectName('imageGenerationModel');image_model_row=QHBoxLayout();image_model_row.addWidget(self.image_model,1);button(self.tr('Choose image model…'),self.choose_image_model,image_model_row);image_form.addRow(self.tr('Image model'),image_model_row)
        self.image_endpoint=QLineEdit(image_settings['endpoint']);self.image_endpoint.setObjectName('imageGenerationEndpoint');self.image_endpoint.setPlaceholderText(self.tr('Default: connection URL + /images'));image_form.addRow(self.tr('Image endpoint (optional)'),self.image_endpoint)
        image_notice=QLabel(self.tr('Image prompts and selected reference images are sent to the image connection. Generation may incur charges.'));image_notice.setWordWrap(True);layout.addWidget(image_notice)
        form=QFormLayout();layout.addLayout(form);self.decision_connection=QComboBox();self.decision_connection.setObjectName('globalDecisionConnection');self.decision_connection.addItem(self.tr('Not configured'),'')
        for name in window.connections:self.decision_connection.addItem(name,name)
        saved=settings.get('decision_model',{});name=saved.get('connection','')
        if name and self.decision_connection.findData(name)<0:self.decision_connection.addItem(name+self.tr(' (unavailable)'),name)
        self.decision_connection.setCurrentIndex(max(0,self.decision_connection.findData(name)));form.addRow(self.tr('Decision connection'),self.decision_connection)
        self.decision_model=QLineEdit(saved.get('model',''));self.decision_model.setObjectName('globalDecisionModel');model_row=QHBoxLayout();model_row.addWidget(self.decision_model,1);button(self.tr('Choose model…'),self.choose_decision_model,model_row);form.addRow(self.tr('Decision model'),model_row)
        self.decision_connection.currentIndexChanged.connect(lambda _:self.decision_model.setText(window.connections.get(self.decision_connection.currentData(),{}).get('model','')))
        self.advice=QCheckBox(self.tr('Check shell approvals with Decision model'));self.advice.setChecked(settings.get('decision_advice_enabled',False));layout.addWidget(self.advice)
        disclosure=QLabel(self.tr('Advice sends the command, working directory, shell and environment variable names to the Decision endpoint; it never approves commands.'));disclosure.setWordWrap(True);layout.addWidget(disclosure)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);outer.addWidget(buttons);self.model_job=None
    def change_git_author_repository(self,*_):
        if self._git_author_id is not None:self.git_authors[self._git_author_id]={'name':self.git_author_name.text(),'email':self.git_author_email.text()}
        self._git_author_id=self.git_repository.currentData();author=self.git_authors.get(self._git_author_id) or {}
        self.git_author_name.setEnabled(self._git_author_id is not None);self.git_author_email.setEnabled(self._git_author_id is not None)
        self.git_author_name.setText(author.get('name',''));self.git_author_email.setText(author.get('email',''))

    def search_providers(self):
        from .research_ui import SearchBackends
        SearchBackends(self,self.store).exec()
    def code_limits(self):
        from .code_ui import CodingLimitsDialog
        dialog=CodingLimitsDialog(self,self.coding_limits,self.goal_limits)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.coding_limits=dialog.values();self.goal_limits=dialog.goal_values()
    def research_limits(self):
        dialog=ResearchLimitsDialog(self,self.chat_limits)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.chat_limits=dialog.values()
    def choose_image_model(self):
        name=self.image_connection.currentData();connection=dict(self.window.connections.get(name,{}));endpoint=self.image_endpoint.text().strip()
        if not connection or self.image_job:return
        from .image_generation import list_models
        def done(names):
            self.image_job=None
            if not self.isVisible() or self.image_connection.currentData()!=name or self.image_endpoint.text().strip()!=endpoint:return
            from .code_ui import ModelPicker
            dialog=ModelPicker(self,self.tr('Choose image model'),names)
            if dialog.exec()==QDialog.DialogCode.Accepted:self.image_model.setText(dialog.selected_model)
        def failed(_):
            self.image_job=None
            if self.isVisible():QMessageBox.warning(self,self.tr('Settings'),self.tr('Image model listing failed. You can enter an alias manually.'))
        self.image_job=Job(lambda *_,listing=list_models:listing(connection,endpoint),done,failed)

    def choose_decision_model(self):
        name=self.decision_connection.currentData();connection=dict(self.window.connections.get(name,{}))
        if not connection or self.model_job:return
        def done(names):
            self.model_job=None
            if not self.isVisible() or self.decision_connection.currentData()!=name:return
            choices=[value for value in names if isinstance(value,str) and len(value)<=512][:2000]
            model,ok=QInputDialog.getItem(self,self.tr('Choose Decision model'),self.tr('Model alias:'),choices,0,True)
            if ok:self.decision_model.setText(model)
        def failed(_):
            self.model_job=None
            if self.isVisible():QMessageBox.warning(self,self.tr('Settings'),self.tr('Model listing failed. You can enter an alias manually.'))
        self.model_job=Job(lambda *_,models=core.models:models(connection),done,failed)
    def forget_subagents(self):
        self.store.config.pop('subagent_tool_capabilities',None);self.store.flush()
    def accept(self):
        if self.advice.isChecked() and (not self.decision_connection.currentData() or not self.decision_model.text().strip()):
            QMessageBox.warning(self,self.tr('Settings'),self.tr('Choose a Decision connection and model before enabling advice.'));return
        image_config={'enabled':self.image_enabled.isChecked(),'connection':self.image_connection.currentData() or '', 'model':self.image_model.text().strip(), 'endpoint':self.image_endpoint.text().strip()}
        if image_config['enabled']:
            connection=self.window.connections.get(image_config['connection'])
            if not connection or not image_config['model']:
                QMessageBox.warning(self,self.tr('Settings'),self.tr('Choose an image connection and model before enabling the image tool.'));return
            try:
                from .image_generation import image_endpoint
                image_endpoint(connection,image_config['endpoint'])
            except ValueError:
                QMessageBox.warning(self,self.tr('Settings'),self.tr('The image endpoint must use the selected connection host and scheme.'));return
        from .repositories import validate_git_author
        if self._git_author_id is not None:self.git_authors[self._git_author_id]={'name':self.git_author_name.text(),'email':self.git_author_email.text()}
        try:authors={ident:validate_git_author(author) for ident,author in self.git_authors.items()}
        except ValueError:
            QMessageBox.warning(self,self.tr('Settings'),self.tr('Enter both a valid Git author name and email, or leave both blank.'));return
        for ident,author in authors.items():self.window.repositories.set_git_author(ident,author)
        settings=self.store.config['settings'];settings['image_generation']=image_config
        settings.update(relaxed_tls=self.relaxed.isChecked(),coding_limits=self.coding_limits,coding_goal_limits=self.goal_limits,decision_advice_enabled=self.advice.isChecked(),decision_model={'connection':self.decision_connection.currentData(),'model':self.decision_model.text().strip()})
        if self.chat_limits is not None:settings['chat_research_limits']=self.chat_limits
        settings['theme']=self.theme.currentData();settings['language']=self.language.currentData();settings['research_policy']=self.research_policy.currentData();settings['research_access_policy']=self.research_access.currentData();settings['mcp_priority']=self.mcp_priority.currentData()
        self.store.flush();self.window.apply_theme();super().accept()

class Window(QMainWindow):
    def __init__(self,store):
        super().__init__(); self.store = store; self.repositories=RepositoryRegistry(store); self.local = {}; self.connections = {}; self.setWindowTitle('Agentnik')
        tls.configure(store.config['settings'].get('relaxed_tls',False))
        self._system_palette = QPalette(QApplication.palette())
        toolbar = self.addToolBar('Agentnik'); toolbar.setMovable(False)
        self.brand = QLabel(); self.brand.setContentsMargins(2,0,12,0); toolbar.addWidget(self.brand)
        for text, fn in [(self.tr('☰ History'),self.toggle_history),(self.tr('☆ Prompts'),self.toggle_prompts),(self.tr('＋ Chat'),lambda:self.new_session('chat')),(self.tr('＋ Code'),self.new_code),(self.tr('Repositories'),self.manage_repositories),(self.tr('Connections'),self.manage_connections),(self.tr('MCP servers'),self.manage_mcp_servers)]:
            action = QAction(text,self); action.triggered.connect(fn); toolbar.addAction(action)
        controls=self.addToolBar('Display and settings');controls.setMovable(False)
        self.settings_action=QAction(self.tr('Settings · TLS relaxed') if tls.relaxed() else self.tr('Settings'),self);self.settings_action.triggered.connect(self.configure_settings);controls.addAction(self.settings_action)
        self.font_smaller = QPushButton('A−'); self.font_smaller.setAccessibleName(self.tr('Decrease font size')); self.font_smaller.setToolTip(self.tr('Decrease font size')); self.font_smaller.clicked.connect(lambda:self.adjust_font_size(-1)); controls.addWidget(self.font_smaller)
        self.font_larger = QPushButton('A+'); self.font_larger.setAccessibleName(self.tr('Increase font size')); self.font_larger.setToolTip(self.tr('Increase font size')); self.font_larger.clicked.connect(lambda:self.adjust_font_size(1)); controls.addWidget(self.font_larger)
        self.web_search=WebAccessSwitch(self.tr('Web'));self.web_search.setObjectName('globalWebSearch');self.web_search.setToolTip(self.tr('Enable web search and public-page retrieval for new Chat and Code runs.'));self.web_search.setChecked(store.config['settings'].get('web_search_enabled',False));self.web_search.toggled.connect(self.save_global_web_search);controls.addWidget(self.web_search)
        self.mcp_access=WebAccessSwitch(self.tr('MCP'));self.mcp_access.setObjectName('globalMcpAccess');self.mcp_access.setToolTip(self.tr('Enable selected MCP servers for new Chat and Code runs.'));self.mcp_access.setChecked(store.config['settings'].get('mcp_access_enabled',True));self.mcp_access.toggled.connect(self.save_global_mcp_access);controls.addWidget(self.mcp_access);controls.setMinimumWidth(controls.sizeHint().width())
        self.split = QSplitter(); self.setCentralWidget(self.split)
        self.sidebar = QWidget(); side = QVBoxLayout(self.sidebar); side.addWidget(QLabel(self.tr('History')))
        self.search = QLineEdit(); self.search.setPlaceholderText(self.tr('Search conversations')); self.search.textChanged.connect(self.refresh_history); side.addWidget(self.search)
        self.history = QListWidget(); self.history.itemActivated.connect(self.open_item); self.history.itemClicked.connect(self.open_item); side.addWidget(self.history,1)
        row = QHBoxLayout(); side.addLayout(row); button(self.tr('Rename'),self.rename,row); button(self.tr('Delete'),self.delete,row); button(self.tr('Clear all'),self.clear_all,side)
        self.split.addWidget(self.sidebar); self.tabs = QTabWidget(); self.tabs.setTabsClosable(True); self.tabs.setMovable(True); self.tabs.tabCloseRequested.connect(self.close_tab); self.tabs.currentChanged.connect(self.stats); self.split.addWidget(self.tabs)
        self.prompts_panel = QWidget(); prompts = QVBoxLayout(self.prompts_panel); prompts.addWidget(QLabel(self.tr('Prompts')))
        self.prompts_search = QLineEdit(); self.prompts_search.setPlaceholderText(self.tr('Search prompts')); self.prompts_search.textChanged.connect(self.refresh_prompts); prompts.addWidget(self.prompts_search)
        self.prompts_list = QListWidget(); self.prompts_list.setTextElideMode(Qt.TextElideMode.ElideRight); self.prompts_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.prompts_list.itemDoubleClicked.connect(lambda _:self.copy_selected_prompt()); prompts.addWidget(self.prompts_list,1)
        prompt_buttons = QHBoxLayout(); prompts.addLayout(prompt_buttons)
        button(self.tr('Copy to tab'),self.copy_selected_prompt,prompt_buttons); button(self.tr('Remove'),self.remove_selected_prompt,prompt_buttons)
        if store.list_prompts('decision'):button(self.tr('View saved Decision prompts…'),self.show_legacy_decision_prompts,prompts)
        self.split.addWidget(self.prompts_panel); self.split.setSizes([250,820,250])
        self.prompts_panel.setVisible(store.config['settings'].get('prompts_visible',True))
        self.sidebar.setVisible(store.config['settings'].get('history_visible',True)); self.reload_connections(); self.refresh_history(); self.apply_theme()
        self.apply_font_size(store.config['settings'].get('font_size',max(8,self.font().pointSize())))
        self.statusBar().showMessage(self.tr('Discovering local endpoints…'))
        self.discovery = Job(lambda *_,discover=core.discover:discover(),self.discovered,lambda e:self.statusBar().showMessage(e))
        QShortcut(QKeySequence('Ctrl+N'),self,activated=lambda:self.new_session('chat'))
        QShortcut(QKeySequence('Ctrl+B'),self,activated=self.toggle_history)
        self.empty = QWidget(); welcome = QVBoxLayout(self.empty); welcome.addStretch()
        self.welcome_brand = QLabel(); self.welcome_brand.setAlignment(Qt.AlignmentFlag.AlignCenter); welcome.addWidget(self.welcome_brand)
        hint = QLabel(self.tr('Open a chat or Code tab to begin.\nConnections are discovered from your environment and local servers.')); hint.setAlignment(Qt.AlignmentFlag.AlignCenter); hint.setWordWrap(True); welcome.addWidget(hint); welcome.addStretch()
        self.tabs.addTab(self.empty,self.tr('Welcome')); self.update_branding()
        QApplication.styleHints().colorSchemeChanged.connect(self.system_theme_changed)
        self.fit_initial_screen(toolbar,controls)
    def fit_initial_screen(self,toolbar,controls):
        screen=QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1320,850);return
        area=screen.availableGeometry()
        if area.width()<=0 or area.height()<=0:
            self.resize(1320,850);return
        width=max(1,min(1320,area.width()-32));height=max(1,min(850,area.height()-64))
        self.ensurePolished();self.layout().activate()
        if self.minimumSizeHint().width()>width:
            toolbar.setMinimumWidth(0);self.insertToolBarBreak(controls)
            if controls.minimumWidth()>width:controls.setMinimumWidth(width)
            for pane in (self.sidebar,self.tabs,self.prompts_panel):
                pane.setMinimumWidth(0);pane.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
            self.layout().invalidate();self.layout().activate();self.setMinimumWidth(0)
        self.resize(width,height)
        self.move(area.x()+max(0,(area.width()-width)//2),area.y()+max(0,(area.height()-height)//2))
    def configure_settings(self):
        if SettingsDialog(self).exec()==QDialog.DialogCode.Accepted:self.statusBar().showMessage(self.tr('Settings saved. Language and TLS changes apply after restart.'))
    def save_global_web_search(self,enabled):
        self.store.config['settings']['web_search_enabled']=bool(enabled);self.store.flush()
    def save_global_mcp_access(self,enabled):
        self.store.config['settings']['mcp_access_enabled']=bool(enabled);self.store.flush()
    def image_tool_config(self):
        from .image_settings import validate_image_settings
        from .image_generation import image_endpoint
        settings=validate_image_settings(self.store.config['settings'].get('image_generation'))
        if not settings['enabled']:return None
        connection=self.connections.get(settings['connection'])
        if not connection or not settings['model']:raise ValueError('The configured image connection or model is unavailable')
        image_endpoint(connection,settings['endpoint'])
        return {'connection':dict(connection),'model':settings['model'],'endpoint':settings['endpoint']}

    def decision_connection(self):
        settings=self.store.config['settings'];binding=settings.get('decision_model',{})
        if not settings.get('decision_advice_enabled',False):return None,''
        name=binding.get('connection','');connection=dict(self.connections.get(name,{}));connection['model']=binding.get('model','').strip()
        if not connection.get('url') or not connection['model']:raise ValueError(self.tr('Choose an available Decision connection and model in Settings.'))
        return connection,name+' / '+connection['model']+' / '+core.endpoint(connection,'decision')
    def apply_theme(self,*_):
        value = self.store.config['settings'].get('theme','System'); self.store.flush()
        scheme = {'Light':Qt.ColorScheme.Light,'Dark':Qt.ColorScheme.Dark}.get(value,Qt.ColorScheme.Unknown)
        QApplication.styleHints().setColorScheme(scheme)
        dark = value == 'Dark' or (value == 'System' and QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark)
        window,base,text,edge = ('#20232b','#171a21','#eef0f5','#4a5261') if dark else ('#fafafa','#ffffff','#18202d','#c3c8d0')
        palette = QPalette(self._system_palette)
        for role,color in [(QPalette.ColorRole.Window,window),(QPalette.ColorRole.Base,base),(QPalette.ColorRole.AlternateBase,window),(QPalette.ColorRole.WindowText,text),(QPalette.ColorRole.Text,text),(QPalette.ColorRole.Button,window),(QPalette.ColorRole.ButtonText,text),(QPalette.ColorRole.Highlight,'#c83545'),(QPalette.ColorRole.HighlightedText,'#ffffff'),(QPalette.ColorRole.Link,'#e34b59' if dark else '#c83545'),(QPalette.ColorRole.LinkVisited,'#d77a83' if dark else '#aa2938')]: palette.setColor(role,QColor(color))
        QApplication.setPalette(palette)
        size = self.store.config['settings'].get('font_size',max(8,self.font().pointSize()))
        colors = f'QWidget {{ font-size: {size}pt; background-color: {window}; color: {text}; }} QLabel {{ background: transparent; }} QLineEdit,QPlainTextEdit,QTextBrowser,QListWidget,QTableWidget {{ background-color: {base}; border: 1px solid {edge}; selection-background-color: #c83545; }} QPushButton,QComboBox {{ border: 1px solid {edge}; border-radius: 4px; }} QPushButton:disabled {{ color: #808795; }} QTabWidget::pane {{ border: 1px solid {edge}; }} QTabBar::tab:selected {{ background-color: {base}; }}'
        muted = '#aab3c2' if dark else '#687382'
        self.setStyleSheet(colors+f' QLabel#metrics {{ font-size: {max(7,size*.8):g}pt; color: {muted}; }}'+'QToolBar { spacing: 9px; padding: 8px; } QPushButton { padding: 6px 11px; } QLineEdit, QComboBox { padding: 5px; } QTabBar::tab { padding: 9px 16px; } QPushButton#primary { background: #c83545; color: white; border-radius: 5px; padding: 9px 24px; } QFrame#questionCard { border: 1px solid #808080; border-radius: 5px; } QProgressBar { min-height: 19px; text-align: center; } QProgressBar::chunk { background: #e34b59; }')
        self.update_branding()
    def apply_font_size(self,size):
        size = max(8,min(32,size))
        font = QApplication.font(); font.setPointSize(size); QApplication.setFont(font)
        self.store.config['settings']['font_size'] = size; self.apply_theme()
        self.font_smaller.setEnabled(size>8); self.font_larger.setEnabled(size<32)
        self.font_smaller.setToolTip(self.tr('Decrease font size (currently {size} pt)').format(size=size)); self.font_larger.setToolTip(self.tr('Increase font size (currently {size} pt)').format(size=size))
    def adjust_font_size(self,delta):
        self.apply_font_size(self.store.config['settings'].get('font_size',self.font().pointSize())+delta)
    def system_theme_changed(self,*_):
        if self.store.config['settings'].get('theme','System') == 'System': self.apply_theme()
        else: self.update_branding()
    def update_branding(self,*_):
        dark = self.store.config['settings'].get('theme','System') == 'Dark' or (self.store.config['settings'].get('theme','System') == 'System' and QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark)
        assets = Path(__file__).parent/'assets'
        self.brand_variant = 'dark' if dark else 'light'
        path = assets/f'agentnik-{self.brand_variant}.svg'
        logo = QPixmap(str(path if path.exists() else path.with_suffix('.png')))
        if not logo.isNull():
            ratio = self.devicePixelRatioF()
            header = logo.scaledToHeight(round(34*ratio),Qt.TransformationMode.SmoothTransformation); header.setDevicePixelRatio(ratio)
            self.brand.setPixmap(header); self.brand.setToolTip('Agentnik')
            if hasattr(self,'welcome_brand'):
                welcome = logo.scaledToWidth(round(540*ratio),Qt.TransformationMode.SmoothTransformation); welcome.setDevicePixelRatio(ratio); self.welcome_brand.setPixmap(welcome)
        else: self.brand.setText('Agentnik')
        icon = QIcon(str(assets/'agentnik-icon.svg'))
        self.setWindowIcon(icon); QApplication.setWindowIcon(icon)
    def reload_connections(self):
        previous=getattr(self,'connections',{})
        self.connections = {**core.merge_discovered(core.environment_connections(),self.local),**self.store.connections()}
        from .research_settings import invalidate_capabilities
        changed=[]
        for name,c in self.connections.items():
            if name not in self.store.config['connections']:
                # Stable, opaque scope lets remembered unsupported routes survive restart
                # while separating connections whose endpoint or credentials differ.
                import hashlib
                settings=self.store.config['settings'];salt=settings.get('research_scope_salt')
                if not salt:
                    salt=uuid.uuid4().hex;settings['research_scope_salt']=salt;self.store.flush()
                fields=('url','protocol','model','api_key','reasoning','stream','context_limit','service_tier')
                identity=json.dumps([salt,name,*[c.get(k,'') for k in fields]],ensure_ascii=True,separators=(',',':'))
                c['_capability_scope']=hashlib.sha256(identity.encode()).hexdigest()
            old=(previous or {}).get(name)
            if old is not None and any(old.get(k)!=c.get(k) for k in ('url','protocol','model','api_key','reasoning','stream','context_limit','service_tier')): changed.extend([old,c])
        if changed:
            invalidate_capabilities(self.store.config,changed)
            self.store.flush()
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget,SessionTab): widget.refresh_connections()
    def discovered(self,found): self.local = found; self.reload_connections(); self.stats()
    def manage_repositories(self): RepositoryPicker(self,self.repositories,select=False).exec()
    def new_code(self):
        picker=RepositoryPicker(self,self.repositories)
        if picker.exec()!=QDialog.DialogCode.Accepted or not picker.selected_id: return
        try:
            session=self.repositories.session(picker.selected_id);self.store.save(session);self.open_session(session);self.refresh_history()
        except (OSError,ValueError) as exc: error(self,exc)
    def manage_connections(self): Connections(self).exec()

    def manage_mcp_servers(self):
        from .mcp_ui import MCPServers
        MCPServers(self).exec()
    def toggle_history(self):
        self.sidebar.setVisible(not self.sidebar.isVisible()); self.store.config['settings']['history_visible'] = not self.sidebar.isHidden(); self.store.flush()
    def toggle_prompts(self):
        self.prompts_panel.setVisible(self.prompts_panel.isHidden()); self.store.config['settings']['prompts_visible'] = not self.prompts_panel.isHidden(); self.store.flush()
    def show_legacy_decision_prompts(self):
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Saved Decision prompts'));dialog.resize(700,520);layout=QVBoxLayout(dialog)
        label=QLabel(self.tr('Earlier Decision prompts are read-only. Use Promptnik for new System One queries.'));label.setWordWrap(True);layout.addWidget(label)
        view=QPlainTextEdit(json.dumps(self.store.list_prompts('decision'),ensure_ascii=False,indent=2));view.setObjectName('legacyDecisionPrompts');view.setReadOnly(True);layout.addWidget(view)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()
    def refresh_prompts(self,*_):
        if not hasattr(self,'prompts_list'): return
        current = self.prompts_list.currentItem(); selected = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.prompts_list.clear(); tab = self.tabs.currentWidget()
        if not isinstance(tab,SessionTab): return
        needle = self.prompts_search.text().casefold()
        for prompt in self.store.list_prompts(tab.session['mode']):
            payload = prompt['payload']; text = payload.get('text',payload.get('state',''))
            questions = ' '.join(q.get('instructions','')+' '+' '.join(' '.join(choice) for choice in q.get('choices',[])) for q in payload.get('questions',[]))
            if needle not in (prompt.get('name','')+' '+text+' '+questions).casefold(): continue
            title = prompt.get('name') or ' '.join(text.split()) or ' '.join(questions.split()) or self.tr('Image prompt')
            count = len(payload.get('images',[])); item = QListWidgetItem(title[:100]+(f'  ·  {count} image(s)' if count else ''))
            item.setToolTip(text or questions); item.setData(Qt.ItemDataRole.UserRole,prompt['id']); self.prompts_list.addItem(item)
            if prompt['id'] == selected: self.prompts_list.setCurrentItem(item)
    def toggle_prompt(self,mode,payload):
        ident = self.store.prompt_id(mode,payload)
        if ident: self.store.delete_prompt(ident)
        else:
            default = ' '.join((payload.get('text') or payload.get('state') or '').split())[:100] or self.tr('Saved prompt')
            name,ok = QInputDialog.getText(self,self.tr('Save prompt'),self.tr('Prompt name:'),text=default)
            if not ok: return
            self.store.save_prompt(mode,payload,name.strip() or default)
        self.prompts_changed()
    def prompts_changed(self):
        self.refresh_prompts()
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab,SessionTab): tab.refresh_prompt_stars()
    def selected_prompt(self):
        item = self.prompts_list.currentItem(); tab = self.tabs.currentWidget()
        if not item or not isinstance(tab,SessionTab): return None
        return next((p for p in self.store.list_prompts(tab.session['mode']) if p['id'] == item.data(Qt.ItemDataRole.UserRole)),None)
    def copy_selected_prompt(self):
        prompt = self.selected_prompt()
        if prompt: self.tabs.currentWidget().copy_prompt(prompt['payload'])
    def remove_selected_prompt(self):
        prompt = self.selected_prompt()
        if prompt and confirm(self,self.tr('Remove this saved prompt?')):
            self.store.delete_prompt(prompt['id']); self.prompts_changed()
    def new_session(self,mode,name=None):
        if mode!='chat':return
        if not self.connections:
            self.manage_connections()
            if not self.connections: return
        if name is None:
            name,ok = QInputDialog.getItem(self,self.tr('New decision') if mode=='decision' else self.tr('New chat'),self.tr('Connection:'),list(self.connections),0,False)
            if not ok: return
        session = self.store.new_session(mode,name,self.connections[name]); self.store.save(session); self.open_session(session); self.refresh_history()
    def open_session(self,session):
        if session.get('_unavailable'): return error(self,self.tr('This saved session cannot be opened with the current version. Its original data is preserved in history.sqlite3. Repair or restore the record, or use a compatible Agentnik version.'))
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab,(SessionTab,CodeTab,LegacyDecisionTab)) and tab.session['id'] == session['id']: self.tabs.setCurrentIndex(i); return
        tab = CodeTab(self,session) if session['mode']=='code' else LegacyDecisionTab(self,session) if session['mode']=='decision' else SessionTab(self,session); tab.updated.connect(self.session_updated)
        if hasattr(self,'empty') and self.tabs.indexOf(self.empty) >= 0: self.tabs.removeTab(self.tabs.indexOf(self.empty))
        self.tabs.setCurrentIndex(self.tabs.addTab(tab,session['title'])); self.stats()
    def open_item(self,item):
        session = next((s for s in self.store.list_sessions() if s['id']==item.data(Qt.ItemDataRole.UserRole)),None)
        if session: self.open_session(session)
    def refresh_history(self,*_):
        selected = self.history.currentItem().data(Qt.ItemDataRole.UserRole) if self.history.currentItem() else None
        self.history.clear(); needle = self.search.text().lower()
        for s in self.store.list_sessions():
            if needle not in (s['title']+' '+s['connection_name']).lower(): continue
            stamp = datetime.datetime.fromtimestamp(s['updated']).strftime('%b %d · %H:%M')
            item = QListWidgetItem(('⌘ ' if s['mode']=='code' else '◇ ' if s['mode']=='decision' else '○ ')+s['title']+'\n'+s['connection_name']+'\n'+stamp); item.setData(Qt.ItemDataRole.UserRole,s['id']); self.history.addItem(item)
            if s['id']==selected: self.history.setCurrentItem(item)
    def session_updated(self):
        self.refresh_history()
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab,(SessionTab,CodeTab,LegacyDecisionTab)): self.tabs.setTabText(i,tab.session['title'])
        self.stats()
    def close_tab(self,index):
        tab = self.tabs.widget(index)
        if isinstance(tab,(SessionTab,CodeTab,LegacyDecisionTab)):
            if tab.job: return error(self,self.tr('Cancel the running request and wait for it to finish before closing this tab.'))
            tab.save_draft()
            tab._closed = True
        self.tabs.removeTab(index); tab.deleteLater(); self.stats()
    def rename(self):
        item = self.history.currentItem()
        if not item: return
        session = next(s for s in self.store.list_sessions() if s['id']==item.data(Qt.ItemDataRole.UserRole))
        if session.get('_unavailable'): return error(self,self.tr('This session cannot be renamed until its stored data is repaired. The original record is preserved.'))
        name,ok = QInputDialog.getText(self,self.tr('Rename session'),self.tr('Title:'),text=session['title'])
        if ok and name.strip():
            session['title'] = name.strip()
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if isinstance(tab,(SessionTab,CodeTab,LegacyDecisionTab)) and tab.session['id']==session['id']: tab.session['title']=name.strip()
            self.store.save(session); self.session_updated()
    def delete_ids(self,ids):
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab,(SessionTab,CodeTab,LegacyDecisionTab)) and tab.session['id'] in ids and tab.job:
                return error(self,self.tr('Cancel running requests before deleting their sessions.'))
        for i in reversed(range(self.tabs.count())):
            tab = self.tabs.widget(i)
            if isinstance(tab,(SessionTab,CodeTab,LegacyDecisionTab)) and tab.session['id'] in ids: tab._closed = True; self.tabs.removeTab(i); tab.deleteLater()
        self.store.delete(ids); self.refresh_history(); self.stats()
    def delete(self):
        item = self.history.currentItem()
        if item and confirm(self,self.tr('Delete this session and its unshared stored images?')): self.delete_ids([item.data(Qt.ItemDataRole.UserRole)])
    def clear_all(self):
        if confirm(self,self.tr('Delete ALL chat and decision history, including drafts and stored images? Saved connections will remain.')):
            self.delete_ids([s['id'] for s in self.store.list_sessions()])
    def stats(self,*_):
        self.refresh_prompts()
        tab = self.tabs.currentWidget()
        if not hasattr(self,'session_status'):
            self.session_status=QLabel(); self.session_status.setTextFormat(Qt.TextFormat.PlainText); self.statusBar().addPermanentWidget(self.session_status)
        self.session_status.setText(tab.info.text() if isinstance(tab,SessionTab) else '')
        if isinstance(tab,CodeTab): self.statusBar().showMessage(self.tr('Code · {project} · {state}').format(project=tab.session['project_name'],state=self.tr('Running') if tab.job else self.tr('Ready'))); return
        if not isinstance(tab,SessionTab): self.statusBar().showMessage(self.tr('Ready · New chat: Ctrl+N · Toggle history: Ctrl+B')); return
        s = tab.session; measurements = [m['metrics'] for m in s['messages'] if 'metrics' in m] if s['mode']=='chat' else [r['result']['metrics'] for r in s['runs']]
        total_in = sum(m.get('input_tokens',0) for m in measurements); total_out = sum(m.get('output_tokens',0) for m in measurements)
        unknown = any('input_tokens' not in m or 'output_tokens' not in m or m.get('usage_complete') is False for m in measurements)
        last = measurements[-1] if measurements else {}; context = last.get('last_input_tokens',last.get('input_tokens')); limit = last.get('context_limit') or s['connection'].get('context_limit')
        text = self.tr('Context (last input): {current} / {limit}').format(current=number(context),limit=number(limit or None))
        if context is not None and limit: text += f' ({context/limit:.1%})'
        totals=self.tr(' tokens   ·   Total in: {incoming}   ·   Total out: {outgoing}').format(incoming=number(total_in),outgoing=number(total_out))
        self.statusBar().showMessage(text+totals+(self.tr(' (known usage only)') if unknown else '')+'   ·   '+s['connection_name'])
    def closeEvent(self,event):
        running = [self.tabs.widget(i) for i in range(self.tabs.count()) if isinstance(self.tabs.widget(i),(SessionTab,CodeTab)) and self.tabs.widget(i).job]
        if running and not confirm(self,self.tr('Requests are running. Close Agentnik and stop receiving responses?')): event.ignore(); return
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab,(SessionTab,CodeTab,LegacyDecisionTab)): tab.cancel(); tab.save_draft(); tab._closed = True
        event.accept()

def main():
    parser = argparse.ArgumentParser(description='Agentnik desktop chat and System One client')
    parser.add_argument('--data-dir',type=Path,help='Override the application data directory')
    parser.add_argument('--litellm-url',help='Expose a LiteLLM connection for this launch')
    parser.add_argument('--litellm-key-file',type=Path,help='Read the LiteLLM API key without putting it on the command line')
    parser.add_argument('--ollama-key-file',type=Path,help='Expose an Ollama Cloud connection using a key file')
    args = parser.parse_args()
    if args.litellm_url: os.environ['LITELLM_BASE_URL'] = args.litellm_url
    try:
        if args.litellm_key_file: os.environ['LITELLM_API_KEY'] = args.litellm_key_file.read_text('utf-8-sig').strip()
        if args.ollama_key_file:
            os.environ['OLLAMA_API_KEY'] = args.ollama_key_file.read_text('utf-8-sig').strip(); os.environ['OLLAMA_BASE_URL'] = 'https://ollama.com/v1'
            # Avoid an inherited host overriding the explicit Cloud connection.
            os.environ.pop('OLLAMA_HOST',None)
    except OSError as exc: parser.error(f'Cannot read key file: {exc}')
    app = QApplication(sys.argv); app.setApplicationName('Agentnik'); app.setOrganizationName('Agentnik'); app.setStyle('Fusion')
    try:
        store=Store(args.data_dir);translator=localization.install(app,store.config['settings'].get('language','system'))
        window = Window(store)
    except Exception as exc: error(None,exc); return
    window.show(); sys.exit(app.exec())
