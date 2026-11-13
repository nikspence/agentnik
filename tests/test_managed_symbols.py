"""C# and Java syntax outlines and coding-tool integration."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentnik.code_agent import ProjectFiles,CodingRun
from agentnik.managed_symbols import managed_outline
from agentnik.project_tools import ProjectToolError,ProjectTools
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire

class ManagedOutlines(unittest.TestCase):
    def test_csharp_namespaces_types_members_and_edit_boundary(self):
        text='''namespace Demo.App;
public record Item(int Id);
public interface IService { void Run(); }
public class Box {
  public Box() {}
  public string Name { get; set; }
  public void Open() { int local = 1; }
  public event System.Action Changed;
}
'''
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'Box.cs').write_text(text,encoding='utf-8');files=ProjectFiles(root);result=managed_outline(files,'Box.cs')
            symbols={(x['name'],x['kind']) for x in result['symbols']}
            for item in [('Demo.App','namespace'),('Demo.App.Item','record'),('Demo.App.IService.Run','method'),('Demo.App.Box','class'),('Demo.App.Box.Box','constructor'),('Demo.App.Box.Name','property'),('Demo.App.Box.Open','method'),('Demo.App.Box.Changed','event')]:self.assertIn(item,symbols)
            self.assertNotIn(('Demo.App.Box.Open.local','field'),symbols);self.assertFalse(result['incomplete']);self.assertFalse(files.observed)
            with self.assertRaises(ValueError):files.proposal('Box.cs','replacement')
            with self.assertRaises(ProjectToolError):ProjectTools(files).patch('Box.cs','void Open()','void Close()')

    def test_java_packages_records_nested_types_and_fields(self):
        text='''package demo.api;
public record Item(int id) {}
interface Reader { void read(); }
class Box {
 Box() {}
 void open() { int local=1; }
 private int x, y;
 enum State { ON, OFF }
}
'''
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'Box.java').write_text(text,encoding='utf-8');result=managed_outline(ProjectFiles(root),'Box.java');symbols={(x['name'],x['kind']) for x in result['symbols']}
            for item in [('demo.api','package'),('demo.api.Item','record'),('demo.api.Reader.read','method'),('demo.api.Box.Box','constructor'),('demo.api.Box.open','method'),('demo.api.Box.x','field'),('demo.api.Box.y','field'),('demo.api.Box.State.ON','enum_member')]:self.assertIn(item,symbols)
            self.assertFalse(any(x['name'].endswith('.local') for x in result['symbols']));self.assertFalse(result['incomplete'])

    def test_syntax_errors_bounds_protected_paths_and_cancellation(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);(root/'broken.java').write_text('class Good {}\nclass Bad { void broken(',encoding='utf-8');(root/'many.cs').write_text('\n'.join('class C%d {}'%i for i in range(180)),encoding='utf-8');(root/'.env.cs').write_text('class Secret {}',encoding='utf-8')
            files=ProjectFiles(root);result=managed_outline(files,'broken.java');self.assertTrue(result['syntax_errors']);self.assertTrue(result['incomplete']);self.assertIn('Good',[x['name'] for x in result['symbols']])
            result=managed_outline(files,'many.cs');self.assertTrue(result['incomplete']);self.assertEqual(len(result['symbols']),150)
            for path in ('.env.cs','../outside.cs','bad.py'):
                with self.subTest(path=path),self.assertRaises((ValueError,ProjectToolError)):managed_outline(files,path)
            count=[0]
            def cancel():
                count[0]+=1
                if count[0]>=3:raise InterruptedError('cancelled')
            with self.assertRaises(InterruptedError):managed_outline(files,'many.cs',cancel)
            from agentnik.tools import LimitError
            count[0]=0
            def timeout():
                count[0]+=1
                if count[0]>=3:raise LimitError('deadline')
            with self.assertRaises(LimitError):managed_outline(files,'many.cs',timeout)

    def test_model_tool_call_and_targeted_read(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'Box.java').write_text('class Box { void run() {} }\n',encoding='utf-8')
            replies=[Wire(chat(calls=[call('managed_outline',{'path':'Box.java'})],finish='tool_calls'),False),Wire(chat(calls=[call('read_file_range',{'path':'Box.java','start_line':'1','end_line':'1'})],finish='tool_calls'),False),Wire(chat('Done'),False)];bodies=[];events=[]
            def request(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch('agentnik.core.open_request',side_effect=request):CodingRun(dict(C,stream=False),root,'Inspect').run(events.append)
            self.assertEqual(events[-1]['status'],'completed');result=next(json.loads(m['content']) for m in bodies[1]['messages'] if m.get('role')=='tool');self.assertEqual(result['symbols'][0]['name'],'Box');self.assertIn('void run',json.dumps(bodies[2]))
