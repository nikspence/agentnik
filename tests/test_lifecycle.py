"""Offline bounded-worker, pinned transport, and Qt lifecycle contracts."""
import copy
import os
import socket
import ssl
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock,patch
from agentnik import core,research,tools,web
from agentnik.tools import Runtime,Limits,LimitError
from agentnik.storage import Store
from test_research import PUBLIC


class WorkerLifecycle(unittest.TestCase):
    def test_cancelled_workers_hold_capacity_until_they_actually_exit(self):
        slots=threading.BoundedSemaphore(2);release=threading.Event()
        entered=[threading.Event(),threading.Event()];finished=[threading.Event(),threading.Event()]
        runtimes=[Runtime(),Runtime()];outcomes=[];callers=[]
        def invoke(index):
            def stalled(): entered[index].set();release.wait(2);return 'late'
            try: runtimes[index].wait(stalled);outcomes.append('unexpected')
            except InterruptedError: outcomes.append('cancelled')
            finally: finished[index].set()
        with patch.object(tools,'_WORKER_SLOTS',slots):
            try:
                for index in range(2):
                    thread=threading.Thread(target=invoke,args=(index,));callers.append(thread);thread.start()
                for event in entered:self.assertTrue(event.wait(1))
                for runtime in runtimes:runtime.cancel.set()
                for event in finished:self.assertTrue(event.wait(1))
                # Repeated restart attempts cannot create further blocked workers.
                for _ in range(12):
                    with self.assertRaisesRegex(LimitError,'worker capacity'):Runtime().wait(lambda:self.fail('Must not start'))
                self.assertEqual(outcomes,['cancelled','cancelled'])
            finally:
                release.set()
                for thread in callers:thread.join(1)
                for _ in range(2):self.assertTrue(slots.acquire(timeout=1))
                for _ in range(2):slots.release()
            self.assertEqual(Runtime().wait(lambda:'new request'),'new request')

    def test_nested_waits_are_bounded_without_blocking_for_a_slot(self):
        with patch.object(tools,'_WORKER_SLOTS',threading.BoundedSemaphore(2)):
            runtime=Runtime();self.assertEqual(runtime.wait(lambda:runtime.wait(lambda:'DNS complete')),'DNS complete')
        with patch.object(tools,'_WORKER_SLOTS',threading.BoundedSemaphore(1)):
            runtime=Runtime()
            with self.assertRaisesRegex(LimitError,'worker capacity'):runtime.wait(lambda:runtime.wait(lambda:None))

    def test_timeout_and_thread_start_failure_do_not_leak_slots(self):
        slots=threading.BoundedSemaphore(1);release=threading.Event()
        with patch.object(tools,'_WORKER_SLOTS',slots):
            try:
                runtime=Runtime(limits=Limits(request_seconds=.03,turn_seconds=1))
                with self.assertRaises(LimitError):runtime.wait(lambda:release.wait(2))
                self.assertFalse(slots.acquire(blocking=False))
            finally:
                release.set();self.assertTrue(slots.acquire(timeout=1));slots.release()
            with patch.object(tools.threading,'Thread') as thread:
                thread.return_value.start.side_effect=RuntimeError('cannot start')
                with self.assertRaises(RuntimeError):Runtime().wait(lambda:None)
            self.assertTrue(slots.acquire(blocking=False));slots.release()


class AddressFailover(unittest.TestCase):
    def test_tcp_failover_uses_only_vetted_addresses_and_original_tls_name(self):
        addresses=PUBLIC+[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
        first=MagicMock();second=MagicMock();first.connect.side_effect=ConnectionRefusedError('first unreachable')
        context=MagicMock()
        with patch.object(web.socket,'socket',side_effect=[first,second]),patch.object(web.ssl,'create_default_context',return_value=context),patch.object(web.socket,'getaddrinfo') as dns:
            c=web.PinnedConnection('https://example.com/',addresses,5);c.connect()
        first.close.assert_called_once();second.connect.assert_called_once_with(addresses[1][-1]);dns.assert_not_called()
        context.wrap_socket.assert_called_once_with(second,server_hostname='example.com')

    def test_certificate_error_is_terminal_and_closes_socket(self):
        sock=MagicMock();context=MagicMock();context.wrap_socket.side_effect=ssl.SSLCertVerificationError('bad certificate')
        with patch.object(web.socket,'socket',return_value=sock) as create,patch.object(web.ssl,'create_default_context',return_value=context):
            with self.assertRaises(ssl.SSLCertVerificationError):web.PinnedConnection('https://example.com/',PUBLIC*2,5).connect()
        self.assertEqual(create.call_count,1);sock.close.assert_called_once()

    def test_failover_shares_one_deadline_and_skips_duplicate_addresses(self):
        addresses=PUBLIC+PUBLIC+[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
        first=MagicMock();second=MagicMock();first.connect.side_effect=OSError('unreachable')
        with patch.object(web.socket,'socket',side_effect=[first,second]),patch.object(web.time,'monotonic',side_effect=[0,1,4,5]):
            c=web.PinnedConnection('http://example.com/',addresses,10);c.connect()
        first.settimeout.assert_called_once_with(9)
        self.assertEqual(second.settimeout.call_args_list[0].args,(6,))
        with patch.object(web.socket,'socket') as create,patch.object(web.time,'monotonic',side_effect=[0,2]):
            with self.assertRaises(TimeoutError):web.PinnedConnection('http://example.com/',PUBLIC,1).connect()
            create.assert_not_called()


class QtLifecycle(unittest.TestCase):
    def test_thinking_choice_survives_completion_and_reopen_in_both_themes(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window,MessageBubble
        app=QApplication.instance() or QApplication([])
        c={'url':'https://gateway.example/v1','protocol':'chat','model':'mock'}
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(directory);store.config['connections']={'test':c};window=Window(store)
            try:
                for theme,visible in [('Light',False),('Dark',True)]:
                    window.theme.setCurrentText(theme);window.new_session('chat','test');tab=window.tabs.currentWidget();app.processEvents()
                    tab.pending={'role':'user','text':'Test','images':[]};tab.research_connection=tab.active_connection()
                    tab.job=MagicMock();tab.job.cancel.is_set.return_value=False;tab.research_running=True
                    tab.partial={'text':'Partial','thinking':'Reasoning'};tab.render()
                    tab.live_bubble.thinking_toggle.setChecked(visible)
                    result={'status':'ok','text':'Answer','thinking':'Reasoning','metrics':{},'research':{'version':2,'status':'completed','route':'managed','sources':[],'events':[]}}
                    tab.complete_research(result)
                    saved=next(s for s in store.list_sessions() if s['id']==tab.session['id'])
                    self.assertEqual(saved['messages'][-1]['thinking_visible'],visible)
                    window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents()
                    bubbles=window.tabs.currentWidget().findChildren(MessageBubble)
                    self.assertEqual(bubbles[-1].thinking_toggle.isChecked(),visible)
            finally:window.close();app.processEvents();store.db.close()


    def test_two_tabs_cancel_restart_and_late_result_isolation(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        release=[threading.Event(),threading.Event()];entered=[threading.Event(),threading.Event()]
        slots=threading.BoundedSemaphore(2)
        def settle(predicate):
            deadline=time.monotonic()+2
            while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertTrue(predicate());app.processEvents()
        def work(c,messages,key,emit,cancel,**kwargs):
            index=int(c['model']);runtime=Runtime(cancel)
            def stalled():
                entered[index].set();release[index].wait(3)
                return {'status':'ok','text':'late '+str(index),'thinking':'','metrics':{},
                        'research':{'version':2,'status':'completed','sources':[],'events':[]}}
            try:return runtime.wait(stalled)
            finally:runtime.closed=True
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]),patch.object(research,'run',side_effect=work),patch.object(tools,'_WORKER_SLOTS',slots):
            store=Store(directory)
            store.config['connections']={str(i):{'url':'https://gateway.example/v1','protocol':'chat','model':str(i)} for i in range(2)}
            window=Window(store);tabs=[];jobs=[]
            try:
                for i in range(2):
                    window.new_session('chat',str(i));tab=window.tabs.currentWidget();tabs.append(tab);app.processEvents()
                    tab.web_access.setChecked(True);tab.composer.setPlainText('Draft '+str(i));tab.submit();jobs.append(tab.job)
                settle(lambda:all(e.is_set() for e in entered))
                tabs[0].cancel();self.assertEqual(tabs[0].composer.toPlainText(),'Draft 0')
                self.assertIsNotNone(tabs[1].job);self.assertEqual(tabs[1].session['messages'],[])
                tabs[0].submit();settle(lambda:tabs[0].job is None)
                self.assertIn('worker capacity',tabs[0].session['messages'][-1]['error'])
                before=copy.deepcopy(tabs[0].session['messages'])
                release[0].set();release[1].set();settle(lambda:tabs[1].job is None)
                for job in jobs:job.thread.join(1)
                app.processEvents()
                self.assertEqual(tabs[0].session['messages'],before)
                self.assertEqual(tabs[1].session['messages'][-1]['text'],'late 1')
                self.assertEqual(tabs[0].composer.toPlainText(),'Draft 0')
            finally:
                for event in release:event.set()
                for tab in tabs:
                    if tab.job:tab.cancel()
                window.close();app.processEvents();store.db.close()

    def test_saved_connection_remains_distinct_from_merged_discovery(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        env={'env:local':{'url':'http://127.0.0.1:11434/v1','protocol':'chat','model':'environment-model','api_key':'environment-key'}}
        probe={'probe':{'url':'http://localhost:11434/v1','protocol':'responses','model':'probe-model'}}
        saved={'url':'http://localhost:11434/v1','protocol':'messages','model':'saved-model','api_key':'saved-key'}
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value=env):
            store=Store(directory);store.config['connections']={'Saved':saved};window=Window(store)
            try:
                window.local=probe;window.reload_connections();app.processEvents()
                self.assertEqual(len(window.connections),2)
                self.assertEqual(window.connections['Saved']['model'],'saved-model')
                self.assertEqual(window.connections['Saved']['protocol'],'messages')
                self.assertEqual(window.connections['Saved']['api_key'],'saved-key')
                discovered=next(v for k,v in window.connections.items() if k!='Saved')
                self.assertEqual(discovered['model'],'environment-model')
                self.assertEqual(discovered['protocol'],'chat')
                self.assertEqual(discovered['api_key'],'environment-key')
            finally:window.close();app.processEvents();store.db.close()


if __name__=='__main__':unittest.main()
