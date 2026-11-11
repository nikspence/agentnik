import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from agentnik.mcp_support import PROTOCOL,parse_initialize,validate_servers
from agentnik.storage import Store,load_config,ConfigurationError


class MCPFoundation(unittest.TestCase):
    def test_configuration_validation_and_persistence(self):
        item={'name':'Local','command':sys.executable,'args':['server.py'],'enabled':True}
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            try:store.config['mcp_servers']=[item];store.flush();self.assertEqual(load_config(store.config_path)['mcp_servers'],[item])
            finally:store.db.close()
            for invalid in ([item,item],[dict(item,args='unsafe')],[dict(item,enabled=1)],[dict(item,api_key='secret')]):
                with self.assertRaises(ValueError):validate_servers(invalid)
            Path(folder,'connections.json').write_text(json.dumps({'version':1,'connections':{},'settings':{},'mcp_servers':[dict(item,args='bad')]}),encoding='utf-8')
            with self.assertRaises(ConfigurationError):load_config(Path(folder,'connections.json'))

    def test_protocol_response_validation(self):
        result={'jsonrpc':'2.0','id':1,'result':{'protocolVersion':PROTOCOL,'serverInfo':{'name':'Example','version':'1'},'capabilities':{'tools':{},'resources':{}}}}
        self.assertEqual(parse_initialize(json.dumps(result).encode())['capabilities'],['tools','resources'])
        for message in (b'not json',json.dumps(dict(result,id=True)).encode(),json.dumps(dict(result,result={'protocolVersion':'different'})).encode()):
            with self.assertRaises(ValueError):parse_initialize(message)

    def test_explicit_local_initialization_and_no_launch_on_open(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication,QMessageBox
        from agentnik.mcp_ui import MCPServers
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);marker=root/'started';server=root/'server.py'
            server.write_text('import json,sys,pathlib\npathlib.Path(sys.argv[1]).write_text("started")\nrequest=json.loads(sys.stdin.readline())\nprint(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":{"protocolVersion":request["params"]["protocolVersion"],"serverInfo":{"name":"Fake","version":"1"},"capabilities":{"tools":{}}}}),flush=True)\n',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Fake','command':sys.executable,'args':[str(server),str(marker)],'enabled':True}];store.flush();window=Window(store)
            try:
                dialog=MCPServers(window);dialog.list.setCurrentRow(0);self.assertFalse(marker.exists())
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):dialog.test()
                loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if dialog.process is None else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                self.assertIsNone(dialog.process);self.assertTrue(marker.exists());self.assertIn('Initialization response: Fake',dialog.status.text());self.assertIn('tools',dialog.status.text());dialog.close()
            finally:window.close();app.processEvents();store.db.close()
