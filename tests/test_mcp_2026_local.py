import sys
import json
import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from agentnik.mcp_local import LocalSession


class ModernLocalSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_modern_only_stdio_discovery_and_tool_call(self):
        server=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py'
        session=LocalSession(sys.executable,['-u',str(server)],timeout_seconds=5);loop=QEventLoop();out=[];info=[]
        def discovered(result):info.append(result);session.call(result['tool_details'][0],{'text':'hello'})
        session.discovered.connect(discovered);session.called.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertTrue(out);self.assertEqual(info[0]['protocol'],'2026-07-28');self.assertEqual(out[0]['call_result']['content'][0]['text'],'hello')
        finally:session.close()

    def test_initialization_envelope_errors_probe_modern_stdio(self):
        server=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py'
        for code in (-32600,-32601,-32602,-32020,-32022):
            with self.subTest(code=code):
                session=LocalSession(sys.executable,['-u',str(server),'--init-error='+str(code)],timeout_seconds=5);loop=QEventLoop();out=[]
                session.discovered.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
                timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
                try:loop.exec();timer.stop();self.assertEqual(out[0]['protocol'],'2026-07-28')
                finally:session.close()

    def test_legacy_initialization_can_finish_after_modern_probe_version_error(self):
        script='''import json,sys,time,threading
def send_init(ident):
 time.sleep(1.5)
 result={"protocolVersion":"2025-11-25","serverInfo":{"name":"slow","version":"1"},"capabilities":{"tools":{}}}
 print(json.dumps({"jsonrpc":"2.0","id":ident,"result":result}),flush=True)
for line in sys.stdin:
 m=json.loads(line);method=m.get("method")
 if "id" not in m:continue
 if method=="initialize":threading.Thread(target=send_init,args=(m["id"],),daemon=True).start();continue
 if method=="server/discover":reply={"error":{"code":-32022} if sys.argv[1]=="malformed" else {"code":-32022,"message":"unsupported","data":{"supported":["2025-11-25"]}}}
 elif method=="tools/list":reply={"result":{"tools":[]}}
 else:raise RuntimeError(method)
 print(json.dumps(dict(reply,jsonrpc="2.0",id=m["id"])),flush=True)
'''
        with tempfile.TemporaryDirectory() as directory:
            server=Path(directory)/'legacy.py';server.write_text(script,encoding='utf-8')
            for mode in ('unsupported','malformed'):
                with self.subTest(mode=mode):
                    session=LocalSession(sys.executable,['-u',str(server),mode],timeout_seconds=5);loop=QEventLoop();out=[]
                    session.discovered.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
                    timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
                    try:loop.exec();timer.stop();self.assertEqual(out[0]['protocol'],'2025-11-25');self.assertEqual(out[0]['name'],'slow')
                    finally:session.close()

    def test_cancellation_notifies_modern_stdio_server(self):
        server=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py'
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'cancel.json';session=LocalSession(sys.executable,['-u',str(server),str(output)],timeout_seconds=5);loop=QEventLoop()
            session.discovered.connect(lambda result:session.call(result['tool_details'][0],{'text':'wait'}))
            session.progress.connect(lambda _: (session.close(),loop.quit()))
            session.ended.connect(lambda _:loop.quit());timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
            try:
                loop.exec();timer.stop();self.assertTrue(output.exists());record=json.loads(output.read_text());self.assertEqual(record['requestId'],record['original'])
            finally:session.close()

    def test_silent_modern_server_is_probed(self):
        server=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py'
        session=LocalSession(sys.executable,['-u',str(server),'--ignore-initialize'],timeout_seconds=5);loop=QEventLoop();out=[]
        session.discovered.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertTrue(out);self.assertEqual(out[0]['protocol'],'2026-07-28')
        finally:session.close()

    def test_delayed_legacy_rejection_uses_existing_modern_probe(self):
        server=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py'
        session=LocalSession(sys.executable,['-u',str(server),'--delay-reject'],timeout_seconds=5);loop=QEventLoop();out=[]
        session.discovered.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertTrue(out);self.assertEqual(out[0]['protocol'],'2026-07-28')
        finally:session.close()

    def test_slow_legacy_server_ignores_outstanding_probe_response(self):
        script='''import json,sys,time
for line in sys.stdin:
 m=json.loads(line);method=m.get("method")
 if "id" not in m:continue
 if method=="initialize":
  time.sleep(1.3);result={"protocolVersion":"2025-11-25","serverInfo":{"name":"slow","version":"1"},"capabilities":{"tools":{}}};reply={"result":result}
 elif method=="server/discover":reply={"error":{"code":-32601,"message":"unknown"}}
 elif method=="tools/list":reply={"result":{"tools":[]}}
 else:raise RuntimeError(method)
 print(json.dumps(dict(reply,jsonrpc="2.0",id=m["id"])),flush=True)
'''
        with tempfile.TemporaryDirectory() as directory:
            server=Path(directory)/'legacy.py';server.write_text(script,encoding='utf-8')
            session=LocalSession(sys.executable,['-u',str(server)],timeout_seconds=5);loop=QEventLoop();out=[]
            session.discovered.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
            timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
            try:
                loop.exec();timer.stop();self.assertTrue(out);self.assertEqual(out[0]['protocol'],'2025-11-25');self.assertEqual(out[0]['name'],'slow')
            finally:session.close()

    def test_subscription_notices_are_multiplexed_with_tool_response(self):
        server=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py'
        session=LocalSession(sys.executable,['-u',str(server),'--subscriptions'],timeout_seconds=5);loop=QEventLoop();out=[];events=[]
        def discovered(result):
            session.resource_items=[{'uri':'test://old'}];session.prompt_items=[{'name':'old'}]
            session.call(result['tool_details'][0],{'text':'notify'})
        session.discovered.connect(discovered);session.progress.connect(events.append);session.called.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertEqual(out[0]['call_result']['content'][0]['text'],'notify');self.assertEqual(session.resource_items,[]);self.assertEqual(session.prompt_items,[]);self.assertEqual(len([text for text in events if 'changed' in text]),2)
        finally:session.close()

    def test_invalid_subscription_acknowledgement_invalidates_cached_listings(self):
        session=LocalSession(sys.executable,[]);session.modern=True;session.subscription_active=True;session.info={'subscription_filters':{'resourcesListChanged':True}};session.resource_items=[{'uri':'test://old'}];session.prompt_items=[{'name':'old'}];events=[];session.progress.connect(events.append)
        session.subscription_notification({'method':'notifications/subscriptions/acknowledged','params':{'notifications':{'resourcesListChanged':True},'_meta':{'io.modelcontextprotocol/subscriptionId':42}}})
        self.assertFalse(session.subscription_active);self.assertEqual(session.resource_items,[]);self.assertEqual(session.prompt_items,[]);self.assertTrue(any('invalid' in text for text in events));session.close()

    def test_ended_subscription_reopens_with_new_identifier(self):
        server=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py'
        session=LocalSession(sys.executable,['-u',str(server),'--subscriptions','--end-first-subscription'],timeout_seconds=5);loop=QEventLoop();events=[]
        session.progress.connect(events.append);session.ended.connect(lambda _:loop.quit())
        poll=QTimer();poll.timeout.connect(lambda:loop.quit() if session.subscription_id==-2 and session.subscription_ack is not None else None);poll.start(25)
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();poll.stop();self.assertEqual(session.subscription_id,-2);self.assertTrue(session.subscription_active);self.assertIsNotNone(session.subscription_ack);self.assertTrue(any('subscription ended' in text for text in events))
        finally:session.close()

    def test_input_required_is_reported_without_continuation(self):
        server=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py'
        session=LocalSession(sys.executable,['-u',str(server)],timeout_seconds=5);loop=QEventLoop();out=[]
        session.discovered.connect(lambda result:session.call(result['tool_details'][0],{'text':'input'}));session.called.connect(lambda result:(out.append(('called',result)),loop.quit()));session.ended.connect(lambda result:(out.append(('ended',result)),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertEqual(out[0][0],'ended');self.assertIn('interactive input',out[0][1]['error']);self.assertTrue(out[0][1]['call_uncertain']);self.assertNotIn('private',str(out))
        finally:session.close()

    def test_prompt_and_resource_input_requirements_are_reported(self):
        server=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py'
        for kind in ('resource','prompt'):
            with self.subTest(kind=kind):
                session=LocalSession(sys.executable,['-u',str(server),'--'+kind+'-input'],timeout_seconds=5);loop=QEventLoop();out=[]
                def discovered(_):session.list_resources() if kind=='resource' else session.list_prompts()
                def resources(result):session.read_resource(result['resources'][0]['uri'])
                def prompts(result):session.list_prompts({'prompt':result['prompts'][0],'arguments':{}})
                session.discovered.connect(discovered);session.resources.connect(resources);session.prompts.connect(prompts);session.ended.connect(lambda result:(out.append(result),loop.quit()))
                timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
                try:
                    loop.exec();timer.stop();self.assertTrue(out);self.assertIn('interactive input',out[0]['error']);self.assertFalse(out[0]['call_uncertain']);self.assertNotIn('private',str(out))
                finally:session.close()

    def test_prompt_and_resource_form_responses_continue(self):
        server=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py'
        for kind in ('resource','prompt'):
            with self.subTest(kind=kind):
                session=LocalSession(sys.executable,['-u',str(server),'--'+kind+'-input'],timeout_seconds=5);session.elicitation_enabled=True;loop=QEventLoop();out=[];step=[]
                def discovered(_):session.list_resources() if kind=='resource' else session.list_prompts()
                def resources(result):
                    if not step:step.append(True);session.read_resource(result['resources'][0]['uri'])
                    else:out.append(result);loop.quit()
                def prompts(result):
                    if not step:step.append(True);session.list_prompts({'prompt':result['prompts'][0],'arguments':{}})
                    else:out.append(result);loop.quit()
                session.discovered.connect(discovered);session.resources.connect(resources);session.prompts.connect(prompts);session.elicitation_requested.connect(lambda _:session.continue_elicitation({'question':{'action':'accept','content':{'choice':'yes'}}}));session.ended.connect(lambda result:(out.append(result),loop.quit()))
                timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
                try:
                    loop.exec();timer.stop();self.assertTrue(out)
                    text=out[0]['contents'][0]['text'] if kind=='resource' else out[0]['messages'][0]['content']['text']
                    self.assertEqual(text,'continued')
                finally:session.close()
