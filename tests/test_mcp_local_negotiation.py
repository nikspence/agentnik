import sys
import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from agentnik.mcp_local import LocalSession


class LocalNegotiationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def exercise(self,mode):
        with tempfile.TemporaryDirectory() as folder:
            record=Path(folder)/'record.txt';script=Path(__file__).parent/'fixtures'/'mcp_local_negotiation.py'
            session=LocalSession(sys.executable,['-u',str(script),mode,str(record)],timeout_seconds=6);loop=QEventLoop();out=[]
            session.discovered.connect(lambda value:(out.append(value),loop.quit()));session.ended.connect(lambda value:(out.append(value),loop.quit()))
            timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(8000);session.start()
            try:
                loop.exec();timer.stop();self.assertTrue(out);session.close();return out[0],record.read_text().splitlines()
            finally:session.close()

    def test_dual_era_server_uses_modern_without_initializing(self):
        result,calls=self.exercise('modern');self.assertEqual(result['protocol'],'2026-07-28');self.assertEqual(calls,['start','server/discover'])

    def test_legacy_error_uses_same_process(self):
        result,calls=self.exercise('error');self.assertEqual(result['protocol'],'2025-11-25');self.assertEqual(calls,['start','server/discover','initialize','notifications/initialized'])

    def test_legacy_exiting_or_ignoring_probe_is_restarted_once(self):
        for mode in ('exit','silent'):
            with self.subTest(mode=mode):
                result,calls=self.exercise(mode);self.assertEqual(result['protocol'],'2025-11-25');self.assertEqual(calls,['start','server/discover','start','initialize','notifications/initialized'])

    def test_modern_protocol_error_does_not_fallback(self):
        result,calls=self.exercise('modern_error');self.assertIn('-32022',result['error']);self.assertNotIn('private',str(result));self.assertEqual(calls,['start','server/discover'])

    def test_slow_modern_server_can_recover_after_probe_timeout(self):
        result,calls=self.exercise('slow_modern');self.assertEqual(result['protocol'],'2026-07-28');self.assertEqual(calls,['start','start','initialize','server/discover'])

    def test_stop_during_probe_does_not_restart_server(self):
        with tempfile.TemporaryDirectory() as folder:
            record=Path(folder)/'record.txt';script=Path(__file__).parent/'fixtures'/'mcp_local_negotiation.py'
            session=LocalSession(sys.executable,['-u',str(script),'silent',str(record)],timeout_seconds=2);loop=QEventLoop()
            def stop_after_probe():
                if record.exists() and 'server/discover' in record.read_text():session.close();QTimer.singleShot(1200,loop.quit)
                else:QTimer.singleShot(10,stop_after_probe)
            timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(5000);session.start();QTimer.singleShot(10,stop_after_probe)
            try:
                loop.exec();timer.stop();self.assertTrue(session.closed);self.assertEqual(record.read_text().splitlines(),['start','server/discover'])
            finally:session.close()
