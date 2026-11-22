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
