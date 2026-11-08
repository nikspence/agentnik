"""Offline simulation and exact-proposal approval contracts."""
import copy
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from agentnik.coding import SimulationRun,CommandProposal
from agentnik import core
from agentnik.storage import Store


class ApprovalContract(unittest.TestCase):
    def test_exact_approval_rejects_mutation_duplicate_and_stale_decisions(self):
        run=SimulationRun('project');events=[];ready=threading.Event()
        def emit(event):events.append(event);ready.set()
        with patch('subprocess.Popen') as process:
            thread=threading.Thread(target=run.run,args=(emit,));thread.start()
            try:
                self.assertTrue(ready.wait(1));proposal=run.pending
                changed=CommandProposal(proposal.run_id,proposal.command_id,('git','clean','-fd'),proposal.cwd)
                self.assertFalse(run.decide(changed.fingerprint,True))
                self.assertTrue(run.decide(proposal.fingerprint,True))
                self.assertFalse(run.decide(proposal.fingerprint,True));thread.join(1)
                self.assertFalse(thread.is_alive());self.assertEqual(events[-1]['status'],'completed')
                self.assertIn('diff',[e['kind'] for e in events]);process.assert_not_called()
                self.assertFalse(run.decide(proposal.fingerprint,True))
            finally:run.stop();thread.join(1)

    def test_rejection_timeout_and_cancel_do_not_produce_fake_execution_output(self):
        for action in ('reject','timeout','cancel'):
            with self.subTest(action=action):
                run=SimulationRun('project',seconds=.03 if action=='timeout' else 1);events=[];ready=threading.Event()
                def emit(event):events.append(event);ready.set()
                thread=threading.Thread(target=run.run,args=(emit,));thread.start()
                try:
                    self.assertTrue(ready.wait(1));fingerprint=run.pending.fingerprint
                    if action=='reject':self.assertTrue(run.decide(fingerprint,False))
                    elif action=='cancel':run.stop()
                    thread.join(1);self.assertFalse(thread.is_alive())
                    self.assertNotIn('output',[e['kind'] for e in events])
                    self.assertFalse(run.decide(fingerprint,True))
                finally:run.stop();thread.join(1)


class SimulationUI(unittest.TestCase):
    def test_approve_cancel_stale_events_and_interrupted_reopen(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        def settle(predicate):
            deadline=time.monotonic()+2
            while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertTrue(predicate())
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'open_request') as request,patch('subprocess.Popen') as process:
            root=Path(directory);folder=root/'project';folder.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(folder);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();tab.composer.setPlainText('Keep draft')
                tab.start_simulation();settle(lambda:tab.approve.isEnabled())
                self.assertIn('Not checked',tab.approval.toPlainText());tab.decide(True);settle(lambda:tab.job is None)
                self.assertIn('SIMULATED DIFF',tab.diff.toPlainText());self.assertEqual(tab.composer.toPlainText(),'Keep draft')
                tab.start_simulation();settle(lambda:tab.approve.isEnabled());old=tab.run_id;worker=tab.worker
                tab.cancel();before=copy.deepcopy(tab.session)
                tab.receive({'run_id':old,'kind':'finished','status':'completed','text':'LATE'})
                worker.join(1);app.processEvents();self.assertEqual(tab.session,before)
                tab.session['code_state']='awaiting_approval';store.save(tab.session)
                saved=next(s for s in store.list_sessions() if s['id']==session['id'])
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents()
                reopened=window.tabs.currentWidget();self.assertIsNone(reopened.job)
                self.assertEqual(reopened.session['code_state'],'interrupted')
                self.assertEqual(reopened.composer.toPlainText(),'Keep draft');request.assert_not_called();process.assert_not_called()
            finally:window.close();app.processEvents();store.db.close()


if __name__=='__main__':unittest.main()
