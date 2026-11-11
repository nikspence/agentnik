"""Repository picker and Agentnik-owned coding pane."""
from pathlib import Path
import json
import re
import threading
from urllib.parse import urlsplit
from PySide6.QtCore import Qt,Signal,QObject,QUrl,QPoint,QTimer
from PySide6.QtGui import QDesktopServices,QTextCursor
from PySide6.QtWidgets import QScrollArea,QApplication,QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QListWidget,QListWidgetItem,QPushButton,QDialogButtonBox,QFileDialog,QInputDialog,QMessageBox,QPlainTextEdit,QComboBox,QCheckBox,QSpinBox
from .repositories import RepositoryRegistry
from .coding import SimulationRun,plain
from .code_agent import CodingRun
from .research import scrub
from . import decision_advice
from .decision_advice import parse_advice
from .task_plan import validate_plan
from .subagent_status import validate_record
from .sessions import append_code_activity
from .code_limits import FIELDS,coding_limits
from .web import public_url
from . import core,routing
from .research_ui import SearchBackends
from .search_providers import SEARCH_KINDS


class RepositoryPicker(QDialog):
    def __init__(self,parent,registry,select=True):
        super().__init__(parent);self.registry=registry;self.selected_id=None;self.select=select
        self.setWindowTitle(self.tr('Choose repository') if select else self.tr('Repositories'));self.resize(680,400)
        layout=QVBoxLayout(self);self.search=QLineEdit();self.search.setPlaceholderText(self.tr('Search project names and paths'));layout.addWidget(self.search)
        self.items=QListWidget();layout.addWidget(self.items);self.search.textChanged.connect(self.refresh)
        actions=QHBoxLayout();layout.addLayout(actions)
        for label,fn in [(self.tr('Add folder'),self.add),(self.tr('Rename'),self.rename),(self.tr('Locate folder'),self.locate),(self.tr('Remove from list'),self.remove)]:
            button=QPushButton(label);button.clicked.connect(fn);actions.addWidget(button)
        self.hint=QLabel(self.tr('Git is optional. Removing an entry never deletes files. Add a folder to begin.'));self.hint.setWordWrap(True);layout.addWidget(self.hint)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Open|QDialogButtonBox.StandardButton.Cancel if select else QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self.choose);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        if select:self.items.itemDoubleClicked.connect(lambda *_:self.choose())
        self.refresh()

    def selected(self):
        item=self.items.currentItem();return self.registry.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def refresh(self,*_):
        old=self.selected();self.items.clear();needle=self.search.text().casefold()
        for row in self.registry.list():
            if needle not in (row['name']+' '+row['path']).casefold():continue
            item=QListWidgetItem(row['name']+(' · '+self.tr('missing/unavailable') if not row['available'] else '')+'\n'+row['path']);item.setData(Qt.ItemDataRole.UserRole,row['id']);self.items.addItem(item)
            if old and row['id']==old['id']:self.items.setCurrentItem(item)
        if self.items.currentRow()<0 and self.items.count():self.items.setCurrentRow(0)

    def attempt(self,fn):
        try:fn();self.refresh()
        except (OSError,ValueError) as exc:QMessageBox.warning(self,self.tr('Repositories'),str(exc))

    def add(self):
        path=QFileDialog.getExistingDirectory(self,self.tr('Add project folder'))
        if path:self.attempt(lambda:self.registry.put(path))

    def rename(self):
        row=self.selected()
        if not row:return
        name,ok=QInputDialog.getText(self,self.tr('Rename project'),self.tr('Name:'),text=row['name'])
        if ok:self.attempt(lambda:self.registry.rename(row['id'],name))

    def locate(self):
        row=self.selected()
        if not row:return
        path=QFileDialog.getExistingDirectory(self,self.tr('Locate project folder'))
        if path:self.attempt(lambda:self.registry.put(path,row['name'],row['id']))

    def remove(self):
        row=self.selected()
        if row and QMessageBox.question(self,self.tr('Remove project'),self.tr('Remove this entry from the list? Its files and history will remain.'))==QMessageBox.StandardButton.Yes:
            self.attempt(lambda:self.registry.remove(row['id']))

    def choose(self):
        row=self.selected()
        if not row:return
        try:self.registry.directory(row['path'])
        except (OSError,ValueError) as exc:QMessageBox.warning(self,self.tr('Unavailable project'),str(exc));return
        self.selected_id=row['id'];self.accept()


class CodeEvents(QObject):
    event=Signal(object)


class CodingLimitsDialog(QDialog):
    def __init__(self,parent,values):
        super().__init__(parent);self.setWindowTitle(self.tr('Coding run limits'))
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form);self.fields={}
        labels={'rounds':self.tr('Tool rounds'),'requests':self.tr('Model requests'),'calls':self.tr('Tool calls'),'turn_seconds':self.tr('Total run time (seconds)'),'model_seconds':self.tr('Model call timeout (seconds)'),'context_bytes':self.tr('Retained context (bytes)')}
        for key,(_,minimum,maximum) in FIELDS.items():
            box=QSpinBox();box.setRange(minimum,maximum);box.setValue(coding_limits(values)[key]);form.addRow(labels[key],box);self.fields[key]=box
        hint=QLabel(self.tr('Limits are shared by Heavy, Light, and web research for each run.')+'\n'+self.tr('Each model timeout covers waiting for the first token and generating the complete response. Total run time can end a request sooner.'));hint.setWordWrap(True);layout.addWidget(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.reset);layout.addWidget(buttons)

    def reset(self):
        for key,value in coding_limits().items():self.fields[key].setValue(value)

    def values(self):return coding_limits({key:box.value() for key,box in self.fields.items()})


class CodingSourcesDialog(QDialog):
    def __init__(self,parent,sources):
        super().__init__(parent);self.setWindowTitle(self.tr('Research sources'));self.resize(680,380)
        layout=QVBoxLayout(self);hint=QLabel(self.tr('Sources from the most recent coding run. Review each source before relying on it.'));hint.setWordWrap(True);layout.addWidget(hint)
        self.items=QListWidget();layout.addWidget(self.items)
        for source in sources:
            try:url=public_url(source['url'])
            except (KeyError,ValueError):continue
            item=QListWidgetItem(source['id']+' · '+source['title']+'\n'+url);item.setData(Qt.ItemDataRole.UserRole,url);item.setToolTip(url);self.items.addItem(item)
        row=QHBoxLayout();layout.addLayout(row)
        open_button=QPushButton(self.tr('Open in browser'));open_button.clicked.connect(self.open_source);row.addWidget(open_button)
        copy_button=QPushButton(self.tr('Copy link'));copy_button.clicked.connect(self.copy_source);row.addWidget(copy_button)
        close_button=QPushButton(self.tr('Close'));close_button.clicked.connect(self.accept);row.addWidget(close_button)
        if self.items.count():self.items.setCurrentRow(0)

    def selected_url(self):
        item=self.items.currentItem()
        if not item:return None
        try:return public_url(item.data(Qt.ItemDataRole.UserRole))
        except ValueError:return None

    def open_source(self):
        url=self.selected_url()
        if url:QDesktopServices.openUrl(QUrl(url))

    def copy_source(self):
        url=self.selected_url()
        if url:QApplication.clipboard().setText(url)


class CodeTab(QWidget):
    updated=Signal()
    def __init__(self,window,session):
        super().__init__();self.window=window;self.store=window.store;self.session=session;self.job=None;self.model_jobs={};self._closed=False;self.run_id=None;self.pending_fingerprint=None;self.advice_fingerprint=None;self.advice_job=None;self.advice_connection=None;self.advice_destination=''
        self.events=CodeEvents(self);self.events.event.connect(self.receive)
        if session.get("code_state") in ("running","awaiting_approval"):
            session["code_state"]="interrupted"
            for item in session.get("coding_subagents",[]):
                if item["status"]=="running":item["status"]="interrupted"
            append_code_activity(session,'interrupted','Interrupted coding run; nothing resumes automatically.')
            self.store.save(session)
        layout=QVBoxLayout(self)
        header=QHBoxLayout();layout.addLayout(header)
        title=QLabel(session['project_name']);title.setTextFormat(Qt.TextFormat.PlainText);header.addWidget(title)
        path=QLabel(self.tr('Working directory snapshot: {path}').format(path=session['path_snapshot']));path.setTextFormat(Qt.TextFormat.PlainText);path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);path.setToolTip(session['path_snapshot']);header.addWidget(path,1)
        current=window.repositories.get(session['project_id'])
        note=''
        if not Path(session['path_snapshot']).is_dir():note+=' '+self.tr('The saved folder is missing or unavailable.')
        if current is None:note+=' '+self.tr('This project was removed from the registry; its history is retained.')
        elif current['path']!=session['path_snapshot']:note+=' '+self.tr('The registered folder moved. This session retains its original path; open a new Code pane to use the relocated folder.')
        if note:
            warning=QLabel(note.strip());warning.setWordWrap(True);warning.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(warning)
        self.plan_toggle=QPushButton();self.plan_toggle.setCheckable(True);layout.addWidget(self.plan_toggle)
        self.plan_panel=QWidget();plan_layout=QVBoxLayout(self.plan_panel);plan_layout.setContentsMargins(0,0,0,0);layout.addWidget(self.plan_panel)
        self.plan_list=QListWidget();self.plan_list.setMaximumHeight(140);plan_layout.addWidget(self.plan_list)
        self.plan_explanation=QPlainTextEdit();self.plan_explanation.setReadOnly(True);self.plan_explanation.setMaximumHeight(55);plan_layout.addWidget(self.plan_explanation)
        plan_note=QLabel(self.tr('Model-reported progress. Unfinished steps remain after a stopped run; reopening does not resume work.'));plan_note.setWordWrap(True);plan_layout.addWidget(plan_note)
        self.plan_toggle.toggled.connect(self.plan_panel.setVisible);self.plan_panel.hide();self.refresh_plan()
        self.subagents_toggle=QPushButton();self.subagents_toggle.setCheckable(True);layout.addWidget(self.subagents_toggle)
        self.subagents_view=QPlainTextEdit();self.subagents_view.setReadOnly(True);self.subagents_view.setMinimumHeight(35);self.subagents_view.setMaximumHeight(135);self.subagents_view.setToolTip(self.tr('Cancellation stops waiting; an already submitted provider request may continue.'));layout.addWidget(self.subagents_view)
        self.subagents_controls=QWidget();subagent_actions=QHBoxLayout(self.subagents_controls);subagent_actions.setContentsMargins(0,0,0,0)
        self.subagent_choice=QComboBox();self.subagent_choice.setAccessibleName(self.tr('Running subagent'));self.subagent_choice.setMinimumContentsLength(30);self.subagent_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.subagent_choice.setMaximumWidth(360);subagent_actions.addWidget(self.subagent_choice)
        self.stop_subagent_button=QPushButton(self.tr('Cancel subagent'));self.stop_subagent_button.clicked.connect(self.cancel_selected_subagent);subagent_actions.addWidget(self.stop_subagent_button);subagent_actions.addStretch();layout.addWidget(self.subagents_controls)
        self.subagents_toggle.toggled.connect(self.subagents_view.setVisible);self.subagents_toggle.toggled.connect(self.subagents_controls.setVisible);self.subagents_view.hide();self.subagents_controls.hide();self.refresh_subagents()
        self.activity=QPlainTextEdit('\n'.join(self.activity_text(e) for e in session.get('code_activity',[])));self.activity.setPlaceholderText(self.tr('No commands have been run.'));self.activity.setReadOnly(True);layout.addWidget(self.activity,1)
        self.activity.moveCursor(QTextCursor.MoveOperation.End)
        self._activity_revision=0;self._activity_initial_follow=True;self.activity.verticalScrollBar().actionTriggered.connect(self.activity_scrolled)
        QTimer.singleShot(0,self.finish_activity_open)
        self.composer=QPlainTextEdit(session.get('draft',''));self.composer.setPlaceholderText(self.tr('Describe the coding task; repository files may be sent to the selected models'));self.composer.setMaximumHeight(90);layout.addWidget(self.composer)
        context=session.get('coding_context')
        self.context_view=QPlainTextEdit(self.context_text(context))
        self.context_view.setReadOnly(True);self.context_view.setMaximumHeight(110);layout.addWidget(self.context_view)
        self.use_context=QCheckBox(self.tr('Send previous task and answer with next run (up to 2,048 characters each)'));self.use_context.setEnabled(bool(context))
        options=QHBoxLayout();layout.addLayout(options)
        self.roles={}
        bindings=dict(session.get('coding_models',{}));bindings['decision']=session.get('coding_decision_model',{});bindings['alternate']=session.get('coding_subagent_model',{});bindings['alternate2']=session.get('coding_subagent_model_2',{})
        self.model_toggle=QPushButton(self.tr('Models'));self.model_toggle.setCheckable(True);layout.addWidget(self.model_toggle)
        self.model_panel=QWidget();model_layout=QVBoxLayout(self.model_panel);layout.addWidget(self.model_panel);self.model_panel.hide()
        self.model_toggle.toggled.connect(self.model_panel.setVisible)
        for role in ('heavy','light','alternate','alternate2','decision'):
            row=QHBoxLayout();model_layout.addLayout(row);row.addWidget(QLabel({'heavy':self.tr('Heavy model'),'light':self.tr('Light model'),'alternate':self.tr('Alternate subagent model (optional)'),'alternate2':self.tr('Second alternate subagent model (optional)'),'decision':self.tr('Decision model')}[role]))
            connection=QComboBox();connection.addItem(self.tr('Not configured'),'');
            for name in window.connections:connection.addItem(name,name)
            model=QLineEdit();model.setPlaceholderText(self.tr('Model alias (any supported coding model)'))
            saved=bindings.get(role,{})
            missing=saved.get('connection','')
            if missing and connection.findData(missing)<0:connection.addItem(missing+' (unavailable)',missing)
            connection.setCurrentIndex(max(0,connection.findData(saved.get('connection',''))));model.setText(saved.get('model',''))
            row.addWidget(connection);row.addWidget(model,1);self.roles[role]=(connection,model)
            choose=QPushButton(self.tr('Choose model…'));choose.clicked.connect(lambda _,r=role:self.choose_model(r));row.addWidget(choose)
            connection.currentIndexChanged.connect(lambda _,r=role:self.role_changed(r))
            model.editingFinished.connect(self.save_models)
        self.advice_enabled=QCheckBox(self.tr('Check shell approvals with Decision model'))
        self.advice_enabled.setChecked(session.get('coding_advice_enabled',False));self.advice_enabled.toggled.connect(self.save_advice_enabled);model_layout.addWidget(self.advice_enabled)
        disclosure=QLabel(self.tr('When enabled, each shell proposal sends its command, working directory, shell, and environment variable names to the selected Decision endpoint. Environment values are not sent. Advice never approves a command.'))
        disclosure.setWordWrap(True);model_layout.addWidget(disclosure)
        self.skills_button=QPushButton();self.skills_button.clicked.connect(self.choose_skills);options.addWidget(self.skills_button);self.refresh_skills_button()
        self.skills_history_button=QPushButton(self.tr('Skill history…'));self.skills_history_button.clicked.connect(self.show_skills_history);options.addWidget(self.skills_history_button)
        self.light_enabled=QCheckBox(self.tr('Allow Light model delegation'));self.light_enabled.setToolTip(self.tr('Allow individual or parallel Light analysis tasks. Parallel tasks can use Light or either optional alternate subagent model. Each project file sent to a subagent requires approval; run limits are shared.'));self.light_enabled.setChecked(session.get('coding_light_enabled',True) is not False);options.addWidget(self.light_enabled);options.addWidget(self.use_context)
        self.light_enabled.toggled.connect(self.save_light_enabled)
        self.web_enabled=QCheckBox(self.tr('Allow web research'));self.web_enabled.setToolTip(self.tr('Search uses configured providers, then Firecrawl Keyless and Google fallback when eligible. Without configured providers, Firecrawl Keyless is first. Ollama search is used only for direct Ollama Cloud. Filtered public page reads may send the page URL to a retrieval provider.'))
        self.web_enabled.setChecked(session.get('coding_web_enabled',False));options.addWidget(self.web_enabled)
        self.web_enabled.toggled.connect(self.save_web_enabled)
        mcp_row=QHBoxLayout();layout.addLayout(mcp_row);mcp_row.addWidget(QLabel(self.tr('MCP server for this run:')))
        self.mcp_choice=QComboBox();self.mcp_choice.setToolTip(self.tr('Optional MCP server for this run. Connecting or starting it and every tool call require approval; tool results go to the selected model.'));mcp_row.addWidget(self.mcp_choice,1)
        self.mcp_extra=[];self.mcp_extra_button=QPushButton(self.tr('Additional servers…'));self.mcp_extra_button.clicked.connect(self.choose_additional_mcp);mcp_row.addWidget(self.mcp_extra_button)
        self.mcp_refresh=QPushButton(self.tr('Refresh MCP'));self.mcp_refresh.clicked.connect(self.refresh_mcp_servers);mcp_row.addWidget(self.mcp_refresh);self.refresh_mcp_servers()
        self.limits_button=QPushButton(self.tr('Limits…'));self.limits_button.clicked.connect(self.configure_limits);options.addWidget(self.limits_button)
        self.sources_button=QPushButton();self.sources_button.clicked.connect(self.show_sources)
        run_row=QHBoxLayout();layout.addLayout(run_row)
        self.send=QPushButton(self.tr('Run'));self.send.clicked.connect(self.start_coding);run_row.addWidget(self.send)
        self.simulate=QPushButton(self.tr('Simulate'));self.simulate.clicked.connect(self.start_simulation);run_row.addWidget(self.simulate)
        self.cancel_button=QPushButton(self.tr('Cancel'));self.cancel_button.setEnabled(False);self.cancel_button.clicked.connect(self.cancel);run_row.addWidget(self.cancel_button)
        run_row.addWidget(self.model_toggle)
        self.search_settings=QPushButton(self.tr('Search settings…'));self.search_settings.setToolTip(self.tr('Manage search profiles shared with Chat'));self.search_settings.clicked.connect(self.configure_search);run_row.addWidget(self.search_settings)
        run_row.addWidget(self.sources_button);self.update_sources_button()
        self.approval_panel=QWidget();review=QVBoxLayout(self.approval_panel);layout.addWidget(self.approval_panel);self.approval_panel.hide()
        self.approval=QPlainTextEdit();self.approval.setReadOnly(True);self.approval.setPlaceholderText(self.tr('Command approval preview'));review.addWidget(self.approval)
        self.advice_label=QLabel();self.advice_label.setWordWrap(True);self.advice_label.setTextFormat(Qt.TextFormat.PlainText);review.addWidget(self.advice_label);self.advice_label.hide()
        actions=QHBoxLayout();review.addLayout(actions)
        self.approve=QPushButton(self.tr('Approve proposed step'));self.reject=QPushButton(self.tr('Reject proposed step'))
        for button in (self.approve,self.reject):actions.addWidget(button);button.setEnabled(False)
        self.approve.clicked.connect(lambda:self.decide(True));self.reject.clicked.connect(lambda:self.decide(False))
        self.diff=QPlainTextEdit();self.diff.setReadOnly(True);self.diff.setPlaceholderText(self.tr('Review the complete proposed file diff before approving'));review.addWidget(self.diff)
        self.composer.textChanged.connect(self.save_draft)

    def refresh_plan(self):
        plan=self.session.get('coding_plan');self.plan_list.clear()
        self.plan_toggle.setVisible(bool(plan))
        if not plan:
            self.plan_toggle.setChecked(False);self.plan_panel.hide();self.plan_explanation.clear();return
        completed=sum(step['status']=='completed' for step in plan['steps'])
        self.plan_toggle.setText(self.tr('Task plan · {completed}/{total} completed').format(completed=completed,total=len(plan['steps'])))
        labels={'pending':self.tr('Pending'),'in_progress':self.tr('In progress'),'completed':self.tr('Completed'),'blocked':self.tr('Blocked')}
        for step in plan['steps']:
            item=QListWidgetItem(labels[step['status']]+' · '+step['step']);item.setToolTip(item.text())
            item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Checked if step['status']=='completed' else Qt.CheckState.Unchecked)
            self.plan_list.addItem(item)
        height=sum(max(16,self.plan_list.sizeHintForRow(i)) for i in range(min(8,self.plan_list.count())))+2*self.plan_list.frameWidth()+6
        self.plan_list.setMaximumHeight(max(44,min(140,height)))
        self.plan_explanation.setPlainText(plan['explanation']);self.plan_explanation.setVisible(bool(plan['explanation']))

    def refresh_subagents(self):
        items=self.session.get('coding_subagents',[]);self.subagents_toggle.setVisible(bool(items))
        if not items:
            self.subagents_toggle.setChecked(False);self.subagents_view.hide();self.subagents_controls.hide();self.subagents_view.clear();self.subagent_choice.clear();self.stop_subagent_button.setEnabled(False);return
        selected=self.subagent_choice.currentData();self.subagent_choice.blockSignals(True);self.subagent_choice.clear()
        for item in items:
            if item['status']=='running':self.subagent_choice.addItem(item['text'].replace('\n',' ')[:80],item['id'])
        index=self.subagent_choice.findData(selected)
        if index>=0:self.subagent_choice.setCurrentIndex(index)
        self.subagent_choice.blockSignals(False);self.stop_subagent_button.setEnabled(bool(self.job) and self.subagent_choice.count()>0)
        running=sum(item['status']=='running' for item in items)
        self.subagents_toggle.setText(self.tr('Subagents · {count} total · {running} running').format(count=len(items),running=running))
        labels={'running':self.tr('Running'),'completed':self.tr('Completed'),'failed':self.tr('Failed'),'cancelled':self.tr('Cancelled'),'interrupted':self.tr('Interrupted'),'stopped':self.tr('Stopped')}
        self.subagents_view.setMaximumHeight(min(135,max(45,self.subagents_view.fontMetrics().lineSpacing()*min(8,2*len(items)+1)+10)))
        self.subagents_view.setPlainText('\n\n'.join(labels[item['status']]+' · '+item['text'] for item in items))

    def cancel_selected_subagent(self):
        ident=self.subagent_choice.currentData()
        if not isinstance(self.job,CodingRun) or not ident or not self.job.cancel_subagent(ident):return
        item=next((item for item in self.session.get('coding_subagents',[]) if item['id']==ident),None)
        if item and item['status']=='running':item['status']='cancelled'
        self.refresh_subagents();self.record('cancelled',self.tr('Subagent cancellation requested: {id}').format(id=ident))

    def stop_subagents(self,status):
        for item in self.session.get('coding_subagents',[]):
            if item['status']=='running':item['status']=status
        self.refresh_subagents()

    def choose_model(self,role):
        if self.job or role in self.model_jobs:return
        name=self.roles[role][0].currentData()
        if not name:return QMessageBox.information(self,self.tr('Coding model'),self.tr('Choose a connection first, or enter an alias manually.'))
        c=dict(self.window.connections.get(name,{}))
        from .ui import Job
        def done(names):
            self.model_jobs.pop(role,None)
            if self._closed or self.job or self.roles[role][0].currentData()!=name:return
            choices=[value for value in names if isinstance(value,str) and len(value)<=512][:2000]
            title={'heavy':self.tr('Choose Heavy model'),'light':self.tr('Choose Light model'),'alternate':self.tr('Choose alternate subagent model'),'alternate2':self.tr('Choose second alternate subagent model'),'decision':self.tr('Choose Decision model')}[role]
            model,ok=QInputDialog.getItem(self,title,self.tr('Model alias:'),choices,0,True)
            if ok:self.roles[role][1].setText(model);self.save_models()
        def failed(_):
            self.model_jobs.pop(role,None)
            if not self._closed:QMessageBox.warning(self,self.tr('Coding models'),self.tr('Model listing failed. You can enter an alias manually.'))
        self.model_jobs[role]=Job(lambda *_:core.models(c),done,failed)

    def context_text(self,context):
        if not context:return self.tr('No completed coding task available.')
        return self.tr('Previous task:\n{task}\n\nPrevious answer:\n{answer}').format(task=context['task'],answer=context['answer'])

    def role_changed(self,role):
        connection,model=self.roles[role];c=self.window.connections.get(connection.currentData(),{})
        model.setText(c.get('model',''));self.save_models()

    def save_models(self):
        self.session['coding_models']={role:{'connection':self.roles[role][0].currentData(),'model':self.roles[role][1].text().strip()} for role in ('heavy','light')}
        widgets=self.roles['alternate'];self.session['coding_subagent_model']={'connection':widgets[0].currentData(),'model':widgets[1].text().strip()}
        widgets=self.roles['alternate2'];self.session['coding_subagent_model_2']={'connection':widgets[0].currentData(),'model':widgets[1].text().strip()}
        widgets=self.roles['decision'];self.session['coding_decision_model']={'connection':widgets[0].currentData(),'model':widgets[1].text().strip()}
        self.store.save(self.session)

    def save_light_enabled(self,enabled):
        self.session['coding_light_enabled']=enabled;self.store.save(self.session)

    def save_web_enabled(self,enabled):
        self.session['coding_web_enabled']=enabled;self.store.save(self.session)

    def save_advice_enabled(self,enabled):
        self.session['coding_advice_enabled']=enabled;self.store.save(self.session)

    def configure_limits(self):
        if self.job:return
        dialog=CodingLimitsDialog(self,coding_limits(self.session.get('coding_limits')))
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.session['coding_limits']=dialog.values();self.store.save(self.session)

    def configure_search(self):
        if not self.job:SearchBackends(self,self.store).exec()

    def update_sources_button(self):
        count=len(self.session.get('coding_sources',[]));self.sources_button.setText(self.tr('Sources ({count})').format(count=count));self.sources_button.setVisible(count>0)

    def show_sources(self):
        CodingSourcesDialog(self,self.session.get('coding_sources',[])).exec()

    def show_advice(self,raw=None,fingerprint=None):
        if raw is None:
            self.advice_label.setText(self.tr('Safety advice: NOT CHECKED · No System One request was made.'))
        else:
            if not self.job or not self.pending_fingerprint or fingerprint!=self.pending_fingerprint or fingerprint!=self.advice_fingerprint:return
            result=parse_advice(raw);category=result['category']
            labels={'safe':self.tr('SAFE'),'warning':self.tr('WARNING'),'risky':self.tr('RISKY'),'privacy':self.tr('PRIVACY'),'danger':self.tr('DANGER'),'unknown':self.tr('UNKNOWN')}
            guides={'safe':self.tr('Low apparent risk; review before approving.'),'warning':self.tr('Uncertain or requires closer review.'),'risky':self.tr('May change files or system state.'),'privacy':self.tr('May expose private information.'),'danger':self.tr('May cause severe or irreversible effects.'),'unknown':self.tr('No valid category was returned.')}
            confidence=result['confidence']
            detail=self.tr('Confidence unavailable') if confidence is None else self.tr('Confidence: {value}').format(value=f'{confidence:.0%}')
            self.advice_label.setText(self.tr('Safety advice: {label} · {detail}\nCategory guide: {guide}\nAdvisory only; you decide.').format(label=labels[category],detail=detail,guide=guides[category]))
        self.advice_label.show()

    def check_advice(self,proposal,fingerprint):
        if not self.advice_connection:return
        from .ui import Job
        from shiboken6 import isValid
        connection=dict(self.advice_connection);run_id=self.run_id
        self.approve.setEnabled(False);self.reject.setEnabled(False)
        self.advice_label.setText(self.tr('Checking safety advice with {destination}…').format(destination=self.advice_destination))
        secret=connection.get('api_key','')
        fields=[str(proposal.get(key,'')) for key in ('command','cwd','shell','environment_keys')]
        if any('[redacted]' in value or (secret and secret in value) for value in fields):
            self.advice_label.setText(self.tr('Safety advice: UNKNOWN · The proposal contains a configured credential; no request was made.'))
            self.approve.setEnabled(True);self.reject.setEnabled(True);return
        def active():
            return isValid(self) and not self._closed and self.job is not None and self.run_id==run_id and self.pending_fingerprint==fingerprint and self.advice_fingerprint==fingerprint
        def done(raw):
            if not active():return
            self.advice_job=None;self.show_advice(raw,fingerprint);self.advice_label.setText(self.advice_label.text()+'\n'+self.tr('Decision endpoint: {destination}').format(destination=self.advice_destination));self.approve.setEnabled(True);self.reject.setEnabled(True)
            result=parse_advice(raw);confidence=(' confidence '+f'{result["confidence"]:.0%}') if result['confidence'] is not None else ' confidence unavailable'
            self.record('advice','System One advice '+result['category'].upper()+confidence+' for proposal '+fingerprint[:12]+' via '+self.advice_destination)
        def failed(_):
            if not active():return
            self.advice_job=None;self.advice_label.setText(self.tr('Safety advice: UNKNOWN · The decision check failed or timed out. Review the command yourself.')+'\n'+self.tr('Decision endpoint: {destination}').format(destination=self.advice_destination))
            self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('advice','System One advice unavailable for proposal '+fingerprint[:12]+' via '+self.advice_destination)
        self.advice_job=Job(lambda emit,cancel:decision_advice.request(connection,proposal,cancel),done,failed)

    def role_connection(self,role):
        name=self.roles[role][0].currentData()
        if not name:return None
        c=dict(self.window.connections.get(name,{}));c['model']=self.roles[role][1].text().strip()
        if not c.get('url') or not c.get('model'):
            raise ValueError({'heavy':self.tr('Choose a connection and model alias for Heavy.'),'light':self.tr('Choose a connection and model alias for Light.'),'alternate':self.tr('Choose a connection and model alias for the alternate subagent.'),'alternate2':self.tr('Choose a connection and model alias for the second alternate subagent.'),'decision':self.tr('Choose a connection and model alias for Decision.')}[role])
        return c

    def refresh_skills_button(self):
        names=self.session.get('coding_skills',[])
        self.skills_button.setText(self.tr('Skills ({count})').format(count=len(names)) if names else self.tr('Skills…'))
        self.skills_button.setToolTip(', '.join(names) if names else self.tr('Choose skills'))

    def show_skills_history(self):
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Skill history'));dialog.resize(700,450)
        layout=QVBoxLayout(dialog);view=QPlainTextEdit();view.setReadOnly(True)
        history=self.session.get('coding_skill_history',[])
        lines=[]
        for run in reversed(history):
            lines.append(self.tr('Run: {id}').format(id=run['run_id']))
            lines.extend('  '+skill['id']+' ['+skill['source']+'] · SHA-256 '+skill['sha256'] for skill in run['skills'])
            if not run['skills']:lines.append('  '+self.tr('No skill revisions recorded'))
            lines.append('')
        if not history and self.session.get('coding_skill_revisions'):
            lines.append(self.tr('Last run (legacy record)'))
            lines.extend('  '+skill['id']+' ['+skill['source']+'] · SHA-256 '+skill['sha256'] for skill in self.session['coding_skill_revisions'])
        view.setPlainText('\n'.join(lines) if lines else self.tr('No skill history recorded.'));layout.addWidget(view)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

    def choose_skills(self):
        if self.job: return
        from .code_agent import ProjectFiles
        from .project_skills import list_skills,read_skill
        try:
            files=ProjectFiles(self.session['path_snapshot']);skills=list_skills(files)
            snapshots={skill['id']:read_skill(files,skill['id']) for skill in skills}
        except (OSError,ValueError,UnicodeError) as exc:
            QMessageBox.warning(self,self.tr('Skills'),str(exc));return
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Choose skills'));layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel(self.tr('Selected skill instructions are sent to the model. Scripts still require approval.')))
        scroll=QScrollArea();scroll.setWidgetResizable(True);container=QWidget();skill_layout=QVBoxLayout(container);scroll.setWidget(container);layout.addWidget(scroll);dialog.resize(720,500)
        checks=[]
        for skill in skills:
            skill=snapshots[skill['id']]
            row=QHBoxLayout();skill_layout.addLayout(row)
            check=QCheckBox(skill['name']+' ['+skill['source']+'] — '+skill['description']);check.setChecked(skill['id'] in self.session.get('coding_skills',[]));row.addWidget(check);checks.append((skill['id'],check))
            preview=QPushButton(self.tr('Preview…'));row.addWidget(preview)
            def show_skill(checked=False,name=skill['id']):
                text=snapshots[name]['instructions']
                viewer=QDialog(dialog);viewer.setWindowTitle(name);viewer.resize(700,500);box=QVBoxLayout(viewer);content=QPlainTextEdit();content.setReadOnly(True);content.setPlainText(text);box.addWidget(content);viewer.exec()
            preview.clicked.connect(show_skill)
        available={skill['id'] for skill in skills}
        for ident in self.session.get('coding_skills',[]):
            if ident not in available:
                check=QCheckBox(self.tr('{name} (unavailable; uncheck to remove)').format(name=ident));check.setChecked(True);skill_layout.addWidget(check);checks.append((ident,check))
        if not checks:layout.addWidget(QLabel(self.tr('No skills found in repository or user .agents/skills.')))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            selected=[name for name,check in checks if check.isChecked()]
            if len(selected)>5:QMessageBox.warning(self,self.tr('Skills'),self.tr('Select at most five skills.'));return
            previous=self.session.get('coding_skill_pins',{});pins={}
            try:
                for ident in selected:
                    if ident in available:
                        pins[ident]=snapshots[ident]['sha256']
                        if read_skill(files,ident)['sha256']!=pins[ident]:raise ValueError('Skill changed')
                    elif ident in previous:pins[ident]=previous[ident]
            except (OSError,ValueError,UnicodeError) as exc:
                QMessageBox.warning(self,self.tr('Skills'),self.tr('A selected skill changed or became unavailable. Reopen Skills and try again.'));return
            self.session['coding_skills']=selected;self.session['coding_skill_pins']=pins;self.store.save(self.session);self.refresh_skills_button()

    def refresh_mcp_servers(self):
        current=self.mcp_choice.currentData();self.mcp_choice.clear();self.mcp_choice.addItem(self.tr('No MCP server'),None)
        for item in self.store.config.get('mcp_servers',[]):
            if item.get('enabled'):self.mcp_choice.addItem(item['name']+(' · HTTPS' if item.get('transport')=='http' else ' · local'),item['name'])
        if current:self.mcp_choice.setCurrentIndex(max(0,self.mcp_choice.findData(current)))

    def choose_additional_mcp(self):
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Additional MCP servers'));layout=QVBoxLayout(dialog)
        note=QLabel(self.tr('Select up to five servers total, including the server selected in the Code pane. Each server must be approved before connecting.'));note.setWordWrap(True);layout.addWidget(note)
        checks=[]
        for item in self.store.config.get('mcp_servers',[]):
            if not item.get('enabled'):continue
            check=QCheckBox(item['name']+(' · HTTPS' if item.get('transport')=='http' else ' · local'));check.setChecked(item['name'] in self.mcp_extra);layout.addWidget(check);checks.append((item['name'],check))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        selected=[name for name,check in checks if check.isChecked()]
        primary=self.mcp_choice.currentData()
        if len(set(selected+([primary] if primary else [])))>5:
            QMessageBox.warning(self,self.tr('MCP servers'),self.tr('Select at most five servers total.'));return
        self.mcp_extra=selected;self.mcp_extra_button.setText(self.tr('Additional servers ({count})…').format(count=len(selected)))

    def start_coding(self):
        if self.job or self._closed:return
        try:
            from .code_agent import ProjectFiles
            from .project_skills import verify_skill_pins
            verify_skill_pins(ProjectFiles(self.session['path_snapshot']),self.session.get('coding_skills',[]),self.session.get('coding_skill_pins',{}))
            self.save_models();heavy=self.role_connection('heavy');light=self.role_connection('light') if self.light_enabled.isChecked() else None
            alternate=self.role_connection('alternate') if self.light_enabled.isChecked() else None
            alternate2=self.role_connection('alternate2') if self.light_enabled.isChecked() else None
            if self.light_enabled.isChecked() and self.roles['alternate'][1].text().strip() and not alternate:raise ValueError(self.tr('Choose a connection for the alternate subagent model.'))
            if self.light_enabled.isChecked() and self.roles['alternate2'][1].text().strip() and not alternate2:raise ValueError(self.tr('Choose a connection for the second alternate subagent model.'))
            if (alternate or alternate2) and not light:raise ValueError(self.tr('Choose a Light model before using an alternate subagent model.'))
            advice=self.role_connection('decision') if self.advice_enabled.isChecked() else None
            if self.advice_enabled.isChecked() and not advice:raise ValueError(self.tr('Choose a Decision model before enabling safety advice.'))
            destination=(self.roles['decision'][0].currentText()+' / '+advice['model']+' / '+core.endpoint(advice,'decision')) if advice else ''
            if not heavy or not self.composer.toPlainText().strip():raise ValueError(self.tr('Choose a heavy model and enter a coding task'))
            context=self.session.get('coding_context') if self.use_context.isChecked() else None
            enabled=self.web_enabled.isChecked();backends=[];provider='none'
            if enabled:
                strict=routing.connection_defaults(self.store.config,self.roles['heavy'][0].currentData(),heavy)['access_policy']=='strict_public'
                parsed=urlsplit(heavy['url']);direct=parsed.scheme=='https' and parsed.hostname=='ollama.com' and parsed.port in (None,443)
                if not strict:
                    backends=[b for b in self.store.web_backend_specs() if b.get('kind') in SEARCH_KINDS and (b.get('kind')!='ollama' or direct)]
                    provider='managed'
            primary=self.mcp_choice.currentData();names=list(dict.fromkeys(([primary] if primary else [])+self.mcp_extra))
            if len(names)>5:raise ValueError(self.tr('Select at most five MCP servers.'))
            entries=self.store.config.get('mcp_servers',[]);servers=[]
            for name in names:
                server=next((item for item in entries if item.get('name')==name and item.get('enabled')),None)
                if not server:raise ValueError(self.tr('A selected MCP server is unavailable. Refresh the list.'))
                servers.append(server)
            from .mcp_code import CodingMCPBridge
            mcp_bridges=[CodingMCPBridge(server,self.store.config,self) for server in servers]
            run=CodingRun(heavy,self.session['path_snapshot'],self.composer.toPlainText(),light,context,backends,limits=self.session.get('coding_limits'),web_enabled=enabled,search_provider=provider,skills=self.session.get('coding_skills',[]),alternate=alternate,alternate2=alternate2,skill_pins=self.session.get('coding_skill_pins',{}),mcp_bridges=mcp_bridges)
        except (OSError,ValueError) as exc:QMessageBox.warning(self,self.tr('Coding settings'),str(exc));return
        self.advice_connection=advice;self.advice_destination=destination
        self.launch(run,'Agentnik coding started. Project file changes apply without per-file approval; shell commands require approval. Repository content goes to the selected models.')
        if enabled:self.record('output',{'none':'Web research: public page reads only; strict navigation disables search.','google':'Web research: Google search and public page reads.','ollama':'Web research: Ollama search and public page reads.','managed':'Web research: configured search providers and public page reads.'}[provider])

    def launch(self,run,notice):
        if isinstance(run,CodingRun):
            history=self.session.setdefault('coding_skill_history',[])
            history.append({'run_id':run.run_id,'skills':[]});self.session['coding_skill_history']=history[-32:]
            self.session['coding_subagents']=[];self.refresh_subagents()
            self.session['coding_sources']=[];self.session['coding_skill_revisions']=[];self.update_sources_button();self.session.pop('coding_plan',None);self.refresh_plan()
        self.job=run;self.run_id=run.run_id;self.pending_fingerprint=None;self.session['code_state']='running'
        self.simulate.setEnabled(False);self.send.setEnabled(False);self.cancel_button.setEnabled(True)
        self.light_enabled.setEnabled(False);self.web_enabled.setEnabled(False);self.limits_button.setEnabled(False);self.search_settings.setEnabled(False);self.advice_enabled.setEnabled(False);self.mcp_choice.setEnabled(False);self.mcp_refresh.setEnabled(False);self.mcp_extra_button.setEnabled(False)
        self.use_context.setEnabled(False)
        for connection,model in self.roles.values():connection.setEnabled(False);model.setEnabled(False)
        self.diff.clear();self.approval.clear();self.record('started',notice)
        signals=self.events
        def work():
            try:run.run(signals.event.emit)
            except RuntimeError:pass
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()

    def save_draft(self):
        self.session['draft']=self.composer.toPlainText();self.store.save(self.session);self.updated.emit()

    def activity_text(self,event):
        kind=event.get('kind','');text=plain(event.get('text',kind))
        fixed={('started','Agentnik coding started. Repository content goes to the selected models; edits await approval.'):self.tr('Agentnik coding started. Repository content goes to the selected models; edits await approval.'),
               ('started','Agentnik coding started. Project file changes apply without per-file approval; shell commands require approval. Repository content goes to the selected models.'):self.tr('Agentnik coding started. Project file changes apply without per-file approval; shell commands require approval. Repository content goes to the selected models.'),
               ('started','Simulation started; no commands or inference will run.'):self.tr('Simulation started; no commands or inference will run.'),
               ('approval','Awaiting explicit approval for simulated step.'):self.tr('Awaiting explicit approval for simulated step.'),
               ('cancelled','Run cancelled. No further tool work will be scheduled; already approved edits are retained.'):self.tr('Run cancelled. No further tool work will be scheduled; already approved edits are retained.'),
               ('interrupted','Interrupted coding run; nothing resumes automatically.'):self.tr('Interrupted coding run; nothing resumes automatically.')}
        if (kind,text) in fixed:return fixed[(kind,text)]
        prefix='Awaiting approval for file edit: '
        if kind=='approval' and text.startswith(prefix):return self.tr('Awaiting approval for file edit: {path}').format(path=text[len(prefix):])
        for prefix,template in [('Approved proposal ',self.tr('Approved proposal {id}')),('Rejected proposal ',self.tr('Rejected proposal {id}'))]:
            if kind=='decision' and text.startswith(prefix):return template.format(id=text[len(prefix):])
        if kind=='output':
            prefix='Heavy task: requesting ';suffix=' through the selected connection.'
            if text.startswith(prefix) and text.endswith(suffix):return self.tr('Heavy task: requesting {model} through the selected connection.').format(model=text[len(prefix):-len(suffix)])
            prefix='Light task delegated to ';suffix=' through its configured connection.'
            if text.startswith(prefix) and text.endswith(suffix):return self.tr('Light task delegated to {model} through its configured connection.').format(model=text[len(prefix):-len(suffix)])
            prefix='Applied approved edit: '
            if text.startswith(prefix):return self.tr('Applied approved edit: {path}').format(path=text[len(prefix):])
        if kind=='usage':
            if text=='Usage: no model requests':return self.tr('Usage: no model requests')
            if text.startswith('Usage: '):
                parts=[]
                for part in text[7:].split('; '):
                    match=re.fullmatch(r'(Heavy|Light): (\d+) request\(s\), input (\d+(?:\.\d+)?|unknown)( \(known usage only\))?, output (\d+(?:\.\d+)?|unknown)( \(known usage only\))? tokens',part)
                    if not match:return text
                    role,count,incoming,in_partial,outgoing,out_partial=match.groups()
                    incoming=self.tr('unknown') if incoming=='unknown' else incoming
                    outgoing=self.tr('unknown') if outgoing=='unknown' else outgoing
                    partial=self.tr(' (known usage only)')
                    parts.append(self.tr('{role}: {count} request(s), input {incoming}{in_partial}, output {outgoing}{out_partial} tokens').format(role=self.tr('Heavy') if role=='Heavy' else self.tr('Light'),count=count,incoming=incoming,in_partial=partial if in_partial else '',outgoing=outgoing,out_partial=partial if out_partial else ''))
                return self.tr('Usage: {details}').format(details='; '.join(parts))
        return text

    def activity_scrolled(self,*_):
        self._activity_initial_follow=False;self._activity_revision+=1

    def finish_activity_open(self):
        if not self._closed and self._activity_initial_follow:
            scroll=self.activity.verticalScrollBar();scroll.setValue(scroll.maximum())
        self._activity_initial_follow=False

    def record(self,kind,text):
        self._activity_revision+=1;revision=self._activity_revision
        scroll=self.activity.verticalScrollBar();position=scroll.value();following=self._activity_initial_follow or position==scroll.maximum()
        anchor=self.activity.cursorForPosition(QPoint(2,2));anchor_block=anchor.blockNumber();anchor_offset=anchor.positionInBlock();anchor_y=self.activity.cursorRect(anchor).top()
        cleaned=plain(text);removed=append_code_activity(self.session,kind,cleaned)
        if removed:
            removed_blocks=sum(self.activity_text(e).count('\n')+1 for e in removed)
            self.activity.setPlainText('\n'.join(self.activity_text(e) for e in self.session['code_activity']))
            position=max(0,position-removed_blocks)
        else:self.activity.appendPlainText(self.activity_text({'kind':kind,'text':cleaned}))
        scroll.setValue(scroll.maximum() if following else position)
        if removed and not following and anchor_block>=removed_blocks:
            def restore_anchor():
                if self._closed or self._activity_revision!=revision:return
                block=self.activity.document().findBlockByNumber(anchor_block-removed_blocks)
                if not block.isValid():return
                cursor=QTextCursor(block);cursor.setPosition(min(block.position()+anchor_offset,block.position()+block.length()-1))
                for _ in range(5):
                    delta=self.activity.cursorRect(cursor).top()-anchor_y
                    if abs(delta)<2:break
                    step=round(delta/max(1,self.activity.fontMetrics().lineSpacing())) or (1 if delta>0 else -1)
                    previous=scroll.value();scroll.setValue(previous+step)
                    if scroll.value()==previous:break
            QTimer.singleShot(0,restore_anchor)
        self.store.save(self.session);self.updated.emit()

    def start_simulation(self):
        if self.job or self._closed:return
        self.launch(SimulationRun(self.session['path_snapshot']),'Simulation started; no commands or inference will run.')

    def receive(self,event):
        if self._closed or not self.job or event.get('run_id')!=self.run_id:return
        kind=event.get('kind')
        if kind=='subagent':
            try:
                value=validate_record(event.get('subagent'));value['text']=plain(value['text'])[:1600]
            except (ValueError,TypeError):return
            records=self.session.setdefault('coding_subagents',[])
            prior=next((item for item in records if item['id']==value['id']),None)
            if prior is None:
                if value['status']!='running':return
                records.append(value);self.session['coding_subagents']=records[-32:]
            elif (prior['status']=='running' and value['status'] in ('completed','failed','cancelled')) or (prior['status']=='cancelled' and value['status']=='cancelled'):
                prior.update(value)
            else:return
            self.refresh_subagents();self.store.save(self.session);self.updated.emit();return
        if kind=='skill_revision':
            revision=event.get('skill',{})
            if not isinstance(revision,dict) or set(revision)!={'id','source','sha256'}:return
            if not isinstance(revision['id'],str) or not 0<len(revision['id'])<=69 or revision['source'] not in ('repository','user') or not isinstance(revision['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',revision['sha256']):return
            revisions=self.session.setdefault('coding_skill_revisions',[])
            if len(revisions)>=5 or any(item['id']==revision['id'] for item in revisions):return
            revisions.append(dict(revision))
            history=self.session.get('coding_skill_history',[])
            if history and history[-1]['run_id']==self.run_id:history[-1]['skills'].append(dict(revision))
            self.store.save(self.session);self.updated.emit();return
        if kind=='plan':
            try:plan=validate_plan(event.get('plan'))
            except ValueError:return
            self.session['coding_plan']=plan;self.refresh_plan();self.store.save(self.session);self.updated.emit();return
        elif kind=='source':
            source=event.get('source',{})
            try:
                ident=source['id'];title=source['title'];url=public_url(source['url'])
                if not isinstance(ident,str) or not re.fullmatch(r'S[1-9][0-9]{0,14}',ident) or not isinstance(title,str):return
                sources=self.session.setdefault('coding_sources',[])
                if len(sources)>=32:return
                sources.append({'id':ident,'title':plain(title)[:200],'url':url});self.store.save(self.session);self.update_sources_button()
            except (KeyError,TypeError,ValueError):return
        elif kind=='edit_proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval'
            self.advice_fingerprint=None;self.advice_label.hide()
            proposal=event['proposal'];self.diff.setVisible(True);self.diff.setPlainText(proposal['diff'])
            self.approval.setPlainText(self.tr('FILE EDIT\nProject: {project}\nPath: {path}\nReview the full diff below.\nSafety recommendation: Not checked; no System One request was made.').format(project=proposal['cwd'],path=proposal['path']))
            self.approval_panel.show();self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting approval for file edit: '+proposal['path'])
        elif kind=='operation_proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval';proposal=event['proposal'];operation=proposal['operation']
            self.advice_fingerprint=self.pending_fingerprint if operation=='run_shell' else None
            if operation=='run_shell':self.show_advice()
            else:self.advice_label.hide()
            self.diff.setPlainText(proposal.get('diff',''));self.diff.setVisible(operation in ('delete_file','git_commit','git_commit_staged','git_stage','git_unstage','subagent_file_transfer','independent_review'))
            if operation=='mcp_start':
                text=self.tr('START LOCAL MCP SERVER\nServer: {server}\nExecutable: {command}\nArguments: {arguments}\n\nThis program runs with your user permissions. Tool descriptions and results may be sent to the selected model.').format(server=proposal['server'],command=proposal['command'],arguments=json.dumps(proposal['arguments'],ensure_ascii=True))
            elif operation=='mcp_connect':
                text=self.tr('CONNECT TO REMOTE MCP SERVER\nServer: {server}\nDestination: {url}\n\nThe server receives a discovery request and any configured credential. Tool descriptions and results may be sent to the selected model.').format(**proposal)
            elif operation=='mcp_call_remote':
                text=self.tr('REMOTE MCP TOOL CALL\nServer: {server}\nDestination: {url}\nTool: {tool}\n\nDescription:\n{description}\n\nInput schema:\n{schema}\n\nArguments:\n{arguments}\n\nThe server receives these arguments and may perform external actions.').format(server=proposal['server'],url=proposal['url'],tool=proposal['tool'],description=proposal['description'],schema=json.dumps(proposal['schema'],ensure_ascii=True,indent=2),arguments=json.dumps(proposal['arguments'],ensure_ascii=True,indent=2))
            elif operation in ('mcp_list_resources','mcp_read_resource'):
                destination=('Destination: '+proposal['url']) if 'url' in proposal else ('Executable: '+proposal['command']+'\nServer arguments: '+json.dumps(proposal['server_arguments'],ensure_ascii=True))
                text=self.tr('MCP RESOURCE REQUEST\nServer: {server}\n{destination}\n\n{action}\n\nThe server may access your data. Resource metadata or text will be sent to the selected model.').format(server=proposal['server'],destination=destination,action=('List up to five pages or 100 resources.' if operation=='mcp_list_resources' else 'Read resource:\n'+json.dumps(proposal['resource'],ensure_ascii=True,indent=2)))
            elif operation in ('mcp_list_resource_templates','mcp_read_resource_template'):
                destination=('Destination: '+proposal['url']) if 'url' in proposal else ('Executable: '+proposal['command']+'\nServer arguments: '+json.dumps(proposal['server_arguments'],ensure_ascii=True))
                action='List up to five pages or 100 resource templates.' if operation=='mcp_list_resource_templates' else 'Template:\n'+json.dumps(proposal['template'],ensure_ascii=True,indent=2)+'\n\nVariables:\n'+json.dumps(proposal['variables'],ensure_ascii=True,indent=2)+'\n\nExpanded URI:\n'+proposal['uri']
                text=self.tr('MCP RESOURCE TEMPLATE REQUEST\nServer: {server}\n{destination}\n\n{action}\n\nThe server may access your data. Resource content will be sent to the selected model.').format(server=proposal['server'],destination=destination,action=action)
            elif operation in ('mcp_list_prompts','mcp_get_prompt'):
                destination=('Destination: '+proposal['url']) if 'url' in proposal else ('Executable: '+proposal['command']+'\nServer arguments: '+json.dumps(proposal['server_arguments'],ensure_ascii=True))
                action='List up to five pages or 100 prompts.' if operation=='mcp_list_prompts' else 'Retrieve prompt:\n'+json.dumps(proposal['prompt'],ensure_ascii=True,indent=2)+'\n\nArguments:\n'+json.dumps(proposal['arguments'],ensure_ascii=True,indent=2)
                text=self.tr('MCP PROMPT REQUEST\nServer: {server}\n{destination}\n\n{action}\n\nThe server receives these arguments. Prompt metadata or text will be sent to the selected model as untrusted data.').format(server=proposal['server'],destination=destination,action=action)
            elif operation=='mcp_call':
                text=self.tr('MCP TOOL CALL\nServer: {server}\nExecutable: {command}\nServer arguments: {server_arguments}\nTool: {tool}\n\nDescription:\n{description}\n\nInput schema:\n{schema}\n\nArguments:\n{arguments}\n\nThe server may access your data or perform external actions.').format(server=proposal['server'],command=proposal['command'],server_arguments=json.dumps(proposal['server_arguments'],ensure_ascii=True),tool=proposal['tool'],description=proposal['description'],schema=json.dumps(proposal['schema'],ensure_ascii=True,indent=2),arguments=json.dumps(proposal['arguments'],ensure_ascii=True,indent=2))
            elif operation=='independent_review':
                text=self.tr('INDEPENDENT DOCUMENT REVIEW\nReview role: {role}\nProject: {cwd}\nDocument: {path}\nModel: {model}\nDestination: {destination}\nDocument SHA-256: {source_sha256}\nInput SHA-256: {payload_sha256}\nInput: {payload_bytes} UTF-8 bytes\n\nReview the complete reviewer instructions, document and any evidence below. Approving sends this exact input to the selected endpoint. The reviewer has no tools and does not receive the drafting conversation, Skills, or project guidance. Its findings are untrusted.').format(**{'role':proposal.get('role','comprehension'),**proposal})
                evidence=proposal.get('evidence',[])
                if evidence:
                    text+='\n\n'+self.tr('Additional evidence (path · source SHA-256 · transmitted text SHA-256):')+'\n'+'\n'.join(item['path']+' · '+item['sha256']+' · '+item['payload_sha256'] for item in evidence)
            elif operation=='subagent_file_transfer':
                text=self.tr('SEND PROJECT FILE TO SUBAGENT\nProject: {cwd}\nFile: {path}\nModel: {model}\nDestination: {destination}\nSubagent: {child}\nTask: {task}\nPayload: {payload_bytes} UTF-8 bytes\nSHA-256: {payload_sha256}\n\nReview the exact file text to be sent below.').format(**proposal)
            elif operation in ('git_commit','git_commit_staged'):
                text=self.tr('GIT COMMIT\nProject: {cwd}\nFiles: {path}\nIdentity: {identity}\nParent: {head}\nMessage: {message}\nHooks and signing are disabled. Review the complete diff below.').format(**proposal)
            elif operation in ('git_stage','git_unstage'):
                label=self.tr('STAGE FILES') if operation=='git_stage' else self.tr('UNSTAGE FILES')
                text=self.tr('{operation}\nProject: {cwd}\nFiles: {path}\nWorking files will remain unchanged. Review the index diff below.').format(operation=label,cwd=proposal['cwd'],path=proposal['path'])
            elif operation=='git_create_branch':
                text=self.tr('CREATE BRANCH\nProject: {cwd}\nBranch: {name}\nStarting commit: {head}\nThe current branch will remain selected.').format(**proposal)
            elif operation=='run_shell':
                text=self.tr('SHELL COMMAND\nWorking directory: {cwd}\nShell: {shell}\nTime limit: up to {seconds} seconds; output limit: {size} bytes.\nThe command runs with your account permissions, including network and access outside the project. It is not sandboxed.\nInherited environment variables: {environment}\n\nCommand:\n{command}').format(cwd=proposal['cwd'],shell=proposal['shell'],seconds=proposal['max_seconds'],size=proposal['max_output_bytes'],environment=', '.join(proposal['environment_keys']),command=proposal['command'])
            else:
                label=self.tr('DELETE FILE') if operation=='delete_file' else self.tr('CREATE DIRECTORY')
                text=self.tr('{operation}\nProject: {project}\nPath: {path}\nSafety recommendation: Not checked.').format(operation=label,project=proposal['cwd'],path=proposal['path'])
            if proposal.get('purpose')=='tests':text=self.tr('TEST RUN · Report format: {format}').format(format=proposal['test_format'])+'\n'+text
            self.approval.setPlainText(text);self.approval_panel.show();self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting approval: '+operation+' '+proposal.get('path',''))
            if operation=='run_shell' and self.advice_connection:self.check_advice(proposal,self.pending_fingerprint)
        elif kind=='proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval'
            self.advice_fingerprint=None;self.advice_label.hide()
            proposal=event['proposal'];self.diff.setVisible(True)
            self.approval.setPlainText(self.tr('SIMULATION ONLY\nDirectory: {directory}\nArguments: {arguments}\nRecommendation: {recommendation}').format(directory=proposal['cwd'],arguments=json.dumps(proposal['argv']),recommendation=event['recommendation']))
            self.approval_panel.show();self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting explicit approval for simulated step.')
        elif kind=='diff':self.diff.setPlainText(plain(event['text']));self.record(kind,event['text'])
        elif kind=='output':self.record(kind,event['text'])
        elif kind=='finished':
            if event['status']=='completed' and isinstance(self.job,CodingRun):
                secrets=[self.job.connection.get('api_key',''),(self.job.light or {}).get('api_key',''),(self.job.alternate or {}).get('api_key',''),(self.job.alternate2 or {}).get('api_key','')]
                context={'task':plain(scrub(self.job.prompt,secrets)),'answer':plain(event['text'])}
                self.session['coding_context']=context
                self.context_view.setPlainText(self.context_text(context))
                self.use_context.setChecked(False)
            self.stop_subagents('stopped');self.session['code_state']=event['status'];self.finish();self.record(kind,event['text'])
            if event.get('usage'):self.record('usage',event['usage'])

    def decide(self,allowed):
        if self.advice_job:return
        if self.job and self.pending_fingerprint and self.job.decide(self.pending_fingerprint,allowed):
            decision=self.pending_fingerprint;self.approve.setEnabled(False);self.reject.setEnabled(False);self.pending_fingerprint=None
            self.advice_fingerprint=None
            self.approval_panel.hide();self.approval.clear();self.diff.clear()
            self.session['code_state']='running';self.record('decision',('Approved' if allowed else 'Rejected')+' proposal '+decision)

    def finish(self):
        if self.advice_job:self.advice_job.cancel.set();self.advice_job=None
        self.advice_connection=None;self.advice_destination=''
        self.run_id=None;self.job=None;self.pending_fingerprint=None;self.advice_fingerprint=None
        self.approval_panel.hide()
        for button in (self.approve,self.reject,self.cancel_button):button.setEnabled(False)
        self.simulate.setEnabled(True);self.send.setEnabled(True)
        self.light_enabled.setEnabled(True);self.web_enabled.setEnabled(True);self.limits_button.setEnabled(True);self.search_settings.setEnabled(True);self.advice_enabled.setEnabled(True);self.mcp_choice.setEnabled(True);self.mcp_refresh.setEnabled(True);self.mcp_extra_button.setEnabled(True)
        self.use_context.setEnabled(bool(self.session.get('coding_context')))
        for connection,model in self.roles.values():connection.setEnabled(True);model.setEnabled(True)

    def cancel(self):
        if not self.job:return
        self.job.stop()
        for bridge in getattr(self.job,'mcp_bridges',[]):bridge.close()
        self.stop_subagents('cancelled');self.session['code_state']='cancelled';self.finish()
        self.record('cancelled','Run cancelled. No further tool work will be scheduled; project changes already applied are retained.')
