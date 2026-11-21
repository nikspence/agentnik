"""Repository picker and Agentnik-owned coding pane."""
from pathlib import Path
import json
import os
import copy
import re
import sqlite3
import threading
import uuid
import time
from datetime import datetime
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
from .code_limits import FIELDS,coding_limits,GOAL_FIELDS,goal_limits
from .selection_scroll import SelectionScroll
from .web import public_url
from . import core,routing
from .research_ui import SearchBackends
from .search_providers import SEARCH_KINDS,SEARCH_PROVIDERS


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
    def __init__(self,parent,values,goal_values=None):
        super().__init__(parent);self.setWindowTitle(self.tr('Coding run limits'))
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form);self.fields={}
        labels={'rounds':self.tr('Tool rounds'),'requests':self.tr('Model requests'),'calls':self.tr('Tool calls'),'turn_seconds':self.tr('Run or goal step time (seconds)'),'model_seconds':self.tr('Model call timeout (seconds)'),'context_bytes':self.tr('Retained context (bytes)')}
        for key,(_,minimum,maximum) in FIELDS.items():
            box=QSpinBox();box.setRange(minimum,maximum);box.setValue(coding_limits(values)[key]);form.addRow(labels[key],box);self.fields[key]=box
        self.goal_fields={}
        for key,label in (('steps',self.tr('Goal steps')),('seconds',self.tr('Goal active time (seconds)'))):
            box=QSpinBox();box.setRange(GOAL_FIELDS[key][1],GOAL_FIELDS[key][2]);box.setSpecialValueText(self.tr('Unlimited'));box.setValue(goal_limits(goal_values)[key]);form.addRow(label,box);self.goal_fields[key]=box
        hint=QLabel(self.tr('Run limits are shared by the model, subagents, and web research. In goal mode they reset for each step; the separate goal limits cover the current run. Continuing a stopped goal starts fresh limits.')+'\n'+self.tr('The model timeout covers waiting for the first token and the complete response. The run, step, or goal time limit can end a request sooner.'));hint.setWordWrap(True);layout.addWidget(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.reset);layout.addWidget(buttons)

    def reset(self):
        for key,value in coding_limits().items():self.fields[key].setValue(value)
        for key,value in goal_limits().items():self.goal_fields[key].setValue(value)

    def values(self):return coding_limits({key:box.value() for key,box in self.fields.items()})
    def goal_values(self):return goal_limits({key:box.value() for key,box in self.goal_fields.items()})




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
        self._draft_search_signature=None;self._draft_search_secrets=[];self.refresh_draft_search_secrets()
        self.events=CodeEvents(self);self.events.event.connect(self.receive)
        self.goal_checkpoint_timer=QTimer(self);self.goal_checkpoint_timer.setInterval(2000);self.goal_checkpoint_timer.timeout.connect(self.checkpoint_goal_progress)
        if session.get("code_state") in ("running","awaiting_approval"):
            session["code_state"]="interrupted"
            if session.get('coding_last_run_goal',True) and session.get('coding_goal',{}).get('status')=='active':session['coding_goal']['status']='interrupted'
            for item in session.get("coding_subagents",[]):
                if item["status"] in ("queued","running"):item["status"]="interrupted"
            append_code_activity(session,'interrupted','Interrupted coding run; nothing resumes automatically.')
            self.store.save(session)
        layout=QVBoxLayout(self)
        header=QHBoxLayout();layout.addLayout(header)
        title=QLabel(session['project_name']);title.setTextFormat(Qt.TextFormat.PlainText);header.addWidget(title)
        path=QLabel(self.tr('Working directory snapshot: {path}').format(path=session['path_snapshot']));path.setTextFormat(Qt.TextFormat.PlainText);path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);path.setToolTip(session['path_snapshot']);header.addWidget(path,1)
        self.track_selection_label=QLabel();self.track_selection_label.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.track_selection_label);self.refresh_selected_track()
        goal_row=QHBoxLayout();layout.addLayout(goal_row)
        self.goal_status_label=QLabel();self.goal_status_label.setObjectName('goalStatus');self.goal_status_label.setTextFormat(Qt.TextFormat.PlainText);self.goal_status_label.setWordWrap(True);goal_row.addWidget(self.goal_status_label,1)
        self.goal_details_button=QPushButton(self.tr('Goal details…'));self.goal_details_button.setObjectName('goalDetails');self.goal_details_button.clicked.connect(self.show_goal_details);goal_row.addWidget(self.goal_details_button);self.refresh_goal_status()
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
        self.saved_reviews_button=QPushButton(self.tr('Saved review snapshots…'));self.saved_reviews_button.setEnabled(bool(session.get('coding_review_history')));self.saved_reviews_button.clicked.connect(self.show_saved_reviews);layout.addWidget(self.saved_reviews_button)
        activity_options=QHBoxLayout();layout.addLayout(activity_options)
        self.show_thinking=QCheckBox(self.tr('Show model thinking'));self.show_thinking.setToolTip(self.tr('Show and save thinking returned by the model in coding activity. Applies to the next run; not all providers expose thinking.'));self.show_thinking.setChecked(session.get('coding_show_thinking',False));self.show_thinking.toggled.connect(self.save_show_thinking);activity_options.addWidget(self.show_thinking);activity_options.addStretch()
        self.activity=QPlainTextEdit('\n'.join(self.activity_text(e) for e in session.get('code_activity',[])));self.activity.setPlaceholderText(self.tr('No commands have been run.'));self.activity.setReadOnly(True);layout.addWidget(self.activity,1);self._activity_selection_scroll=SelectionScroll(self.activity)
        self.activity.moveCursor(QTextCursor.MoveOperation.End)
        self._activity_revision=0;self._activity_initial_follow=True;self.activity.verticalScrollBar().actionTriggered.connect(self.activity_scrolled)
        QTimer.singleShot(0,self.finish_activity_open)
        composer_row=QHBoxLayout();layout.addLayout(composer_row)
        history_buttons=QVBoxLayout();composer_row.addLayout(history_buttons)
        self.history_up=QPushButton('↑');self.history_up.setAccessibleName(self.tr('Previous coding prompt'));self.history_up.setToolTip(self.tr('Previous coding prompt'));history_buttons.addWidget(self.history_up)
        self.history_down=QPushButton('↓');self.history_down.setAccessibleName(self.tr('Next coding prompt'));self.history_down.setToolTip(self.tr('Next coding prompt'));history_buttons.addWidget(self.history_down)
        self.composer=CodingComposer(session.get('draft',''));self.composer.setPlaceholderText(self.tr('Describe the coding task; repository files may be sent to the selected models'));self.composer.setMaximumHeight(90);composer_row.addWidget(self.composer,1)
        steering_row=QHBoxLayout();layout.addLayout(steering_row)
        self.steering_input=QLineEdit();self.steering_input.setMaxLength(16000);self.steering_input.setText(session.get('coding_steering_draft',''));self.steering_input.setPlaceholderText(self.tr('Steer the active coding run'));self.steering_input.setEnabled(False);self.steering_input.textChanged.connect(self.save_steering_draft);steering_row.addWidget(self.steering_input,1)
        self.steering_button=QPushButton(self.tr('Send steering'));self.steering_button.setEnabled(False);self.steering_button.clicked.connect(self.send_steering);self.steering_input.returnPressed.connect(self.send_steering);steering_row.addWidget(self.steering_button)
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
        self.use_context=QCheckBox(self.tr('Send previous context'));self.use_context.setToolTip(self.tr('Send the previous task and answer with the next run, up to 2,048 characters each.'));self.use_context.setEnabled(bool(context))
        self.coding_context_button=QPushButton(self.tr('Coding context…'));self.coding_context_button.clicked.connect(self.edit_coding_context)
        self.coding_auto_compact=QCheckBox(self.tr('Auto compact context'),self);self.coding_auto_compact.setToolTip(self.tr('Before a follow-up run, summarize a long previous task and answer using the selected model. This uses an additional model request.'));self.coding_auto_compact.setChecked(session.get('coding_auto_compact',True));self.coding_auto_compact.toggled.connect(self.save_coding_auto_compact);self.coding_auto_compact.hide()
        self.roles={}
        bindings=dict(session.get('coding_models',{}));saved=bindings.get('model',bindings.get('heavy',{}))
        model_row=QHBoxLayout();layout.insertLayout(1,model_row);model_row.addWidget(QLabel(self.tr('Model')))
        connection=QComboBox();connection.setObjectName('codeModelConnection');connection.addItem(self.tr('Not configured'),'')
        for name in window.connections:connection.addItem(name,name)
        model=QLineEdit();model.setObjectName('codeModelAlias');model.setPlaceholderText(self.tr('Model alias (any supported coding model)'))
        missing=saved.get('connection','')
        if missing and connection.findData(missing)<0:connection.addItem(missing+' (unavailable)',missing)
        connection.setCurrentIndex(max(0,connection.findData(saved.get('connection',''))));model.setText(saved.get('model',''))
        model_row.addWidget(connection);model_row.addWidget(model,1);self.roles['heavy']=(connection,model)
        choose=QPushButton(self.tr('Choose model…'));choose.clicked.connect(lambda:self.choose_model('heavy'));model_row.addWidget(choose)
        connection.currentIndexChanged.connect(lambda _:self.role_changed('heavy'));model.editingFinished.connect(self.save_models)
        self.skills_button=QPushButton();self.skills_button.clicked.connect(self.choose_skills);self.refresh_skills_button()
        self.tracks_button=QPushButton(self.tr('Spec & Plan…'));self.tracks_button.clicked.connect(self.show_tracks)
        more_options=QHBoxLayout();layout.addLayout(more_options)
        self.memory_button=QPushButton(self.tr('Project memory…'));self.memory_button.clicked.connect(self.edit_project_memory);more_options.addWidget(self.memory_button)
        self.notes_button=QPushButton(self.tr('Working notes…'));self.notes_button.clicked.connect(self.edit_working_notes);more_options.addWidget(self.notes_button)
        self.skills_history_button=QPushButton(self.tr('Skill history…'));self.skills_history_button.clicked.connect(self.show_skills_history);more_options.addWidget(self.skills_history_button)
        preferences=QHBoxLayout();layout.addLayout(preferences);preferences.addWidget(self.use_context)
        self.goal_enabled=QCheckBox(self.tr('Pursue as goal'));self.goal_enabled.setToolTip(self.tr('Keep taking the next step until the objective is complete, blocked, stopped, or a run limit is reached.'));self.goal_enabled.setChecked(session.get('coding_last_run_goal',True) and session.get('coding_goal',{}).get('status') in ('active','limited','paused','blocked','interrupted','failed'));preferences.addWidget(self.goal_enabled)
        self.shell_auto=QCheckBox(self.tr('Run shell commands without approval'));self.shell_auto.setToolTip(self.tr('Shell and test commands run with your account permissions, including network access and files outside the project. This setting can be changed during a run.'));preferences.addWidget(self.shell_auto);self.shell_auto.toggled.connect(self.change_shell_approval)
        self.web_enabled=window.web_search;preferences.addStretch()
        mcp_row=QHBoxLayout();layout.addLayout(mcp_row);mcp_row.addWidget(QLabel(self.tr('MCP server for this run:')))
        self.mcp_choice=QComboBox();self.mcp_choice.setToolTip(self.tr('Optional MCP server for this run. MCP operations run without approval and may write data or perform other actions; tool results go to the selected model.'));mcp_row.addWidget(self.mcp_choice,1)
        saved_mcp=session.get('coding_mcp_selection',{});self.mcp_primary_ref=saved_mcp.get('primary');self.mcp_extra_refs=list(saved_mcp.get('extra',[]));self.mcp_extra=[ref['name'] for ref in self.mcp_extra_refs]
        self.mcp_extra_button=QPushButton(self.tr('Additional servers…'));self.mcp_extra_button.clicked.connect(self.choose_additional_mcp);mcp_row.addWidget(self.mcp_extra_button)
        self.mcp_refresh=QPushButton(self.tr('Refresh MCP'));self.mcp_refresh.clicked.connect(self.refresh_mcp_servers);mcp_row.addWidget(self.mcp_refresh);self.refresh_mcp_servers();self.mcp_choice.currentIndexChanged.connect(self.mcp_primary_changed)
        more_options.addStretch();more_options.addWidget(self.coding_context_button);more_options.addWidget(self.skills_button);more_options.addWidget(self.tracks_button)
        self.sources_button=QPushButton();self.sources_button.clicked.connect(self.show_sources)
        run_row=QHBoxLayout();layout.addLayout(run_row)
        self.send=QPushButton(self.tr('Run'));self.send.clicked.connect(self.start_coding);run_row.addWidget(self.send)
        self.continue_button=QPushButton(self.tr('Continue'));self.continue_button.setObjectName('continueCodingRun');self.continue_button.setToolTip(self.tr('Start a fresh run using the saved task and recent activity. Review project state before repeating unfinished operations.'));self.continue_button.clicked.connect(self.continue_coding);run_row.addWidget(self.continue_button)
        self.continue_button.setEnabled(self.can_continue())
        self.cancel_button=QPushButton(self.tr('Cancel'));self.cancel_button.setEnabled(False);self.cancel_button.clicked.connect(self.cancel);run_row.addWidget(self.cancel_button)
        self.pause_goal_button=QPushButton(self.tr('Pause goal'));self.pause_goal_button.setEnabled(False);self.pause_goal_button.clicked.connect(self.pause_goal);run_row.addWidget(self.pause_goal_button)
        run_row.addWidget(self.sources_button);self.update_sources_button()
        self.approval_panel=QWidget();review=QVBoxLayout(self.approval_panel);layout.addWidget(self.approval_panel);self.approval_panel.hide()
        self.approval=QPlainTextEdit();self.approval.setReadOnly(True);self.approval.setPlaceholderText(self.tr('Command approval preview'));review.addWidget(self.approval)
        self.git_auth_row=QWidget();git_auth_layout=QVBoxLayout(self.git_auth_row);git_auth_layout.setContentsMargins(0,0,0,0);git_auth=QHBoxLayout();git_auth_layout.addLayout(git_auth)
        git_auth.addWidget(QLabel(self.tr('Git username')));self.git_username=QLineEdit();self.git_username.setAccessibleName(self.tr('Git username'));git_auth.addWidget(self.git_username)
        git_auth.addWidget(QLabel(self.tr('Token')));self.git_token=QLineEdit();self.git_token.setAccessibleName(self.tr('Git access token'));self.git_token.setEchoMode(QLineEdit.EchoMode.Password);git_auth.addWidget(self.git_token)
        git_saved=QHBoxLayout();git_auth_layout.addLayout(git_saved)
        self.git_remember_token=QCheckBox(self.tr('Save token in OS credential store'));git_saved.addWidget(self.git_remember_token)
        self.git_load_token=QPushButton(self.tr('Use saved token'));self.git_load_token.clicked.connect(self.load_git_token);git_saved.addWidget(self.git_load_token)
        self.git_forget_token=QPushButton(self.tr('Forget saved token'));self.git_forget_token.clicked.connect(self.forget_git_token);git_saved.addWidget(self.git_forget_token);git_saved.addStretch()
        self.git_auth_row.setToolTip(self.tr('Optional HTTPS Basic authentication. Tokens are saved only if selected, and are not sent to the model.'));review.addWidget(self.git_auth_row);self.git_auth_row.hide();self._git_auth_pending=False;self._git_auth_url=''
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
            if item['status'] in ('queued','running'):self.subagent_choice.addItem(item['text'].replace('\n',' ')[:80],item['id'])
        index=self.subagent_choice.findData(selected)
        if index>=0:self.subagent_choice.setCurrentIndex(index)
        self.subagent_choice.blockSignals(False);self.stop_subagent_button.setEnabled(bool(self.job) and self.subagent_choice.count()>0)
        running=sum(item['status']=='running' for item in items)
        queued=sum(item['status']=='queued' for item in items)
        self.subagents_toggle.setText(self.tr('Subagents · {count} total · {running} running · {queued} queued').format(count=len(items),running=running,queued=queued))
        labels={'queued':self.tr('Queued'),'running':self.tr('Running'),'completed':self.tr('Completed'),'failed':self.tr('Failed'),'cancelled':self.tr('Cancelled'),'interrupted':self.tr('Interrupted'),'stopped':self.tr('Stopped')}
        self.subagents_view.setMaximumHeight(min(135,max(45,self.subagents_view.fontMetrics().lineSpacing()*min(8,2*len(items)+1)+10)))
        self.subagents_view.setPlainText('\n\n'.join(labels[item['status']]+' · '+item['text'] for item in items))

    def cancel_selected_subagent(self):
        ident=self.subagent_choice.currentData()
        if not isinstance(self.job,CodingRun) or not ident or not self.job.cancel_subagent(ident):return
        item=next((item for item in self.session.get('coding_subagents',[]) if item['id']==ident),None)
        if item and item['status'] in ('queued','running'):item['status']='cancelled'
        self.refresh_subagents();self.record('cancelled',self.tr('Subagent cancellation requested: {id}').format(id=ident))

    def stop_subagents(self,status):
        for item in self.session.get('coding_subagents',[]):
            if item['status'] in ('queued','running'):item['status']=status
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
            title={'heavy':self.tr('Choose model'),'decision':self.tr('Choose Decision model')}[role]
            model,ok=QInputDialog.getItem(self,title,self.tr('Model alias:'),choices,0,True)
            if ok:self.roles[role][1].setText(model);self.save_models()
        def failed(_):
            self.model_jobs.pop(role,None)
            if not self._closed:QMessageBox.warning(self,self.tr('Coding models'),self.tr('Model listing failed. You can enter an alias manually.'))
        self.model_jobs[role]=Job(lambda *_:core.models(c),done,failed)

    def save_coding_auto_compact(self,enabled):
        self.session['coding_auto_compact']=bool(enabled);self.store.save(self.session);self.updated.emit()

    def save_show_thinking(self,enabled):
        self.session['coding_show_thinking']=bool(enabled);self.store.save(self.session);self.updated.emit()

    def edit_coding_context(self):
        if self.job:return
        from .context_compaction import coding_snapshot,coding_effective_context
        context=self.session.get('coding_context');snapshot=self.session.get('coding_compaction')
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Coding context'));dialog.resize(700,520)
        layout=QVBoxLayout(dialog);hint=QLabel(self.tr('The previous task and answer are retained separately. A summary replaces them only when you enable previous context for a future run. Compaction uses the selected model and may omit details.'));hint.setWordWrap(True);layout.addWidget(hint)
        layout.addWidget(self.coding_auto_compact);self.coding_auto_compact.show()
        layout.addWidget(QLabel(self.tr('Previous task and answer (JSON):')))
        original=QPlainTextEdit(json.dumps(context or {'task':'','answer':''},ensure_ascii=False,indent=2));layout.addWidget(original)
        layout.addWidget(QLabel(self.tr('Compacted summary:')))
        summary=QPlainTextEdit(snapshot['summary'] if snapshot else '');layout.addWidget(summary)
        resume=self.session.get('coding_resume');resume_editor=None;steering_editor=None;steering_saved=None
        state=self.session.get('code_state')
        if self.session.get('coding_last_run_goal',True) and self.session.get('coding_goal',{}).get('status')==state and state in ('paused','blocked','interrupted','failed') and not self.session.get('coding_resume_reviewed'):
            resume=self.build_goal_resume()
        if resume and state in ('limited','paused','blocked','interrupted','failed'):
            layout.addWidget(QLabel(self.tr('Continue task and evidence (JSON; original attachments are also sent):')))
            resume_editor=QPlainTextEdit(json.dumps({key:resume[key] for key in ('task','evidence')},ensure_ascii=False,indent=2));resume_editor.setObjectName('continuationContext');layout.addWidget(resume_editor)
            steering_saved=self.session.get('coding_continuation_steering')
            if steering_saved is None:
                legacy=self.continuation_steering(self.draft_secrets());header='Delivered steering for this task:\n';legacy=legacy[len(header):] if legacy.startswith(header) else legacy
                marker='[Earlier delivered steering omitted due to the size limit.]\n';omitted=legacy.startswith(marker)
                if omitted:legacy=legacy[len(marker):]
                steering_saved={'text':legacy[-14000:],'omitted':omitted or len(legacy)>14000}
            label=QLabel(self.tr('Retained steering for future continuations (review the evidence above too):'));label.setWordWrap(True);layout.addWidget(label)
            steering_editor=QPlainTextEdit(steering_saved['text']);steering_editor.setObjectName('continuationSteering');layout.addWidget(steering_editor)
        row=QHBoxLayout();layout.addLayout(row)
        save=QPushButton(self.tr('Save context'));reset=QPushButton(self.tr('Use original context'));compact=QPushButton(self.tr('Compact now'))
        for control in (save,reset,compact):row.addWidget(control)
        save.setEnabled(bool(context) or bool(resume_editor));compact.setEnabled(bool(context))
        def save_context():
            try:
                secrets=self.draft_secrets();value=scrub(json.loads(original.toPlainText()),secrets)
                from .context_compaction import coding_digest
                coding_digest(value);text=scrub(summary.toPlainText().strip(),secrets);new_snapshot=coding_snapshot(value,text) if text else None
                if resume_editor:
                    resume_value=scrub(json.loads(resume_editor.toPlainText()),secrets)
                    if not isinstance(resume_value,dict) or set(resume_value)!={'task','evidence'} or not isinstance(resume_value['task'],str) or len(resume_value['task'])>16000 or not isinstance(resume_value['evidence'],str) or len(resume_value['evidence'])>24000:raise ValueError('Invalid continuation task or evidence')
                    if self.session.get('coding_last_run_goal',True) and self.session.get('coding_goal') and not resume_value['task'].strip():raise ValueError(self.tr('A goal objective cannot be empty.'))
                if steering_editor:
                    steering_value=scrub(steering_editor.toPlainText(),secrets)
                    if len(steering_value)>14000:raise ValueError(self.tr('Retained steering must be at most 14,000 characters.'))
                    if steering_value and steering_value!=steering_saved['text']:
                        resume_value['evidence']=self.bounded_continuation_evidence('\n'.join(filter(None,[resume_value['evidence'],'User-reviewed retained steering:\n'+steering_value])))
            except (ValueError,TypeError) as exc:QMessageBox.warning(dialog,self.tr('Coding context'),str(exc));return
            self.session['coding_context']=value
            if resume_editor:self.session['coding_resume']={**resume,**resume_value};self.session['coding_resume_reviewed']=True
            if steering_editor:self.session['coding_continuation_steering']={'text':steering_value,'omitted':steering_saved['omitted'] if steering_value==steering_saved['text'] else False}
            if new_snapshot:self.session['coding_compaction']=new_snapshot
            else:self.session.pop('coding_compaction',None)
            self.use_context.setEnabled(True);self.store.save(self.session);self.updated.emit();dialog.accept()
        def restore():summary.clear()
        def compact_now():
            if original.toPlainText()!=json.dumps(context or {'task':'','answer':''},ensure_ascii=False,indent=2):
                QMessageBox.information(dialog,self.tr('Coding context'),self.tr('Save your edits before compacting.'));return
            dialog.accept();self.compact_coding_context()
        save.clicked.connect(save_context);reset.clicked.connect(restore);compact.clicked.connect(compact_now)
        try:dialog.exec()
        finally:self.coding_auto_compact.setParent(self);self.coding_auto_compact.hide()

    def compact_coding_context(self,auto_start=False,connection=None):
        from .context_compaction import coding_summary_input,coding_snapshot,coding_digest
        from .ui import Job
        if self.job or self._closed:return
        try:
            context=dict(self.session.get('coding_context') or {})
            connection=connection or self.role_connection('heavy')
            if not connection or not connection.get('model'):raise ValueError(self.tr('Choose a model first.'))
            inputs=coding_summary_input(context);body=core.chat_body(connection,inputs)
        except (ValueError,OSError) as exc:QMessageBox.warning(self,self.tr('Coding context'),str(exc));return
        token=uuid.uuid4().hex;self._compaction_token=token;self._compaction_active=True
        self.send.setEnabled(False);self.cancel_button.setEnabled(True);self.coding_context_button.setEnabled(False);self.coding_auto_compact.setEnabled(False);self.memory_button.setEnabled(False);self.notes_button.setEnabled(False);self.composer.setReadOnly(True)
        self.mcp_choice.setEnabled(False);self.mcp_refresh.setEnabled(False);self.mcp_extra_button.setEnabled(False);self.use_context.setEnabled(False)
        for choice,model in self.roles.values():choice.setEnabled(False);model.setEnabled(False)
        self.record('output','Compacting previous coding context before a run; the selected model receives the previous task and answer.')
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
        bindings=dict(self.session.get('coding_models',{}))
        widgets=self.roles['heavy'];bindings['model']={'connection':widgets[0].currentData(),'model':widgets[1].text().strip()};self.session['coding_models']=bindings
        self.store.save(self.session)

    def change_shell_approval(self,enabled):
        if isinstance(self.job,CodingRun):
            self.job.set_shell_without_approval(enabled)
            self.record('output',self.tr('Shell commands without approval: {state}').format(state=self.tr('on') if enabled else self.tr('off')))

    def refresh_draft_search_secrets(self):
        environment=[os.environ.get(variable,'') for _,variable,_ in SEARCH_PROVIDERS.values() if variable]
        signature=json.dumps([self.store.config.get('web_backends',[]),environment],sort_keys=True)
        if signature!=self._draft_search_signature:
            self._draft_search_secrets=[item.get('key','') for item in self.store.web_backend_specs()];self._draft_search_signature=signature

    def draft_secrets(self):
        self.refresh_draft_search_secrets()
        secrets=[connection.get('api_key','') for connection in self.window.connections.values()]
        secrets.extend(self._draft_search_secrets)
        for server in self.store.config.get('mcp_servers',[]):
            mapping=server.get('env',{})
            if isinstance(mapping,dict):secrets.extend(os.environ.get(name,'') for name in mapping.values() if isinstance(name,str))
        if self.job is not None and isinstance(self.job,CodingRun):
            secrets.extend([self.job.connection.get('api_key','')]+[item.get('key','') for item in self.job.web_backends])
            for bridge in self.job.mcp_bridges:secrets.extend(getattr(bridge,'environment_values',{}).values())
        return list(dict.fromkeys(secret for secret in secrets if isinstance(secret,str) and secret))

    def save_steering_draft(self,text):
        secrets=self.draft_secrets()
        self.session['coding_steering_draft']=scrub(text,secrets);self.store.save(self.session);self.updated.emit()

    def send_steering(self):
        job=self.job;text=self.steering_input.text()
        if not isinstance(job,CodingRun) or not text.strip():return
        secrets=self.draft_secrets()
        message=scrub(text.strip(),secrets)
        if not job.steer(message):
            self.record('output',self.tr('Steering was not queued; the run may have ended or the message may exceed the limit.'));return
        self.steering_input.clear();self.record_steering(self.tr('Steering queued: '),message)
        if self.pending_fingerprint:
            self.pending_fingerprint=None;self.advice_fingerprint=None
            if self.advice_job:self.advice_job.cancel.set();self.advice_job=None
            self.approval_panel.hide();self.approval.clear();self.diff.clear();self.session['code_state']='running'
            self.record('decision',self.tr('Pending approval invalidated by steering.'))

    def record_steering(self,prefix,message,delivered=False):
        # Activity entries are bounded to 2,048 characters; preserve the full message.
        if delivered:
            previous=self.session.get('coding_continuation_steering',{'text':'','omitted':False})
            text='\n'.join(filter(None,[previous['text'],message]));self.session['coding_continuation_steering']={'text':text[-14000:],'omitted':previous['omitted'] or len(text)>14000}
        for offset in range(0,len(message),1800):self.record('steering_delivered' if delivered else 'steering',prefix+message[offset:offset+1800])

    def continuation_activity(self):
        activity=self.session.get('code_activity',[]);start=next((i for i in range(len(activity)-1,-1,-1) if activity[i].get('kind')=='started'),0)
        prefixes=('Steering delivered: ',self.tr('Steering delivered: '))
        return '\n'.join(item.get('text','') for item in activity[start:] if item.get('kind') in ('output','approval','decision','finished','steering_delivered') or (item.get('kind')=='steering' and item.get('text','').startswith(prefixes)))

    def continuation_steering(self,secrets):
        saved=self.session.get('coding_continuation_steering')
        if saved is None:
            activity=self.session.get('code_activity',[]);start=next((i for i in range(len(activity)-1,-1,-1) if activity[i].get('kind')=='started'),0)
            prefixes=('Steering delivered: ',self.tr('Steering delivered: '))
            text='\n'.join(item.get('text','') for item in activity[start:] if item.get('kind')=='steering_delivered' or (item.get('kind')=='steering' and item.get('text','').startswith(prefixes)))
            saved={'text':text[-14000:],'omitted':len(text)>14000}
        text=scrub(saved['text'],secrets)
        if not text:return ''
        marker='[Earlier delivered steering omitted due to the size limit.]\n'
        if len(text)>14000:text=text[-14000:];saved={'omitted':True}
        if saved['omitted']:text=marker+text
        return 'Delivered steering for this task:\n'+text

    def continuation_snapshot(self,secrets):
        sources=scrub(copy.deepcopy(self.session.get('coding_sources',[])),secrets)
        plan=scrub(copy.deepcopy(self.session.get('coding_plan')),secrets);omitted=0
        while True:
            snapshot=json.dumps({'plan':plan,'sources':sources,'sources_omitted':omitted},ensure_ascii=False)
            if len(snapshot)<=8000:return snapshot
            if not sources:return json.dumps({'plan':None,'plan_omitted':True,'sources':[],'sources_omitted':omitted})
            sources.pop(0);omitted+=1

    @staticmethod
    def bounded_continuation_evidence(text):
        marker='[Earlier continuation evidence omitted due to the size limit.]\n'
        return text if len(text)<=24000 else marker+text[-(24000-len(marker)):]

    def configure_limits(self):
        if self.job:return
        settings=self.store.config['settings'];dialog=CodingLimitsDialog(self,coding_limits(settings.get('coding_limits')),settings.get('coding_goal_limits'))
        if dialog.exec()==QDialog.DialogCode.Accepted:
            settings['coding_limits']=dialog.values();settings['coding_goal_limits']=dialog.goal_values();self.store.flush()

    def configure_search(self):
        if not self.job:
            SearchBackends(self,self.store).exec();self.refresh_draft_search_secrets()

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
            raise ValueError({'heavy':self.tr('Choose a connection and model alias.'),'decision':self.tr('Choose a connection and model alias for Decision.')}[role])
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
        original_snapshots=copy.deepcopy(sidecar['snapshots'])
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
        export=QPushButton(self.tr('Export snapshot…'));export.setObjectName('exportProjectReview');export.setEnabled(bool(original_snapshots));box.addWidget(export)
        def export_snapshot():
            record=next((item for item in original_snapshots if item['id']==selection.currentData()),None)
            if not record:return
            def still_current():
                return any(item==record for item in read_sidecar(files,track_id)['snapshots'])
            self.export_review_snapshot(record,preview,still_current)
        export.clicked.connect(export_snapshot)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);controls.rejected.connect(preview.reject);box.addWidget(controls);preview.exec()

    def export_review_snapshot(self,record,parent,still_current):
        from .review_export import prepare_review_export,write_new_review_export
        def known_secrets():return [item.get('api_key','') for item in self.window.connections.values()]+[item.get('key','') for item in self.store.web_backend_specs()]
        try:
            if not still_current():raise ValueError(self.tr('The selected snapshot changed or is unavailable.'))
            content=prepare_review_export(record,known_secrets())
            preview=QDialog(parent);preview.setWindowTitle(self.tr('Export review snapshot'));preview.resize(760,540);box=QVBoxLayout(preview)
            label=QLabel(self.tr('Review the complete export before saving. Findings, paths and dispositions may contain sensitive information. Known configured credentials are blocked, but other secrets may remain. A new file will be created; existing files are not replaced.'));label.setWordWrap(True);box.addWidget(label)
            text=QPlainTextEdit(content);text.setObjectName('reviewExportPreview');text.setReadOnly(True);box.addWidget(text)
            controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);controls.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr('Choose export file'));controls.accepted.connect(preview.accept);controls.rejected.connect(preview.reject);box.addWidget(controls)
            if preview.exec()!=QDialog.DialogCode.Accepted:return
            path,_=QFileDialog.getSaveFileName(parent,self.tr('Export review snapshot'),'review-snapshot.json',self.tr('JSON files (*.json)'))
            if not path:return
            if not still_current() or prepare_review_export(record,known_secrets())!=content:raise ValueError(self.tr('The selected snapshot or configured credentials changed; review the export again.'))
            write_new_review_export(path,content)
            QMessageBox.information(parent,self.tr('Export review snapshot'),self.tr('Review snapshot exported.'))
        except (ValueError,TypeError,UnicodeError,OSError,sqlite3.Error,RecursionError) as exc:QMessageBox.warning(parent,self.tr('Export review snapshot'),str(exc))

    def review_selected_track(self,track,connection,prompt):
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Review track run'));dialog.resize(800,600);layout=QVBoxLayout(dialog)
        label=QLabel(self.tr('Review the task and track data to be sent to {model} at {endpoint}. Track data is untrusted. Progress is model-reported and is not written to track files. Direct file tools cannot modify agentnik-plans during this run; shell commands and MCP retain their existing permissions.').format(model=connection['model'],endpoint=core.endpoint(connection,'chat')));label.setWordWrap(True);layout.addWidget(label)
        view=QPlainTextEdit(self.tr('User task:')+'\n'+prompt+'\n\n'+self.tr('Selected track data:')+'\n'+track['context']);view.setReadOnly(True);layout.addWidget(view)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr('Start coding run'));buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        return dialog.exec()==QDialog.DialogCode.Accepted

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
            row=QHBoxLayout();rows.addLayout(row);status=QComboBox()
            for label,value in ((self.tr('pending'),'pending'),(self.tr('in_progress'),'in_progress'),(self.tr('completed'),'completed'),(self.tr('blocked'),'blocked')):status.addItem(label,value)
            status.setCurrentIndex(status.findData(task['status']));status.setAccessibleName(self.tr('Status for {id}').format(id=task['id']));row.addWidget(status)
            result=QComboBox();result.addItem(self.tr('Keep existing evidence'),None)
            for value in ('passed','failed','unknown','not_run'):result.addItem(self.tr('Replace evidence: {status}').format(status=value),value)
            result.setAccessibleName(self.tr('Evidence for {id}').format(id=task['id']));row.addWidget(result);detail=QLineEdit();detail.setPlaceholderText(self.tr('Evidence description'));row.addWidget(detail,1);controls.append((task['id'],status,result,detail))
        rows.addStretch();actions=QHBoxLayout();layout.addLayout(actions);review_button=QPushButton(self.tr('Review status changes…'));actions.addWidget(review_button);close=QPushButton(self.tr('Close'));actions.addWidget(close);close.clicked.connect(dialog.reject)
        def review():
            try:
                choices=[{'id':ident,'status':status.currentData(),'evidence':([{'status':result.currentData(),'detail':detail.text()}] if result.currentData() is not None else None)} for ident,status,result,detail in controls]
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
        ask_button=QPushButton(self.tr('Ask model…'));save_button=QPushButton(self.tr('Save draft'));publish_button=QPushButton(self.tr('Review and publish…'));close_button=QPushButton(self.tr('Close'))
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
                if not connection:raise ValueError(self.tr('Choose a model first.'))
                if initial['created_dirs'] or initial['written']:raise ValueError(self.tr('A partially published draft cannot be regenerated.'))
                history=validate_history(self.session.get('track_draft_conversation',[]));secrets=known_secrets()
                endpoint=core.endpoint(connection,'chat')
            except (ValueError,TypeError,OSError) as exc:QMessageBox.warning(dialog,self.tr('Draft with model'),str(exc));return
            ai=QDialog(dialog);ai.setWindowTitle(self.tr('Draft with model'));ai.resize(720,560);box=QVBoxLayout(ai)
            info=QLabel(self.tr('Model: {model}\nEndpoint: {endpoint}\nYour requirements, displayed conversation, and current draft are sent. No project files or tools are automatically supplied. Model output is untrusted and must be reviewed.').format(model=connection['model'],endpoint=endpoint));info.setWordWrap(True);box.addWidget(info)
            transcript=QPlainTextEdit();transcript.setReadOnly(True);box.addWidget(transcript,1)
            def show_history():transcript.setPlainText('\n\n'.join(('You: ' if item['role']=='user' else 'Model: ')+item['text'] for item in history))
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
                    body=prepare(connection,initial,history,user_text,secrets);seconds=min(coding_limits(self.store.config['settings'].get('coding_limits'))['model_seconds'],coding_limits(self.store.config['settings'].get('coding_limits'))['turn_seconds'])
                except (ValueError,TypeError,OSError) as exc:status.setText(str(exc));return
                token=uuid.uuid4().hex;pending['token']=token;pending['draft']=None;busy(True);status.setText(self.tr('Waiting for model…'))
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


    def start_coding(self,continuation=False):
        if self.job or self._closed:return
        try:
            from .code_agent import ProjectFiles
            from .project_skills import verify_skill_pins
            verify_skill_pins(ProjectFiles(self.session['path_snapshot']),self.session.get('coding_skills',[]),self.session.get('coding_skill_pins',{}))
            self.save_models();heavy=self.role_connection('heavy')
            advice,destination=self.window.decision_connection()
            resume=self.session.get('coding_resume') if continuation else None
            prompt=(self.tr('Continue the previous task with fresh limits. Inspect the current project state before proceeding; do not repeat an uncertain operation without checking.') if continuation else self.composer.toPlainText());ident=self.session.get('selected_track')
            if continuation and not resume:return
            if not heavy or (not prompt.strip() and not ident and not self.attachments.paths and not self.documents):raise ValueError(self.tr('Choose a model and enter a coding task, attach a file, or select a track'))
            if not prompt.strip():prompt=self.tr('Work on the selected project track. Inspect the project and report progress against its task IDs.') if ident else self.tr('Consider the attached files for this coding task.')
            if self.goal_enabled.isChecked() and len((resume or {}).get('task',prompt))>16000:raise ValueError(self.tr('Goal objectives must be at most 16,000 characters so they can be saved and resumed.'))
            context=self.session.get('coding_context') if self.use_context.isChecked() and not continuation else None
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
            refs=(([self.mcp_primary_ref] if self.mcp_primary_ref else [])+self.mcp_extra_refs) if self.window.mcp_access.isChecked() else []
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
            unsupported_roles=set()
            if unsupported(self.store.config,self.subagent_capability_connection('heavy',heavy)):unsupported_roles.add('model')
            from .project_memory import ProjectMemory
            project_memory=ProjectMemory(self.store.root/'history.sqlite3',self.session['project_id']) if self.window.repositories.get(self.session['project_id']) else None
            selected=None
            if ident:
                from .track_execution import prepare_track
                secrets=[heavy.get('api_key','')]+[backend.get('key','') for backend in backends]
                for bridge in mcp_bridges:secrets.extend(getattr(bridge,'environment_values',{}).values())
                files=ProjectFiles(self.session['path_snapshot']);limit=coding_limits(self.store.config['settings'].get('coding_limits'))['context_bytes'];selected=prepare_track(files,ident,secrets,limit)
                if not self.review_selected_track(selected,heavy,prompt):return
                if prepare_track(files,ident,secrets,limit)!=selected:raise ValueError(self.tr('Selected track changed after review; review and start again.'))
            from . import hosted,research
            hosted_enabled=enabled and not strict and not (refs and self.store.config['settings'].get('mcp_priority','first')=='first') and self.store.config['settings'].get('research_policy','Provider first')=='Provider first' and hosted.supported_endpoint(heavy) and research.capability(self.store.config,heavy,'hosted_search').state!='unsupported'
            run=CodingRun(heavy,self.session['path_snapshot'],prompt,context=context,web_backends=backends,limits=self.store.config['settings'].get('coding_limits'),web_enabled=enabled,search_provider=provider,skills=self.session.get('coding_skills',[]),skill_pins=self.session.get('coding_skill_pins',{}),mcp_bridges=mcp_bridges,unsupported_subagent_roles=unsupported_roles,working_notes=self.session.get('coding_working_notes',{}),project_memory=project_memory,selected_track=selected,images=resume.get('images',[]) if resume else self.attachments.paths,documents=resume.get('documents',[]) if resume else self.documents,resume_context={key:resume[key] for key in ('task','evidence')} if resume else None,goal=self.goal_enabled.isChecked(),goal_budget=self.store.config['settings'].get('coding_goal_limits'),hosted_search=hosted_enabled,mcp_priority=self.store.config['settings'].get('mcp_priority','first'))
            secrets=self.draft_secrets()+[heavy.get('api_key','')]+[item.get('key','') for item in backends]
            for bridge in mcp_bridges:secrets.extend(getattr(bridge,'environment_values',{}).values())
            secrets=list(dict.fromkeys(secret for secret in secrets if isinstance(secret,str) and secret))
            if self.goal_enabled.isChecked():
                if len(scrub((resume or {}).get('task',prompt),secrets))>16000:raise ValueError(self.tr('Goal objectives must be at most 16,000 characters so they can be saved and resumed.'))
        except (OSError,ValueError) as exc:QMessageBox.warning(self,self.tr('Coding settings'),str(exc));return
        if not continuation and self.composer.toPlainText().strip():self.remember_prompt(scrub(self.composer.toPlainText(),secrets))
        if not continuation:self.session['coding_continuation_steering']={'text':'','omitted':False}
        elif 'coding_continuation_steering' not in self.session:
            legacy=self.continuation_steering(secrets);header='Delivered steering for this task:\n';legacy=legacy[len(header):] if legacy.startswith(header) else legacy
            marker='[Earlier delivered steering omitted due to the size limit.]\n';omitted=legacy.startswith(marker)
            if omitted:legacy=legacy[len(marker):]
            self.session['coding_continuation_steering']={'text':legacy[-14000:],'omitted':omitted or len(legacy)>14000}
        self.session['coding_last_run_goal']=self.goal_enabled.isChecked()
        if self.goal_enabled.isChecked():
            objective=(resume or {}).get('task',prompt)
            self.session['coding_goal']={'objective':scrub(objective,secrets),'status':'active','detail':''}
            self.session['coding_goal_progress']={'steps':0,'seconds':0}
            self.session['coding_goal_run_limits']=dict(run.goal_budget)
            if not resume:self.session['coding_resume']={'task':self.session['coding_goal']['objective'],'evidence':'','images':list(run.images),'documents':scrub(copy.deepcopy(run.documents),secrets)}
        self.advice_connection=advice;self.advice_destination=destination
        self.launch(run,'Agentnik coding started. Project file changes apply without per-file approval. Shell commands '+('run without approval' if self.shell_auto.isChecked() else 'require approval')+'. Repository content goes to the selected models.')
        if enabled:self.record('output',{'none':'Web research: public page reads only; strict navigation disables search.','google':'Web research: Google search and public page reads.','ollama':'Web research: Ollama search and public page reads.','managed':'Web research: configured search providers and public page reads.'}[provider])

    def can_continue(self):
        state=self.session.get('code_state')
        if self.session.get('coding_last_run_goal',True) and self.session.get('coding_goal',{}).get('status')==state and state in ('limited','paused','blocked','interrupted','failed'):return bool(self.session['coding_goal'].get('objective'))
        return state=='limited' and bool(self.session.get('coding_context'))

    def refresh_goal_status(self):
        goal=self.session.get('coding_goal')
        if not goal:
            self.goal_status_label.hide();self.goal_details_button.hide();return
        status={'active':self.tr('Active'),'paused':self.tr('Paused'),'blocked':self.tr('Blocked'),'limited':self.tr('Limit reached'),'interrupted':self.tr('Interrupted'),'cancelled':self.tr('Cancelled'),'failed':self.tr('Failed'),'completed':self.tr('Completed (model reported)')}.get(goal['status'],goal['status'])
        objective=goal['objective'].replace('\n',' ')
        preview=objective[:160]+('…' if len(objective)>160 else '')
        template=self.tr('Goal · {status}: {objective}') if self.session.get('coding_last_run_goal',True) else self.tr('Previous goal · {status}: {objective}')
        self.goal_status_label.setText(template.format(status=status,objective=preview));self.goal_status_label.setToolTip(goal['objective']);self.goal_status_label.show();self.goal_details_button.show()

    def show_goal_details(self):
        goal=self.session.get('coding_goal')
        if not goal:return
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Goal details'));dialog.resize(700,420);layout=QVBoxLayout(dialog)
        progress=self.job.goal_progress_snapshot() if isinstance(self.job,CodingRun) and self.job.goal else self.session.get('coding_goal_progress',{'steps':0,'seconds':0})
        saved_limits=self.session.get('coding_goal_run_limits');limits=goal_limits(saved_limits) if saved_limits is not None else None;unlimited=self.tr('Unlimited')
        steps=(str(limits['steps']) if limits['steps'] else unlimited) if limits else self.tr('Unknown')
        seconds=(str(limits['seconds']) if limits['seconds'] else unlimited) if limits else self.tr('Unknown')
        usage=self.tr('Completed goal steps: {used} / {limit}\nActive goal time (seconds): {seconds:.1f} / {time_limit}').format(used=progress['steps'],limit=steps,seconds=progress['seconds'],time_limit=seconds)
        steering=self.continuation_steering(self.draft_secrets())
        text=self.tr('Objective:')+'\n'+goal['objective']+'\n\n'+self.tr('Status:')+' '+goal['status']+'\n\n'+usage+'\n\n'+self.tr('Latest detail:')+'\n'+goal['detail']
        if steering:text+='\n\n'+self.tr('Retained delivered steering:')+'\n'+steering
        details=QPlainTextEdit(text);details.setObjectName('goalDetailsText');details.setReadOnly(True);layout.addWidget(details)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

    def build_goal_resume(self):
        goal=self.session['coding_goal'];previous=self.session.get('coding_resume',{})
        recent=self.continuation_activity()
        secrets=self.draft_secrets();snapshot=self.continuation_snapshot(secrets)
        evidence=self.bounded_continuation_evidence('\n'.join(filter(None,[scrub(previous.get('evidence',''),secrets),scrub(recent,secrets),scrub(goal.get('detail',''),secrets),self.continuation_steering(secrets),snapshot,'Interrupted or uncertain actions must be inspected before any retry.'])))
        return {'task':goal['objective'],'evidence':evidence,'images':list(previous.get('images',[])),'documents':copy.deepcopy(previous.get('documents',[]))}

    def capture_goal_resume(self):
        self.session['coding_resume']=self.build_goal_resume();goal=self.session['coding_goal'];evidence=self.session['coding_resume']['evidence']
        self.session['coding_context']={'task':plain(goal['objective'])[:2048],'answer':plain(evidence)[-2048:]}

    def continue_coding(self):
        if self.job or not self.can_continue():return
        if self.session.get('coding_last_run_goal',True) and self.session.get('coding_goal',{}).get('status')==self.session.get('code_state') and self.session.get('code_state') in ('limited','paused','blocked','interrupted','failed'):
            if not self.session.get('coding_resume_reviewed') and (self.session.get('code_state')!='limited' or not self.session.get('coding_resume')):self.capture_goal_resume()
            self.goal_enabled.setChecked(True)
        if not self.session.get('coding_resume'):
            context=self.session['coding_context'];self.session['coding_resume']={'task':context['task'],'evidence':context['answer']}
        self.start_coding(True)

    def launch(self,run,notice):
        if isinstance(run,CodingRun):
            self.session.pop('coding_resume_reviewed',None)
            run.set_shell_without_approval(self.shell_auto.isChecked())
            run.show_thinking=self.show_thinking.isChecked()
            self.session['coding_subagents']=[];self.refresh_subagents()
            history=self.session.setdefault('coding_skill_history',[])
            history.append({'run_id':run.run_id,'skills':[]});self.session['coding_skill_history']=history[-32:]
            self.session['coding_sources']=[];self.session['coding_skill_revisions']=[];self.update_sources_button();self.session.pop('coding_plan',None);self.refresh_plan()
        self.job=run;self.run_id=run.run_id;self.pending_fingerprint=None;self.session['code_state']='running'
        self.refresh_goal_status()
        self.steering_input.setEnabled(isinstance(run,CodingRun));self.steering_button.setEnabled(isinstance(run,CodingRun))
        self.goal_enabled.setEnabled(False)
        self.pause_goal_button.setEnabled(isinstance(run,CodingRun) and run.goal)
        self.continue_button.setEnabled(False)
        self.send.setEnabled(False);self.cancel_button.setEnabled(True)
        self.coding_context_button.setEnabled(False);self.coding_auto_compact.setEnabled(False);self.memory_button.setEnabled(False);self.notes_button.setEnabled(False);self.mcp_choice.setEnabled(False);self.mcp_refresh.setEnabled(False);self.mcp_extra_button.setEnabled(False)
        self.use_context.setEnabled(False)
        for connection,model in self.roles.values():connection.setEnabled(False);model.setEnabled(False)
        self.diff.clear();self.approval.clear();self.record('started',notice)
        self._run_started_at=time.monotonic();self.record('timing',self.tr('Started: {time}').format(time=datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')))
        signals=self.events
        def work():
            try:run.run(signals.event.emit)
            except RuntimeError:pass
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()
        if isinstance(run,CodingRun) and run.goal:self.goal_checkpoint_timer.start()

    def checkpoint_goal_progress(self):
        job=self.job
        if not isinstance(job,CodingRun) or not job.goal or job.goal_started is None:return
        self.session['coding_goal_progress']=job.goal_progress_snapshot();self.store.save(self.session)

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
        self.session['draft']=scrub(self.composer.toPlainText(),self.draft_secrets());self.session['draft_images']=list(self.attachments.paths);self.session['draft_documents']=copy.deepcopy(self.documents);self.store.save(self.session);self.updated.emit()

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
            fixed_output={
                'Goal remains active; continuing to the next step.':self.tr('Goal remains active; continuing to the next step.'),
                'Invalid JSON tool arguments were replaced with an empty object in continuation history; the batch was not executed.':self.tr('Invalid JSON tool arguments were replaced with an empty object in continuation history; the batch was not executed.'),
                'Web research returned no sources.':self.tr('Web research returned no sources.'),
                'Google search is unavailable; direct public page reads remain available.':self.tr('Google search is unavailable; direct public page reads remain available.'),
                'Search was blocked by an access restriction. Further searches are disabled for this run; existing sources and other work remain available.':self.tr('Search was blocked by an access restriction. Further searches are disabled for this run; existing sources and other work remain available.'),
            }
            if text in fixed_output:return fixed_output[text]
            prefix='Tool call: '
            if text.startswith(prefix):return self.tr('Tool call: {detail}').format(detail=text[len(prefix):])
            match=re.fullmatch(r'Tool result: (.+) — (returned|rejected|error)',text)
            if match:
                outcomes={'returned':self.tr('returned'),'rejected':self.tr('rejected'),'error':self.tr('error')}
                return self.tr('Tool result: {tool} — {outcome}').format(tool=match[1],outcome=outcomes[match[2]])
            for prefix,template in [('Reading web page: ',self.tr('Reading web page: {detail}')),('Searching web: ',self.tr('Searching web: {detail}')),('Applying project edit: ',self.tr('Applying project edit: {detail}')),('Applying project patch: ',self.tr('Applying project patch: {detail}')),('Applied project edit: ',self.tr('Applied project edit: {detail}')),('Applied project patch: ',self.tr('Applied project patch: {detail}')),('Moving project file: ',self.tr('Moving project file: {detail}')),('Moving project directory: ',self.tr('Moving project directory: {detail}')),('MCP server connected: ',self.tr('MCP server connected: {detail}')),('MCP tool completed: ',self.tr('MCP tool completed: {detail}')),('MCP tool returned an error: ',self.tr('MCP tool returned an error: {detail}')),('Read repository skill: ',self.tr('Read repository skill: {detail}')),('Read skill reference: ',self.tr('Read skill reference: {detail}')),('Parallel search: ',self.tr('Parallel search: {detail}')),('Test report: ',self.tr('Test report: {detail}'))]:
                if text.startswith(prefix):return template.format(detail=text[len(prefix):])
            prefix='Model task: requesting ';suffix=' through the selected connection.'
            if text.startswith(prefix) and text.endswith(suffix):return self.tr('Model task: requesting {model} through the selected connection.').format(model=text[len(prefix):-len(suffix)])
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
                    match=re.fullmatch(r'(Model|Subagent|Heavy|Light): (\d+) request\(s\), input (\d+(?:\.\d+)?|unknown)( \(known usage only\))?, output (\d+(?:\.\d+)?|unknown)( \(known usage only\))? tokens',part)
                    if not match:return text
                    role,count,incoming,in_partial,outgoing,out_partial=match.groups()
                    incoming=self.tr('unknown') if incoming=='unknown' else incoming
                    outgoing=self.tr('unknown') if outgoing=='unknown' else outgoing
                    partial=self.tr(' (known usage only)')
                    parts.append(self.tr('{role}: {count} request(s), input {incoming}{in_partial}, output {outgoing}{out_partial} tokens').format(role=self.tr(role),count=count,incoming=incoming,in_partial=partial if in_partial else '',outgoing=outgoing,out_partial=partial if out_partial else ''))
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


    def show_saved_reviews(self):
        from .code_agent import ProjectFiles
        from .independent_review import sources_unchanged,validate_review_history,track_context_matches
        try:history=validate_review_history(self.session.get('coding_review_history',[]))
        except (ValueError,TypeError,OSError):return
        try:files=ProjectFiles(self.session['path_snapshot'])
        except (ValueError,OSError):files=None
        dialog=QDialog(self);dialog.setWindowTitle(self.tr('Saved review snapshots'));dialog.resize(760,540);layout=QVBoxLayout(dialog)
        note=QLabel(self.tr('Saved findings are untrusted and may be stale. Opening this view does not start a model request or change saved records.'));note.setWordWrap(True);layout.addWidget(note)
        choice=QComboBox();choice.setObjectName('savedReviewChoice');layout.addWidget(choice)
        for index,record in enumerate(history,1):choice.addItem(self.tr('Snapshot {number} · {count} recorded passes · {id}').format(number=index,count=len(record['reviews']),id=record['id'][:8]),record['id'])
        view=QPlainTextEdit();view.setReadOnly(True);layout.addWidget(view)
        view_project=QPushButton(self.tr('View project track reviews…'));view_project.setObjectName('viewProjectReviews');layout.addWidget(view_project)
        export=QPushButton(self.tr('Export snapshot…'));export.setObjectName('exportReviewSnapshot');export.setEnabled(bool(history));layout.addWidget(export)
        def selected_track_id(record):
            if not record:return None
            contexts=[item.get('track_context') for item in record['reviews']]
            if not contexts or any(not item for item in contexts):return None
            ids={item['id'] for item in contexts}
            return next(iter(ids)) if len(ids)==1 else None
        def display_selected():
            record=next((copy.deepcopy(item) for item in history if item['id']==choice.currentData()),None)
            if not record:view.clear();view_project.setEnabled(False);return
            for review in record['reviews']:
                sources=[(review['path'],review['source_sha256'])]+[(entry['path'],entry['sha256']) for entry in review['evidence']]
                review['source_status']=self.tr('Current source hashes match the reviewed snapshots.') if files and sources_unchanged(files,sources) else self.tr('Stale or unavailable: a reviewed source changed or cannot be read.')
                if review.get('track_context'):
                    review['track_status']=self.tr('Track run context matches its starting revision; this does not mean the full track was reviewed.') if files and track_context_matches(files,review['track_context']) else self.tr('Track run context changed or is unavailable; this does not mean the full track was reviewed.')
            view_project.setEnabled(bool(files and selected_track_id(record)));view.setPlainText(json.dumps(record,ensure_ascii=False,indent=2))
        choice.currentIndexChanged.connect(display_selected);display_selected()
        def show_project_reviews():
            record=next((item for item in history if item['id']==choice.currentData()),None);track_id=selected_track_id(record)
            if files and track_id:self.show_project_track_reviews(track_id,dialog)
        view_project.clicked.connect(show_project_reviews)
        def export_snapshot():
            record=next((item for item in history if item['id']==choice.currentData()),None)
            if record:self.export_review_snapshot(record,dialog,lambda:any(item==record for item in validate_review_history(self.session.get('coding_review_history',[]))))
        export.clicked.connect(export_snapshot)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

    def receive(self,event):
        if self._closed or not self.job or event.get('run_id')!=self.run_id:return
        kind=event.get('kind')
        if kind=='hosted_search_unsupported':
            from . import research
            original=self.job.connection;name=self.roles['heavy'][0].currentData();saved=self.store.config.get('connections',{}).get(name)
            try:current=self.role_connection('heavy')
            except ValueError:return
            if any(original.get(k)!=current.get(k) for k in ('url','protocol','model','api_key','_capability_scope')):return
            if saved is not None and original.get('_capability_scope'):saved.setdefault('_capability_scope',original['_capability_scope'])
            research.set_capability(self.store.config,original,'unsupported','Provider explicitly rejected hosted search','hosted_search');self.store.flush();return
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
            if role!='model' or not isinstance(self.job,CodingRun):return
            original=self.job.connection
            widget_role='heavy'
            try:current=self.role_connection(widget_role)
            except ValueError:return
            fields=('url','protocol','model','api_key','reasoning','stream','context_limit','_capability_scope')
            if not original or not current or any(original.get(key)!=current.get(key) for key in fields):return
            name=self.roles[widget_role][0].currentData();saved=self.store.config.get('connections',{}).get(name)
            if saved is not None and not saved.get('_capability_scope') and current.get('_capability_scope'):saved['_capability_scope']=current['_capability_scope']
            from .subagent_capabilities import remember
            remember(self.store.config,self.subagent_capability_connection(widget_role,current));self.store.flush();return
        if kind in ('edit_proposal','operation_proposal'):self.approve_mcp_run.hide()
        if kind=='subagent':
            try:
                value=validate_record(event.get('subagent'));value['text']=plain(value['text'])[:1600]
            except (ValueError,TypeError):return
            records=self.session.setdefault('coding_subagents',[])
            prior=next((item for item in records if item['id']==value['id']),None)
            if prior is None:
                if value['status'] not in ('queued','running'):return
                records.append(value);self.session['coding_subagents']=records[-32:]
            elif (prior['status']=='queued' and value['status'] in ('running','failed','cancelled')) or (prior['status']=='running' and value['status'] in ('completed','failed','cancelled')) or (prior['status']=='cancelled' and value['status']=='cancelled'):
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
            self._git_auth_pending=False;self._git_auth_url='';self.git_auth_row.hide();self.git_username.clear();self.git_token.clear();self.git_remember_token.setChecked(False)
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval'
            self.advice_fingerprint=None;self.advice_label.hide()
            proposal=event['proposal'];self.diff.setVisible(True);self.diff.setPlainText(proposal['diff'])
            self.approval.setPlainText(self.tr('FILE EDIT\nProject: {project}\nPath: {path}\nReview the full diff below.\nSafety recommendation: Not checked; no System One request was made.').format(project=proposal['cwd'],path=proposal['path']))
            self.approval_panel.show();self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting approval for file edit: '+proposal['path'])
        elif kind=='operation_proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval';proposal=event['proposal'];operation=proposal['operation']
            self._git_auth_pending=operation in ('git_fetch_connect','git_push_connect');self._git_auth_url=proposal.get('url','') if self._git_auth_pending else '';self.git_username.clear();self.git_token.clear();self.git_remember_token.setChecked(False);self.git_auth_row.setVisible(self._git_auth_pending)
            from .code_agent import MCP_APPROVAL_OPERATIONS
            if operation in MCP_APPROVAL_OPERATIONS:
                self.approve_mcp_run.show();self.approve_mcp_run.setEnabled(True)
            self.advice_fingerprint=self.pending_fingerprint if operation=='run_shell' else None
            if operation=='run_shell':self.show_advice()
            else:self.advice_label.hide()
            self.diff.setPlainText(proposal.get('diff',''));self.diff.setVisible(operation in ('delete_file','git_commit','git_commit_staged','git_stage','git_unstage','subagent_file_transfer'))
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
            elif operation=='subagent_file_transfer':
                text=self.tr('SEND PROJECT FILE TO SUBAGENT\nProject: {cwd}\nFile: {path}\nModel: {model}\nDestination: {destination}\nSubagent: {child}\nTask: {task}\nPayload: {payload_bytes} UTF-8 bytes\nSHA-256: {payload_sha256}\n\nReview the exact file text to be sent below.').format(**proposal)
            elif operation in ('git_commit','git_commit_staged'):
                text=self.tr('GIT COMMIT\nProject: {cwd}\nFiles: {path}\nIdentity: {identity}\nParent: {head}\nMessage: {message}\nHooks and signing are disabled. Review the complete diff below.').format(**proposal)
            elif operation in ('git_stage','git_unstage'):
                label=self.tr('STAGE FILES') if operation=='git_stage' else self.tr('UNSTAGE FILES')
                text=self.tr('{operation}\nProject: {cwd}\nFiles: {path}\nWorking files will remain unchanged. Review the index diff below.').format(operation=label,cwd=proposal['cwd'],path=proposal['path'])
            elif operation=='git_create_branch':
                text=self.tr('CREATE BRANCH\nProject: {cwd}\nBranch: {name}\nStarting commit: {head}\nThe current branch will remain selected.').format(**proposal)
            elif operation=='git_fetch_connect':
                text=self.tr('CONNECT TO GIT REMOTE\nProject: {cwd}\nRemote: {remote}\nHTTPS destination: {url}\nBranch: {branch}\n\nOptionally enter a Git username and token below. They are sent only to this HTTPS origin; save the token only if desired. Agentnik will inspect the branch. A separate approval is required before downloading objects or updating the tracking reference.').format(**proposal)
            elif operation=='git_fetch':
                text=self.tr('FETCH GIT BRANCH\nProject: {cwd}\nRemote: {remote}\nHTTPS destination: {url}\nBranch: {branch}\nCommit: {commit}\nTracking reference: {target}\nPrevious commit: {previous}\n\nThe tracking reference may move backward or diverge. Working files and local branches are not changed.').format(**proposal)
            elif operation=='git_push_connect':
                text=self.tr('CONNECT TO GIT PUSH DESTINATION\nProject: {cwd}\nRemote: {remote}\nHTTPS destination: {url}\nLocal branch: {local_branch}\nLocal commit: {commit}\nRemote branch: {branch}\n\nOptionally enter a Git username and token below. They are sent only to this HTTPS origin; save the token only if desired. Agentnik will inspect the remote branch. A separate approval is required to send repository history and update it.').format(**proposal)
            elif operation=='git_push':
                text=self.tr('PUSH GIT BRANCH\nProject: {cwd}\nRemote: {remote}\nHTTPS destination: {url}\nLocal branch: {local_branch}\nCommit to send: {commit}\nRemote reference: {target}\nPrevious remote commit: {previous}\n\nThe server will receive the commits and repository objects needed for this update. Only a new branch or a verified fast-forward is permitted.').format(**proposal)
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
        elif kind in ('shell_approval_resolved','approval_invalidated'):
            if self.pending_fingerprint==event.get('fingerprint'):
                self.pending_fingerprint=None;self.advice_fingerprint=None
                if self.advice_job:self.advice_job.cancel.set();self.advice_job=None
                self.approve.setEnabled(False);self.reject.setEnabled(False);self.approval_panel.hide();self.approval.clear();self.diff.clear();self.session['code_state']='running'
                self.record('decision',self.tr('Pending approval invalidated by steering.') if kind=='approval_invalidated' else self.tr('Shell command allowed by the current switch.'))
        elif kind=='goal_status':
            if self.session.get('coding_goal'):
                self.session['coding_goal']['detail']=event['detail'][:4000];self.refresh_goal_status();self.record('output',self.tr('Goal status (model reported): ')+event['status']+' · '+event['detail'])
        elif kind=='goal_progress':
            previous=self.session.get('coding_goal_progress',{'steps':0,'seconds':0})
            self.session['coding_goal_progress']={'steps':max(previous['steps'],event['steps']),'seconds':max(previous['seconds'],event['seconds'])};self.store.save(self.session)
        elif kind=='steering_delivered':
            self.record_steering(self.tr('Steering delivered: '),event['text'],delivered=True)
            if isinstance(self.job,CodingRun):self.job.acknowledge_steering(event['text'])
        elif kind=='steering_undelivered':self.record_steering(self.tr('Steering not delivered: '),event['text'])
        elif kind=='steering_uncertain':self.record_steering(self.tr('Steering delivery uncertain: '),event['text'])
        elif kind=='output':self.record(kind,event['text'])
        elif kind=='model_response':
            role=event.get('role','Model');model=event.get('model','')
            for field,label in (('thinking',self.tr('Thinking')),('text',self.tr('Response'))):
                value=event.get(field,'')
                if not isinstance(value,str) or not value:continue
                self.record('output',self.tr('{role} model {model} — {label}:').format(role=role,model=model,label=label))
                for start in range(0,len(value),1800):self.record('output',value[start:start+1800])
        elif kind=='finished':
            if isinstance(self.job,CodingRun) and self.job.goal and self.session.get('coding_goal'):
                if 'goal_progress' in event:self.session['coding_goal_progress']=event['goal_progress']
                self.session['coding_goal']['status']='limited' if event.get('limited') else event['status']
                if event['status']!='completed':self.session['coding_goal']['detail']=event['text'][:4000]
            if event.get('limited') and isinstance(self.job,CodingRun):
                secrets=self.draft_secrets()
                recent=self.continuation_activity()
                previous=getattr(self.job,'resume_context',None) or {}
                task=previous.get('task',self.job.prompt)
                evidence='\n'.join(filter(None,[scrub(previous.get('evidence',''),secrets),scrub(recent,secrets),scrub(event['text'],secrets),self.continuation_steering(secrets),self.continuation_snapshot(secrets)]))
                resume={'task':scrub(task,secrets)[:16000],'evidence':self.bounded_continuation_evidence(evidence),'images':list(self.job.images),'documents':scrub(copy.deepcopy(self.job.documents),secrets)};self.session['coding_resume']=resume
                context={'task':plain(resume['task'])[:2048],'answer':plain(resume['evidence'])[-2048:]}
                self.session['coding_context']=context;self.session.pop('coding_compaction',None)
            if event['status']=='completed' and isinstance(self.job,CodingRun):
                self.session.pop('coding_resume',None)
                secrets=self.draft_secrets()
                original=(self.job.resume_context or {}).get('task',self.job.prompt)
                context={'task':plain(scrub(original,secrets)),'answer':plain(event['text'])}
                self.session['coding_context']=context;self.session.pop('coding_compaction',None)
                self.use_context.setChecked(False)
            self.stop_subagents('stopped');self.session['code_state']='limited' if event.get('limited') else event['status'];self.finish();self.record(kind,self.tr('Coding turn completed.') if event.get('response_shown') and event['status']=='completed' else event['text'])
            if event.get('usage'):self.record('usage',event['usage'])

    def load_git_token(self):
        if not self._git_auth_pending:return
        try:
            from .git_credentials import load_token
            token=load_token(self._git_auth_url,self.git_username.text())
            if token is not None and (not isinstance(token,str) or not 1<=len(token)<=4096 or any(not 33<=ord(ch)<=126 for ch in token)):raise ValueError('Invalid saved token')
        except Exception:
            QMessageBox.warning(self,self.tr('Git credentials'),self.tr('Could not read the saved Git token. Check the username and OS credential store.'));return
        if token is None:QMessageBox.information(self,self.tr('Git credentials'),self.tr('No saved token was found for this destination and username.'));return
        self.git_token.setText(token)

    def forget_git_token(self):
        if not self._git_auth_pending:return
        try:
            from .git_credentials import delete_token
            delete_token(self._git_auth_url,self.git_username.text())
        except Exception:
            QMessageBox.warning(self,self.tr('Git credentials'),self.tr('Could not remove the saved Git token. Check the username and OS credential store.'));return
        self.git_token.clear();self.git_remember_token.setChecked(False)
        QMessageBox.information(self,self.tr('Git credentials'),self.tr('The saved token for this destination and username was removed.'))

    def decide(self,allowed,scope='once'):
        if self.advice_job or not self.job or not self.pending_fingerprint:return
        credentials=None
        if allowed and self._git_auth_pending:
            username=self.git_username.text();token=self.git_token.text()
            if username or token:
                if not username or not token or len(username)>256 or len(token)>4096 or ':' in username or any(not 33<=ord(ch)<=126 for ch in username+token):
                    QMessageBox.warning(self,self.tr('Git credentials'),self.tr('Enter both a username and token using visible ASCII characters; usernames cannot contain a colon.'));return
                credentials=(username,token)
            if self.git_remember_token.isChecked():
                if credentials is None:
                    QMessageBox.warning(self,self.tr('Git credentials'),self.tr('Enter a username and token before saving.'));return
                try:
                    from .git_credentials import save_token
                    save_token(self._git_auth_url,username,token)
                except Exception:
                    QMessageBox.warning(self,self.tr('Git credentials'),self.tr('Could not save the Git token in the OS credential store. Nothing was submitted.'));return
        accepted=self.job and self.pending_fingerprint and (self.job.decide(self.pending_fingerprint,allowed,git_credentials=credentials) if credentials else self.job.decide(self.pending_fingerprint,allowed,scope) if scope!='once' else self.job.decide(self.pending_fingerprint,allowed))
        if accepted:
            self.git_username.clear();self.git_token.clear();self.git_remember_token.setChecked(False);self.git_auth_row.hide();self._git_auth_pending=False;self._git_auth_url=''
            decision=self.pending_fingerprint;self.approve.setEnabled(False);self.reject.setEnabled(False);self.approve_mcp_run.setEnabled(False);self.approve_mcp_run.hide();self.pending_fingerprint=None
            self.advice_fingerprint=None
            self.approval_panel.hide();self.approval.clear();self.diff.clear()
            self.session['code_state']='running';self.record('decision',('Allowed MCP server for this run' if scope=='mcp_server_run' else 'Approved' if allowed else 'Rejected')+' proposal '+decision)

    def finish(self):
        self.goal_checkpoint_timer.stop()
        started=getattr(self,'_run_started_at',None)
        if started is not None:
            self._run_started_at=None
            self.record('timing',self.tr('Ended: {time} · Elapsed: {elapsed:.1f} seconds').format(time=datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z'),elapsed=max(0,time.monotonic()-started)))
        self.git_username.clear();self.git_token.clear();self.git_remember_token.setChecked(False);self.git_auth_row.hide();self._git_auth_pending=False;self._git_auth_url=''
        if self.advice_job:self.advice_job.cancel.set();self.advice_job=None
        self.advice_connection=None;self.advice_destination=''
        self.run_id=None;self.job=None;self.pending_fingerprint=None;self.advice_fingerprint=None
        self.refresh_goal_status()
        self.steering_input.setEnabled(False);self.steering_button.setEnabled(False)
        self.goal_enabled.setEnabled(True)
        self.approval_panel.hide()
        for button in (self.approve,self.reject,self.approve_mcp_run,self.cancel_button,self.pause_goal_button):button.setEnabled(False)
        self.approve_mcp_run.hide()
        self.send.setEnabled(True)
        self.coding_context_button.setEnabled(True);self.coding_auto_compact.setEnabled(True);self.memory_button.setEnabled(True);self.notes_button.setEnabled(True);self.mcp_choice.setEnabled(True);self.mcp_refresh.setEnabled(True);self.mcp_extra_button.setEnabled(True)
        self.use_context.setEnabled(bool(self.session.get('coding_context')))
        self.continue_button.setEnabled(self.can_continue())
        for connection,model in self.roles.values():connection.setEnabled(True);model.setEnabled(True)

    def pause_goal(self):
        if not isinstance(self.job,CodingRun) or not self.job.goal:return
        job=self.job;steering=job.stop()
        for message in steering['delivered']:self.record_steering(self.tr('Steering delivered: '),message,delivered=True)
        for message in steering['uncertain']:self.record_steering(self.tr('Steering delivery uncertain: '),message)
        for message in steering['undelivered']:self.record_steering(self.tr('Steering not delivered: '),message)
        self.session['coding_goal_progress']=job.goal_progress_snapshot();self.capture_goal_resume();self.session['coding_goal']['status']='paused';self.session['code_state']='paused'
        for bridge in job.mcp_bridges:bridge.close()
        self.stop_subagents('cancelled');self.finish();self.record('output',self.tr('Goal paused. Inspect uncertain actions before resuming.'))
        self.record('usage',job.usage_text())

    def cancel(self):
        if not self.job:return
        if getattr(self,'_drafting_active',False):
            if self._drafting_cancel_callback:self._drafting_cancel_callback()
            return
        if getattr(self,'_compaction_active',False):
            self.job.cancel.set();self._compaction_active=False;self._compaction_token=None;self.composer.setReadOnly(False);self.finish();self.record('output','Coding context compaction cancelled.');return
        job=self.job;steering=job.stop()
        if isinstance(job,CodingRun):
            for message in steering['delivered']:self.record_steering(self.tr('Steering delivered: '),message,delivered=True)
            for message in steering['uncertain']:self.record_steering(self.tr('Steering delivery uncertain: '),message)
            for message in steering['undelivered']:self.record_steering(self.tr('Steering not delivered: '),message)
        if isinstance(job,CodingRun) and job.goal and self.session.get('coding_goal'):self.session['coding_goal']['status']='cancelled';self.session['coding_goal_progress']=job.goal_progress_snapshot()
        usage=job.usage_text() if isinstance(job,CodingRun) else None
        for bridge in getattr(self.job,'mcp_bridges',[]):bridge.close()
        self.stop_subagents('cancelled');self.session['code_state']='cancelled';self.finish()
        self.record('cancelled','Run cancelled. No further tool work will be scheduled; project changes already applied are retained.')
        if usage:self.record('usage',usage)
