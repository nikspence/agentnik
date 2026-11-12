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
    def test_tool_result_audiences_are_separated_without_mutation(self):
        from agentnik.mcp_content import model_tool_result
        content=[{'type':'text','text':'public'}, {'type':'text','text':'user-only','annotations':{'audience':['user']}},
                 {'type':'text','text':'model-only','annotations':{'audience':['assistant']}},
                 {'type':'text','text':'both','annotations':{'audience':['user','assistant']}},
                 {'type':'image','data':'user-binary','mimeType':'image/png','annotations':{'audience':['user']}},
                 {'type':'text','text':'neither','annotations':{'audience':[]}}]
        result={'content':content,'structuredContent':{'count':1},'isError':False};model,user,nontext=model_tool_result(result)
        self.assertEqual([x['text'] for x in model['content']],['public','model-only','both']);self.assertEqual(user,['user-only']);self.assertEqual(nontext,1)
        self.assertEqual(result['content'],content);self.assertEqual(model['structuredContent'],{'count':1})
        for invalid in (None,{},['user',3],['invalid'],'user'):
            with self.subTest(audience=invalid),self.assertRaises(ValueError):model_tool_result({'content':[{'type':'text','text':'x','annotations':{'audience':invalid}}]})
        for invalid in (None,[],{'audience':None}):
            with self.subTest(annotations=invalid),self.assertRaises(ValueError):model_tool_result({'content':[{'type':'text','text':'x','annotations':invalid}]})

    def test_structured_tool_output_schema_validation_and_definition_identity(self):
        from agentnik.mcp_schema import validate_tool_result
        from agentnik.mcp_remote import preview_tool
        output={'type':'object','properties':{'count':{'type':'integer','minimum':0}},'required':['count'],'additionalProperties':False}
        tool=preview_tool({'inputSchema':{'type':'object'},'outputSchema':output})
        self.assertEqual(tool['output_schema'],output);self.assertEqual(tool['output_schema_status'],'available')
        self.assertTrue(validate_tool_result(tool,{'content':[],'structuredContent':{'count':1}}))
        self.assertTrue(validate_tool_result(tool,{'content':[],'isError':True}))
        for result in ({'content':[]},{'content':[],'structuredContent':{'count':-1}},{'content':[],'structuredContent':[]}, {'content':[],'structuredContent':{'count':1,'extra':True}}):
            with self.subTest(result=result),self.assertRaises(ValueError):validate_tool_result(tool,result)
        changed=preview_tool({'inputSchema':{'type':'object'},'outputSchema':dict(output,required=[])})
        self.assertNotEqual(tool,changed)
        self.assertEqual(preview_tool({'inputSchema':{'type':'object'},'outputSchema':{'description':'x'*33000}})['output_schema_status'],'oversized')
        with self.assertRaises(ValueError):preview_tool({'outputSchema':[]})
        external=preview_tool({'inputSchema':{'type':'object'},'outputSchema':{'type':'object','$ref':'https://example.com/schema'}})
        with self.assertRaises(ValueError):validate_tool_result(external,{'structuredContent':{}})

    def test_argument_schema_validation_and_unsupported_features(self):
        from agentnik.mcp_schema import validate_tool_arguments
        schema={'type':'object','properties':{'query':{'type':'string'},'n':{'type':'integer','minimum':1}},'required':['query'],'additionalProperties':False}
        self.assertTrue(validate_tool_arguments(schema,{'query':'MCP','n':2}))
        for arguments in ({},{'query':3},{'query':'ok','n':0},{'query':'ok','extra':True}):
            with self.subTest(arguments=arguments),self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,arguments)
        self.assertTrue(validate_tool_arguments({'type':'object','properties':{'database':{'anyOf':[{'type':'string'},{'type':'null'}]}}},{'database':None}))
        for unsafe in ({'type':'object','$ref':'https://example.com/schema'},{'type':'object','properties':{'q':{'type':'string','pattern':'(a+)+$'}}}):
            with self.subTest(schema=unsafe),self.assertRaisesRegex(ValueError,'unsupported'):validate_tool_arguments(unsafe,{})
        with self.assertRaisesRegex(ValueError,'invalid'):validate_tool_arguments({'type':'object','required':'query'}, {})

    def test_schema_local_definitions_unions_and_bounds(self):
        from agentnik.mcp_schema import validate_tool_arguments
        schema={'type':'object','$defs':{
            'record':{'type':'object','properties':{'id':{'type':'integer','minimum':1}},'required':['id'],'additionalProperties':False},
            'alias/name':{'type':'string','minLength':1}},
            'properties':{'item':{'$ref':'#/$defs/record'},'name':{'$ref':'#/$defs/alias~1name'},
                          'mode':{'oneOf':[{'const':'quick'},{'const':'full'}]},
                          'value':{'anyOf':[{'type':'integer'},{'type':'string'},{'type':'null'}]}},
            'allOf':[{'required':['item','name']},{'required':['mode']}],'additionalProperties':False}
        self.assertTrue(validate_tool_arguments(schema,{'item':{'id':3},'name':'sample','mode':'quick','value':None}))
        for arguments in ({'item':{'id':0},'name':'sample','mode':'quick'},{'item':{'id':1},'name':'sample','mode':'other'},{'item':{'id':1},'name':'','mode':'full'}):
            with self.subTest(arguments=arguments),self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,arguments)
        cyclic={'type':'object','$defs':{'x':{'$ref':'#/$defs/y'},'y':{'$ref':'#/$defs/x'}},'properties':{'x':{'$ref':'#/$defs/x'}}}
        with self.assertRaisesRegex(ValueError,'recursive'):validate_tool_arguments(cyclic,{})
        for reference in ('https://example.com/s.json','#','file:///secret','#/$defs/missing','#/$defs/a%2Fb','#/$defs/a~2b','#/$defs/a/extra'):
            with self.subTest(reference=reference),self.assertRaises(ValueError):validate_tool_arguments({'type':'object','$defs':{'a':{'type':'string'}},'properties':{'x':{'$ref':reference}}},{})
        broad={'type':'object','properties':{'x':{'anyOf':[{'anyOf':[{'const':n} for n in range(8)]} for _ in range(8)]}}}
        with self.assertRaisesRegex(ValueError,'complex'):validate_tool_arguments(broad,{})
        with self.assertRaises(ValueError):validate_tool_arguments({'type':'object','allOf':[]},{})

    def test_schema_legacy_definitions_and_cross_namespace_cycles(self):
        from agentnik.mcp_schema import validate_tool_arguments
        schema={'type':'object','definitions':{'key/name':{'type':'integer','minimum':1},'alias':{'$ref':'#/$defs/target'}},'$defs':{'target':{'$ref':'#/definitions/key~1name'}},'properties':{'id':{'$ref':'#/definitions/alias'}},'required':['id']}
        self.assertTrue(validate_tool_arguments(schema,{'id':2}))
        with self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,{'id':0})
        cycle={'type':'object','definitions':{'x':{'$ref':'#/$defs/y'}},'$defs':{'y':{'$ref':'#/definitions/x'}}}
        with self.assertRaisesRegex(ValueError,'recursive'):validate_tool_arguments(cycle,{})
        for invalid in ({'type':'object','definitions':{'bad':{'pattern':'(a+)+$'}}}, {'type':'object','properties':{'x':{'definitions':{'y':{'type':'string'}}}}}, {'type':'object','definitions':{str(i):{} for i in range(129)}}, {'type':'object','definitions':{'a':{}},'properties':{'x':{'$ref':'#/definitions/a/extra'}}}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):validate_tool_arguments(invalid,{})

    def test_draft7_tool_schema_uses_declared_dialect_and_bounded_references(self):
        from agentnik.mcp_schema import validate_tool_arguments
        for uri in ('http://json-schema.org/draft-07/schema#','https://json-schema.org/draft-07/schema'):
            with self.subTest(uri=uri):
                schema={'$schema':uri,'type':'object','definitions':{'item':{'type':'integer','minimum':1}},'properties':{'id':{'$ref':'#/definitions/item','maximum':2}},'required':['id']}
                self.assertTrue(validate_tool_arguments(schema,{'id':3})) # Draft 7 ignores $ref siblings.
                with self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,{'id':0})
                with self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,{})
        schema['$schema']='https://json-schema.org/draft/2020-12/schema'
        with self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,{'id':3})
        for invalid in ({'$schema':'http://json-schema.org/draft-04/schema#','type':'object'}, {'$schema':'http://json-schema.org/draft-07/schema#','type':'object','properties':{'x':{'$schema':'http://json-schema.org/draft-07/schema#'}}}, {'$schema':'http://json-schema.org/draft-07/schema#','type':'object','definitions':{'x':{'$ref':'#/definitions/x'}}}):
            with self.subTest(schema=invalid),self.assertRaises(ValueError):validate_tool_arguments(invalid,{})

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

    def test_server_timeout_validation_and_legacy_defaults(self):
        from agentnik.mcp_support import server_timeout,server_fingerprint
        local={'name':'Local','command':sys.executable,'args':[],'enabled':True}
        remote={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        for item in (local,remote):
            self.assertEqual(server_timeout(item),60)
            self.assertEqual(server_timeout(dict(item,timeout_seconds=300)),300)
            self.assertNotEqual(server_fingerprint(item),server_fingerprint(dict(item,timeout_seconds=300)))
            for value in (0,901,True,1.5,'60',None):
                with self.subTest(value=value),self.assertRaises(ValueError):validate_servers([dict(item,timeout_seconds=value)])

    def test_working_directory_configuration_is_absolute_and_fingerprinted(self):
        from agentnik.mcp_support import server_fingerprint
        item={'name':'Local','command':sys.executable,'args':[],'enabled':True}
        with tempfile.TemporaryDirectory() as directory:
            changed=dict(item,working_directory=directory);validate_servers([changed])
            self.assertNotEqual(server_fingerprint(item),server_fingerprint(changed))
            with tempfile.TemporaryDirectory() as data:
                store=Store(data)
                try:store.config['mcp_servers']=[changed];store.flush();self.assertEqual(load_config(store.config_path)['mcp_servers'],[changed])
                finally:store.db.close()
        for value in ('relative/path','../folder','C:relative',3,'x\x00y'):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_servers([dict(item,working_directory=value)])
        remote={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True,'working_directory':'/tmp'}
        with self.assertRaises(ValueError):validate_servers([remote])

    def test_local_server_launches_in_configured_working_directory(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);work=root/'server-work';work.mkdir();server=root/'server.py'
            server.write_text('''import json,os,sys
for line in sys.stdin:
 req=json.loads(line)
 if req['method']=='initialize':
  result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':os.getcwd(),'version':'1'},'capabilities':{}}
  print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],working_directory=str(work));loop=QEventLoop();out=[]
            session.discovered.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(Path(out[0]['name']).resolve(),work.resolve())
        with self.assertRaises(ValueError):LocalSession(sys.executable,[],working_directory='relative')

    def test_local_and_remote_operation_timers_use_configured_timeout(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        from agentnik.mcp_remote import RemoteProbe,RemoteSession
        app=QApplication.instance() or QApplication([])
        local=LocalSession(sys.executable,[],timeout_seconds=180);local.phase='ready'
        tool={'name':'test','schema_status':'available','task_support':'forbidden'};local.details=[tool]
        try:
            with patch.object(local,'list_page'):
                self.assertTrue(local.call(tool,{}));self.assertEqual(local.timer.interval(),180000)
            local.timer.stop()
            remote=RemoteSession('https://example.com/mcp','',timeout_seconds=240);remote.phase='ready'
            with patch.object(remote,'send'):
                self.assertTrue(remote.call(tool,{}));self.assertEqual(remote.timer.interval(),240000)
            remote.timer.stop()
            probe=RemoteProbe('https://example.com/mcp','',timeout_seconds=120)
            with patch.object(probe,'send'):
                probe.start();self.assertEqual(probe.timer.interval(),120000)
            probe.timer.stop()
        finally:local.close();app.processEvents()

    def test_manager_saves_and_loads_per_server_timeout(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QFileDialog
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}):
            store=Store(folder);window=Window(store);dialog=MCPServers(window)
            try:
                dialog.new();dialog.name.setText('Local');dialog.command.setText(sys.executable);dialog.timeout.setValue(300)
                with patch.object(QFileDialog,'getExistingDirectory',return_value=folder):dialog.working_directory_button.click()
                self.assertEqual(dialog.working_directory.text(),folder);dialog.save()
                self.assertEqual(store.config['mcp_servers'][0]['timeout_seconds'],300)
                self.assertEqual(store.config['mcp_servers'][0]['working_directory'],folder)
                dialog.timeout.setValue(1);dialog.load_row(0);self.assertEqual(dialog.timeout.value(),300)
                self.assertEqual(dialog.working_directory.text(),folder)
                self.assertEqual(load_config(store.config_path)['mcp_servers'][0]['timeout_seconds'],300)
            finally:dialog.close();window.close();app.processEvents();store.db.close()

    def test_manager_fits_small_window_and_scrolls_to_controls(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QScrollArea
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}):
            store=Store(folder);window=Window(store);dialog=MCPServers(window)
            try:
                dialog.resize(520,400);dialog.show();app.processEvents()
                scroll=dialog.findChild(QScrollArea,'mcpSettingsScroll')
                self.assertLessEqual(dialog.height(),400);self.assertGreater(scroll.verticalScrollBar().maximum(),0)
                scroll.ensureWidgetVisible(dialog.tool_result);app.processEvents()
                self.assertGreater(scroll.verticalScrollBar().value(),0)
            finally:dialog.close();window.close();app.processEvents();store.db.close()

    @unittest.skipUnless(os.name=='nt','Windows job-object behavior')
    def test_local_mcp_shutdown_terminates_owned_descendant(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'server.py';child=Path(folder)/'child.py';marker=Path(folder)/'child-finished'
            child.write_text('import pathlib,sys,time\ntime.sleep(1.5)\npathlib.Path(sys.argv[1]).write_text("survived")\n',encoding='utf-8')
            server.write_text('''import json,subprocess,sys
for line in sys.stdin:
 req=json.loads(line)
 if req['method']=='initialize':
  subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
  result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Parent','version':'1'},'capabilities':{}}
  print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(child),str(marker)]);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:(out.append(info),loop.quit()));session.ended.connect(lambda error:(out.append(error),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertEqual(out[0]['name'],'Parent');session.close()
            wait=QEventLoop();QTimer.singleShot(2000,wait.quit);wait.exec();self.assertFalse(marker.exists(),'Owned descendant continued after session shutdown')

    @unittest.skipUnless(os.name=='nt','Windows job-object behavior')
    def test_local_mcp_job_assignment_failure_does_not_initialize(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            marker=Path(folder)/'received';server=Path(folder)/'server.py'
            server.write_text('import pathlib,sys\nline=sys.stdin.readline()\nif line:pathlib.Path(sys.argv[1]).write_text("received")\n',encoding='utf-8')
            with patch('agentnik.shell.WindowsJob') as job:
                job.return_value.assign_pid.side_effect=OSError('fixture');session=LocalSession(sys.executable,[str(server),str(marker)]);loop=QEventLoop();out=[]
                session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
                self.assertIn('isolate',out[0]['error']);self.assertFalse(marker.exists());job.return_value.close.assert_called_once()

    def test_local_environment_references_validate_and_persist_names_only(self):
        from agentnik.mcp_support import resolve_environment_references
        item={'name':'Env','command':sys.executable,'args':[],'env':{'TARGET_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'},'enabled':True}
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'AGENTNIK_TEST_MCP_TOKEN':'secret-fixture-value'}):
            store=Store(folder)
            try:
                store.config['mcp_servers']=[item];store.flush();saved=store.config_path.read_text(encoding='utf-8')
                self.assertNotIn('secret-fixture-value',saved);self.assertEqual(load_config(store.config_path)['mcp_servers'],[item]);self.assertEqual(resolve_environment_references(item['env'])['TARGET_TOKEN'],'secret-fixture-value')
            finally:store.db.close()
        for mapping in ({'BAD=NAME':'SOURCE'},{'GOOD':'literal value'},{'A':'SOURCE','a':'OTHER'},['bad'],{'X':123}):
            with self.subTest(mapping=mapping),self.assertRaises(ValueError):validate_servers([dict(item,env=mapping)])
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,'missing'):resolve_environment_references({'TOKEN':'AGENTNIK_MISSING_TEST'})

    def test_local_mcp_environment_mapping_hides_values_and_blocks_reflection(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'AGENTNIK_TEST_MCP_TOKEN':'secret-fixture-value'}):
            server=Path(folder)/'server.py'
            server.write_text('''import json,os,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'mapped' if os.environ.get('TARGET_TOKEN')==os.environ.get('AGENTNIK_TEST_MCP_TOKEN') else 'missing','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'echo','inputSchema':{'type':'object'}}]}
 else:result={'content':[{'type':'text','text':os.environ['TARGET_TOKEN']}]}
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],env_refs={'TARGET_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'});loop=QEventLoop();results=[]
            def discovered(info):results.append(info);session.call(info['tool_details'][0],{})
            session.discovered.connect(discovered);session.ended.connect(lambda result:(results.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(results[0]['name'],'mapped');self.assertIn('mapped environment value',results[1]['error']);self.assertTrue(results[1]['call_uncertain']);self.assertNotIn('secret-fixture-value',str(results))

    def test_local_server_ping_and_unsupported_request_during_operations(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'ping.py'
            server.write_text('''import json,sys

def send(message):print(json.dumps(message),flush=True)
def ask(method,ident):
 send({'jsonrpc':'2.0','id':ident,'method':method})
 answer=json.loads(sys.stdin.readline())
 assert answer['id']==ident
 if method=='ping':assert answer.get('result')=={}
 else:assert answer.get('error',{}).get('code')==-32601
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':
  ask('ping',req['id']);result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':
  ask('roots/list','server-request');result={'tools':[{'name':'echo','inputSchema':{'type':'object'}}]}
 elif method=='tools/call':
  ask('ping','heartbeat');result={'content':[{'type':'text','text':'ok'}]}
 else:raise RuntimeError('unexpected')
 send({'jsonrpc':'2.0','id':req['id'],'result':result})
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)]);loop=QEventLoop();results=[]
            session.discovered.connect(lambda info:(results.append(info),session.call(info['tool_details'][0],{})))
            session.called.connect(lambda result:(results.append(result),loop.quit()));session.ended.connect(lambda result:(results.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(results[0]['name'],'Fake');self.assertEqual(results[1]['call_result']['content'][0]['text'],'ok')

    def test_local_server_request_flood_is_bounded(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'flood.py';server.write_text('''import json,sys
sys.stdin.readline()
for n in range(33):print(json.dumps({'jsonrpc':'2.0','id':n,'method':'ping'}),flush=True)
sys.stdin.read()
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)]);loop=QEventLoop();results=[]
            session.ended.connect(lambda result:(results.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertIn('error',results[0]);self.assertEqual(len(session.server_requests),32)

    def test_protocol_response_validation(self):
        result={'jsonrpc':'2.0','id':1,'result':{'protocolVersion':PROTOCOL,'serverInfo':{'name':'Example','version':'1'},'capabilities':{'tools':{},'resources':{}}}}
        self.assertEqual(parse_initialize(json.dumps(result).encode())['capabilities'],['tools','resources'])
        older=dict(result,result=dict(result['result'],protocolVersion='2024-11-05'))
        self.assertEqual(parse_initialize(json.dumps(older).encode(),(PROTOCOL,'2024-11-05'))['protocol'],'2024-11-05')
        for message in (b'not json',json.dumps(dict(result,id=True)).encode(),json.dumps(dict(result,result={'protocolVersion':'different'})).encode()):
            with self.assertRaises(ValueError):parse_initialize(message)

    def test_rpc_error_is_bounded_and_drops_error_data(self):
        from agentnik.mcp_support import rpc_error
        message={'jsonrpc':'2.0','id':2,'error':{'code':-32602,'message':'bad\nquery '+('x'*700),'data':{'secret':'never-show'}}}
        result=rpc_error(message);self.assertIn('-32602',result);self.assertIn('bad query',result);self.assertNotIn('never-show',result);self.assertNotIn('\n',result);self.assertLess(len(result),600)
        for error in ({'code':True,'message':'bad'},{'code':-1,'message':3},'bad'):
            with self.subTest(error=error),self.assertRaises(ValueError):rpc_error({'error':error})
        with self.assertRaises(ValueError):rpc_error({'error':{'code':-1,'message':'bad'},'result':{}})

    def test_local_call_rpc_error_reports_diagnostic_and_uncertainty(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'error.py';marker=Path(folder)/'calls'
            server.write_text('''import json,sys,pathlib
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
 else:
  pathlib.Path(sys.argv[1]).write_text('once');print(json.dumps({'jsonrpc':'2.0','id':req['id'],'error':{'code':-32602,'message':'Invalid query parameter','data':'private data'}}),flush=True);continue
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)]);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertIn('-32602',out[0]['error']);self.assertIn('Invalid query parameter',out[0]['error']);self.assertNotIn('private data',str(out));self.assertTrue(out[0]['call_uncertain']);self.assertTrue(marker.exists())

    def test_local_timed_out_call_is_uncertain_and_not_replayed(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'slow.py';marker=Path(folder)/'calls'
            server.write_text('''import json,sys,pathlib,time
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
 else:
  pathlib.Path(sys.argv[1]).write_text('once');time.sleep(5);continue
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)],timeout_seconds=1);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(marker.read_text(),'once');self.assertTrue(out[0]['call_uncertain']);self.assertIn('timed out',out[0]['error'])

    def test_remote_call_rpc_error_reports_diagnostic_and_uncertainty(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method'];calls.append(method)
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
                else:result=None
                msg={'jsonrpc':'2.0','id':request['id']}
                if result is None:msg['error']={'code':-32603,'message':'Database unavailable','data':'private data'}
                else:msg['result']=result
                payload=json.dumps(msg).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','');loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.shutdown()
            self.assertIn('-32603',out[0]['error']);self.assertIn('Database unavailable',out[0]['error']);self.assertNotIn('private data',str(out));self.assertTrue(out[0]['call_uncertain']);self.assertEqual(calls.count('tools/call'),1)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_remote_validation_and_sse_messages(self):
        from agentnik.mcp_remote import response_message,preview_tool
        remote={'name':'Parallel','transport':'http','url':'https://mcp.parallel.ai/mcp','credential_id':'opaque','enabled':True}
        validate_servers([remote])
        for url in ('http://example.com/mcp','https://user:secret@example.com/mcp','https://example.com/mcp?key=secret'):
            with self.assertRaises(ValueError):validate_servers([dict(remote,url=url)])
        body=b': keepalive\n\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
        self.assertEqual(response_message(body,'text/event-stream',1)['id'],1)
        for newline in (b'\n',b'\r\n',b'\r'):
            framed=newline.join([b'\xef\xbb\xbf: comment',b'id: 1',b'data:',b'',b'event: message',b'data: {"jsonrpc":"2.0",',b'data: "id":1,"result":{}}',b'',b''])
            self.assertEqual(response_message(framed,'text/event-stream',1)['id'],1)
        for incomplete in (b'data: {"jsonrpc":"2.0","id":1}\n',body+b'data: {"jsonrpc":',body+b'data:'):
            with self.subTest(incomplete=incomplete),self.assertRaises(ValueError):response_message(incomplete,'text/event-stream',1)
        with self.assertRaises(ValueError):response_message(body+body,'text/event-stream',1)
        with self.assertRaises(ValueError):response_message(b'{"jsonrpc":"2.0","id":9}','application/json',1)
        detail=preview_tool({'description':'Search','inputSchema':{'type':'object'}})
        self.assertEqual(detail['schema'],{'type':'object'});self.assertEqual(detail['schema_status'],'available')
        self.assertEqual(preview_tool({'description':'x'*9000,'inputSchema':{'long':'a'*33000}})['schema_status'],'oversized')
        self.assertTrue(preview_tool({'description':'x'*9000})['description_clipped'])
        self.assertEqual(preview_tool({})['schema_status'],'missing')
        self.assertEqual(preview_tool({'execution':{'taskSupport':'required'}})['task_support'],'required')
        hints={'title':'Search','readOnlyHint':True,'destructiveHint':False,'openWorldHint':True}
        self.assertEqual(preview_tool({'annotations':hints})['annotations'],hints)
        for invalid in (None,{'readOnlyHint':1},{'title':'bad\nname'}):
            with self.assertRaises(ValueError):preview_tool({'annotations':invalid})
        with self.assertRaises(ValueError):preview_tool({'execution':{'taskSupport':'unknown'}})
        with self.assertRaises(ValueError):preview_tool({'inputSchema':[]})

    def test_remote_session_and_discovery_with_fake_server(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteProbe
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((body['method'],self.headers.get('Mcp-Session-Id'),self.headers.get('MCP-Protocol-Version'),self.headers.get('Authorization')))
                method=body['method']
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='tools/call' and body['params']['arguments'].get('query')=='uncertain':
                    incomplete=('data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':{'content':[]}})+'\r').encode()
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(incomplete)));self.end_headers();self.wfile.write(incomplete);return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':''},'capabilities':{'tools':{}}}
                elif method=='tools/call':result={'content':[{'type':'text','text':'A search result'}],'isError':False}
                elif not body.get('params',{}).get('cursor'):result={'tools':[{'name':'web_search','description':'Search the web','inputSchema':{'type':'object','properties':{'query':{'type':'string'}}},'outputSchema':{'type':'object','properties':{'items':{'type':'array','items':{'type':'string'}}}}}],'nextCursor':'page-2'}
                else:result={'tools':[{'name':'web_fetch','inputSchema':{'type':'object'}}]}
                payload=('data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result})+'\r\r').encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-1');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):
                calls.append(('DELETE',self.headers.get('Mcp-Session-Id'),self.headers.get('MCP-Protocol-Version'),self.headers.get('Authorization')));self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            loop=QEventLoop();probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token');results=[]
            probe.finished.connect(lambda result:(results.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertEqual(results[0]['tools'],['web_search','web_fetch']);self.assertEqual(results[0]['version'],'unknown');self.assertTrue(results[0]['session_closed'])
            self.assertEqual(results[0]['tool_details'][0]['description'],'Search the web');self.assertIn('query',results[0]['tool_details'][0]['schema']['properties'])
            self.assertEqual([call[0] for call in calls],['initialize','notifications/initialized','tools/list','tools/list','DELETE'])
            self.assertTrue(all(call[1:3]==('session-1',PROTOCOL) for call in calls[1:]));self.assertTrue(all(call[3]=='Bearer test-token' for call in calls))
            loop2=QEventLoop();probe2=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',invocation={'tool':results[0]['tool_details'][0],'arguments':{'query':'MCP'}});calls_result=[]
            probe2.finished.connect(lambda result:(calls_result.append(result),loop2.quit()));probe2.start();QTimer.singleShot(5000,loop2.quit);loop2.exec()
            self.assertEqual(calls_result[0]['call_result']['content'][0]['text'],'A search result');self.assertEqual([call[0] for call in calls].count('tools/call'),1)
            altered=dict(results[0]['tool_details'][0],description='stale');loop3=QEventLoop();probe3=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',invocation={'tool':altered,'arguments':{'query':'MCP'}});stale=[]
            probe3.finished.connect(lambda result:(stale.append(result),loop3.quit()));probe3.start();QTimer.singleShot(5000,loop3.quit);loop3.exec()
            self.assertIn('error',stale[0]);self.assertTrue(stale[0]['session_closed']);self.assertEqual(calls[-1][0],'DELETE');self.assertEqual([call[0] for call in calls].count('tools/call'),1)
            changed_output=dict(results[0]['tool_details'][0],output_schema={'type':'object','required':['changed']});loop5=QEventLoop();probe5=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',invocation={'tool':changed_output,'arguments':{'query':'MCP'}});out5=[]
            probe5.finished.connect(lambda result:(out5.append(result),loop5.quit()));probe5.start();QTimer.singleShot(5000,loop5.quit);loop5.exec()
            self.assertIn('definition changed',out5[0]['error']);self.assertFalse(out5[0]['call_uncertain']);self.assertEqual([call[0] for call in calls].count('tools/call'),1)
            loop4=QEventLoop();probe4=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',invocation={'tool':results[0]['tool_details'][0],'arguments':{'query':'uncertain'}});uncertain=[]
            probe4.finished.connect(lambda result:(uncertain.append(result),loop4.quit()));probe4.start();QTimer.singleShot(5000,loop4.quit);loop4.exec()
            self.assertTrue(uncertain[0]['call_uncertain']);self.assertTrue(uncertain[0]['session_closed']);self.assertEqual(calls[-1][0],'DELETE');self.assertEqual([call[0] for call in calls].count('tools/call'),2)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_manual_remote_failure_preserves_error_when_cleanup_fails(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteProbe
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(body['method'])
                if body['method']=='notifications/initialized':self.send_response(202);self.end_headers();return
                if body['method']=='initialize':
                    result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                    payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode()
                    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session');self.end_headers();self.wfile.write(payload);return
                self.send_response(503);self.end_headers()
            def do_DELETE(self):
                calls.append(('DELETE',self.headers.get('Authorization'),self.headers.get('Mcp-Session-Id')));self.send_response(405);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','fixture-secret');out=[];loop=QEventLoop()
            probe.finished.connect(lambda result:(out.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertEqual(len(out),1);self.assertIn('503',out[0]['error']);self.assertFalse(out[0]['call_uncertain']);self.assertFalse(out[0]['session_closed'])
            self.assertEqual(calls[-1],('DELETE','Bearer fixture-secret','session'));self.assertNotIn('fixture-secret',str(out));self.assertEqual(probe.token,'')
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_remote_cleanup_after_identity_mismatch_and_oversized_response(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteProbe
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(body['method'])
                if body['method']=='notifications/initialized':self.send_response(202);self.end_headers();return
                if body['method']=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                else:result={'tools':[],'padding':'x'*70000}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):calls.append('DELETE');self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for expected in ({'name':'Different'},None):
                with self.subTest(expected=expected):
                    calls.clear();out=[];loop=QEventLoop()
                    probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','',expected_identity=expected)
                    probe.finished.connect(lambda result:(out.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
                    self.assertEqual(len(out),1);self.assertIn('error',out[0]);self.assertTrue(out[0]['session_closed']);self.assertEqual(calls[-1],'DELETE')
                    self.assertFalse(out[0]['call_uncertain'])
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_manual_remote_timeout_attempts_cleanup_without_replaying_call(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteProbe,preview_tool
        calls=[];release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append(method)
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='tools/call':release.wait(5);return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                else:result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):calls.append('DELETE');self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            tool=dict(preview_tool({'inputSchema':{'type':'object'}}),name='query');out=[];loop=QEventLoop()
            probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','',invocation={'tool':tool,'arguments':{}},timeout_seconds=1)
            probe.finished.connect(lambda result:(out.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertEqual(len(out),1);self.assertIn('timed out',out[0]['error']);self.assertTrue(out[0]['call_uncertain']);self.assertTrue(out[0]['session_closed'])
            self.assertEqual(calls.count('tools/call'),1);self.assertEqual(calls[-1],'DELETE')
        finally:release.set();server.shutdown();server.server_close();thread.join(2)

    def test_remote_protocol_negotiation_and_headers(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteProbe,RemoteSession
        calls=[];selected=['2025-06-18']
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];header=self.headers.get('MCP-Protocol-Version');calls.append((method,header))
                if method!='initialize' and header!=selected[0]:self.send_response(400);self.end_headers();return
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':selected[0],'serverInfo':{'name':'Older','version':'1'},'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'echo','inputSchema':{'type':'object'}}]}
                else:result={'content':[{'type':'text','text':'ok'}]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):
                header=self.headers.get('MCP-Protocol-Version');calls.append(('DELETE',header));self.send_response(204 if header==selected[0] else 400);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)+'/mcp'
            for version in ('2025-06-18','2025-03-26'):
                with self.subTest(version=version):
                    selected[0]=version;calls.clear();loop=QEventLoop();session=RemoteSession(url,'');results=[]
                    def discovered(info):
                        results.append(info);self.assertTrue(session.call(info['tool_details'][0],{}))
                    session.discovered.connect(discovered);session.called.connect(lambda result:(results.append(result),session.shutdown()));session.finished.connect(lambda result:(results.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec()
                    self.assertEqual(results[0]['protocol'],version);self.assertEqual(results[1]['call_result']['content'][0]['text'],'ok');self.assertTrue(results[2]['session_closed'])
                    self.assertEqual([item[0] for item in calls],['initialize','notifications/initialized','tools/list','tools/list','tools/call','DELETE'])
                    self.assertIsNone(calls[0][1]);self.assertTrue(all(header==version for _,header in calls[1:]))
            selected[0]='2024-11-05';calls.clear();loop=QEventLoop();probe=RemoteProbe(url,'');results=[]
            probe.finished.connect(lambda result:(results.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertIn('error',results[0]);self.assertEqual(calls,[('initialize',None)])
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_remote_discovery_rejects_repeated_cursor(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteProbe
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(body['method'])
                if body['method']=='notifications/initialized':self.send_response(202);self.end_headers();return
                result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}} if body['method']=='initialize' else {'tools':[],'nextCursor':'repeat'}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            loop=QEventLoop();probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','');results=[]
            probe.finished.connect(lambda result:(results.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertIn('error',results[0]);self.assertEqual(calls.count('tools/list'),2)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_manager_explains_unsaved_server_and_invalid_windows_json(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QMessageBox
        from agentnik.mcp_ui import MCPServers
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}):
            store=Store(folder);window=Window(store);dialog=MCPServers(window)
            try:
                dialog.name.setText('Local');dialog.command.setText(sys.executable)
                dialog.args.setPlainText('["D:\\dev\\parquet_mcp\\server.py"]')
                dialog.test();self.assertIn('Save and select',dialog.status.text())
                with patch.object(QMessageBox,'warning') as warning:
                    dialog.save();self.assertIn('double each backslash',warning.call_args.args[2])
                self.assertEqual(store.config.get('mcp_servers',[]),[])
                dialog.args.setPlainText('["D:/dev/parquet_mcp/server.py"]');dialog.save()
                self.assertEqual(store.config['mcp_servers'][0]['args'],['D:/dev/parquet_mcp/server.py'])
                dialog.args.setPlainText('["D:/dev/parquet_mcp/different.py"]')
                with patch.object(QMessageBox,'question') as confirm:
                    dialog.test();confirm.assert_not_called()
                self.assertIn('Save your changes',dialog.status.text());self.assertIsNone(dialog.process)
            finally:dialog.close();window.close();app.processEvents();store.db.close()

    def test_explicit_local_initialization_and_no_launch_on_open(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication,QMessageBox,QDialog
        from agentnik.mcp_ui import MCPServers
        from agentnik.ui import Window
        from agentnik import core
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(folder);marker=root/'started';server=root/'server.py'
            server.write_text('''import json,sys,pathlib
pathlib.Path(sys.argv[1]).write_text("started")
for line in sys.stdin:
 request=json.loads(line); method=request['method']
 if method=='notifications/initialized': continue
 if method=='initialize': result={'protocolVersion':request['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list': result={'tools':[{'name':'query','description':'Run a query','inputSchema':{'type':'object'},'annotations':{'readOnlyHint':True}}]}
 else: result={'content':[{'type':'text','text':'success'}]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Fake','command':sys.executable,'args':[str(server),str(marker)],'enabled':True,'working_directory':str(root)}];store.flush();window=Window(store)
            try:
                dialog=MCPServers(window);dialog.list.setCurrentRow(0);self.assertFalse(marker.exists())
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes) as review:
                    dialog.test();review.assert_not_called()
                loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if dialog.discovered else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                self.assertIsNotNone(dialog.process);self.assertTrue(marker.exists());self.assertIn('Connected: Fake',dialog.status.text());self.assertEqual(dialog.tool_choice.currentText(),'query')
                session=dialog.process;results=[];session.called.connect(lambda result:results.append(result))
                for _ in range(2):
                    self.assertTrue(session.call(dialog.discovered['tools'][0],{}));loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if len(results)>_ else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                self.assertEqual(len(results),2);self.assertEqual(results[1]['call_result']['content'][0]['text'],'success')
                with patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted) as review_call:
                    dialog.call_remote();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if len(results)>2 else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                    review_call.assert_not_called()
                self.assertEqual(len(results),3);self.assertIn('success',dialog.tool_result.toPlainText());dialog.finish_test('Closed');dialog.close()
            finally:window.close();app.processEvents();store.db.close()

    def test_resource_template_expansion_and_pagination(self):
        from agentnik.mcp_resources import TemplatePages,expand_template
        self.assertEqual(expand_template('test://item/{id}',{'id':'a/b ?'}),'test://item/a%2Fb%20%3F')
        self.assertEqual(expand_template('test://x{/id,part}{?query,empty}{&next}',{'id':'a/b','part':'雪','query':'a&b =','empty':'','next':'%'}),'test://x/a%2Fb/%E9%9B%AA?query=a%26b%20%3D&empty=&next=%25')
        self.assertEqual(expand_template('test://x/{a,b}/{a}',{'a':'x,y','b':'z'}),'test://x/x%2Cy,z/x%2Cy')
        self.assertEqual(expand_template('test://x{/a,b}{?q,limit}{&next}',{'b':'','limit':'10','next':None}),'test://x/?limit=10')
        self.assertEqual(expand_template('test://x{/id}{?q}',{}),'test://x')
        self.assertEqual(expand_template('test://x/{a,b}',{'b':'test'}),'test://x/test')
        self.assertEqual(expand_template('test://x{?q}',{'q':''}),'test://x?q=')
        for template,values in [('{id}',{}),('test://x/{+id}',{'id':'a'}),('test://x/{id}',{'id':['bad']}),('test://x/{id',{'id':'a'}),('test://x/{?x*}',{'x':'a'}),('test://x/{?x}',{'x':'a','extra':'b'}),('test://x/{/x}',{'x':'a'*2040})]:
            with self.subTest(template=template),self.assertRaises(ValueError):expand_template(template,values)
        pages=TemplatePages();cursor,result=pages.accept({'resourceTemplates':[{'uriTemplate':'test://x/{id}','name':'One'},{'uriTemplate':'test://x/{+id}','name':'Complex'}],'nextCursor':'next'})
        self.assertEqual(cursor,'next');self.assertTrue(result['templates'][0]['supported']);self.assertFalse(result['templates'][1]['supported'])
        query=TemplatePages().accept({'resourceTemplates':[{'uriTemplate':'test://x{/id}{?q,limit}','name':'Search'}]})[1]['templates'][0]
        self.assertTrue(query['supported']);self.assertEqual(query['variables'],['id','q','limit'])
        with self.assertRaises(ValueError):pages.accept({'resourceTemplates':[],'nextCursor':'next'})

    def test_local_resource_template_listing_and_read(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'templates.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'resources':{}}}
 elif method=='resources/templates/list':result={'resourceTemplates':[{'uriTemplate':'test://item{/id}{?q,limit}','name':'Item'}]}
 elif method=='resources/read':result={'contents':[{'uri':req['params']['uri'],'text':'content'}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)]);loop=QEventLoop();out=[]
            def received(result):
                out.append(result)
                if len(out)==1:
                    template=result['templates'][0];values={'id':'a/b','q':'x&y'};self.assertFalse(session.read_resource_template(template,values,'test://item/a/b?q=x&y'));self.assertTrue(session.read_resource_template(template,values,'test://item/a%2Fb?q=x%26y'))
                else:loop.quit()
            session.discovered.connect(lambda _:session.list_resource_templates());session.resources.connect(received);session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(out[1]['contents'][0]['uri'],'test://item/a%2Fb?q=x%26y');self.assertEqual(out[1]['contents'][0]['text'],'content')

    def test_resource_pagination_limits_and_invalid_cursors(self):
        from agentnik.mcp_resources import ResourcePages
        pages=ResourcePages()
        for i in range(5):
            cursor,out=pages.accept({'resources':[{'uri':'test://'+str(i),'name':str(i)}],'nextCursor':'cursor-'+str(i)})
            self.assertEqual(cursor,'cursor-'+str(i) if i<4 else None)
        self.assertTrue(out['more_resources']);self.assertEqual(len(out['resources']),5)
        pages=ResourcePages();pages.accept({'resources':[],'nextCursor':'same'})
        with self.assertRaisesRegex(ValueError,'Repeated'):pages.accept({'resources':[],'nextCursor':'same'})
        pages=ResourcePages();pages.accept({'resources':[{'uri':'test://a','name':'a'}],'nextCursor':'next'})
        with self.assertRaisesRegex(ValueError,'Duplicate'):pages.accept({'resources':[{'uri':'test://a','name':'a'}]})
        pages=ResourcePages();cursor,out=pages.accept({'resources':[{'uri':'test://'+str(i),'name':str(i)} for i in range(100)],'nextCursor':'more'})
        self.assertIsNone(cursor);self.assertTrue(out['more_resources']);self.assertEqual(len(out['resources']),100)
        pages=ResourcePages();cursor,out=pages.accept({'resources':[{'uri':'test://'+str(i),'name':str(i),'description':'x'*4000} for i in range(60)]})
        self.assertIsNone(cursor);self.assertTrue(out['more_resources']);self.assertLess(len(out['resources']),60)

    def test_prompt_validation_and_pagination(self):
        from agentnik.mcp_prompts import PromptPages,validate_prompt_arguments,parse_prompt_messages
        pages=PromptPages();cursor,result=pages.accept({'prompts':[{'name':'review','description':'Review','arguments':[{'name':'code','required':True}]}],'nextCursor':'next'})
        self.assertEqual(cursor,'next');prompt=result['prompts'][0];self.assertTrue(validate_prompt_arguments(prompt,{'code':'hello'}))
        for args in ({},{'code':1},{'code':'x','extra':'y'}):
            with self.assertRaises(ValueError):validate_prompt_arguments(prompt,args)
        with self.assertRaises(ValueError):pages.accept({'prompts':[],'nextCursor':'next'})
        with self.assertRaises(ValueError):parse_prompt_messages({'messages':[{'role':'system','content':{'type':'text','text':'bad'}}]})
        with self.assertRaises(ValueError):parse_prompt_messages({'messages':[{'role':'user','content':{'type':'image','data':'a'}}]})

    def test_local_prompt_listing_get_and_definition_recheck(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'prompt_server.py';marker=Path(folder)/'called'
            server.write_text('''import json,sys,pathlib
pages=0
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'prompts':{}}}
 elif method=='prompts/list':
  pages+=1;result={'prompts':[{'name':'review','description':'Changed' if pages>2 else 'Review','arguments':[{'name':'code','required':True}]}]}
 elif method=='prompts/get':
  pathlib.Path(sys.argv[1]).write_text('called');result={'messages':[{'role':'user','content':{'type':'text','text':'Review '+req['params']['arguments']['code']}}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)]);loop=QEventLoop();out=[]
            def response(result):
                out.append(result)
                if len(out)==1:
                    prompt=result['prompts'][0];self.assertFalse(session.list_prompts({'prompt':prompt,'arguments':{}}));self.assertTrue(session.list_prompts({'prompt':prompt,'arguments':{'code':'safe'}}))
                elif len(out)==2:
                    self.assertTrue(marker.exists());marker.unlink();self.assertTrue(session.list_prompts({'prompt':out[0]['prompts'][0],'arguments':{'code':'safe'}}))
            session.discovered.connect(lambda _:session.list_prompts());session.prompts.connect(response);session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(out[1]['messages'][0]['content']['text'],'Review safe');self.assertIn('definition changed',out[2]['error']);self.assertFalse(marker.exists())

    def test_local_resource_listing_and_text_read(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'resources.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'resources':{}}}
 elif method=='resources/list':result={'resources':[{'uri':'test://record/2','name':'Second'}]} if req.get('params',{}).get('cursor') else {'resources':[{'uri':'test://record/1','name':'Record','description':'Test','mimeType':'text/plain'}],'nextCursor':'next'}
 elif method=='resources/read':result={'contents':[{'uri':req['params']['uri'],'text':'Resource text','mimeType':'text/plain'}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)]);loop=QEventLoop();results=[]
            def ready(info):
                self.assertIn('resources',info['capabilities']);self.assertTrue(session.list_resources())
            def resource(result):
                results.append(result)
                if len(results)==1:
                    self.assertFalse(session.read_resource('test://unlisted'));self.assertTrue(session.read_resource(result['resources'][1]['uri']))
                else:loop.quit()
            session.discovered.connect(ready);session.resources.connect(resource);session.ended.connect(lambda result:(results.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(results[0]['resources'][0]['name'],'Record');self.assertFalse(results[0]['more_resources']);self.assertEqual(results[0]['resources'][1]['name'],'Second');self.assertEqual(results[1]['contents'][0]['text'],'Resource text')

    def test_local_resource_read_rejects_binary_and_mismatched_uri(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'bad_resources.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'resources':{}}}
 elif method=='resources/list':result={'resources':[{'uri':'test://one','name':'One'}]}
 else:result={'contents':[{'uri':'test://other','text':'unexpected'}] if sys.argv[1]=='mismatch' else [{'uri':'test://one','blob':'YWJj'}]}
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            for mode in ('mismatch','binary'):
                with self.subTest(mode=mode):
                    session=LocalSession(sys.executable,[str(server),mode]);loop=QEventLoop();out=[]
                    session.discovered.connect(lambda _:session.list_resources())
                    session.resources.connect(lambda result:session.read_resource(result['resources'][0]['uri']))
                    session.ended.connect(lambda result:(out.append(result),loop.quit()))
                    session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
                    self.assertIn('Invalid or unsupported',out[0]['error'])

    def test_local_call_rechecks_definition_before_execution(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'server.py';marker=Path(folder)/'called'
            server.write_text('''import json,sys,pathlib
pages=0
for line in sys.stdin:
 request=json.loads(line);method=request['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':request['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':
  pages+=1;result={'tools':[{'name':'query','description':'Original','annotations':{'readOnlyHint':pages==1},'inputSchema':{'type':'object'}}]}
 else:
  pathlib.Path(sys.argv[1]).write_text('called');result={'content':[]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)]);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}))
            session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertIn('definition changed',out[0]['error']);self.assertFalse(out[0]['call_uncertain']);self.assertFalse(marker.exists())

    def test_local_output_schema_changes_block_the_call(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'server.py';marker=Path(folder)/'called'
            server.write_text('''import json,sys,pathlib
pages=0
for line in sys.stdin:
 request=json.loads(line);method=request['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':request['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':
  pages+=1;result={'tools':[{'name':'query','inputSchema':{'type':'object'},'outputSchema':{'type':'object','required':['one' if pages==1 else 'two']}}]}
 else:
  pathlib.Path(sys.argv[1]).write_text('called');result={'content':[]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)]);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertIn('definition changed',out[0]['error']);self.assertFalse(out[0]['call_uncertain']);self.assertFalse(marker.exists())

    def test_manager_checks_structured_output_in_worker(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}):
            store=Store(folder);window=Window(store);dialog=MCPServers(window)
            try:
                dialog.call_tool={'output_schema_status':'available','output_schema':{'type':'object','required':['count']}}
                dialog.show_call_result({'call_result':{'content':[],'structuredContent':{'bad':1}}})
                loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if dialog.validation_job is None else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                self.assertIsNone(dialog.validation_job);self.assertIn('failed validation',dialog.status.text());self.assertIn('"bad"',dialog.tool_result.toPlainText())
            finally:dialog.close();window.close();app.processEvents();store.db.close()

    def test_remote_prompt_session_and_secret_isolation(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append((method,self.headers.get('Mcp-Session-Id')))
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'prompts':{}}}
                elif method=='prompts/list':result={'prompts':[{'name':'review','arguments':[{'name':'code','required':True}]}]}
                elif method=='prompts/get':result={'messages':[{'role':'user','content':{'type':'text','text':'Review '+body['params']['arguments']['code']}}]}
                else:raise AssertionError(method)
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):calls.append(('DELETE',self.headers.get('Mcp-Session-Id')));self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        config={'mcp_servers':[{'name':'Remote','transport':'http','url':'http://127.0.0.1:'+str(server.server_port)+'/mcp','credential_id':'id','enabled':True}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config);runtime=Runtime(threading.Event(),Limits());out=[]
        def work():
            out.append(bridge.request('discover',{},runtime));out.append(bridge.request('prompts_list',{},runtime));prompt=out[1]['prompts'][0]
            out.append(bridge.request('prompts_get',{'prompt':prompt,'arguments':{'code':'secret-token'}},runtime));out.append(bridge.request('prompts_get',{'prompt':prompt,'arguments':{'code':'safe'}},runtime));bridge.close_signal.emit()
        try:
            with patch('keyring.get_password',return_value='secret-token'):
                thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() and any(c[0]=='DELETE' for c in calls) else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertIn('error',out[2]);self.assertEqual(out[3]['messages'][0]['content']['text'],'Review safe');self.assertEqual([c[0] for c in calls].count('prompts/get'),1);self.assertTrue(all(c[1]=='session-one' for c in calls[1:]));self.assertNotIn('secret-token',str(out))
        finally:bridge.close();server.shutdown();server.server_close();server_thread.join(2)

    def test_remote_resource_listing_and_read_in_authenticated_session(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append((method,self.headers.get('Mcp-Session-Id'),self.headers.get('Authorization')))
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'resources':{}}}
                elif method=='resources/list':result={'resources':[{'uri':'test://two','name':'Two'}]} if body.get('params',{}).get('cursor') else {'resources':[{'uri':'test://one','name':'One','description':'Example'}],'nextCursor':'next'}
                elif method=='resources/read':result={'contents':[{'uri':body['params']['uri'],'text':'Evidence'}]}
                else:raise AssertionError(method)
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):
                calls.append(('DELETE',self.headers.get('Mcp-Session-Id'),self.headers.get('Authorization')));self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        config={'mcp_servers':[{'name':'Remote','transport':'http','url':'http://127.0.0.1:'+str(server.server_port)+'/mcp','credential_id':'id','enabled':True}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config);runtime=Runtime(threading.Event(),Limits());out=[]
        def work():
            out.append(bridge.request('discover',{},runtime));out.append(bridge.request('resources_list',{},runtime))
            out.append(bridge.request('resources_read',{'uri':'test://unlisted'},runtime));out.append(bridge.request('resources_read',{'uri':'test://two'},runtime));bridge.close_signal.emit()
        try:
            with patch('keyring.get_password',return_value='secret-token'):
                thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() and any(c[0]=='DELETE' for c in calls) else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertIn('resources',out[0]['capabilities']);self.assertFalse(out[1]['more_resources']);self.assertEqual(len(out[1]['resources']),2);self.assertIn('error',out[2]);self.assertEqual(out[3]['contents'][0]['text'],'Evidence')
            self.assertEqual([c[0] for c in calls],['initialize','notifications/initialized','resources/list','resources/list','resources/read','DELETE']);self.assertTrue(all(c[1]=='session-one' for c in calls[1:]));self.assertTrue(all(c[2]=='Bearer secret-token' for c in calls));self.assertNotIn('secret-token',str(out))
        finally:bridge.close();server.shutdown();server.server_close();server_thread.join(2)

    def test_coding_remote_session_is_stateful_and_rechecks_tool_changes(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        calls=[];state={'value':0,'changed':False}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append((method,body.get('id'),self.headers.get('Mcp-Session-Id')))
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'step','description':'Changed' if state['changed'] else 'Count','inputSchema':{'type':'object'}}]}
                else:state['value']+=1;result={'content':[{'type':'text','text':str(state['value'])}]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):
                calls.append(('DELETE',None,self.headers.get('Mcp-Session-Id')));self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        config={'mcp_servers':[{'name':'Remote','transport':'http','url':'http://127.0.0.1:'+str(server.server_port)+'/mcp','credential_id':'','enabled':True,'timeout_seconds':180}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config);runtime=Runtime(threading.Event(),Limits());out=[];timeouts=[]
        def work():
            info=bridge.request('discover',{},runtime);timeouts.append(bridge.session.timeout_ms);payload={'tool':info['tool_details'][0],'arguments':{}}
            out.append(bridge.request('call',payload,runtime));out.append(bridge.request('call',payload,runtime));state['changed']=True
            out.append(bridge.request('call',payload,runtime));bridge.close_signal.emit()
        try:
            thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() and any(item[0]=='DELETE' for item in calls) else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertEqual(timeouts,[180000]);self.assertEqual([out[0]['call_result']['content'][0]['text'],out[1]['call_result']['content'][0]['text']],['1','2'])
            self.assertIn('definition changed',out[2]['error']);self.assertEqual([c[0] for c in calls].count('initialize'),1);self.assertEqual([c[0] for c in calls].count('tools/call'),2)
            self.assertTrue(all(c[2]=='session-one' for c in calls[1:]));ids=[c[1] for c in calls if c[1] is not None];self.assertEqual(len(ids),len(set(ids)));self.assertEqual(calls[-1][0],'DELETE')
        finally:bridge.close();server.shutdown();server.server_close();server_thread.join(2)

    def test_coding_remote_bridge_rechecks_and_stops_after_uncertainty(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append(method)
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='tools/call':self.connection.close();return
                result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}} if method=='initialize' else {'tools':[{'name':'query','description':'Query','inputSchema':{'type':'object'}}]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        config={'mcp_servers':[{'name':'Remote','transport':'http','url':'http://127.0.0.1:'+str(server.server_port)+'/mcp','credential_id':'saved','enabled':True}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config);runtime=Runtime(threading.Event(),Limits());out=[]
        def work():
            info=bridge.request('discover',{},runtime);out.append(info);payload={'tool':info['tool_details'][0],'arguments':{}}
            out.append(bridge.request('call',payload,runtime));out.append(bridge.request('call',payload,runtime));bridge.close_signal.emit()
        try:
            with patch('keyring.get_password',return_value='secret-token'):
                thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1);app.processEvents()
            self.assertFalse(thread.is_alive());self.assertTrue(out[1]['call_uncertain']);self.assertIn('uncertain',out[2]['error']);self.assertEqual(calls.count('tools/call'),1);self.assertNotIn('secret-token',str(out))
        finally:bridge.close();server.shutdown();server.server_close();server_thread.join(2)

    def test_remote_response_secret_is_detected_after_json_unescaping(self):
        from agentnik.mcp_remote import contains_secret
        self.assertTrue(contains_secret(json.loads('{"text":"s\\u0065cret"}'),'secret'))
        self.assertTrue(contains_secret({'secret':'value'},'secret'))

    def test_coding_bridge_keeps_local_session_and_checks_configuration(self):
        import threading
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'AGENTNIK_MCP_TEST_SOURCE':'snapshot-unique-value'}):
            server=Path(folder)/'server.py'
            server.write_text('''import json,os,sys
for line in sys.stdin:
 request=json.loads(line);method=request['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':request['params']['protocolVersion'],'serverInfo':{'name':'Fake' if os.environ.get('TARGET_TOKEN')=='snapshot-unique-value' else 'Incorrect','version':os.getcwd()},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
 else:result={'content':[{'type':'text','text':'ok'}]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            config={'mcp_servers':[{'name':'Fake','command':sys.executable,'args':[str(server)],'env':{'TARGET_TOKEN':'AGENTNIK_MCP_TEST_SOURCE'},'enabled':True,'timeout_seconds':180,'working_directory':folder}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config)
            os.environ['AGENTNIK_MCP_TEST_SOURCE']='changed-after-snapshot'
            runtime=Runtime(threading.Event(),Limits());out=[];timeouts=[]
            def work():
                info=bridge.request('discover',{},runtime);out.append(info);timeouts.append(bridge.session.timeout_ms)
                out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{}},runtime))
                config['mcp_servers']=[]
                out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{}},runtime));bridge.close_signal.emit()
            thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1);app.processEvents()
            self.assertFalse(thread.is_alive());self.assertEqual(Path(out[0]['version']).resolve(),Path(folder).resolve());self.assertEqual(timeouts,[180000]);self.assertEqual(out[1]['call_result']['content'][0]['text'],'ok');self.assertIn('changed',out[2]['error']);self.assertTrue(bridge.closed)

    def test_local_environment_mapping_editor_saves_and_reloads(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QMessageBox
        from agentnik.mcp_ui import MCPServers
        from agentnik.ui import Window
        from agentnik import core
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.dict(os.environ,{'AGENTNIK_TEST_MCP_TOKEN':'secret-mapped-value'}):
            store=Store(folder);window=Window(store)
            try:
                dialog=MCPServers(window);dialog.name.setText('Local');dialog.command.setText(sys.executable);dialog.args.setPlainText('[]');dialog.env.setPlainText('{"SERVER_TOKEN":"AGENTNIK_TEST_MCP_TOKEN"}');dialog.save()
                self.assertEqual(store.config['mcp_servers'][0]['env'],{'SERVER_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'});self.assertNotIn('secret-mapped-value',store.config_path.read_text(encoding='utf-8'))
                self.assertEqual(json.loads(dialog.env.toPlainText()),{'SERVER_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'})
                dialog.env.setPlainText('{"bad=name":"SOURCE"}')
                with patch.object(QMessageBox,'warning') as warning:dialog.save();warning.assert_called_once()
                self.assertEqual(store.config['mcp_servers'][0]['env'],{'SERVER_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'});dialog.close()
            finally:window.close();app.processEvents();store.db.close()

    def test_remote_credential_uses_keyring_and_is_not_reused_for_changed_url(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog
        from PySide6.QtCore import QEventLoop,QTimer
        from agentnik.mcp_ui import MCPServers
        from agentnik.ui import Window
        from agentnik import core
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            store=Store(folder);window=Window(store)
            try:
                dialog=MCPServers(window);dialog.transport.setCurrentIndex(1);dialog.name.setText('Remote');dialog.url.setText('https://example.com/mcp');dialog.token.setText('secret-test-token');dialog.timeout.setValue(240)
                with patch('keyring.set_password') as put,patch('keyring.delete_password') as delete:
                    dialog.save();put.assert_called_once();self.assertNotIn('secret-test-token',store.config_path.read_text(encoding='utf-8'))
                    self.assertTrue(store.config['mcp_servers'][0]['credential_id']);dialog.url.setText('https://other.example/mcp');dialog.save()
                    self.assertEqual(store.config['mcp_servers'][0]['credential_id'],'');delete.assert_called_once()
                dialog.discovered_config=dict(store.config['mcp_servers'][0]);dialog.remote_done({'name':'Fake','version':'1','protocol':PROTOCOL,'tools':['search'],'tool_details':[{'name':'search','description':'Search web','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}]})
                self.assertIn('Search web',dialog.tool_details.toPlainText());self.assertIn('"type": "object"',dialog.tool_details.toPlainText())
                def wait_validation():
                    loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if dialog.validation_job is None else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();self.assertIsNone(dialog.validation_job)
                dialog.tool_args.setPlainText('{"value":1e999}');dialog.call_remote();self.assertIsNone(dialog.validation_job);self.assertIn('JSON object',dialog.status.text());dialog.tool_args.setPlainText('{}')
                dialog.discovered['tools'][0]['schema']={'type':'object','required':['query']}
                with patch.object(QDialog,'exec') as review:
                    dialog.call_remote();wait_validation();review.assert_not_called();self.assertIn('do not match',dialog.status.text())
                dialog.discovered['tools'][0]['schema']={'type':'object'}
                dialog.tool_args.setPlainText('{"query":"MCP"}')
                with patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted) as review,patch('agentnik.mcp_remote.RemoteProbe') as remote:
                    dialog.call_remote();wait_validation();remote.assert_called_once()
                    review.assert_not_called()
                    self.assertEqual(remote.call_args.kwargs['invocation']['arguments'],{'query':'MCP'});self.assertEqual(remote.call_args.kwargs['timeout_seconds'],240);remote.return_value.start.assert_called_once()
                    dialog.remote=None
                dialog.close()
            finally:window.close();app.processEvents();store.db.close()
