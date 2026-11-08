"""Offline session recovery and research-retention contracts."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from agentnik import core, research
from agentnik.retention import retain_result
from agentnik.sessions import SessionError
from agentnik.storage import Store
from agentnik.tools import Limits, Source
from test_research import Backend, MESSAGES
from test_routing import Wire
from test_compat_tools import chat, chat_call

C={'url':'https://gateway.example/v1','protocol':'chat','model':'mock','stream':False}


class SessionRecovery(unittest.TestCase):
    def test_bad_and_future_rows_preserved_while_valid_history_remains_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            try:
                good=store.new_session('chat','test',C);store.save(good)
                cases=['{bad',json.dumps(dict(good,id='future',version=99)),json.dumps(dict(good,id='wrong-id')),
                       json.dumps(dict(good,id='broken',messages=[{'role':'assistant','metrics':{'input_tokens':'bad'}}]))]
                for index,payload in enumerate(cases):
                    store.db.execute('INSERT INTO sessions VALUES (?, ?, ?)',(str(index),index,payload))
                store.db.commit()
                rows=store.list_sessions()
                self.assertEqual(len(rows),5);self.assertEqual(sum(bool(r.get('_unavailable')) for r in rows),4)
                for row in rows:
                    if row.get('_unavailable'):
                        with self.assertRaises(SessionError): store.save(row)
                self.assertEqual([p for p, in store.db.execute('SELECT payload FROM sessions WHERE id != ? ORDER BY updated',(good['id'],))],cases)
                store.save(next(r for r in rows if r['id']==good['id']))
            finally: store.db.close()

    def test_legacy_defaults_are_read_without_rewriting_original(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            try:
                value={'id':'legacy','mode':'chat','connection':C,'messages':[{'role':'user'}]}
                payload=json.dumps(value)
                store.db.execute('INSERT INTO sessions VALUES (?, ?, ?)',('legacy',0,payload));store.db.commit()
                row=store.list_sessions()[0]
                self.assertEqual(row['messages'][0]['text'],'');self.assertEqual(row['version'],1)
                self.assertEqual(row['draft_images'],[])
                self.assertEqual(store.db.execute('SELECT payload FROM sessions').fetchone()[0],payload)
            finally: store.db.close()

    def test_unreadable_session_prevents_shared_attachment_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            try:
                image=Path(store.attach(data=b'image'))
                good=store.new_session('chat','test',C);good['draft_images']=[str(image)];store.save(good)
                store.db.execute('INSERT INTO sessions VALUES (?, ?, ?)',('unreadable',0,'{bad'));store.db.commit()
                store.delete([good['id']]);self.assertTrue(image.exists())
                store.delete(['unreadable']);self.assertFalse(image.exists())
            finally: store.db.close()


class Retention(unittest.TestCase):
    def test_under_limit_continuation_is_unchanged(self):
        value={'text':'Answer','research':{'status':'completed','continuation_eligible':True,'response_items':[{'type':'reasoning','encrypted_content':'opaque'}]}}
        before=copy.deepcopy(value)
        self.assertEqual(retain_result(value,2048),before)

    def test_oversized_records_are_bounded_and_never_partially_replayed(self):
        value={'text':'Answer [S1]','status':'ok','research':{'status':'completed','route':'hosted','response_items':[{'encrypted_content':'x'*5000}],
               'sources':[{'id':'S1','url':'https://example.com/','excerpt':'evidence '*2000}],'events':[{'detail':'x'*5000}]}}
        result=retain_result(value,2048)
        self.assertLessEqual(len(json.dumps(result['research']).encode()),2048)
        self.assertFalse(result['research']['continuation_eligible'])
        self.assertEqual(result['text'],'Answer [S1]')
        self.assertTrue(result['research']['retention']['truncated'])
        self.assertEqual(core.chat_body(C,[dict(role='assistant',**result)])['messages'],[])
        with self.assertRaises(ValueError): Limits(record_bytes=10)

    def test_managed_snapshots_and_reopened_record_stay_bounded(self):
        class LargeBackend(Backend):
            def search(self,query,runtime):
                return [Source('','Example','https://example.com/','synthetic evidence '*400,'now',backend='fixture')]
        updates=[]
        with patch.object(core,'open_request',side_effect=[Wire(chat(calls=[chat_call()],finish='tool_calls'),False),Wire(chat('Answer [S1]'),False)]):
            result=research.run_managed(C,MESSAGES,'fixture',updates.append,threading.Event(),limits=Limits(record_bytes=2048),backend=LargeBackend())
        self.assertEqual(result['status'],'ok')
        self.assertTrue(result['research']['retention']['truncated'])
        for value in updates+[result]: self.assertLessEqual(len(json.dumps(value['research']).encode()),2048)
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            try:
                session=store.new_session('chat','test',C);session['messages']=[dict(role='assistant',**result)];store.save(session)
                saved=store.list_sessions()[0]
                self.assertFalse(saved['messages'][0]['research']['continuation_eligible'])
            finally: store.db.close()


    def test_hosted_output_is_bounded_without_truncating_answer(self):
        from agentnik import hosted
        from test_routing import C as hosted_connection, message, response
        with patch.object(core,'open_request',return_value=Wire([{'type':'response.completed','response':response([message('text '*1000)])}])):
            result=hosted.run_hosted(hosted_connection,MESSAGES,'',lambda _:None,threading.Event(),limits=Limits(record_bytes=2048))
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['text'],'text '*1000)
        self.assertLessEqual(len(json.dumps(result['research']).encode()),2048)
        self.assertFalse(result['research']['continuation_eligible'])

    def test_routed_result_keeps_retention_after_policy_metadata_is_added(self):
        from agentnik import routing
        from test_routing import config
        value={'text':'Answer','status':'ok','metrics':{'model_requests':1},'research':{
            'status':'completed','route':'managed','events':[],'attempts':[],
            'response_items':[],'exchanges':[{'role':'assistant','content':'x'*5000}]}}
        with patch.object(research,'run_managed',return_value=value):
            result=routing.run(C,MESSAGES,'fixture',lambda _:None,threading.Event(),config(C),'Agentnik only',
                               [{'id':'fixture','kind':'ollama','key':'fixture'}],'public_fetch',limits=Limits(record_bytes=2048))
        self.assertLessEqual(len(json.dumps(result['research']).encode()),2048)
        self.assertTrue(result['research']['retention']['truncated'])
        self.assertFalse(result['research']['continuation_eligible'])


class RecoveryUI(unittest.TestCase):
    def test_unavailable_history_and_interrupted_reopen(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            store=Store(directory);window=Window(store)
            try:
                store.db.execute('INSERT INTO sessions VALUES (?, ?, ?)',('bad',0,'{bad'));store.db.commit()
                window.refresh_history();bad=next(s for s in store.list_sessions() if s.get('_unavailable'))
                with patch('agentnik.ui.error') as error:
                    window.open_session(bad);error.assert_called_once()
                session=store.new_session('chat','test',C)
                session['research_pending']={'user':{'role':'user','text':'pending'},'result':{'text':'partial','thinking':'','research':{'version':2,'status':'running','sources':[]}}}
                store.save(session)
                with patch.object(core,'models',return_value=[]),patch.object(core,'open_request') as transport:
                    window.open_session(next(s for s in store.list_sessions() if s['id']==session['id']))
                    app.processEvents();transport.assert_not_called()
                recovered=next(s for s in store.list_sessions() if s['id']==session['id'])
                self.assertNotIn('research_pending',recovered)
                self.assertEqual(recovered['messages'][-1]['status'],'failed')
            finally:
                window.close();app.processEvents();store.db.close()


if __name__=='__main__': unittest.main()
