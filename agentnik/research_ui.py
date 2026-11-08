"""Research controls and safe source/activity rendering for Qt chat tabs."""
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox,QDialog,QDialogButtonBox,QFormLayout,QLabel,
                               QLineEdit,QPlainTextEdit,QPushButton,QToolButton,QVBoxLayout,QWidget)
from . import research
from .tools import Limits
from .web import public_url


class WebSettings(QDialog):
    def __init__(self,parent,c):
        super().__init__(parent); self.setWindowTitle('Managed web research'); self.resize(600,420)
        layout=QFormLayout(self)
        notice=QLabel('Experimental: native Ollama chat only. Search queries are sent to Ollama.com, even when your model runs locally. Pages are read directly from public sites. Service search navigation cannot be controlled by Agentnik; direct page reads enforce public-address restrictions. Full conversations and images are not attached to search requests.'); notice.setWordWrap(True); layout.addRow(notice)
        layout.addRow('Search service',QLabel('Ollama.com · https://ollama.com/api/web_search'))
        self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('Leave blank to keep the saved key / OLLAMA_WEB_API_KEY')
        layout.addRow('Separate search API key',self.key)
        self.remove=QCheckBox('Remove saved search key'); layout.addRow(self.remove)
        self.plain=QCheckBox('Store the new search key as plaintext (explicit fallback)'); layout.addRow(self.plain)
        current=research.capability(parent.store.config,c)
        self.allow=QCheckBox('Enable tool requests for this endpoint/model')
        self.allow.setChecked(current.state in ('configured','verified')); layout.addRow(self.allow)
        label=QLabel(f'Model: {c.get("model", "")}\nTool capability: {current.state}\n{current.evidence}'); label.setTextFormat(Qt.TextFormat.PlainText); label.setWordWrap(True); layout.addRow(label)
        bounds=Limits()
        info=QLabel(f'Limits: {bounds.rounds} tool rounds, {bounds.calls} calls, {bounds.results} results/call, {bounds.context_bytes//1000} KB new tool context; {bounds.request_seconds:g}s/request, {bounds.turn_seconds:g}s/turn. No automatic retry or route fallback. Hosted search and other model protocols are not implemented yet.'); info.setWordWrap(True); layout.addRow(info)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addRow(buttons)


class ResearchDetails(QWidget):
    def __init__(self,data=None):
        super().__init__(); self.signature=None
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self.toggle=QToolButton(); self.toggle.setCheckable(True); self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        layout.addWidget(self.toggle)
        self.panel=QWidget(); self.details=QVBoxLayout(self.panel); self.details.setContentsMargins(6,0,0,0)
        self.activity=QPlainTextEdit(); self.activity.setReadOnly(True); self.activity.setMaximumBlockCount(200); self.activity.setMaximumHeight(140); self.details.addWidget(self.activity)
        self.links=QWidget(); self.links_layout=QVBoxLayout(self.links); self.details.addWidget(self.links)
        self.excerpts=QPlainTextEdit(); self.excerpts.setReadOnly(True); self.excerpts.setMaximumHeight(180); self.details.addWidget(self.excerpts)
        layout.addWidget(self.panel); self.panel.hide(); self.toggle.toggled.connect(self.panel.setVisible)
        if data: self.set_data(data)

    def set_data(self,data):
        sources=data.get('sources',[]); events=data.get('events',[])
        signature=(data.get('status'),len(events),len(sources),tuple(data.get('unverified_citations',[])))
        if signature==self.signature: return
        self.signature=signature
        self.toggle.setText(f'Research · {data.get("status","running")} · {len(sources)} source(s)')
        self.activity.setPlainText('\n'.join(f'{e.get("kind", "")}: {e.get("detail", "")}' for e in events))
        while self.links_layout.count():
            item=self.links_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        excerpts=[]
        for source in sources:
            try: url=public_url(source['url'])
            except (ValueError,KeyError): continue
            link=QPushButton(f'[{source["id"]}] {source["title"][:100]}'); link.setToolTip(url)
            link.clicked.connect(lambda checked=False,u=url:QDesktopServices.openUrl(QUrl(u)))
            self.links_layout.addWidget(link)
            excerpts.append(f'[{source["id"]}] {url}\nRetrieved: {source["retrieved_at"]} · {source.get("backend","")}\nSaved excerpt'+(' (truncated)' if source.get('truncated') else '')+'; not a fresh or complete page.\n'+source['excerpt'])
        text='\n\n'.join(excerpts)
        if sources: text+='\n\nSource links identify retrieved evidence; they do not verify that every claim is supported.'
        if data.get('unverified_citations'): text+='\nUnverified citation IDs: '+', '.join(data['unverified_citations'])
        self.excerpts.setPlainText(text); self.excerpts.setVisible(bool(text))
