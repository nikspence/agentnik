"""Forced-process-stop recovery of opted-in review progress, offline only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

CHILD = r'''
import json, os, sys, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, os.environ['REVIEW_TEST_ROOT'])
sys.path.insert(0, str(Path(os.environ['REVIEW_TEST_ROOT']) / 'tests'))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication, QDialog
from agentnik import core
from agentnik.ui import Window
from agentnik.storage import Store
from agentnik.code_ui import DirectReviewDialog
from test_compat_tools import chat
from test_code_agent import call
from test_routing import Wire
root=Path(os.environ['REVIEW_TEST_DATA']);project=root/'project';project.mkdir();(project/'spec.md').write_text('SPEC',encoding='utf-8')
app=QApplication([]);store=Store(root/'data')
with patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
    window=Window(store);ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
    model={'url':'https://mock.invalid/v1','protocol':'chat','model':'reviewer','stream':False}
    window.connections['Review']=dict(model);box,alias=tab.roles['light'];box.addItem('Review','Review');box.setCurrentIndex(box.findData('Review'));alias.setText('reviewer');tab.light_enabled.setChecked(True)
    mode=os.environ['REVIEW_TEST_MODE'];heavy_count=[0]
    if mode=='heavy':
        window.connections['Heavy']=dict(model,model='heavy');box,alias=tab.roles['heavy'];box.addItem('Heavy','Heavy');box.setCurrentIndex(box.findData('Heavy'));alias.setText('heavy');tab.save_review_progress.setChecked(True);tab.composer.setPlainText('Review this document')
    def send(connection,url,body,timeout):
        if connection['model']=='reviewer':
            (root/'request-started').write_text('started',encoding='utf-8')
            time.sleep(60)
            return Wire(chat('{"version":1,"findings":[]}'),False)
        heavy_count[0]+=1
        if heavy_count[0]==1:
            passes=[{'role':'comprehension','model':'light','paths':[]},{'role':'design','model':'light','paths':[]}]
            return Wire(chat(calls=[call('review_document_parallel',{'path':'spec.md','passes':json.dumps(passes)})],finish='tool_calls'),False)
        return Wire(chat('Done'),False)
    def configure(dialog):dialog.target.setText('spec.md');dialog.save_progress.setChecked(True);return QDialog.DialogCode.Accepted
    with patch.object(core,'open_request',side_effect=send),patch.object(DirectReviewDialog,'exec',configure):
        if mode=='direct':tab.start_direct_review()
        else:tab.start_coding()
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            app.processEvents()
            if tab.pending_fingerprint:tab.decide(True)
            time.sleep(.01)
'''


class ReviewCrashRecovery(unittest.TestCase):
    def test_forced_stop_retains_interrupted_manifest_without_replay(self):
        from PySide6.QtWidgets import QApplication
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([]);repo=Path(__file__).resolve().parent.parent
        for mode in ('direct','heavy'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);script=root/'child.py';script.write_text(CHILD,encoding='utf-8');log=root/'child.log'
                env=dict(os.environ,REVIEW_TEST_ROOT=str(repo),REVIEW_TEST_DATA=str(root),REVIEW_TEST_MODE=mode,QT_QPA_PLATFORM='offscreen')
                with log.open('wb') as output:
                    process=subprocess.Popen([sys.executable,str(script)],cwd=str(repo),env=env,stdout=output,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    try:
                        deadline=time.monotonic()+20;marker=root/'request-started'
                        while not marker.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.05)
                        if not marker.exists():
                            output.flush();self.fail('Child did not reach the mocked reviewer: '+log.read_text(encoding='utf-8',errors='replace')[-2000:])
                    finally:
                        if process.poll() is None:process.kill()
                        process.wait(timeout=10)
                store=Store(root/'data')
                try:
                    sessions=store.list_sessions();self.assertEqual(len(sessions),1);saved=sessions[0]
                    reviews=saved['coding_review_history'][0]['reviews'];self.assertEqual(len(reviews),1 if mode=='direct' else 2)
                    self.assertTrue(all(item['pass_status']=='interrupted' for item in reviews))
                    self.assertTrue(all(item['batch_approved_at']==reviews[0]['batch_approved_at'] for item in reviews));self.assertRegex(reviews[0]['batch_approved_at'],r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
                    if mode=='heavy':self.assertTrue(all(item['status'] in ('queued','running') for item in saved.get('coding_subagents',[])))
                    with patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'open_request') as request:
                        window=Window(store)
                        try:
                            window.open_session(saved);app.processEvents();request.assert_not_called();self.assertTrue(window.tabs.currentWidget().saved_reviews_button.isEnabled())
                            if mode=='heavy':self.assertTrue(all(item['status']=='interrupted' for item in window.tabs.currentWidget().session['coding_subagents']))
                        finally:window.close();app.processEvents()
                finally:store.db.close()
