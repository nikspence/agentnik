"""Tool-free Heavy model track drafting, validation and offline protocol checks."""
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from agentnik import core
from agentnik.track_authoring import new_draft
from agentnik.track_drafting import prepare,parse_reply,request,validate_history
from test_compat_tools import chat,msg
from test_routing import Wire,response,message

C={'url':'https://gateway.example/v1','protocol':'chat','model':'heavy','stream':False}

def proposal():
    draft=new_draft();draft['metadata']['id']='auth_feature';draft['metadata']['title']='Authentication'
    return {'kind':'draft',**{key:draft[key] for key in ('metadata','spec','plan')}}

class TrackDrafting(unittest.TestCase):
    def test_prepare_is_tool_free_bounded_and_blocks_secrets(self):
        draft=new_draft();history=[{'role':'assistant','text':'What sign-in method?'}]
        body=prepare(C,draft,history,'Use passwords',['private-key'])
        self.assertNotIn('tools',body);self.assertIn('Use passwords',json.dumps(body));self.assertNotIn('private-key',json.dumps(body))
        with self.assertRaises(ValueError):prepare(C,draft,history,'Contains private-key',['private-key'])
        with self.assertRaises(ValueError):prepare(C,draft,history,'x'*4001)
        draft['created_dirs']=['agentnik-plans']
        with self.assertRaises(ValueError):prepare(C,draft,history,'Revise')
        with self.assertRaises(ValueError):validate_history([{'role':'tool','text':'x'}])

    def test_questions_drafts_and_invalid_or_secret_responses(self):
        self.assertEqual(parse_reply('{"kind":"question","question":"Which provider?"}')['kind'],'question')
        value=proposal();self.assertEqual(parse_reply(json.dumps(value))['draft']['metadata']['id'],'auth_feature')
        value['metadata']['tasks'][0]['status']='completed'
        with self.assertRaises(ValueError):parse_reply(json.dumps(value))
        value=proposal();value['spec']='한글"key'
        with self.assertRaises(ValueError):parse_reply(json.dumps(value,ensure_ascii=True),['한글"key'])
        for bad in ('not json','{"kind":"question","question":"a","question":"b"}','{"kind":"draft"}'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):parse_reply(bad)

    def test_all_protocols_use_no_tools_and_parse_response(self):
        text=json.dumps(proposal());cases=[
            ('chat','https://gateway.example/v1',chat(text)),
            ('responses','https://gateway.example/v1',response([message(text)])),
            ('messages','https://gateway.example/v1',msg([{'type':'text','text':text}]))]
        from test_research import Response,answer
        cases.append(('chat','http://localhost:11434/v1',None))
        for protocol,url,wire in cases:
            with self.subTest(protocol=protocol,url=url):
                connection=dict(C,protocol=protocol,url=url);body=prepare(connection,new_draft(),[],'Build authentication');sent=[]
                reply=Response([answer(text)]) if wire is None else Wire(wire,False)
                def send(c,url,body,timeout):sent.append(body);return reply
                with patch.object(core,'open_request',side_effect=send):result=request(connection,body,threading.Event(),5)
                self.assertEqual(result['kind'],'draft');self.assertNotIn('tools',sent[0])

    def test_tool_call_and_partial_or_bad_response_are_rejected(self):
        from test_code_agent import call
        connection=dict(C);body=prepare(connection,new_draft(),[],'Work')
        with patch.object(core,'open_request',return_value=Wire(chat(calls=[call('write_file',{'path':'x','content':'bad'})],finish='tool_calls'),False)):
            with self.assertRaises(ValueError):request(connection,body,threading.Event(),5)

class DraftingUI(unittest.TestCase):
    def test_question_followup_proposal_requires_apply_and_save(self):
        import os,time
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QPushButton,QPlainTextEdit,QTabWidget
        from agentnik.storage import Store
        from agentnik.ui import Window
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        app=QApplication.instance() or QApplication([]);errors=[]
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(folder);project=root/'project';project.mkdir();store=Store(root/'data');store.config['connections']={'Heavy':dict(C)};window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget();combo,model=tab.roles['heavy'];combo.setCurrentIndex(combo.findData('Heavy'));model.setText('heavy')
                generated=proposal();candidate={'kind':'draft','draft':{'metadata':generated['metadata'],'spec':generated['spec'],'plan':generated['plan'],'created_dirs':[],'written':{}}};replies=[{'kind':'question','question':'Which method?'},candidate];requests=[]
                def fake_request(connection,body,cancel,seconds,secrets):requests.append(body);return replies.pop(0)
                def button(dialog,text):return next(item for item in dialog.findChildren(QPushButton) if item.text()==text)
                def fail(exc):
                    errors.append(repr(exc))
                    for widget in app.topLevelWidgets():
                        if hasattr(widget,'reject') and widget.isVisible():widget.reject()
                def open_ai():
                    try:
                        outer=app.activeModalWidget()
                        def first():
                            try:
                                ai=app.activeModalWidget();edit=next(x for x in ai.findChildren(QPlainTextEdit) if x.placeholderText());edit.setPlainText('Build sign-in');button(ai,'Send').click();QTimer.singleShot(100,second)
                            except Exception as exc:fail(exc)
                        def second():
                            try:
                                ai=app.activeModalWidget();self.assertIn('Which method?',ai.findChildren(QPlainTextEdit)[0].toPlainText());edit=next(x for x in ai.findChildren(QPlainTextEdit) if x.placeholderText());edit.setPlainText('Use passwords');button(ai,'Send').click();QTimer.singleShot(100,apply)
                            except Exception as exc:fail(exc)
                        def apply():
                            try:
                                ai=app.activeModalWidget();self.assertTrue(button(ai,'Apply proposed draft').isEnabled());self.assertNotIn('track_draft',tab.session);self.assertFalse((project/'agentnik-plans').exists());button(ai,'Apply proposed draft').click()
                            except Exception as exc:fail(exc)
                        QTimer.singleShot(0,first);button(outer,'Ask Heavy…').click()
                        tabs=outer.findChild(QTabWidget);self.assertIn('auth_feature',tabs.widget(0).toPlainText());button(outer,'Save draft').click();outer.reject()
                    except Exception as exc:fail(exc)
                with patch('agentnik.track_drafting.request',side_effect=fake_request):
                    QTimer.singleShot(0,open_ai);tab.edit_track_draft()
                self.assertEqual(errors,[]);self.assertEqual(len(requests),2);saved=store.list_sessions()[0]
                self.assertEqual(saved['track_draft']['metadata']['id'],'auth_feature');self.assertEqual(len(saved['track_draft_conversation']),4);self.assertFalse((project/'agentnik-plans').exists())
            finally:window.close();app.processEvents();store.db.close()
    def test_cancel_discards_late_draft_and_preserves_existing_session(self):
        import os,time
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QPushButton,QPlainTextEdit
        from agentnik.storage import Store
        from agentnik.ui import Window
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        app=QApplication.instance() or QApplication([]);errors=[];release=threading.Event();started=threading.Event()
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(folder);project=root/'project';project.mkdir();store=Store(root/'data');store.config['connections']={'Heavy':dict(C)};window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);session['track_draft']=new_draft();store.save(session);window.open_session(session);tab=window.tabs.currentWidget();combo,model=tab.roles['heavy'];combo.setCurrentIndex(combo.findData('Heavy'));model.setText('heavy')
                generated=proposal();candidate={'kind':'draft','draft':{'metadata':generated['metadata'],'spec':generated['spec'],'plan':generated['plan'],'created_dirs':[],'written':{}}}
                def fake_request(connection,body,cancel,seconds,secrets):started.set();release.wait(2);return candidate
                def button(dialog,text):return next(item for item in dialog.findChildren(QPushButton) if item.text()==text)
                def open_ai():
                    try:
                        outer=app.activeModalWidget()
                        def begin():
                            try:
                                ai=app.activeModalWidget();next(x for x in ai.findChildren(QPlainTextEdit) if x.placeholderText()).setPlainText('Create track');button(ai,'Send').click();QTimer.singleShot(50,cancel)
                            except Exception as exc:errors.append(repr(exc));ai.reject()
                        def cancel():
                            try:
                                ai=app.activeModalWidget();self.assertTrue(started.is_set());button(ai,'Cancel request').click();release.set();ai.reject()
                            except Exception as exc:errors.append(repr(exc));release.set();ai.reject()
                        QTimer.singleShot(0,begin);button(outer,'Ask Heavy…').click();outer.reject()
                    except Exception as exc:errors.append(repr(exc));outer.reject()
                with patch('agentnik.track_drafting.request',side_effect=fake_request):
                    QTimer.singleShot(0,open_ai);tab.edit_track_draft();deadline=time.monotonic()+.3
                    while time.monotonic()<deadline:app.processEvents();time.sleep(.005)
                self.assertEqual(errors,[]);saved=store.list_sessions()[0];self.assertEqual(saved['track_draft']['metadata']['id'],'new_track');self.assertNotIn('track_draft_conversation',saved);self.assertIsNone(tab.job);self.assertFalse((project/'agentnik-plans').exists())
            finally:release.set();window.close();app.processEvents();store.db.close()
