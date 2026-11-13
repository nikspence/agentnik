"""Repository picker and Agentnik-owned coding pane."""
from pathlib import Path
import json
import copy
import re
import sqlite3
import threading
import uuid
from urllib.parse import urlsplit
from PySide6.QtCore import Qt,Signal,QObject,QUrl,QPoint,QTimer
from PySide6.QtGui import QDesktopServices,QTextCursor
from PySide6.QtWidgets import QScrollArea,QApplication,QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QListWidget,QListWidgetItem,QPushButton,QDialogButtonBox,QFileDialog,QInputDialog,QMessageBox,QPlainTextEdit,QComboBox,QCheckBox,QSpinBox,QTabWidget
from .repositories import RepositoryRegistry
from .coding import plain
from .code_agent import CodingRun
from .research import scrub
from . import decision_advice
from .decision_advice import parse_advice
from .task_plan import validate_plan
from .subagent_status import validate_record
from .sessions import append_code_activity
from .code_limits import FIELDS,coding_limits
from .selection_scroll import SelectionScroll
from .web import public_url
from . import core,routing
from .research_ui import SearchBackends
from .search_providers import SEARCH_KINDS


class CodingComposer(QPlainTextEdit):
    history_requested = Signal(int)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.NoModifier and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            cursor = self.textCursor()
            if not cursor.hasSelection():
                probe = QTextCursor(cursor)
                direction = -1 if event.key() == Qt.Key.Key_Up else 1
                move = QTextCursor.MoveOperation.Up if direction < 0 else QTextCursor.MoveOperation.Down
                if not probe.movePosition(move):
                    self.history_requested.emit(direction)
                    return
        super().keyPressEvent(event)


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


class DirectReviewDialog(QDialog):
    def __init__(self,parent,models,default_path=''):
        super().__init__(parent);self.setWindowTitle(self.tr('Independent document review'));self.resize(700,650)
        layout=QVBoxLayout(self);note=QLabel(self.tr('Choose one to three independent passes. Each exact input and destination requires approval before requests start. Comprehension receives only the document; repository fit and drift require project evidence. Reviewers receive no coding conversation, Skills, guidance, or tools.'));note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();layout.addLayout(form);self.target=QLineEdit(default_path);self.target.setObjectName('directReviewTarget');form.addRow(self.tr('Project-relative document path'),self.target)
        self.passes=[];self.evidence_fields=[]
        for index in range(3):
            row=QHBoxLayout();role=QComboBox();role.setObjectName('directReviewRole'+str(index));role.addItem(self.tr('Not selected'),'')
            for label,value in [(self.tr('Comprehension'),'comprehension'),(self.tr('Requirements'),'requirements'),(self.tr('Design'),'design'),(self.tr('Repository fit'),'repository_fit'),(self.tr('Readiness'),'readiness'),(self.tr('Specification / evidence drift'),'drift')]:role.addItem(label,value)
            model=QComboBox();model.setObjectName('directReviewModel'+str(index))
            for key,connection in models.items():model.addItem(key+' · '+connection['model'],key)
            if index==0:role.setCurrentIndex(1)
            row.addWidget(role);row.addWidget(model);form.addRow(self.tr('Pass {number}').format(number=index+1),row);self.passes.append((role,model))
            evidence=QPlainTextEdit();evidence.setObjectName('directReviewEvidence'+str(index));evidence.setMaximumHeight(58);evidence.setPlaceholderText(self.tr('Optional project-relative paths, one per line (up to three).'));form.addRow(self.tr('Pass {number} evidence').format(number=index+1),evidence);self.evidence_fields.append(evidence)
            def update_enabled(_=None,r=role,m=model,e=evidence):
                m.setEnabled(bool(r.currentData()));e.setEnabled(r.currentData() not in ('','comprehension'))
            role.currentIndexChanged.connect(update_enabled);update_enabled()
        self.save_progress=QCheckBox(self.tr('Save pass progress to this session during the review'));self.save_progress.setObjectName('directReviewSaveProgress');self.save_progress.setToolTip(self.tr('Approved passes are saved before requests start. Unfinished passes reopen as interrupted. Finding dispositions are saved separately.'));layout.addWidget(self.save_progress)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr('Prepare approvals'));buttons.accepted.connect(self.validate_and_accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def validate_and_accept(self):
        try:self.values()
        except ValueError as exc:QMessageBox.warning(self,self.tr('Independent review'),str(exc));return
        self.accept()

    def values(self):
        target=self.target.text().strip();passes=[]
        if not target:raise ValueError(self.tr('Enter a document path.'))
        for (role,model),evidence in zip(self.passes,self.evidence_fields):
            if not role.currentData():continue
            paths=[] if role.currentData()=='comprehension' else [line.strip() for line in evidence.toPlainText().splitlines() if line.strip()]
            if len(paths)>3 or len(set(paths))!=len(paths):raise ValueError(self.tr('Each pass accepts up to three distinct evidence paths.'))
            if role.currentData() in ('drift','repository_fit') and not paths:raise ValueError(self.tr('Repository fit and drift checks require at least one project evidence file.'))
            passes.append({'role':role.currentData(),'model':model.currentData(),'paths':paths})
        if not passes:raise ValueError(self.tr('Choose at least one review pass.'))
        return target,passes


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
        super().__init__();self.window=window;self.store=window.store;self.session=session;self.job=None;self.model_jobs={};self._closed=False;self.run_id=None;self.pending_fingerprint=None;self.advice_fingerprint=None;self.advice_job=None;self.advice_connection=None;self.advice_destination='';self.review_results={};self.review_dispositions={};self.review_progress_ids={}
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
        self.track_selection_label=QLabel();self.track_selection_label.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.track_selection_label);self.refresh_selected_track()
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
        self.review_results_button=QPushButton(self.tr('Review findings…'));self.review_results_button.setEnabled(False);self.review_results_button.clicked.connect(self.show_review_results);subagent_actions.insertWidget(2,self.review_results_button)
        self.subagents_toggle.toggled.connect(self.subagents_view.setVisible);self.subagents_toggle.toggled.connect(self.subagents_controls.setVisible);self.subagents_view.hide();self.subagents_controls.hide();self.refresh_subagents()
        self.saved_reviews_button=QPushButton(self.tr('Saved review snapshots…'));self.saved_reviews_button.setEnabled(bool(session.get('coding_review_history')));self.saved_reviews_button.clicked.connect(self.show_saved_reviews);layout.addWidget(self.saved_reviews_button)
        self.activity=QPlainTextEdit('\n'.join(self.activity_text(e) for e in session.get('code_activity',[])));self.activity.setPlaceholderText(self.tr('No commands have been run.'));self.activity.setReadOnly(True);layout.addWidget(self.activity,1);self._activity_selection_scroll=SelectionScroll(self.activity)
        self.activity.moveCursor(QTextCursor.MoveOperation.End)
        self._activity_revision=0;self._activity_initial_follow=True;self.activity.verticalScrollBar().actionTriggered.connect(self.activity_scrolled)
        QTimer.singleShot(0,self.finish_activity_open)
        composer_row=QHBoxLayout();layout.addLayout(composer_row)
        history_buttons=QVBoxLayout();composer_row.addLayout(history_buttons)
        self.history_up=QPushButton('↑');self.history_up.setAccessibleName(self.tr('Previous coding prompt'));self.history_up.setToolTip(self.tr('Previous coding prompt'));history_buttons.addWidget(self.history_up)
        self.history_down=QPushButton('↓');self.history_down.setAccessibleName(self.tr('Next coding prompt'));self.history_down.setToolTip(self.tr('Next coding prompt'));history_buttons.addWidget(self.history_down)
        self.composer=CodingComposer(session.get('draft',''));self.composer.setPlaceholderText(self.tr('Describe the coding task; repository files may be sent to the selected models'));self.composer.setMaximumHeight(90);composer_row.addWidget(self.composer,1)
        from .ui import AttachmentBox
        self.attachments=AttachmentBox(self.store);self.attachments.set_paths(session.get('draft_images',[]));layout.addWidget(self.attachments)
        self.documents=copy.deepcopy(session.get('draft_documents',[]))
        self.documents_button=QPushButton(self.tr('Documents…'));self.documents_button.clicked.connect(self.read_documents);self.attachments.controls.insertWidget(1,self.documents_button)
        self.document_row=QHBoxLayout();layout.addLayout(self.document_row);self.refresh_documents()
        self.attachments.changed.connect(self.save_draft)
        self._history_index=len(session.get('coding_prompt_history',[]));self._history_edits={}
        self.history_up.clicked.connect(lambda:self.navigate_prompt_history(-1));self.history_down.clicked.connect(lambda:self.navigate_prompt_history(1));self.composer.history_requested.connect(self.navigate_prompt_history)
        self.update_prompt_history_buttons()
        context=session.get('coding_context')
        self.context_toggle=QPushButton(self.tr('Previous task and answer'));self.context_toggle.setCheckable(True);layout.addWidget(self.context_toggle)
        self.context_view=QPlainTextEdit(self.context_text(context))
        self.context_view.setReadOnly(True);self.context_view.setMaximumHeight(110);layout.addWidget(self.context_view);self.context_view.hide()
        self.context_toggle.toggled.connect(self.context_view.setVisible)
        self.use_context=QCheckBox(self.tr('Send previous task and answer with next run (up to 2,048 characters each)'));self.use_context.setEnabled(bool(context))
        options=QHBoxLayout();layout.addLayout(options)
        self.coding_context_button=QPushButton(self.tr('Coding context…'));self.coding_context_button.clicked.connect(self.edit_coding_context);options.addWidget(self.coding_context_button)
        self.coding_auto_compact=QCheckBox(self.tr('Auto compact context'));self.coding_auto_compact.setToolTip(self.tr('Before a follow-up run, summarize a long previous task and answer using the selected Heavy model. This uses an additional model request.'));self.coding_auto_compact.setChecked(session.get('coding_auto_compact',True));self.coding_auto_compact.toggled.connect(self.save_coding_auto_compact);options.addWidget(self.coding_auto_compact)
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
        role_help=QLabel(self.tr('Heavy leads the work. Light handles delegated analysis. The two optional alternate models are additional choices Heavy may select for parallel subagents or independent document reviews; they are not automatic fallbacks and may use different connections. Delegation must be enabled and a Light model configured. For parallel reviews, project files are approved individually and supplied as snapshots; optional inspection tools only access those snapshots. If a model explicitly rejects tool calling, Agentnik retries without tools.'))
        role_help.setWordWrap(True);model_layout.addWidget(role_help)
        self.reset_subagent_capabilities=QPushButton(self.tr('Forget remembered subagent tool support'));self.reset_subagent_capabilities.setToolTip(self.tr('Clear remembered tool-calling rejections so selected subagent models can be tried again.'));self.reset_subagent_capabilities.clicked.connect(self.forget_subagent_capabilities);model_layout.addWidget(self.reset_subagent_capabilities)
        self.advice_enabled=QCheckBox(self.tr('Check shell approvals with Decision model'))
        self.advice_enabled.setChecked(session.get('coding_advice_enabled',False));self.advice_enabled.toggled.connect(self.save_advice_enabled);model_layout.addWidget(self.advice_enabled)
        disclosure=QLabel(self.tr('When enabled, each shell proposal sends its command, working directory, shell, and environment variable names to the selected Decision endpoint. Environment values are not sent. Advice never approves a command.'))
        disclosure.setWordWrap(True);model_layout.addWidget(disclosure)
        self.skills_button=QPushButton();self.skills_button.clicked.connect(self.choose_skills);options.addWidget(self.skills_button);self.refresh_skills_button()
        self.tracks_button=QPushButton(self.tr('Spec & Plan…'));self.tracks_button.clicked.connect(self.show_tracks);options.addWidget(self.tracks_button)
        self.memory_button=QPushButton(self.tr('Project memory…'));self.memory_button.clicked.connect(self.edit_project_memory);options.addWidget(self.memory_button)
        self.notes_button=QPushButton(self.tr('Working notes…'));self.notes_button.clicked.connect(self.edit_working_notes);options.addWidget(self.notes_button)
        self.skills_history_button=QPushButton(self.tr('Skill history…'));self.skills_history_button.clicked.connect(self.show_skills_history);options.addWidget(self.skills_history_button)
        self.light_enabled=QCheckBox(self.tr('Allow Light model delegation'));self.light_enabled.setToolTip(self.tr('Allow Light delegation, parallel analysis, and independent reviews. Heavy may choose either configured alternate for parallel tasks or reviews; alternates are not fallbacks. Each project file sent to a subagent requires approval; optional read, glob, and grep tools only inspect approved snapshots. Run limits are shared.'));self.light_enabled.setChecked(session.get('coding_light_enabled',True) is not False);options.addWidget(self.light_enabled);options.addWidget(self.use_context)
        self.light_enabled.toggled.connect(self.save_light_enabled)
        self.save_review_progress=QCheckBox(self.tr('Save Heavy review progress'));self.save_review_progress.setToolTip(self.tr('Save approved Heavy-requested review batches to this session before reviewer requests start. Unfinished passes reopen as interrupted.'));self.save_review_progress.setChecked(session.get('coding_save_review_progress',False));self.save_review_progress.toggled.connect(self.save_heavy_review_progress);options.addWidget(self.save_review_progress)
        self.web_enabled=QCheckBox(self.tr('Allow web research'));self.web_enabled.setToolTip(self.tr('Search uses configured providers, then Firecrawl Keyless and Google fallback when eligible. Without configured providers, Firecrawl Keyless is first. Ollama search is used only for direct Ollama Cloud. Filtered public page reads may send the page URL to a retrieval provider.'))
        self.web_enabled.setChecked(session.get('coding_web_enabled',False));options.addWidget(self.web_enabled)
        self.web_enabled.toggled.connect(self.save_web_enabled)
        mcp_row=QHBoxLayout();layout.addLayout(mcp_row);mcp_row.addWidget(QLabel(self.tr('MCP server for this run:')))
        self.mcp_choice=QComboBox();self.mcp_choice.setToolTip(self.tr('Optional MCP server for this run. MCP operations run without approval and may write data or perform other actions; tool results go to the selected model.'));mcp_row.addWidget(self.mcp_choice,1)
        saved_mcp=session.get('coding_mcp_selection',{});self.mcp_primary_ref=saved_mcp.get('primary');self.mcp_extra_refs=list(saved_mcp.get('extra',[]));self.mcp_extra=[ref['name'] for ref in self.mcp_extra_refs]
        self.mcp_extra_button=QPushButton(self.tr('Additional servers…'));self.mcp_extra_button.clicked.connect(self.choose_additional_mcp);mcp_row.addWidget(self.mcp_extra_button)
        self.mcp_refresh=QPushButton(self.tr('Refresh MCP'));self.mcp_refresh.clicked.connect(self.refresh_mcp_servers);mcp_row.addWidget(self.mcp_refresh);self.refresh_mcp_servers();self.mcp_choice.currentIndexChanged.connect(self.mcp_primary_changed)
        self.limits_button=QPushButton(self.tr('Limits…'));self.limits_button.clicked.connect(self.configure_limits);options.addWidget(self.limits_button)
        self.sources_button=QPushButton();self.sources_button.clicked.connect(self.show_sources)
        run_row=QHBoxLayout();layout.addLayout(run_row)
        self.send=QPushButton(self.tr('Run'));self.send.clicked.connect(self.start_coding);run_row.addWidget(self.send)
        self.direct_review_button=QPushButton(self.tr('Independent review…'));self.direct_review_button.clicked.connect(self.start_direct_review);run_row.addWidget(self.direct_review_button)
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
        self.approve_mcp_run=QPushButton(self.tr('Allow this MCP server for this run'));self.approve_mcp_run.setToolTip(self.tr('Allow this server to perform future MCP operations, including writes and data access, without further prompts until this run ends.'));self.approve_mcp_run.hide();actions.addWidget(self.approve_mcp_run)
        self.approve.clicked.connect(lambda:self.decide(True));self.reject.clicked.connect(lambda:self.decide(False));self.approve_mcp_run.clicked.connect(lambda:self.decide(True,'mcp_server_run'))
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
        for review in self.review_results.values():
            if review['pass_status']=='pending':review['pass_status']='interrupted'
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

    def save_coding_auto_compact(self,enabled):
        self.session['coding_auto_compact']=bool(enabled);self.store.save(self.session);self.updated.emit()

    def edit_coding_context(self):
        if self.job:return
        from .context_compaction import coding_snapshot,coding_effective_context
        context=self.session.get('coding_context');snapshot=self.session.get('coding_compaction')
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Coding context'));dialog.resize(700,520)
        layout=QVBoxLayout(dialog);hint=QLabel(self.tr('The previous task and answer are retained separately. A summary replaces them only when you enable previous context for a future run. Compaction uses the selected Heavy model and may omit details.'));hint.setWordWrap(True);layout.addWidget(hint)
        layout.addWidget(QLabel(self.tr('Previous task and answer (JSON):')))
        original=QPlainTextEdit(json.dumps(context or {'task':'','answer':''},ensure_ascii=False,indent=2));layout.addWidget(original)
        layout.addWidget(QLabel(self.tr('Compacted summary:')))
        summary=QPlainTextEdit(snapshot['summary'] if snapshot else '');layout.addWidget(summary)
        row=QHBoxLayout();layout.addLayout(row)
        save=QPushButton(self.tr('Save context'));reset=QPushButton(self.tr('Use original context'));compact=QPushButton(self.tr('Compact now'))
        for control in (save,reset,compact):row.addWidget(control)
        save.setEnabled(bool(context));compact.setEnabled(bool(context))
        def save_context():
            try:
                value=json.loads(original.toPlainText())
                from .context_compaction import coding_digest
                coding_digest(value);text=summary.toPlainText().strip();new_snapshot=coding_snapshot(value,text) if text else None
            except (ValueError,TypeError) as exc:QMessageBox.warning(dialog,self.tr('Coding context'),str(exc));return
            self.session['coding_context']=value
            if new_snapshot:self.session['coding_compaction']=new_snapshot
            else:self.session.pop('coding_compaction',None)
            self.context_view.setPlainText(self.context_text(value));self.use_context.setEnabled(True);self.store.save(self.session);self.updated.emit();dialog.accept()
        def restore():summary.clear()
        def compact_now():
            if original.toPlainText()!=json.dumps(context or {'task':'','answer':''},ensure_ascii=False,indent=2):
                QMessageBox.information(dialog,self.tr('Coding context'),self.tr('Save your edits before compacting.'));return
            dialog.accept();self.compact_coding_context()
        save.clicked.connect(save_context);reset.clicked.connect(restore);compact.clicked.connect(compact_now);dialog.exec()

    def compact_coding_context(self,auto_start=False,connection=None):
        from .context_compaction import coding_summary_input,coding_snapshot,coding_digest
        from .ui import Job
        if self.job or self._closed:return
        try:
            context=dict(self.session.get('coding_context') or {})
            connection=connection or self.role_connection('heavy')
            if not connection or not connection.get('model'):raise ValueError(self.tr('Choose a Heavy model first.'))
            inputs=coding_summary_input(context);body=core.chat_body(connection,inputs)
        except (ValueError,OSError) as exc:QMessageBox.warning(self,self.tr('Coding context'),str(exc));return
        token=uuid.uuid4().hex;self._compaction_token=token;self._compaction_active=True
        self.send.setEnabled(False);self.cancel_button.setEnabled(True);self.coding_context_button.setEnabled(False);self.coding_auto_compact.setEnabled(False);self.memory_button.setEnabled(False);self.notes_button.setEnabled(False);self.composer.setReadOnly(True)
        self.light_enabled.setEnabled(False);self.web_enabled.setEnabled(False);self.limits_button.setEnabled(False);self.search_settings.setEnabled(False);self.advice_enabled.setEnabled(False);self.mcp_choice.setEnabled(False);self.mcp_refresh.setEnabled(False);self.mcp_extra_button.setEnabled(False);self.use_context.setEnabled(False)
        for choice,model in self.roles.values():choice.setEnabled(False);model.setEnabled(False)
        self.record('output','Compacting previous coding context before a run; the selected Heavy model receives the previous task and answer.')
        def done(result):
            if self._closed or self._compaction_token!=token:return
            self._compaction_active=False;self._compaction_token=None;self.composer.setReadOnly(False);self.finish()
            try:
                text=scrub(result.get('text',''),[connection.get('api_key','')]).strip();snapshot=coding_snapshot(context,text)
                if coding_digest(self.session.get('coding_context'))!=snapshot['digest']:raise ValueError('Coding context changed during compaction')
                self.session['coding_compaction']=snapshot;self.store.save(self.session);self.record('output','Previous coding context compacted; review it in Coding context.');self.updated.emit()
                if auto_start:self.start_coding()
            except (ValueError,OSError) as exc:self.record('output','Coding context compaction failed: '+str(exc))
        def failed(message):
            if self._closed or self._compaction_token!=token:return
            self._compaction_active=False;self._compaction_token=None;self.composer.setReadOnly(False);self.finish();self.record('output','Coding context compaction failed: '+message)
        self.job=Job(lambda emit,cancel:core.run_request(connection,'chat',body,lambda _:None,cancel),done,failed);self.updated.emit()

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

    def save_heavy_review_progress(self,enabled):
        self.session['coding_save_review_progress']=enabled;self.store.save(self.session)

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

    def subagent_capability_connection(self,role,connection):
        scoped=dict(connection);name=self.roles[role][0].currentData()
        if name not in self.store.config.get('connections',{}):scoped.pop('_capability_scope',None)
        return scoped

    def forget_subagent_capabilities(self):
        self.store.config.pop('subagent_tool_capabilities',None);self.store.flush()
        if self.job:self.record('output',self.tr('Remembered subagent tool support cleared for future runs.'))

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

    def show_tracks(self):
        from .code_agent import ProjectFiles
        from .tracks import list_tracks,read_track,read_project_context
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Spec & Plan'));dialog.resize(760,560)
        layout=QVBoxLayout(dialog);label=QLabel(self.tr('Open a track to inspect it or edit it through individually reviewed changes. Opening a track does not start a run or grant permission to execute anything.'));label.setWordWrap(True);layout.addWidget(label)
        listing=QListWidget();layout.addWidget(listing);view=QPlainTextEdit();view.setReadOnly(True);layout.addWidget(view,1)
        draft_button=QPushButton(self.tr('New or edit draft…'));draft_button.setEnabled(not bool(self.job));draft_button.clicked.connect(self.edit_track_draft);layout.addWidget(draft_button)
        edit_button=QPushButton(self.tr('Edit selected track…'));edit_button.setEnabled(False);layout.addWidget(edit_button)
        project_reviews_button=QPushButton(self.tr('View selected track reviews…'));project_reviews_button.setEnabled(False);layout.addWidget(project_reviews_button)
        select_button=QPushButton(self.tr('Select for coding runs'));select_button.setEnabled(False);layout.addWidget(select_button)
        clear_button=QPushButton(self.tr('Clear selected track'));clear_button.setEnabled(not self.job and bool(self.session.get('selected_track')));layout.addWidget(clear_button)
        progress_button=QPushButton(self.tr('Review last track progress…'));progress_button.setEnabled(bool(self.session.get('track_progress')));layout.addWidget(progress_button)
        progress_button.clicked.connect(self.show_track_progress)
        def clear_selection():
            self.session.pop('selected_track',None);self.store.save(self.session);self.refresh_selected_track();self.updated.emit();dialog.accept()
        clear_button.clicked.connect(clear_selection)
        resume_button=QPushButton(self.tr('Resume track edit draft…'));resume_button.setEnabled(not bool(self.job) and bool(self.session.get('track_edit_draft')));layout.addWidget(resume_button)
        def edit_selected():
            item=listing.currentItem();track=item.data(Qt.ItemDataRole.UserRole) if item else None
            if track and track['available'] and not self.job:self.edit_existing_track(track['id'])
        def resume_edit():
            saved=self.session.get('track_edit_draft')
            if saved and not self.job:self.edit_existing_track(saved['id'])
        edit_button.clicked.connect(edit_selected);resume_button.clicked.connect(resume_edit)
        try:
            files=ProjectFiles(self.session['path_snapshot']);data=list_tracks(files)
            for track in data['tracks']:
                title=track.get('title',track['id']);item=QListWidgetItem(title+(' · '+self.tr('unavailable') if not track['available'] else ''));item.setData(Qt.ItemDataRole.UserRole,track);listing.addItem(item)
            if data['incomplete']:label.setText(label.text()+' '+self.tr('Track list is incomplete because the scan limit was reached.'))
            if not data['tracks']:view.setPlainText(self.tr('No Agentnik tracks found. Existing projects and sessions do not need migration.'))
            def select(item,_):
                select_button.setEnabled(False)
                if not item:edit_button.setEnabled(False);project_reviews_button.setEnabled(False);return
                track=item.data(Qt.ItemDataRole.UserRole);edit_button.setEnabled(track['available'] and not bool(self.job))
                project_reviews_button.setEnabled(track['available'])
                if not track['available']:view.setPlainText(track['reason']);return
                try:
                    value=read_track(files,track['id']);lines=[self.tr('Track: {title}').format(title=value['track']['title']),'',self.tr('Tasks (reported status; evidence is not independently verified):')]
                    select_button.setEnabled(not bool(self.job))
                    for task in value['track']['tasks']:
                        lines.append(task['id']+' · '+task['phase']+' · '+task['status']+' · '+task['step'])
                        lines.extend('  '+e['status']+' · '+e['detail'] for e in task['evidence'])
                    lines.extend(['',self.tr('Specification:'),value['spec'],'',self.tr('Plan:'),value['plan']]);view.setPlainText('\n'.join(lines))
                except (ValueError,OSError) as exc:view.setPlainText(self.tr('Track unavailable: {reason}').format(reason=str(exc)))
            listing.currentItemChanged.connect(select)
            def open_project_reviews():
                item=listing.currentItem();track=item.data(Qt.ItemDataRole.UserRole) if item else None
                if track and track['available']:self.show_project_track_reviews(track['id'],dialog)
            project_reviews_button.clicked.connect(open_project_reviews)
            def choose_track():
                item=listing.currentItem()
                if not item or self.job:return
                ident=item.data(Qt.ItemDataRole.UserRole)['id']
                try:read_track(files,ident)
                except (ValueError,OSError,UnicodeError) as exc:QMessageBox.warning(dialog,self.tr('Select track'),str(exc));return
                self.session['selected_track']=ident;self.store.save(self.session);self.refresh_selected_track();self.updated.emit();dialog.accept()
            select_button.clicked.connect(choose_track)
            context_button=QPushButton(self.tr('Project context'));layout.addWidget(context_button)
            def show_context():
                try:
                    content=read_project_context(files);view.setPlainText(content if content is not None else self.tr('No project context document found.'))
                except (ValueError,OSError,UnicodeError):view.setPlainText(self.tr('Project context is unavailable or exceeds the read limit.'))
            context_button.clicked.connect(show_context)
        except (ValueError,OSError) as exc:view.setPlainText(self.tr('Tracks unavailable: {reason}').format(reason=str(exc)))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

    def refresh_selected_track(self):
        ident=self.session.get('selected_track')
        self.track_selection_label.setText(self.tr('Selected track: {id} (used for coding runs until cleared)').format(id=ident) if ident else self.tr('No track selected for coding runs.'))

    def show_project_track_reviews(self,track_id,parent=None):
        from .code_agent import ProjectFiles
        from .track_review_storage import read_sidecar
        from .independent_review import sources_unchanged,track_context_matches
        try:files=ProjectFiles(self.session['path_snapshot']);sidecar=read_sidecar(files,track_id)
        except (ValueError,TypeError,UnicodeError,OSError,RecursionError) as exc:QMessageBox.warning(parent or self,self.tr('Project review history'),str(exc));return
        for snapshot in sidecar['snapshots']:
            for review in snapshot['reviews']:
                sources=[(review['path'],review['source_sha256'])]+[(entry['path'],entry['sha256']) for entry in review['evidence']]
                review['source_status']=self.tr('Current source hashes match the reviewed snapshots.') if sources_unchanged(files,sources) else self.tr('Stale or unavailable: a reviewed source changed or cannot be read.')
                review['track_status']=self.tr('Track run context matches its starting revision; this does not mean the full track was reviewed.') if track_context_matches(files,review['track_context']) else self.tr('Track run context changed or is unavailable; this does not mean the full track was reviewed.')
        preview=QDialog(parent or self);preview.setWindowTitle(self.tr('Project review history'));preview.resize(760,540);box=QVBoxLayout(preview)
        note=QLabel(self.tr('Project-local review records are untrusted and may be stale. Opening this view does not start a model request.'));note.setWordWrap(True);box.addWidget(note)
        text=QPlainTextEdit(json.dumps(sidecar,ensure_ascii=False,indent=2));text.setObjectName('projectReviewHistory');text.setReadOnly(True);box.addWidget(text)
        selection=QComboBox();selection.setObjectName('projectReviewChoice');box.addWidget(selection)
        for index,snapshot in enumerate(sidecar['snapshots'],1):selection.addItem(self.tr('Snapshot {number} · {count} recorded passes · {id}').format(number=index,count=len(snapshot['reviews']),id=snapshot['id'][:8]),snapshot['id'])
        remove=QPushButton(self.tr('Remove selected project snapshot…'));remove.setObjectName('removeProjectReview');remove.setEnabled(bool(sidecar['snapshots']) and not self.job);box.addWidget(remove)
        def remove_snapshot():
            from .track_review_storage import prepare_remove,apply_append
            ident=selection.currentData()
            if not ident or self.job:return
            try:
                secrets=[item.get('api_key','') for item in self.window.connections.values()]+[item.get('key','') for item in self.store.web_backend_specs()]
                prepared=prepare_remove(files,track_id,ident,secrets)
                def approve(proposal):
                    dialog=QDialog(preview);dialog.setWindowTitle(self.tr('Review project change'));dialog.resize(760,540);layout=QVBoxLayout(dialog)
                    label=QLabel(self.tr('Review the complete removal before applying it. This removes the selected project snapshot and its dispositions. Session snapshots remain.\nProject: {project}\nPath: {path}').format(project=proposal['cwd'],path=proposal['path']));label.setWordWrap(True);layout.addWidget(label)
                    diff=QPlainTextEdit(proposal['diff']);diff.setObjectName('projectReviewRemoveDiff');diff.setReadOnly(True);layout.addWidget(diff)
                    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr('Approve and apply'));buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
                    return dialog.exec()==QDialog.DialogCode.Accepted
                result=apply_append(files,prepared,approve,secrets)
                if result['status']=='completed':preview.accept();QMessageBox.information(parent or self,self.tr('Project review history'),self.tr('Removed the selected project snapshot.'))
            except (ValueError,TypeError,UnicodeError,OSError,sqlite3.Error,RecursionError) as exc:QMessageBox.warning(preview,self.tr('Project review history'),str(exc))
        remove.clicked.connect(remove_snapshot)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);controls.rejected.connect(preview.reject);box.addWidget(controls);preview.exec()

    def review_selected_track(self,track,connection,prompt):
        from .code_agent import ProjectFiles
        from .independent_review import track_review_summary
        files=ProjectFiles(self.session['path_snapshot']);history=self.session.get('coding_review_history',[])
        summary=track_review_summary(files,track,history)
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Review track run'));dialog.resize(800,600);layout=QVBoxLayout(dialog)
        label=QLabel(self.tr('Review the task and track data to be sent to {model} at {endpoint}. Track data is untrusted. Progress is model-reported and is not written to track files. Direct file tools cannot modify agentnik-plans during this run; shell commands and MCP retain their existing permissions.').format(model=connection['model'],endpoint=core.endpoint(connection,'chat')));label.setWordWrap(True);layout.addWidget(label)
        view=QPlainTextEdit(self.tr('User task:')+'\n'+prompt+'\n\n'+self.tr('Selected track data:')+'\n'+track['context']+'\n\n'+self.tr('Saved review snapshots for this track (session and project records; untrusted; older or unsaved reviews may be missing):')+'\n'+json.dumps(summary,ensure_ascii=False,indent=2));view.setReadOnly(True);layout.addWidget(view)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr('Start coding run'));buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return False
        if track_review_summary(files,track,self.session.get('coding_review_history',[]))!=summary:raise ValueError(self.tr('Saved review records or source status changed during review; review and start again.'))
        return True

    def show_track_progress(self):
        from .track_execution import prepare_track,validate_progress
        from .code_agent import ProjectFiles
        try:progress=validate_progress(self.session.get('track_progress'))
        except (ValueError,TypeError):return
        try:
            current=prepare_track(ProjectFiles(self.session['path_snapshot']),progress['track_id']);stale=current['digest']!=progress['source_digest'];tasks={item['id']:item for item in current['tasks']}
            state=self.tr('Source changed since the run; review differences before editing the track.') if stale else self.tr('Source matches the track reviewed for the run.')
        except (ValueError,OSError,UnicodeError):tasks={};state=self.tr('Track source is unavailable; current status cannot be compared.')
        lines=[state,self.tr('Reports are unverified and are never automatically applied to track files.'),'']
        for item in progress['tasks']:
            current=tasks.get(item['id']);lines.append(item['id']+' · '+self.tr('reported')+': '+item['status']+' · '+self.tr('current')+': '+(current['status'] if current else self.tr('unavailable'))+' · '+item['detail'])
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Track progress'));dialog.resize(700,420);layout=QVBoxLayout(dialog);view=QPlainTextEdit('\n'.join(lines));view.setReadOnly(True);layout.addWidget(view)
        reconcile_button=QPushButton(self.tr('Reconcile progress…'));reconcile_button.setEnabled(not self.job and bool(tasks) and not stale);reconcile_button.clicked.connect(lambda:self.reconcile_track_progress(dialog));layout.addWidget(reconcile_button)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

    def reconcile_track_progress(self,parent=None):
        if self.job:return
        from .code_agent import ProjectFiles
        from .track_execution import prepare_track,validate_progress
        from .track_editing import apply_edit
        from .track_reconciliation import reconcile
        try:
            progress=validate_progress(self.session.get('track_progress'));files=ProjectFiles(self.session['path_snapshot']);snapshot=prepare_track(files,progress['track_id'])
            if snapshot['digest']!=progress['source_digest']:raise ValueError(self.tr('Track or project context changed since the run; run again before reconciling.'))
            if self.session.get('track_edit_draft'):raise ValueError(self.tr('Finish or discard the existing track edit draft first.'))
            track=json.loads(snapshot['context'])['track']
        except (ValueError,OSError,UnicodeError,TypeError) as exc:QMessageBox.warning(parent or self,self.tr('Reconcile progress'),str(exc));return
        dialog=QDialog(parent or self);dialog.setWindowTitle(self.tr('Reconcile track progress'));dialog.resize(800,650);layout=QVBoxLayout(dialog)
        label=QLabel(self.tr('Model reports are unverified. Choose each status yourself. To replace a task’s evidence, choose a result and enter its description. A newly completed task requires passed evidence and no failed, unknown, or unrun checks. Nothing changes until you approve the file diff.'));label.setWordWrap(True);layout.addWidget(label)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();rows=QVBoxLayout(body);scroll.setWidget(body);layout.addWidget(scroll,1);controls=[]
        reports={item['id']:item for item in progress['tasks']}
        for task in track['tasks']:
            report=reports.get(task['id'])
            if report is None:QMessageBox.warning(dialog,self.tr('Reconcile progress'),self.tr('Task IDs no longer match the report.'));return
            name=QLabel(task['id']+' · '+task['phase']+' · '+task['step']);name.setTextFormat(Qt.TextFormat.PlainText);name.setWordWrap(True);rows.addWidget(name)
            desc=QLabel(self.tr('Current: {current} | reported: {reported} | {detail}').format(current=task['status'],reported=report['status'],detail=report['detail']));desc.setTextFormat(Qt.TextFormat.PlainText);desc.setWordWrap(True);rows.addWidget(desc)
            evidence=QLabel(self.tr('Existing evidence: ')+('; '.join(item['status']+' · '+item['detail'] for item in task['evidence']) if task['evidence'] else self.tr('none')));evidence.setTextFormat(Qt.TextFormat.PlainText);evidence.setWordWrap(True);rows.addWidget(evidence)
            row=QHBoxLayout();rows.addLayout(row);status=QComboBox();status.addItems(['pending','in_progress','completed','blocked']);status.setCurrentText(task['status']);status.setAccessibleName(self.tr('Status for {id}').format(id=task['id']));row.addWidget(status)
            result=QComboBox();result.addItem(self.tr('Keep existing evidence'),None)
            for value in ('passed','failed','unknown','not_run'):result.addItem(self.tr('Replace evidence: {status}').format(status=value),value)
            result.setAccessibleName(self.tr('Evidence for {id}').format(id=task['id']));row.addWidget(result);detail=QLineEdit();detail.setPlaceholderText(self.tr('Evidence description'));row.addWidget(detail,1);controls.append((task['id'],status,result,detail))
        rows.addStretch();actions=QHBoxLayout();layout.addLayout(actions);review_button=QPushButton(self.tr('Review status changes…'));actions.addWidget(review_button);close=QPushButton(self.tr('Close'));actions.addWidget(close);close.clicked.connect(dialog.reject)
        def review():
            try:
                choices=[{'id':ident,'status':status.currentText(),'evidence':([{'status':result.currentData(),'detail':detail.text()}] if result.currentData() is not None else None)} for ident,status,result,detail in controls]
                draft=reconcile(files,progress,choices)
                from .track_drafting import contains_secrets
                secrets=[connection.get('api_key','') for connection in self.window.connections.values() if isinstance(connection,dict)]
                secrets.extend(backend.get('key','') for backend in self.store.web_backend_specs() if isinstance(backend,dict))
                if contains_secrets(draft,secrets):raise ValueError(self.tr('The proposed change contains a configured credential; remove it before saving.'))
                def approve(proposal):
                    if prepare_track(files,progress['track_id'])!=snapshot:raise ValueError(self.tr('Track or project context changed; review again.'))
                    preview=QDialog(dialog);preview.setWindowTitle(self.tr('Review project change'));preview.resize(760,520);box=QVBoxLayout(preview)
                    heading=QLabel(self.tr('Review the complete status and evidence change before applying it:\nProject: {project}\nPath: {path}').format(project=proposal['cwd'],path=proposal['path']));heading.setWordWrap(True);box.addWidget(heading)
                    diff=QPlainTextEdit(proposal['diff']);diff.setReadOnly(True);box.addWidget(diff);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr('Approve and apply'));buttons.accepted.connect(preview.accept);buttons.rejected.connect(preview.reject);box.addWidget(buttons)
                    accepted=preview.exec()==QDialog.DialogCode.Accepted
                    if accepted and prepare_track(files,progress['track_id'])!=snapshot:raise ValueError(self.tr('Track or project context changed during review.'))
                    return accepted
                result=apply_edit(files,draft,approve)
                if result['status']=='completed':
                    QMessageBox.information(dialog,self.tr('Reconcile progress'),self.tr('Review completed. Changed files: {count}.').format(count=len(result['applied'])));dialog.accept()
            except (ValueError,OSError,UnicodeError,TypeError,sqlite3.Error) as exc:QMessageBox.warning(dialog,self.tr('Reconcile progress'),str(exc))
        review_button.clicked.connect(review);dialog.exec()

    def edit_existing_track(self,ident):
        if self.job:return
        from .code_agent import ProjectFiles
        from .track_editing import load_edit,validate_edit,apply_edit,NAMES
        from .track_drafting import contains_secrets
        existing=self.session.get('track_edit_draft')
        if existing and existing['id']!=ident:
            QMessageBox.warning(self,self.tr('Edit track'),self.tr('Finish or discard the existing track edit draft before editing another track.'));return
        try:
            files=ProjectFiles(self.session['path_snapshot']);current=validate_edit(existing) if existing else load_edit(files,ident)
        except (ValueError,OSError,UnicodeError) as exc:QMessageBox.warning(self,self.tr('Edit track'),str(exc));return
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Edit track · {id}').format(id=ident));dialog.resize(780,600)
        layout=QVBoxLayout(dialog);hint=QLabel(self.tr('Edits are saved as a session draft. Each changed file is reviewed separately; if any track file changed externally, publication stops. Earlier approved changes remain.'));hint.setWordWrap(True);layout.addWidget(hint)
        tabs=QTabWidget();layout.addWidget(tabs,1);editors={};original=dict(current['files']);displayed={}
        for name,label in (('track.json',self.tr('Track metadata (JSON)')),('spec.md',self.tr('Specification')),('plan.md',self.tr('Plan'))):
            editor=QPlainTextEdit(original[name]);editors[name]=editor;displayed[name]=editor.toPlainText();tabs.addTab(editor,label)
        state=QLabel();state.setWordWrap(True);layout.addWidget(state);row=QHBoxLayout();layout.addLayout(row)
        save=QPushButton(self.tr('Save edit draft'));publish=QPushButton(self.tr('Review changes…'));discard=QPushButton(self.tr('Discard edit draft'));close=QPushButton(self.tr('Close'))
        for button in (save,publish,discard,close):row.addWidget(button)
        def collect():
            content={name:(original[name] if editors[name].toPlainText()==displayed[name] else editors[name].toPlainText()) for name in NAMES}
            value=validate_edit({'id':ident,'files':content,'base':current['base']})
            secrets=[c.get('api_key','') for c in self.window.connections.values() if isinstance(c,dict)]
            secrets.extend(b.get('key','') for b in self.store.web_backend_specs() if isinstance(b,dict))
            if contains_secrets(value,secrets):raise ValueError(self.tr('The draft contains a configured credential; remove it before saving.'))
            return value
        def persist(value):
            nonlocal current
            self.session['track_edit_draft']=value;self.store.save(self.session);current=value;self.updated.emit()
        def save_draft():
            try:persist(collect());state.setText(self.tr('Track edit draft saved in this coding session.'))
            except (ValueError,TypeError,OSError,sqlite3.Error) as exc:QMessageBox.warning(dialog,self.tr('Edit track'),str(exc))
        def review(proposal):
            preview=QDialog(dialog);preview.setWindowTitle(self.tr('Review project change'));preview.resize(760,520);box=QVBoxLayout(preview)
            label=QLabel(self.tr('Review the complete change before applying it:\nProject: {project}\nPath: {path}').format(project=proposal['cwd'],path=proposal['path']));label.setWordWrap(True);box.addWidget(label)
            view=QPlainTextEdit(proposal['diff']);view.setReadOnly(True);box.addWidget(view)
            controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);controls.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr('Approve and apply'));controls.accepted.connect(preview.accept);controls.rejected.connect(preview.reject);box.addWidget(controls)
            return preview.exec()==QDialog.DialogCode.Accepted
        def publish_changes():
            if self.job:return
            try:
                value=collect();persist(value);result=apply_edit(files,value,review,persist)
                if result['status']=='completed':
                    self.session.pop('track_edit_draft',None);self.store.save(self.session);self.updated.emit();QMessageBox.information(dialog,self.tr('Edit track'),self.tr('Review completed. Applied changes: {count}.').format(count=len(result['applied'])));dialog.accept()
                else:state.setText(self.tr('Stopped at {path}. Earlier approved changes remain; this draft can be resumed if source files are unchanged.').format(path=result['last_path']))
            except (ValueError,TypeError,OSError,sqlite3.Error) as exc:QMessageBox.warning(dialog,self.tr('Edit track'),self.tr('Review stopped. Earlier approved changes remain. {reason}').format(reason=str(exc)))
        def discard_draft():
            if QMessageBox.question(dialog,self.tr('Discard draft'),self.tr('Discard this saved track edit draft? Applied project changes remain.'))!=QMessageBox.StandardButton.Yes:return
            self.session.pop('track_edit_draft',None);self.store.save(self.session);self.updated.emit();dialog.accept()
        save.clicked.connect(save_draft);publish.clicked.connect(publish_changes);discard.clicked.connect(discard_draft);close.clicked.connect(dialog.reject);dialog.exec()

    def edit_track_draft(self):
        if self.job:return
        from .track_authoring import new_draft,validate_draft,publish
        from .tracks import parse_json
        from .code_agent import ProjectFiles
        current=self.session.get('track_draft') or new_draft()
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Spec & Plan draft'));dialog.resize(780,600)
        layout=QVBoxLayout(dialog);hint=QLabel(self.tr('Edit the track metadata, specification and plan. Saving a draft changes only this session. Publishing creates new project files after individual review; it never overwrites an existing track.'));hint.setWordWrap(True);layout.addWidget(hint)
        tabs=QTabWidget();layout.addWidget(tabs,1)
        metadata=QPlainTextEdit(json.dumps(current['metadata'],ensure_ascii=False,indent=2));spec=QPlainTextEdit(current['spec']);plan=QPlainTextEdit(current['plan'])
        for title,editor in ((self.tr('Track metadata (JSON)'),metadata),(self.tr('Specification'),spec),(self.tr('Plan'),plan)):tabs.addTab(editor,title)
        state=QLabel();state.setWordWrap(True);layout.addWidget(state)
        def refresh_state(value):state.setText(self.tr('Previously created directories: {directories}; files: {files}.').format(directories=len(value['created_dirs']),files=len(value['written'])))
        refresh_state(current)
        row=QHBoxLayout();layout.addLayout(row)
        ask_button=QPushButton(self.tr('Ask Heavy…'));save_button=QPushButton(self.tr('Save draft'));publish_button=QPushButton(self.tr('Review and publish…'));close_button=QPushButton(self.tr('Close'))
        for control in (ask_button,save_button,publish_button,close_button):row.addWidget(control)
        def known_secrets():
            secrets=[c.get('api_key','') for c in self.window.connections.values() if isinstance(c,dict)]
            secrets.extend(b.get('key','') for b in self.store.web_backend_specs() if isinstance(b,dict))
            return secrets
        def collect():
            value={'metadata':parse_json(metadata.toPlainText()),'spec':spec.toPlainText(),'plan':plan.toPlainText(),'created_dirs':current['created_dirs'],'written':current['written']}
            value=validate_draft(value)
            secrets=known_secrets()
            def contains_secret(item):
                if isinstance(item,str):return any(isinstance(secret,str) and secret and secret in item for secret in secrets)
                if isinstance(item,list):return any(contains_secret(part) for part in item)
                if isinstance(item,dict):return any(contains_secret(key) or contains_secret(part) for key,part in item.items())
                return False
            if contains_secret(value):raise ValueError(self.tr('The draft contains a configured credential; remove it before saving.'))
            return value
        def persist(value):
            nonlocal current
            self.session['track_draft']=value;self.store.save(self.session);current=value;refresh_state(value);self.updated.emit()
        def save_draft():
            try:persist(collect());state.setText(self.tr('Draft saved in this coding session.'))
            except (ValueError,TypeError,OSError) as exc:QMessageBox.warning(dialog,self.tr('Spec & Plan draft'),str(exc))
        def review(proposal):
            preview=QDialog(dialog);preview.setWindowTitle(self.tr('Review project change'));preview.resize(760,520);box=QVBoxLayout(preview)
            path=proposal['path'];operation=proposal.get('operation','create_file')
            label=QLabel(self.tr('Review the complete change before applying it:\nProject: {project}\nOperation: {operation}\nPath: {path}').format(project=proposal['cwd'],operation=operation,path=path));label.setWordWrap(True);box.addWidget(label)
            content=QPlainTextEdit(proposal.get('diff','') if operation!='create_directory' else self.tr('Create this directory.'));content.setReadOnly(True);box.addWidget(content)
            controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);controls.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr('Approve and apply'));controls.accepted.connect(preview.accept);controls.rejected.connect(preview.reject);box.addWidget(controls)
            return preview.exec()==QDialog.DialogCode.Accepted
        def publish_draft():
            if self.job:return
            try:
                value=collect();persist(value);result=publish(ProjectFiles(self.session['path_snapshot']),value,review,persist)
                if result['status']=='completed':
                    self.session.pop('track_draft',None);self.store.save(self.session);self.updated.emit();QMessageBox.information(dialog,self.tr('Spec & Plan draft'),self.tr('Track files created. Reopen Spec & Plan to inspect them.'));dialog.accept()
                else:state.setText(self.tr('Stopped at {path}. Approved changes remain; save or retry this draft to continue.').format(path=result['last_path']))
            except (ValueError,TypeError,OSError) as exc:QMessageBox.warning(dialog,self.tr('Spec & Plan draft'),self.tr('Publication stopped. Any approved earlier changes remain. {reason}').format(reason=str(exc)))
        def ask_heavy():
            if self.job:return
            from .track_drafting import prepare,request,validate_history
            from .ui import Job
            try:
                initial=collect();connection=self.role_connection('heavy')
                if not connection:raise ValueError(self.tr('Choose a Heavy model first.'))
                if initial['created_dirs'] or initial['written']:raise ValueError(self.tr('A partially published draft cannot be regenerated.'))
                history=validate_history(self.session.get('track_draft_conversation',[]));secrets=known_secrets()
                endpoint=core.endpoint(connection,'chat')
            except (ValueError,TypeError,OSError) as exc:QMessageBox.warning(dialog,self.tr('Draft with Heavy'),str(exc));return
            ai=QDialog(dialog);ai.setWindowTitle(self.tr('Draft with Heavy'));ai.resize(720,560);box=QVBoxLayout(ai)
            info=QLabel(self.tr('Heavy model: {model}\nEndpoint: {endpoint}\nYour requirements, displayed conversation, and current draft are sent. No project files or tools are automatically supplied. Model output is untrusted and must be reviewed.').format(model=connection['model'],endpoint=endpoint));info.setWordWrap(True);box.addWidget(info)
            transcript=QPlainTextEdit();transcript.setReadOnly(True);box.addWidget(transcript,1)
            def show_history():transcript.setPlainText('\n\n'.join(('You: ' if item['role']=='user' else 'Heavy: ')+item['text'] for item in history))
            show_history();question=QPlainTextEdit();question.setPlaceholderText(self.tr('Enter requirements, a revision request, or answer the question'));question.setMaximumHeight(100);box.addWidget(question)
            status=QLabel();status.setWordWrap(True);box.addWidget(status)
            actions=QHBoxLayout();box.addLayout(actions);send=QPushButton(self.tr('Send'));cancel=QPushButton(self.tr('Cancel request'));apply=QPushButton(self.tr('Apply proposed draft'));clear=QPushButton(self.tr('Clear conversation'));close=QPushButton(self.tr('Close'))
            for control in (send,cancel,apply,clear,close):actions.addWidget(control)
            cancel.setEnabled(False);apply.setEnabled(False);pending={'draft':None,'job':None,'token':None}
            def busy(value):
                send.setEnabled(not value);question.setReadOnly(value);clear.setEnabled(not value);cancel.setEnabled(value);apply.setEnabled(not value and pending['draft'] is not None)
            def stop():
                if pending['job'] is not None:
                    pending['job'].cancel.set();pending['job']=None;pending['token']=None;self.job=None;self._drafting_active=False;busy(False);status.setText(self.tr('Draft request cancelled.'));self.updated.emit()
            def clear_history():
                history.clear();self.session.pop('track_draft_conversation',None);self.store.save(self.session);pending['draft']=None;apply.setEnabled(False);show_history();self.updated.emit()
            def send_request():
                if pending['job'] is not None or self.job:return
                user_text=question.toPlainText().strip()
                try:
                    body=prepare(connection,initial,history,user_text,secrets);seconds=min(coding_limits(self.session.get('coding_limits'))['model_seconds'],coding_limits(self.session.get('coding_limits'))['turn_seconds'])
                except (ValueError,TypeError,OSError) as exc:status.setText(str(exc));return
                token=uuid.uuid4().hex;pending['token']=token;pending['draft']=None;busy(True);status.setText(self.tr('Waiting for Heavy…'))
                def done(value):
                    nonlocal initial
                    if self._closed or pending['token']!=token:return
                    pending['token']=None;pending['job']=None;self.job=None;self._drafting_active=False
                    response=value['question'] if value['kind']=='question' else self.tr('A draft was proposed for review; unapplied proposals are not retained.')
                    updated=(history+[{'role':'user','text':user_text},{'role':'assistant','text':response}])[-12:]
                    prior=self.session.get('track_draft_conversation')
                    self.session['track_draft_conversation']=updated
                    try:self.store.save(self.session)
                    except Exception:
                        if prior is None:self.session.pop('track_draft_conversation',None)
                        else:self.session['track_draft_conversation']=prior
                        busy(False);status.setText(self.tr('Could not save the drafting conversation. No draft was changed.'));self.updated.emit();return
                    history[:]=updated;show_history();question.clear()
                    if value['kind']=='draft':
                        pending['draft']=value['draft'];initial=value['draft'];preview=json.dumps({k:value['draft'][k] for k in ('metadata','spec','plan')},ensure_ascii=False,indent=2);transcript.appendPlainText('\n'+self.tr('Proposed draft:')+'\n'+preview);status.setText(self.tr('Review the entire proposal before applying it.'))
                    else:status.setText(self.tr('Answer the question and send again.'))
                    busy(False);self.updated.emit()
                def failed(_message):
                    if self._closed or pending['token']!=token:return
                    pending['token']=None;pending['job']=None;self.job=None;self._drafting_active=False;busy(False);status.setText(self.tr('Draft request failed or returned an invalid response. No draft was changed.'));self.updated.emit()
                job=Job(lambda emit,cancel_event:request(connection,body,cancel_event,seconds,secrets),done,failed);pending['job']=job;self.job=job;self._drafting_active=True;self.updated.emit()
            def apply_proposal():
                proposed=pending['draft']
                if not proposed:return
                metadata.setPlainText(json.dumps(proposed['metadata'],ensure_ascii=False,indent=2));spec.setPlainText(proposed['spec']);plan.setPlainText(proposed['plan']);ai.accept()
            self._drafting_cancel_callback=stop
            send.clicked.connect(send_request);cancel.clicked.connect(stop);clear.clicked.connect(clear_history);apply.clicked.connect(apply_proposal);close.clicked.connect(ai.reject);ai.finished.connect(lambda *_:stop());ai.exec();self._drafting_cancel_callback=None
        ask_button.clicked.connect(ask_heavy);save_button.clicked.connect(save_draft);publish_button.clicked.connect(publish_draft);close_button.clicked.connect(dialog.reject);dialog.exec()

    def edit_project_memory(self):
        from .project_memory import ProjectMemory,validate_entry,digest
        if not self.window.repositories.get(self.session['project_id']):
            QMessageBox.warning(self,self.tr('Project memory'),self.tr('This project is no longer registered.'));return
        memory=ProjectMemory(self.store.root/'history.sqlite3',self.session['project_id'])
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Project memory'));dialog.resize(720,520)
        layout=QVBoxLayout(dialog);hint=QLabel(self.tr('Entries are shared by coding sessions for this project. Memory may be stale and does not override project instructions. Select an entry to edit or delete it.'));hint.setWordWrap(True);layout.addWidget(hint)
        listing=QListWidget();layout.addWidget(listing);metadata=QLabel();layout.addWidget(metadata);editor=QPlainTextEdit();layout.addWidget(editor)
        actions=QHBoxLayout();layout.addLayout(actions)
        add=QPushButton(self.tr('New'));save=QPushButton(self.tr('Save'));delete=QPushButton(self.tr('Delete'))
        for button in (add,save,delete):actions.addWidget(button)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);close.rejected.connect(dialog.reject);layout.addWidget(close)
        state={'entry':None}
        def refresh():
            listing.clear()
            for entry in memory.list():
                item=QListWidgetItem(entry['title']+(' · '+self.tr('May be stale') if entry['stale'] else ''));item.setData(Qt.ItemDataRole.UserRole,entry);listing.addItem(item)
        def select(item):
            if item is None:return
            entry=item.data(Qt.ItemDataRole.UserRole);state['entry']=entry
            metadata.setText(self.tr('Created: {created} · Updated: {updated}').format(created=entry['created'],updated=entry['updated']))
            editor.setPlainText(json.dumps({k:entry[k] for k in ('title','text','source','stale')},ensure_ascii=False,indent=2))
        def new():
            listing.clearSelection();state['entry']=None;metadata.clear();editor.setPlainText(json.dumps({'title':'','text':'','source':'','stale':False},indent=2))
        def store_entry():
            try:
                value=validate_entry(json.loads(editor.toPlainText()));old=state['entry'];prior={k:old[k] for k in ('title','text','source','stale')} if old else None
                memory.save(value,old['id'] if old else None,digest(prior) if old else None);refresh();new()
            except (ValueError,TypeError,OSError) as exc:QMessageBox.warning(dialog,self.tr('Project memory'),str(exc))
        def remove():
            old=state['entry']
            if old and QMessageBox.question(dialog,self.tr('Delete memory'),self.tr('Delete this project memory entry?'))==QMessageBox.StandardButton.Yes:
                try:memory.delete(old['id'],digest({k:old[k] for k in ('title','text','source','stale')}));refresh();new()
                except ValueError as exc:QMessageBox.warning(dialog,self.tr('Project memory'),str(exc))
        listing.currentItemChanged.connect(lambda item,_:select(item));add.clicked.connect(new);save.clicked.connect(store_entry);delete.clicked.connect(remove);refresh();new();dialog.exec()

    def edit_working_notes(self):
        from .code_artifacts import validate_notes
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Working notes'));dialog.resize(640,440)
        layout=QVBoxLayout(dialog);hint=QLabel(self.tr('Edit the JSON object of note names and text. Notes persist with this coding session and can be sent to the selected model.'));hint.setWordWrap(True);layout.addWidget(hint)
        editor=QPlainTextEdit(json.dumps(self.session.get('coding_working_notes',{}),ensure_ascii=False,indent=2));layout.addWidget(editor)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);layout.addWidget(buttons)
        def save():
            try:notes=validate_notes(json.loads(editor.toPlainText()))
            except (ValueError,TypeError) as exc:QMessageBox.warning(dialog,self.tr('Working notes'),str(exc));return
            self.session['coding_working_notes']=notes;self.store.save(self.session);self.updated.emit();dialog.accept()
        buttons.accepted.connect(save);buttons.rejected.connect(dialog.reject);dialog.exec()

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

    def save_mcp_selection(self):
        self.mcp_extra=[ref['name'] for ref in self.mcp_extra_refs]
        self.mcp_extra_button.setText(self.tr('Additional servers ({count})…').format(count=len(self.mcp_extra)))
        self.session['coding_mcp_selection']={'primary':self.mcp_primary_ref,'extra':list(self.mcp_extra_refs)}
        self.store.save(self.session)

    def mcp_primary_changed(self):
        from .mcp_support import server_fingerprint
        name=self.mcp_choice.currentData()
        if isinstance(name,dict):return
        server=next((item for item in self.store.config.get('mcp_servers',[]) if item.get('name')==name and item.get('enabled')),None)
        self.mcp_primary_ref={'name':name,'sha256':server_fingerprint(server)} if server else None
        if name:self.mcp_extra_refs=[ref for ref in self.mcp_extra_refs if ref['name'].casefold()!=name.casefold()]
        self.save_mcp_selection()

    def refresh_mcp_servers(self):
        from .mcp_support import server_fingerprint
        self.mcp_choice.blockSignals(True);self.mcp_choice.clear();self.mcp_choice.addItem(self.tr('No MCP server'),None)
        entries=self.store.config.get('mcp_servers',[])
        for item in entries:
            if item.get('enabled'):self.mcp_choice.addItem(item['name']+(' · HTTPS' if item.get('transport')=='http' else ' · local'),item['name'])
        ref=self.mcp_primary_ref
        if ref:
            server=next((item for item in entries if item.get('name')==ref['name'] and item.get('enabled')),None)
            if server and server_fingerprint(server)==ref['sha256']:self.mcp_choice.setCurrentIndex(self.mcp_choice.findData(ref['name']))
            else:
                self.mcp_choice.addItem(ref['name']+self.tr(' (changed or unavailable; reselect)'),dict(ref));self.mcp_choice.setCurrentIndex(self.mcp_choice.count()-1)
        self.mcp_choice.blockSignals(False)
        self.mcp_extra_button.setText(self.tr('Additional servers ({count})…').format(count=len(self.mcp_extra_refs)))

    def choose_additional_mcp(self):
        from .mcp_support import server_fingerprint
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Additional MCP servers'));layout=QVBoxLayout(dialog)
        note=QLabel(self.tr('Select up to five servers total, including the server selected in the Code pane. Each server must be approved before connecting.'));note.setWordWrap(True);layout.addWidget(note)
        checks=[];entries=self.store.config.get('mcp_servers',[]);old={ref['name']:ref for ref in self.mcp_extra_refs}
        for item in entries:
            if not item.get('enabled'):continue
            name=item['name'];ref=old.get(name);changed=ref and ref['sha256']!=server_fingerprint(item)
            check=QCheckBox(name+(' · HTTPS' if item.get('transport')=='http' else ' · local')+(self.tr(' (changed; confirm selection)') if changed else ''));check.setChecked(bool(ref));layout.addWidget(check);checks.append((name,check,item))
        available={item.get('name') for item in entries if item.get('enabled')}
        for name,ref in old.items():
            if name not in available:
                check=QCheckBox(name+self.tr(' (unavailable; uncheck to remove)'));check.setChecked(True);layout.addWidget(check);checks.append((name,check,None))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        primary=self.mcp_primary_ref['name'] if self.mcp_primary_ref else None
        selected=[(name,item) for name,check,item in checks if check.isChecked() and (not primary or name.casefold()!=primary.casefold())]
        if len(selected)+(1 if primary else 0)>5:
            QMessageBox.warning(self,self.tr('MCP servers'),self.tr('Select at most five servers total.'));return
        self.mcp_extra_refs=[{'name':name,'sha256':server_fingerprint(item)} if item else old[name] for name,item in selected];self.save_mcp_selection()

    def start_direct_review(self):
        if self.job or self._closed:return
        if not self.light_enabled.isChecked():QMessageBox.warning(self,self.tr('Independent review'),self.tr('Enable Light model delegation and configure a reviewer model first.'));return
        try:
            self.save_models();models={}
            for role in ('light','alternate','alternate2'):
                connection,model=self.roles[role]
                if connection.currentData() and model.text().strip():models[role]=self.role_connection(role)
            if not models:raise ValueError(self.tr('Configure a Light or alternate reviewer model.'))
            ident=self.session.get('selected_track');default_path=('agentnik-plans/tracks/'+ident+'/spec.md') if ident else ''
            dialog=DirectReviewDialog(self,models,default_path)
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            target,passes=dialog.values()
            if dialog.save_progress.isChecked() and len(self.session.get('coding_review_history',[]))>=10:raise ValueError(self.tr('The session already has ten review snapshots. Delete one before saving progress.'))
            from .code_agent import ProjectFiles
            files=ProjectFiles(self.session['path_snapshot']);files.path(target)
            for item in passes:
                for path in item['paths']:files.path(path)
            selected=None
            secrets=[connection.get('api_key','') for connection in self.window.connections.values()]+[backend.get('key','') for backend in self.store.web_backend_specs()]
            if ident:
                from .track_execution import prepare_track
                selected=prepare_track(files,ident,secrets,coding_limits(self.session.get('coding_limits'))['context_bytes'])
            from .direct_review import DirectReviewRun
            run=DirectReviewRun(self.session['path_snapshot'],target,passes,models,limits=self.session.get('coding_limits'),selected_track=selected,extra_secrets=secrets,save_progress=dialog.save_progress.isChecked())
        except (OSError,ValueError,TypeError) as exc:QMessageBox.warning(self,self.tr('Independent review'),str(exc));return
        self.launch(run,self.tr('Independent document review started. Each reviewer input and destination requires approval.'))

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
            prompt=self.composer.toPlainText();ident=self.session.get('selected_track')
            if not heavy or (not prompt.strip() and not ident and not self.attachments.paths and not self.documents):raise ValueError(self.tr('Choose a heavy model and enter a coding task, attach a file, or select a track'))
            if not prompt.strip():prompt=self.tr('Work on the selected project track. Inspect the project and report progress against its task IDs.') if ident else self.tr('Consider the attached files for this coding task.')
            context=self.session.get('coding_context') if self.use_context.isChecked() else None
            if context:
                from .context_compaction import coding_effective_context
                snapshot=self.session.get('coding_compaction')
                if snapshot:context=coding_effective_context(context,snapshot)
                elif self.coding_auto_compact.isChecked() and len(context['task'])+len(context['answer'])>=3000:
                    self.compact_coding_context(auto_start=True,connection=heavy);return
            enabled=self.web_enabled.isChecked();backends=[];provider='none'
            if enabled:
                strict=routing.connection_defaults(self.store.config,self.roles['heavy'][0].currentData(),heavy)['access_policy']=='strict_public'
                parsed=urlsplit(heavy['url']);direct=parsed.scheme=='https' and parsed.hostname=='ollama.com' and parsed.port in (None,443)
                if not strict:
                    backends=[b for b in self.store.web_backend_specs() if b.get('kind') in SEARCH_KINDS and (b.get('kind')!='ollama' or direct)]
                    provider='managed'
            from .mcp_support import server_fingerprint
            refs=([self.mcp_primary_ref] if self.mcp_primary_ref else [])+self.mcp_extra_refs
            if len(refs)>5:raise ValueError(self.tr('Select at most five MCP servers.'))
            entries=self.store.config.get('mcp_servers',[]);servers=[]
            for ref in refs:
                server=next((item for item in entries if item.get('name')==ref['name'] and item.get('enabled')),None)
                if not server or server_fingerprint(server)!=ref['sha256']:
                    raise ValueError(self.tr('A selected MCP server changed or is unavailable. Reselect it or remove it from Additional servers.'))
                servers.append(server)
            from .mcp_code import CodingMCPBridge
            mcp_bridges=[CodingMCPBridge(server,self.store.config,self) for server in servers]
            from .subagent_capabilities import unsupported
            role_models={'light':light,'alternate':alternate,'alternate2':alternate2}
            unsupported_roles={role for role,connection in role_models.items() if connection and unsupported(self.store.config,self.subagent_capability_connection(role,connection))}
            from .project_memory import ProjectMemory
            project_memory=ProjectMemory(self.store.root/'history.sqlite3',self.session['project_id']) if self.window.repositories.get(self.session['project_id']) else None
            selected=None;review_guard=None
            if ident:
                from .track_execution import prepare_track
                from .independent_review import track_review_summary,validate_review_history
                secrets=[(connection or {}).get('api_key','') for connection in (heavy,light,alternate,alternate2)]+[backend.get('key','') for backend in backends]
                for bridge in mcp_bridges:secrets.extend(getattr(bridge,'environment_values',{}).values())
                files=ProjectFiles(self.session['path_snapshot']);limit=coding_limits(self.session.get('coding_limits'))['context_bytes'];selected=prepare_track(files,ident,secrets,limit)
                history=validate_review_history(self.session.get('coding_review_history',[]));summary=track_review_summary(files,selected,history)
                if not self.review_selected_track(selected,heavy,prompt):return
                if prepare_track(files,ident,secrets,limit)!=selected:raise ValueError(self.tr('Selected track changed after review; review and start again.'))
                if track_review_summary(files,selected,self.session.get('coding_review_history',[]))!=summary:raise ValueError(self.tr('Saved review records or source status changed during review; review and start again.'))
                review_guard={'history':history,'summary':summary}
            run=CodingRun(heavy,self.session['path_snapshot'],prompt,light,context,backends,limits=self.session.get('coding_limits'),web_enabled=enabled,search_provider=provider,skills=self.session.get('coding_skills',[]),alternate=alternate,alternate2=alternate2,skill_pins=self.session.get('coding_skill_pins',{}),mcp_bridges=mcp_bridges,unsupported_subagent_roles=unsupported_roles,working_notes=self.session.get('coding_working_notes',{}),project_memory=project_memory,selected_track=selected,images=self.attachments.paths,documents=self.documents,review_guard=review_guard,save_review_progress=self.save_review_progress.isChecked())
        except (OSError,ValueError) as exc:QMessageBox.warning(self,self.tr('Coding settings'),str(exc));return
        if self.composer.toPlainText().strip():self.remember_prompt(self.composer.toPlainText())
        self.advice_connection=advice;self.advice_destination=destination
        self.launch(run,'Agentnik coding started. Project file changes apply without per-file approval; shell commands require approval. Repository content goes to the selected models.')
        if enabled:self.record('output',{'none':'Web research: public page reads only; strict navigation disables search.','google':'Web research: Google search and public page reads.','ollama':'Web research: Ollama search and public page reads.','managed':'Web research: configured search providers and public page reads.'}[provider])

    def launch(self,run,notice):
        if isinstance(run,CodingRun):
            self.review_results.clear();self.review_dispositions.clear();self.review_progress_ids.clear();self.review_results_button.setEnabled(False)
            self.session['coding_subagents']=[];self.refresh_subagents()
            if not getattr(run,'direct_review',False):
                history=self.session.setdefault('coding_skill_history',[])
                history.append({'run_id':run.run_id,'skills':[]});self.session['coding_skill_history']=history[-32:]
                self.session['coding_sources']=[];self.session['coding_skill_revisions']=[];self.update_sources_button();self.session.pop('coding_plan',None);self.refresh_plan()
        self.job=run;self.run_id=run.run_id;self.pending_fingerprint=None;self.session['code_state']='running'
        self.send.setEnabled(False);self.direct_review_button.setEnabled(False);self.cancel_button.setEnabled(True)
        self.coding_context_button.setEnabled(False);self.coding_auto_compact.setEnabled(False);self.memory_button.setEnabled(False);self.notes_button.setEnabled(False);self.light_enabled.setEnabled(False);self.save_review_progress.setEnabled(False);self.web_enabled.setEnabled(False);self.limits_button.setEnabled(False);self.search_settings.setEnabled(False);self.advice_enabled.setEnabled(False);self.mcp_choice.setEnabled(False);self.mcp_refresh.setEnabled(False);self.mcp_extra_button.setEnabled(False)
        self.use_context.setEnabled(False)
        for connection,model in self.roles.values():connection.setEnabled(False);model.setEnabled(False)
        self.diff.clear();self.approval.clear();self.record('started',notice)
        signals=self.events
        def work():
            try:run.run(signals.event.emit)
            except RuntimeError:pass
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()

    def update_prompt_history_buttons(self):
        count=len(self.session.get('coding_prompt_history',[]))
        self.history_up.setEnabled(self._history_index>0)
        self.history_down.setEnabled(self._history_index<count)

    def navigate_prompt_history(self, direction):
        history=self.session.get('coding_prompt_history',[]);target=self._history_index+direction
        if not 0<=target<=len(history):return
        self._history_edits[self._history_index]=self.composer.toPlainText()
        self._history_index=target
        self.composer.setPlainText(self._history_edits.get(target,history[target] if target<len(history) else ''))
        self.composer.moveCursor(QTextCursor.MoveOperation.End)
        self.update_prompt_history_buttons()

    def remember_prompt(self, prompt):
        history=self.session.setdefault('coding_prompt_history',[])
        if not history or history[-1]!=prompt:history.append(prompt)
        # Keep complete recent prompts without allowing unbounded session growth.
        while len(history)>100 or sum(map(len,history))>2_000_000:
            history.pop(0)
        self._history_index=len(history);self._history_edits={}
        self.update_prompt_history_buttons()
        self.store.save(self.session)

    def save_draft(self):
        self.session['draft']=self.composer.toPlainText();self.session['draft_images']=list(self.attachments.paths);self.session['draft_documents']=copy.deepcopy(self.documents);self.store.save(self.session);self.updated.emit()

    def read_documents(self):
        from .document_ui import DocumentReader
        if len(self.documents)>=4:
            QMessageBox.warning(self,self.tr('Documents'),self.tr('Attach up to four documents per prompt.'));return
        dlg=DocumentReader(self)
        if dlg.exec()==QDialog.DialogCode.Accepted:
            paths=[self.store.attach(data=page) for page in dlg.pages]
            if paths:dlg.document['images']=paths
            self.documents.append(dlg.document);self.attachments.paths.extend(paths);self.attachments.refresh();self.refresh_documents();self.save_draft()

    def refresh_documents(self):
        while self.document_row.count():
            item=self.document_row.takeAt(0)
            if item.widget():item.widget().deleteLater()
        for index,doc in enumerate(self.documents):
            label=QLabel(doc['name']);label.setTextFormat(Qt.TextFormat.PlainText);self.document_row.addWidget(label)
            remove=QPushButton('×');remove.setAccessibleName(self.tr('Remove document'));remove.clicked.connect(lambda checked=False,i=index:self.remove_document(i));self.document_row.addWidget(remove)
        self.document_row.addStretch()

    def remove_document(self,index):
        doc=self.documents.pop(index);self.attachments.set_paths([p for p in self.attachments.paths if p not in doc.get('images',[])]);self.refresh_documents();self.save_draft()

    def activity_text(self,event):
        kind=event.get('kind','');text=plain(event.get('text',kind))
        fixed={('started','Agentnik coding started. Repository content goes to the selected models; edits await approval.'):self.tr('Agentnik coding started. Repository content goes to the selected models; edits await approval.'),
               ('started','Agentnik coding started. Project file changes apply without per-file approval; shell commands require approval. Repository content goes to the selected models.'):self.tr('Agentnik coding started. Project file changes apply without per-file approval; shell commands require approval. Repository content goes to the selected models.'),
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

    def show_review_results(self):
        if not self.review_results:return
        from .code_agent import ProjectFiles
        from .independent_review import sources_unchanged,track_context_matches
        try:files=ProjectFiles(self.session['path_snapshot'])
        except (ValueError,OSError):files=None
        rows=[]
        for review in self.review_results.values():
            item=copy.deepcopy(review);sources=[(item['path'],item['source_sha256'])]+[(entry['path'],entry['sha256']) for entry in item['evidence']]
            item['source_status']=self.tr('Current source hashes match the reviewed snapshots.') if files and sources_unchanged(files,sources) else self.tr('Stale or unavailable: a reviewed source changed or cannot be read.')
            if item.get('track_context'):
                item['track_status']=self.tr('Track run context matches its starting revision; this does not mean the full track was reviewed.') if files and track_context_matches(files,item['track_context']) else self.tr('Track run context changed or is unavailable; this does not mean the full track was reviewed.')
            rows.append(item)
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Independent review findings'));dialog.resize(760,540)
        layout=QVBoxLayout(dialog);notice=QLabel(self.tr('Untrusted reviewer suggestions, not verified facts. Locations are claims. Source hashes were checked when this view opened and can change afterwards. Dispositions do not approve implementation. Current results are temporary unless explicitly saved as a session snapshot.'));notice.setWordWrap(True);layout.addWidget(notice)
        view=QPlainTextEdit();view.setReadOnly(True);layout.addWidget(view)
        form=QFormLayout();layout.addLayout(form)
        choice=QComboBox();choice.setObjectName('reviewFindingChoice');form.addRow(self.tr('Finding'),choice)
        disposition=QComboBox();disposition.setObjectName('reviewDisposition')
        for label,value in [(self.tr('Unresolved'),'unresolved'),(self.tr('Accepted'),'accepted'),(self.tr('Contested'),'contested'),(self.tr('Deferred'),'deferred')]:disposition.addItem(label,value)
        form.addRow(self.tr('Disposition'),disposition)
        reason=QLineEdit();reason.setObjectName('reviewDispositionReason');reason.setMaxLength(500);form.addRow(self.tr('Rationale (optional)'),reason)
        apply_button=QPushButton(self.tr('Save disposition in this pane'));apply_button.setObjectName('saveReviewDisposition');layout.addWidget(apply_button)
        for row in rows:
            for finding in row['structured']['findings']:
                choice.addItem(row['role']+' · '+row['model']+' · '+finding['id']+' · '+finding['title'][:100],(row['id'],finding['id']))
        def refresh_view():
            display=copy.deepcopy(rows)
            for row in display:
                for finding in row['structured']['findings']:
                    finding['user_disposition']=copy.deepcopy(self.review_dispositions.get((row['id'],finding['id']),{'status':'unresolved','rationale':''}))
            view.setPlainText(json.dumps(display,ensure_ascii=False,indent=2))
        def select_finding():
            current=choice.currentData();saved=self.review_dispositions.get(tuple(current),{'status':'unresolved','rationale':''}) if current else {'status':'unresolved','rationale':''}
            disposition.setCurrentIndex(max(0,disposition.findData(saved['status'])));reason.setText(saved['rationale'])
        def save_disposition():
            current=choice.currentData()
            if not current:return
            self.review_dispositions[tuple(current)]={'status':disposition.currentData(),'rationale':reason.text()};refresh_view()
        choice.currentIndexChanged.connect(select_finding);apply_button.clicked.connect(save_disposition)
        for widget in (choice,disposition,reason,apply_button):widget.setEnabled(choice.count()>0)
        select_finding();refresh_view()
        save_snapshot=QPushButton(self.tr('Save review results to session'));save_snapshot.setObjectName('saveReviewSnapshot');save_snapshot.setEnabled(not self.job);layout.addWidget(save_snapshot)
        save_snapshot.setToolTip(self.tr('Save recorded pass statuses, findings and dispositions to this session. An interrupted batch may have unrecorded passes. This does not modify track files or approve implementation.'))
        def save_current_snapshot():
            from .independent_review import validate_review_history
            record={'version':1,'id':uuid.uuid4().hex,'track_id':None,'reviews':[]}
            for review in self.review_results.values():
                item=copy.deepcopy(review);item['dispositions']={finding['id']:copy.deepcopy(self.review_dispositions[(item['id'],finding['id'])]) for finding in item['structured']['findings'] if (item['id'],finding['id']) in self.review_dispositions};record['reviews'].append(item)
            try:
                history=validate_review_history([*self.session.get('coding_review_history',[]),record])
                updated=copy.deepcopy(self.session);updated['coding_review_history']=history;self.store.save(updated);self.session['coding_review_history']=history
            except (ValueError,TypeError,UnicodeError,sqlite3.Error,OSError) as exc:QMessageBox.warning(dialog,self.tr('Saved reviews'),str(exc));return
            self.saved_reviews_button.setEnabled(True);self.updated.emit();save_snapshot.setEnabled(False)
        save_snapshot.clicked.connect(save_current_snapshot)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

    def show_saved_reviews(self):
        from .code_agent import ProjectFiles
        from .independent_review import sources_unchanged,validate_review_history,track_context_matches
        try:
            history=validate_review_history(self.session.get('coding_review_history',[]))
        except (ValueError,TypeError,OSError):return
        try:files=ProjectFiles(self.session['path_snapshot'])
        except (ValueError,OSError):files=None
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Saved review snapshots'));dialog.resize(760,540);layout=QVBoxLayout(dialog)
        note=QLabel(self.tr('Saved pass statuses and findings are untrusted; older snapshots contain completed passes only. Interrupted batches may have unrecorded passes. Dispositions do not approve implementation. Source hashes are checked when selecting a snapshot and may change.'));note.setWordWrap(True);layout.addWidget(note)
        choice=QComboBox();choice.setObjectName('savedReviewChoice');layout.addWidget(choice)
        for index,record in enumerate(history,1):choice.addItem(self.tr('Snapshot {number} · {count} recorded passes · {id}').format(number=index,count=len(record['reviews']),id=record['id'][:8]),record['id'])
        view=QPlainTextEdit();view.setReadOnly(True);layout.addWidget(view)
        form=QFormLayout();layout.addLayout(form)
        finding_choice=QComboBox();finding_choice.setObjectName('savedReviewFinding');form.addRow(self.tr('Finding'),finding_choice)
        disposition=QComboBox();disposition.setObjectName('savedReviewDisposition')
        for label,value in [(self.tr('Unresolved'),'unresolved'),(self.tr('Accepted'),'accepted'),(self.tr('Contested'),'contested'),(self.tr('Deferred'),'deferred')]:disposition.addItem(label,value)
        form.addRow(self.tr('Disposition'),disposition)
        reason=QLineEdit();reason.setObjectName('savedReviewRationale');reason.setMaxLength(500);form.addRow(self.tr('Rationale (optional)'),reason)
        save_revision=QPushButton(self.tr('Save disposition as new snapshot'));save_revision.setObjectName('saveReviewRevision');layout.addWidget(save_revision)
        save_revision.setToolTip(self.tr('Creates another session snapshot and preserves the original. This does not approve implementation.'))
        project_actions=QHBoxLayout();layout.addLayout(project_actions)
        publish=QPushButton(self.tr('Save snapshot to project track…'));publish.setObjectName('publishReviewSnapshot');project_actions.addWidget(publish)
        view_project=QPushButton(self.tr('View project track reviews…'));view_project.setObjectName('viewProjectReviews');project_actions.addWidget(view_project)
        def selected_track_id(record):
            if not record:return None
            contexts=[item.get('track_context') for item in record['reviews']]
            if not contexts or any(not item for item in contexts):return None
            ids={item['id'] for item in contexts}
            return next(iter(ids)) if len(ids)==1 else None
        def select_finding():
            record=next((item for item in history if item['id']==choice.currentData()),None);key=finding_choice.currentData();saved={'status':'unresolved','rationale':''}
            if record and key:
                review=next((item for item in record['reviews'] if item['id']==key[0]),None)
                if review:saved=review['dispositions'].get(key[1],saved)
            disposition.setCurrentIndex(max(0,disposition.findData(saved['status'])));reason.setText(saved['rationale'])
        finding_choice.currentIndexChanged.connect(select_finding)
        def display_selected():
            record=next((copy.deepcopy(item) for item in history if item['id']==choice.currentData()),None)
            finding_choice.blockSignals(True);finding_choice.clear()
            if not record:
                finding_choice.blockSignals(False);view.clear()
                for widget in (finding_choice,disposition,reason,save_revision,publish,view_project):widget.setEnabled(False)
                return
            for review in record['reviews']:
                sources=[(review['path'],review['source_sha256'])]+[(entry['path'],entry['sha256']) for entry in review['evidence']]
                review['source_status']=self.tr('Current source hashes match the reviewed snapshots.') if files and sources_unchanged(files,sources) else self.tr('Stale or unavailable: a reviewed source changed or cannot be read.')
                if review.get('track_context'):
                    review['track_status']=self.tr('Track run context matches its starting revision; this does not mean the full track was reviewed.') if files and track_context_matches(files,review['track_context']) else self.tr('Track run context changed or is unavailable; this does not mean the full track was reviewed.')
                for finding in review['structured']['findings']:
                    finding_choice.addItem(review['role']+' · '+review['model']+' · '+finding['id']+' · '+finding['title'][:100],(review['id'],finding['id']))
            finding_choice.blockSignals(False)
            for widget in (finding_choice,disposition,reason,save_revision):widget.setEnabled(finding_choice.count()>0)
            track_id=selected_track_id(record);publish.setEnabled(bool(files and track_id and not self.job));view_project.setEnabled(bool(files and track_id))
            select_finding()
            view.setPlainText(json.dumps(record,ensure_ascii=False,indent=2))
        choice.currentIndexChanged.connect(display_selected);display_selected()
        def save_revised_disposition():
            ident=choice.currentData();key=finding_choice.currentData()
            if not ident or not key:return
            try:
                current=validate_review_history(self.session.get('coding_review_history',[]))
                original=next((record for record in current if record['id']==ident),None)
                shown=next((record for record in history if record['id']==ident),None)
                if original is None or original!=shown:raise ValueError(self.tr('The selected snapshot changed or is unavailable.'))
                revised=copy.deepcopy(original);revised['id']=uuid.uuid4().hex
                review=next(item for item in revised['reviews'] if item['id']==key[0])
                review['dispositions'][key[1]]={'status':disposition.currentData(),'rationale':reason.text()}
                updated_history=validate_review_history([*current,revised])
                updated=copy.deepcopy(self.session);updated['coding_review_history']=updated_history;self.store.save(updated);self.session['coding_review_history']=updated_history
            except (ValueError,TypeError,UnicodeError,sqlite3.Error,OSError,StopIteration) as exc:QMessageBox.warning(dialog,self.tr('Saved reviews'),str(exc));return
            history[:]=updated_history;choice.addItem(self.tr('Snapshot {number} · {count} recorded passes · {id}').format(number=len(history),count=len(revised['reviews']),id=revised['id'][:8]),revised['id']);choice.setCurrentIndex(choice.count()-1);self.updated.emit()
        save_revision.clicked.connect(save_revised_disposition)
        def save_project_snapshot():
            from .track_review_storage import prepare_append,apply_append
            record=next((item for item in history if item['id']==choice.currentData()),None);track_id=selected_track_id(record)
            if not files or not record or not track_id or self.job:return
            try:
                current=validate_review_history(self.session.get('coding_review_history',[]))
                if not any(item==record for item in current):raise ValueError(self.tr('The selected snapshot changed or is unavailable.'))
                secrets=[item.get('api_key','') for item in self.window.connections.values()]+[item.get('key','') for item in self.store.web_backend_specs()]
                prepared=prepare_append(files,track_id,record,secrets)
                def approve(proposal):
                    preview=QDialog(dialog);preview.setWindowTitle(self.tr('Review project change'));preview.resize(760,540);box=QVBoxLayout(preview)
                    label=QLabel(self.tr('Review the complete project file change before applying it. Findings are untrusted and this does not approve implementation.\nProject: {project}\nPath: {path}').format(project=proposal['cwd'],path=proposal['path']));label.setWordWrap(True);box.addWidget(label)
                    diff=QPlainTextEdit(proposal['diff']);diff.setObjectName('projectReviewDiff');diff.setReadOnly(True);box.addWidget(diff)
                    controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);controls.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr('Approve and apply'));controls.accepted.connect(preview.accept);controls.rejected.connect(preview.reject);box.addWidget(controls)
                    return preview.exec()==QDialog.DialogCode.Accepted
                result=apply_append(files,prepared,approve,secrets)
                if result['status']=='completed':QMessageBox.information(dialog,self.tr('Project review history'),self.tr('Saved snapshot to {path}.').format(path=result['path']))
            except (ValueError,TypeError,UnicodeError,OSError,sqlite3.Error,RecursionError) as exc:QMessageBox.warning(dialog,self.tr('Project review history'),str(exc))
        def show_project_reviews():
            record=next((item for item in history if item['id']==choice.currentData()),None);track_id=selected_track_id(record)
            if not files or not track_id:return
            self.show_project_track_reviews(track_id,dialog)
        publish.clicked.connect(save_project_snapshot);view_project.clicked.connect(show_project_reviews)
        delete=QPushButton(self.tr('Delete selected snapshot…'));delete.setObjectName('deleteSavedReview');delete.setEnabled(bool(history));layout.addWidget(delete)
        def delete_selected():
            ident=choice.currentData()
            if not ident:return
            if QMessageBox.question(dialog,self.tr('Delete review snapshot'),self.tr('Delete this saved review snapshot and its dispositions from this session? This cannot be undone.'))!=QMessageBox.StandardButton.Yes:return
            try:
                current=validate_review_history(self.session.get('coding_review_history',[]))
                if not any(record['id']==ident for record in current):raise ValueError(self.tr('The selected snapshot is no longer available.'))
                remaining=validate_review_history([record for record in current if record['id']!=ident])
                updated=copy.deepcopy(self.session);updated['coding_review_history']=remaining;self.store.save(updated);self.session['coding_review_history']=remaining
            except (ValueError,TypeError,UnicodeError,sqlite3.Error,OSError) as exc:QMessageBox.warning(dialog,self.tr('Saved reviews'),str(exc));return
            history[:]=remaining;choice.removeItem(choice.currentIndex());delete.setEnabled(bool(remaining));self.saved_reviews_button.setEnabled(bool(remaining));self.updated.emit()
            if not remaining:dialog.accept()
        delete.clicked.connect(delete_selected)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

    def receive(self,event):
        if self._closed or not self.job or event.get('run_id')!=self.run_id:return
        kind=event.get('kind')
        if kind=='independent_review_manifest':
            from .independent_review import validate_review_history
            job=self.job
            if not isinstance(job,CodingRun) or not (getattr(job,'save_progress',False) or getattr(job,'save_review_progress',False)):return
            saved=False
            try:
                reviews=event.get('reviews');snapshot_id=event.get('snapshot_id')
                if not isinstance(snapshot_id,str) or not re.fullmatch('[0-9a-f]{32}',snapshot_id):raise ValueError('Invalid review snapshot id')
                if not isinstance(reviews,list) or not 1<=len(reviews)<=3:raise ValueError('Invalid review progress manifest')
                records=[]
                for review in reviews:
                    if not isinstance(review,dict) or review.get('pass_status')!='pending':raise ValueError('Invalid review progress manifest')
                    item=copy.deepcopy(review);item['pass_status']='interrupted';item['dispositions']={};records.append(item)
                snapshot={'version':1,'id':snapshot_id,'track_id':None,'reviews':records}
                history=validate_review_history([*self.session.get('coding_review_history',[]),snapshot])
                updated=copy.deepcopy(self.session);updated['coding_review_history']=history;self.store.save(updated);self.session['coding_review_history']=history
                for review in records:self.review_progress_ids[review['id']]=snapshot_id
                self.saved_reviews_button.setEnabled(True);self.updated.emit();saved=True
            except (ValueError,TypeError,UnicodeError,sqlite3.Error,OSError,RecursionError):pass
            if not saved:self.activity.appendPlainText(self.tr('Review progress could not be saved; no reviewer requests were sent.'))
            job.acknowledge_manifest(saved);return
        if kind=='independent_review_result':
            from .independent_review import parse_structured_findings,validate_track_context,validate_review_measurements,validate_review_endpoint_identity,RUBRIC_VERSION
            review=event.get('review')
            required={'id','role','model','path','source_sha256','payload_sha256','evidence','structured','pass_status','track_context'}
            if not isinstance(review,dict) or not required<=set(review) or set(review)-required-{'measurements','reason','rubric_version','endpoint','target_payload_sha256'}:return
            if 'target_payload_sha256' in review and (not isinstance(review['target_payload_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',review['target_payload_sha256'])):return
            if 'rubric_version' in review and (type(review['rubric_version']) is not int or not 1<=review['rubric_version']<=RUBRIC_VERSION):return
            try:
                validate_track_context(review['track_context'])
                if 'endpoint' in review:validate_review_endpoint_identity(review['endpoint'])
                if 'measurements' in review:
                    if review['pass_status']!='completed':return
                    validate_review_measurements(review['measurements'])
            except (ValueError,TypeError):return
            if review['pass_status'] not in ('pending','completed','failed','cancelled','stale','skipped'):return
            if 'reason' in review and (review['pass_status'] in ('pending','completed') or not isinstance(review['reason'],str) or not 0<len(review['reason'])<=500):return
            if not isinstance(review['id'],str) or not re.fullmatch(r'[0-9a-f]{32}-[1-3]',review['id']) or review['role'] not in ('comprehension','requirements','design','repository_fit','readiness','drift'):return
            if any(not isinstance(review[key],str) or not 0<len(review[key])<=4096 for key in ('model','path')) or any(not isinstance(review[key],str) or not re.fullmatch('[0-9a-f]{64}',review[key]) for key in ('source_sha256','payload_sha256')):return
            evidence=review['evidence']
            if not isinstance(evidence,list) or len(evidence)>3:return
            if any(not isinstance(item,dict) or set(item)!={'path','sha256','payload_sha256'} or not isinstance(item['path'],str) or not 0<len(item['path'])<=512 or any(not isinstance(item[key],str) or not re.fullmatch('[0-9a-f]{64}',item[key]) for key in ('sha256','payload_sha256')) for item in evidence):return
            structured=review['structured']
            if not isinstance(structured,dict) or set(structured)!={'status','findings'} or structured['status'] not in ('valid','invalid','truncated','too_large','not_available') or not isinstance(structured['findings'],list):return
            if (review['pass_status']=='completed')==(structured['status']=='not_available'):return
            if structured['status']=='valid':
                findings=structured['findings']
                if any(not isinstance(item,dict) or item.get('id')!='finding-'+str(index) for index,item in enumerate(findings,1)):return
                raw=[{k:v for k,v in item.items() if k!='id'} for item in findings]
                if parse_structured_findings(json.dumps({'version':1,'findings':raw},ensure_ascii=False))!=structured:return
            elif structured['findings']:return
            previous=self.review_results.get(review['id'])
            if previous and (previous['pass_status']!='pending' or review['pass_status']=='pending'):return
            if len(self.review_results)>=32 and review['id'] not in self.review_results:return
            self.review_results[review['id']]=copy.deepcopy(review);self.review_results_button.setEnabled(True)
            if review['id'] in self.review_progress_ids and review['pass_status']!='pending':
                from .independent_review import validate_review_history
                try:
                    history=validate_review_history(self.session.get('coding_review_history',[]));snapshot=next(item for item in history if item['id']==self.review_progress_ids[review['id']])
                    index=next(index for index,item in enumerate(snapshot['reviews']) if item['id']==review['id'])
                    item=copy.deepcopy(review);item['dispositions']=snapshot['reviews'][index]['dispositions'];snapshot['reviews'][index]=item
                    history=validate_review_history(history);updated=copy.deepcopy(self.session);updated['coding_review_history']=history;self.store.save(updated);self.session['coding_review_history']=history;self.updated.emit()
                except (ValueError,TypeError,UnicodeError,sqlite3.Error,OSError,RecursionError,StopIteration):
                    self.cancel();self.record('output',self.tr('Review progress could not be saved. The run was stopped; the last saved snapshot may show interrupted passes.'))
            return
        if kind=='track_progress':
            from .track_execution import validate_progress,projected_plan
            try:
                selected=getattr(self.job,'selected_track',None)
                if not selected:return
                progress=validate_progress(event.get('progress'));projected_plan(selected,progress)
            except (ValueError,TypeError):return
            self.session['track_progress']=progress;self.store.save(self.session);self.updated.emit();return
        if kind=='working_notes':
            from .code_artifacts import validate_notes
            try:notes=validate_notes(event.get('notes'))
            except (ValueError,TypeError):return
            self.session['coding_working_notes']=notes;self.store.save(self.session);self.updated.emit();return
        if kind=='subagent_tools_unsupported':
            role=event.get('role')
            if role not in ('light','alternate','alternate2') or not isinstance(self.job,CodingRun):return
            original=getattr(self.job,role,None)
            try:current=self.role_connection(role)
            except ValueError:return
            fields=('url','protocol','model','api_key','reasoning','stream','context_limit','_capability_scope')
            if not original or not current or any(original.get(key)!=current.get(key) for key in fields):return
            name=self.roles[role][0].currentData();saved=self.store.config.get('connections',{}).get(name)
            if saved is not None and not saved.get('_capability_scope') and current.get('_capability_scope'):saved['_capability_scope']=current['_capability_scope']
            from .subagent_capabilities import remember
            remember(self.store.config,self.subagent_capability_connection(role,current));self.store.flush();return
        if kind in ('edit_proposal','operation_proposal'):self.approve_mcp_run.hide()
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
            from .code_agent import MCP_APPROVAL_OPERATIONS
            if operation in MCP_APPROVAL_OPERATIONS:
                self.approve_mcp_run.show();self.approve_mcp_run.setEnabled(True)
            self.advice_fingerprint=self.pending_fingerprint if operation=='run_shell' else None
            if operation=='run_shell':self.show_advice()
            else:self.advice_label.hide()
            self.diff.setPlainText(proposal.get('diff',''));self.diff.setVisible(operation in ('delete_file','git_commit','git_commit_staged','git_stage','git_unstage','subagent_file_transfer','independent_review'))
            if operation=='mcp_start':
                text=self.tr('START LOCAL MCP SERVER\nServer: {server}\nExecutable: {command}\nArguments: {arguments}\nEnvironment mappings (target: source name): {environment}\n\nThis program runs with your user permissions and inherits the app environment. Mapped values are hidden. Tool descriptions and results may be sent to the selected model.').format(server=proposal['server'],command=proposal['command'],arguments=json.dumps(proposal['arguments'],ensure_ascii=True),environment=json.dumps(proposal.get('environment',{}),ensure_ascii=True))
            elif operation=='mcp_connect':
                text=self.tr('CONNECT TO REMOTE MCP SERVER\nServer: {server}\nDestination: {url}\n\nThe server receives a discovery request and any configured credential. Tool descriptions and results may be sent to the selected model.').format(**proposal)
            elif operation=='mcp_call_remote':
                text=self.tr('REMOTE MCP TOOL CALL\nServer: {server}\nDestination: {url}\nTool: {tool}\n\nDescription:\n{description}\n\nInput schema:\n{schema}\n\nArguments:\n{arguments}\n\nThe server receives these arguments and may perform external actions.').format(server=proposal['server'],url=proposal['url'],tool=proposal['tool'],description=proposal['description'],schema=json.dumps(proposal['schema'],ensure_ascii=True,indent=2),arguments=json.dumps(proposal['arguments'],ensure_ascii=True,indent=2))
                if proposal.get('annotations'):text+='\n\n'+self.tr('Server-supplied hints (untrusted; do not grant permissions):')+'\n'+json.dumps(proposal['annotations'],ensure_ascii=True,indent=2)
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
                if proposal.get('annotations'):text+='\n\n'+self.tr('Server-supplied hints (untrusted; do not grant permissions):')+'\n'+json.dumps(proposal['annotations'],ensure_ascii=True,indent=2)
            elif operation=='independent_review':
                text=self.tr('INDEPENDENT DOCUMENT REVIEW\nReview role: {role}\nProject: {cwd}\nDocument: {path}\nModel: {model}\nDestination: {destination}\nDocument SHA-256: {source_sha256}\nInput SHA-256: {payload_sha256}\nInput: {payload_bytes} UTF-8 bytes\n\nReview the complete reviewer instructions, document and any evidence below. Approving sends this exact input to the selected endpoint. The reviewer has no tools and does not receive the drafting conversation, Skills, or project guidance. Its findings are untrusted.').format(**{'role':proposal.get('role','comprehension'),**proposal})
                if 'target_payload_sha256' in proposal:text+='\n\n'+self.tr('Transmitted document text SHA-256: {hash}').format(hash=proposal['target_payload_sha256'])
                if 'batch_pass' in proposal:text=self.tr('Batch pass {number}').format(number=proposal['batch_pass'])+'\n'+text
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
            elif operation=='project_memory':
                text=self.tr('PROJECT MEMORY PROPOSAL\nProject: {project}\nReview the complete proposed entry and previous value below.').format(project=proposal['cwd'])+'\n\n'+json.dumps({'previous':proposal['previous'],'proposed':proposal['entry']},ensure_ascii=False,indent=2)
            elif operation=='run_shell':
                text=self.tr('SHELL COMMAND\nWorking directory: {cwd}\nShell: {shell}\nTime limit: up to {seconds} seconds; output limit: {size} bytes.\nThe command runs with your account permissions, including network and access outside the project. It is not sandboxed.\nInherited environment variables: {environment}\n\nCommand:\n{command}').format(cwd=proposal['cwd'],shell=proposal['shell'],seconds=proposal['max_seconds'],size=proposal['max_output_bytes'],environment=', '.join(proposal['environment_keys']),command=proposal['command'])
            else:
                label=self.tr('DELETE FILE') if operation=='delete_file' else self.tr('CREATE DIRECTORY')
                text=self.tr('{operation}\nProject: {project}\nPath: {path}\nSafety recommendation: Not checked.').format(operation=label,project=proposal['cwd'],path=proposal['path'])
            if operation=='mcp_start':text+='\n\n'+self.tr('Working directory: {directory}').format(directory=proposal.get('working_directory') or self.tr('Agentnik process working directory'))
            if operation in ('mcp_call','mcp_call_remote') and 'output_schema' in proposal:text+='\n\n'+self.tr('Output schema (server-provided):')+'\n'+json.dumps(proposal['output_schema'],ensure_ascii=True,indent=2)
            if operation in MCP_APPROVAL_OPERATIONS:text+='\n\n'+self.tr('Allow this MCP server for this run permits all its later MCP operations, including writes and data access, without further prompts. Other servers still require approval. Permission ends when this run ends.')
            if proposal.get('purpose')=='tests':text=self.tr('TEST RUN · Report format: {format}').format(format=proposal['test_format'])+'\n'+text
            self.approval.setPlainText(text);self.approval_panel.show();self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting approval: '+operation+' '+proposal.get('path',''))
            if operation=='run_shell' and self.advice_connection:self.check_advice(proposal,self.pending_fingerprint)
        elif kind=='output':self.record(kind,event['text'])
        elif kind=='finished':
            if event['status']=='completed' and isinstance(self.job,CodingRun) and not getattr(self.job,'direct_review',False):
                secrets=[self.job.connection.get('api_key',''),(self.job.light or {}).get('api_key',''),(self.job.alternate or {}).get('api_key',''),(self.job.alternate2 or {}).get('api_key','')]
                context={'task':plain(scrub(self.job.prompt,secrets)),'answer':plain(event['text'])}
                self.session['coding_context']=context;self.session.pop('coding_compaction',None)
                self.context_view.setPlainText(self.context_text(context))
                self.use_context.setChecked(False)
            self.stop_subagents('stopped');self.session['code_state']=event['status'];self.finish();self.record(kind,event['text'])
            if event.get('usage'):self.record('usage',event['usage'])

    def decide(self,allowed,scope='once'):
        if self.advice_job:return
        accepted=self.job and self.pending_fingerprint and (self.job.decide(self.pending_fingerprint,allowed,scope) if scope!='once' else self.job.decide(self.pending_fingerprint,allowed))
        if accepted:
            decision=self.pending_fingerprint;self.approve.setEnabled(False);self.reject.setEnabled(False);self.approve_mcp_run.setEnabled(False);self.approve_mcp_run.hide();self.pending_fingerprint=None
            self.advice_fingerprint=None
            self.approval_panel.hide();self.approval.clear();self.diff.clear()
            self.session['code_state']='running';self.record('decision',('Allowed MCP server for this run' if scope=='mcp_server_run' else 'Approved' if allowed else 'Rejected')+' proposal '+decision)

    def finish(self):
        if self.advice_job:self.advice_job.cancel.set();self.advice_job=None
        self.advice_connection=None;self.advice_destination=''
        self.run_id=None;self.job=None;self.pending_fingerprint=None;self.advice_fingerprint=None
        self.approval_panel.hide()
        for button in (self.approve,self.reject,self.approve_mcp_run,self.cancel_button):button.setEnabled(False)
        self.approve_mcp_run.hide()
        self.send.setEnabled(True);self.direct_review_button.setEnabled(True)
        self.coding_context_button.setEnabled(True);self.coding_auto_compact.setEnabled(True);self.memory_button.setEnabled(True);self.notes_button.setEnabled(True);self.light_enabled.setEnabled(True);self.save_review_progress.setEnabled(True);self.web_enabled.setEnabled(True);self.limits_button.setEnabled(True);self.search_settings.setEnabled(True);self.advice_enabled.setEnabled(True);self.mcp_choice.setEnabled(True);self.mcp_refresh.setEnabled(True);self.mcp_extra_button.setEnabled(True)
        self.use_context.setEnabled(bool(self.session.get('coding_context')))
        for connection,model in self.roles.values():connection.setEnabled(True);model.setEnabled(True)

    def cancel(self):
        if not self.job:return
        if getattr(self,'_drafting_active',False):
            if self._drafting_cancel_callback:self._drafting_cancel_callback()
            return
        if getattr(self,'_compaction_active',False):
            self.job.cancel.set();self._compaction_active=False;self._compaction_token=None;self.composer.setReadOnly(False);self.finish();self.record('output','Coding context compaction cancelled.');return
        self.job.stop()
        for bridge in getattr(self.job,'mcp_bridges',[]):bridge.close()
        self.stop_subagents('cancelled');self.session['code_state']='cancelled';self.finish()
        self.record('cancelled','Run cancelled. No further tool work will be scheduled; project changes already applied are retained.')
