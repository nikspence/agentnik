"""User-configured independent review with mocked endpoints and offscreen Qt."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from agentnik import core
from agentnik.direct_review import DirectReviewRun
from test_compat_tools import chat
from test_routing import Wire

MODEL={'url':'https://example.invalid/v1','protocol':'chat','model':'reviewer','stream':False}


class DirectReview(unittest.TestCase):
    def test_direct_run_approves_each_pass_and_sends_only_snapshots(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('SPEC',encoding='utf-8');Path(root,'evidence.txt').write_text('EVIDENCE',encoding='utf-8')
            definitions=[{'role':'comprehension','model':'light','paths':[]},{'role':'design','model':'light','paths':['evidence.txt']}]
            run=DirectReviewRun(root,'spec.md',definitions,{'light':MODEL});events=[];bodies=[]
            def send(connection,url,body,timeout):bodies.append(copy.deepcopy(body));return Wire(chat('{"version":1,"findings":[]}'),False)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual(len(bodies),2)
            approvals=[event['proposal'] for event in events if event['kind']=='operation_proposal'];self.assertEqual(len(approvals),2)
            for body,proposal in zip(bodies,approvals):
                self.assertEqual(body['messages'][0]['content'],proposal['diff']);self.assertNotIn('tools',body)
            self.assertNotIn('EVIDENCE',bodies[0]['messages'][0]['content']);self.assertIn('EVIDENCE',bodies[1]['messages'][0]['content'])
            self.assertEqual(sum(event['kind']=='independent_review_result' and event['review']['pass_status']=='completed' for event in events),2)

    def test_rejection_never_sends(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('SPEC',encoding='utf-8')
            run=DirectReviewRun(root,'spec.md',[{'role':'design','model':'light','paths':[]}],{'light':MODEL});events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],False)
            with patch.object(core,'open_request') as send:run.run(emit)
            send.assert_not_called();self.assertEqual(events[-1]['status'],'failed');self.assertIn('rejected',events[-1]['text'])

    def test_individual_cancel_discards_late_result(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('SPEC',encoding='utf-8');run=DirectReviewRun(root,'spec.md',[{'role':'design','model':'light','paths':[]}],{'light':MODEL});events=[];started=threading.Event();release=threading.Event();ids=[]
            def send(connection,url,body,timeout):started.set();release.wait(5);return Wire(chat('LATE FINDING'),False)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
                if event['kind']=='subagent' and event['subagent']['status']=='running':ids.append(event['subagent']['id'])
            with patch.object(core,'open_request',side_effect=send):
                thread=threading.Thread(target=run.run,args=(emit,));thread.start()
                try:
                    self.assertTrue(started.wait(3));self.assertTrue(run.cancel_subagent(ids[0]));thread.join(3);self.assertFalse(thread.is_alive())
                finally:release.set();thread.join(3)
            self.assertTrue(any(event['kind']=='independent_review_result' and event['review']['pass_status']=='cancelled' for event in events));self.assertNotIn('LATE FINDING',json.dumps(events))

    def test_offscreen_dialog_configures_direct_run_without_heavy(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog
        from agentnik.ui import Window
        from agentnik.code_ui import DirectReviewDialog
        from agentnik.storage import Store
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';project.mkdir();(project/'spec.md').write_text('SPEC',encoding='utf-8');store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                window.connections['Review']=dict(MODEL);box,model=tab.roles['light'];box.addItem('Review','Review');box.setCurrentIndex(box.findData('Review'));model.setText('reviewer');tab.light_enabled.setChecked(True)
                def configure(dialog):
                    dialog.target.setText('spec.md');dialog.passes[0][0].setCurrentIndex(dialog.passes[0][0].findData('design'));return QDialog.DialogCode.Accepted
                with patch.object(DirectReviewDialog,'exec',configure),patch.object(tab,'launch') as launch:
                    tab.start_direct_review();launch.assert_called_once();run=launch.call_args.args[0]
                self.assertIsInstance(run,DirectReviewRun);self.assertEqual(run.target,'spec.md');self.assertEqual(run.definitions[0]['role'],'design')
                session['coding_context']={'task':'Earlier task','answer':'Earlier answer'};session['coding_plan']={'explanation':'Prior plan','steps':[{'step':'Keep','status':'pending'}]};tab.composer.setPlainText('Unsent draft')
                def send(connection,url,body,timeout):return Wire(chat('{"version":1,"findings":[]}'),False)
                with patch.object(DirectReviewDialog,'exec',configure),patch.object(core,'open_request',side_effect=send) as request:
                    tab.start_direct_review();deadline=time.monotonic()+5
                    while tab.job and time.monotonic()<deadline:
                        app.processEvents()
                        if tab.pending_fingerprint:tab.decide(True)
                        time.sleep(.01)
                    app.processEvents()
                self.assertIsNone(tab.job);self.assertEqual(request.call_count,1);self.assertEqual(session['coding_context']['task'],'Earlier task');self.assertEqual(session['coding_plan']['steps'][0]['step'],'Keep');self.assertEqual(tab.composer.toPlainText(),'Unsent draft');self.assertTrue(tab.review_results)
            finally:window.close();app.processEvents();store.db.close()
