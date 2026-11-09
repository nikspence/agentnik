"""Research controls and safe source/activity rendering for Qt chat tabs."""
from PySide6.QtCore import QUrl, Qt, QCoreApplication
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox,QDialog,QDialogButtonBox,QFormLayout,QLabel,
                               QLineEdit,QPlainTextEdit,QPushButton,QToolButton,QVBoxLayout,QWidget,
                               QComboBox,QHBoxLayout,QListWidget,QInputDialog,QMessageBox)
from . import research, routing, hosted
from .tools import Limits
from .web import public_url


def policy_label(policy):
    labels={'Provider first':QCoreApplication.translate('ResearchPolicy','Provider first'),
            'Agentnik first':QCoreApplication.translate('ResearchPolicy','Agentnik first'),
            'Provider only':QCoreApplication.translate('ResearchPolicy','Provider only'),
            'Agentnik only':QCoreApplication.translate('ResearchPolicy','Agentnik only')}
    return labels.get(policy,policy)


class SearchBackends(QDialog):
    def __init__(self,parent,store):
        super().__init__(parent); self.store=store; self.setWindowTitle(self.tr('Search backends')); self.resize(580,360)
        layout=QVBoxLayout(self)
        label=QLabel(self.tr('Saved profiles run in this order. Each has a separate key; the initial adapter is Ollama search. Changes are saved immediately. OLLAMA_WEB_API_KEY supplies an environment profile after saved profiles when needed.')); label.setWordWrap(True); layout.addWidget(label)
        self.list=QListWidget(); layout.addWidget(self.list)
        row=QHBoxLayout(); layout.addLayout(row)
        for text,fn in [(self.tr('Add'),lambda:self.edit(True)),(self.tr('Edit'),lambda:self.edit(False)),(self.tr('Remove'),self.remove),('↑',lambda:self.move(-1)),('↓',lambda:self.move(1))]:
            b=QPushButton(text); b.clicked.connect(fn); row.addWidget(b)
        close=QPushButton(self.tr('Close')); close.clicked.connect(self.accept); layout.addWidget(close); self.refresh()

    def refresh(self,selected=0):
        self.list.clear()
        for entry in self.store.config.get('web_backends',[]): self.list.addItem(entry.get('name','Ollama search'))
        self.list.setCurrentRow(selected)

    def edit(self,add):
        import uuid
        entries=self.store.config.get('web_backends',[]); index=self.list.currentRow()
        if not add and not 0<=index<len(entries): return
        entry={} if add else entries[index]
        if add and len(entries)>=5: return QMessageBox.warning(self,self.tr('Search backends'),self.tr('At most five saved profiles are supported.'))
        dlg=QDialog(self); dlg.setWindowTitle(self.tr('Search backend profile')); form=QFormLayout(dlg)
        name=QLineEdit(entry.get('name','Ollama search')); form.addRow(self.tr('Name'),name)
        key=QLineEdit(); key.setEchoMode(QLineEdit.EchoMode.Password); key.setPlaceholderText(self.tr('Blank keeps an existing key')); form.addRow(self.tr('Ollama search API key'),key)
        plain=QCheckBox(self.tr('Store as plaintext (explicit fallback)')); form.addRow(plain)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept); buttons.rejected.connect(dlg.reject); form.addRow(buttons)
        while dlg.exec()==QDialog.DialogCode.Accepted:
            try:
                label=name.text().strip()
                if not label or len(label)>80: raise ValueError(self.tr('Enter a profile name of 1–80 characters'))
                if add and not key.text().strip(): raise ValueError(self.tr('Enter a search key for the new profile'))
                ident=entry.get('id') or 'search-'+uuid.uuid4().hex
                if key.text().strip(): self.store.save_web_key(key.text().strip(),plain.isChecked(),ident=ident,name=label)
                else:
                    entry['name']=label; self.store.flush()
                self.refresh(index if not add else self.list.count()); return
            except Exception as exc: QMessageBox.warning(self,self.tr('Search backends'),str(exc))

    def remove(self):
        entries=self.store.config.get('web_backends',[]); index=self.list.currentRow()
        if not 0<=index<len(entries): return
        if QMessageBox.question(self,self.tr('Search backends'),self.tr('Remove this profile and its saved credential?'),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes: return
        self.store.save_web_key(remove=True,ident=entries[index]['id']); self.refresh(max(0,index-1))

    def move(self,offset):
        entries=self.store.config.get('web_backends',[]); index=self.list.currentRow(); target=index+offset
        if not 0<=index<len(entries) or not 0<=target<len(entries): return
        entries[index],entries[target]=entries[target],entries[index]; self.store.flush(); self.refresh(target)


class WebSettings(QDialog):
    def __init__(self,parent,c):
        super().__init__(parent); self.store=parent.store; self.setWindowTitle(self.tr('Web research')); self.resize(650,600)
        layout=QFormLayout(self)
        notice=QLabel(self.tr('Hosted search browses inside the model provider using the submitted conversation. Managed search sends generated queries to a separate search service, even with local inference, and reads pages directly. Agentnik cannot enforce service/provider internal navigation. The strict navigation policy disables these external search routes.')); notice.setWordWrap(True); layout.addRow(notice)
        defaults=routing.connection_defaults(self.store.config,parent.session['connection_name'],c)
        self.default_policy=QComboBox()
        for policy in routing.POLICIES:self.default_policy.addItem(policy_label(policy),policy)
        self.default_policy.setCurrentIndex(self.default_policy.findData(defaults['policy'])); layout.addRow(self.tr('Default for this connection'),self.default_policy)
        self.access_policy=QComboBox(); self.access_policy.addItem(self.tr('Public page reads; external search navigation disclosed'),'public_fetch'); self.access_policy.addItem(self.tr('Enforce public-only navigation everywhere'),'strict_public'); self.access_policy.setCurrentIndex(self.access_policy.findData(defaults['access_policy'])); layout.addRow(self.tr('Navigation policy'),self.access_policy)
        manage=QPushButton(self.tr('Manage ordered search backends…')); manage.clicked.connect(self.manage_backends); layout.addRow(manage)
        self.backend_label=QLabel(); layout.addRow(self.tr('Key for first saved backend'),self.backend_label); self.select_backend()
        self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.EchoMode.Password); self.key.setPlaceholderText(self.tr('Blank keeps saved key / OLLAMA_WEB_API_KEY for default profile'))
        layout.addRow(self.tr('Separate search API key'),self.key)
        self.remove=QCheckBox(self.tr('Remove this saved search key')); layout.addRow(self.remove)
        self.plain=QCheckBox(self.tr('Store new search key as plaintext (explicit fallback)')); layout.addRow(self.plain)
        current=research.capability(self.store.config,c)
        self.allow=QCheckBox(self.tr('Enable managed tool requests for this endpoint/model'))
        self.allow.setEnabled(core_managed(c)); self.allow.setChecked(current.state in ('configured','verified')); layout.addRow(self.allow)
        hosted_cap=research.capability(self.store.config,c,'hosted_search')
        self.allow_hosted=QCheckBox(self.tr('Enable OpenAI-hosted web_search for this endpoint/model'))
        self.allow_hosted.setEnabled(hosted.supported_endpoint(c)); self.allow_hosted.setChecked(hosted_cap.state in ('configured','verified')); layout.addRow(self.allow_hosted)
        states={'unknown':self.tr('unknown'),'configured':self.tr('configured'),'verified':self.tr('verified'),'unsupported':self.tr('unsupported')}
        status=self.tr('Model: {model} · managed: {managed} · hosted: {hosted}\nEnabling is configuration, not verification. Hosted search requires the official OpenAI Responses endpoint and a model that supports web_search. No background inference probes are run.')
        label=QLabel(status.format(model=c.get('model',''),managed=states[current.state],hosted=states[hosted_cap.state])); label.setTextFormat(Qt.TextFormat.PlainText); label.setWordWrap(True); layout.addRow(label)
        bounds=Limits()
        limits=self.tr('Limits: {rounds} managed rounds, {calls} tool calls, {requests} model requests across attempts; {request_seconds}s/request, {turn_seconds}s/turn. One retry per route on explicit 429/503 rejection, with bounded Retry-After. Partial or uncertain work always requires explicit restart.')
        info=QLabel(limits.format(rounds=bounds.rounds,calls=bounds.calls,requests=bounds.requests,request_seconds=f'{bounds.request_seconds:g}',turn_seconds=f'{bounds.turn_seconds:g}')); info.setWordWrap(True); layout.addRow(info)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addRow(buttons)

    def select_backend(self):
        entries=self.store.config.get('web_backends',[])
        self.backend_id=entries[0]['id'] if entries else 'ollama-search'
        self.backend_label.setText(entries[0].get('name','Ollama search') if entries else 'Ollama search (default)')

    def manage_backends(self):
        SearchBackends(self,self.store).exec(); self.select_backend()


def core_managed(c):
    from . import core
    return c.get('protocol','chat') in core.PROTOCOLS


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
        signature=(data.get('status'),len(events),len(sources),tuple(data.get('unverified_citations',[])),data.get('unverified_annotations',0))
        if signature==self.signature: return
        self.signature=signature
        route={'hosted':self.tr('Provider hosted'),'managed':self.tr('Agentnik managed')}.get(data.get('route'),self.tr('Selecting route'))
        status=data.get('status','running')
        status_labels={'running':self.tr('Running'),'completed':self.tr('Completed'),'failed':self.tr('Failed'),'cancelled':self.tr('Cancelled'),'limited':self.tr('Limited'),'interrupted':self.tr('Interrupted')}
        self.toggle.setText(self.tr('Research · {route} · {status} · {count} source(s)').format(route=route,status=status_labels.get(status,status),count=len(sources)))
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
            if source.get('metadata_only'):
                excerpts.append(self.tr('[{id}] {url}\nReported: {time} · {backend}\nProvider metadata only; page retrieval time and excerpt were not supplied.').format(id=source['id'],url=url,time=source.get('reported_at','unknown'),backend=source.get('backend','')))
            else:
                prefix=self.tr('[{id}] {url}\nRetrieved: {time} · {backend}\nSaved excerpt (truncated); not a fresh or complete page.\n') if source.get('truncated') else self.tr('[{id}] {url}\nRetrieved: {time} · {backend}\nSaved excerpt; not a fresh or complete page.\n')
                excerpts.append(prefix.format(id=source['id'],url=url,time=source['retrieved_at'],backend=source.get('backend',''))+source['excerpt'])
        text='\n\n'.join(excerpts)
        if sources: text+='\n\n'+self.tr('Source links identify retrieved evidence; they do not verify that every claim is supported.')
        if data.get('unverified_annotations'): text+='\n'+self.tr('Some provider citation annotations could not be validated.')
        if data.get('unverified_citations'): text+='\n'+self.tr('Unverified citation IDs: {ids}').format(ids=', '.join(data['unverified_citations']))
        self.excerpts.setPlainText(text); self.excerpts.setVisible(bool(text))
