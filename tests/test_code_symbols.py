"""Python project symbol outlines and coding tool integration."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentnik.code_agent import ProjectFiles,CodingRun
from agentnik.code_symbols import python_outline,MAX_BYTES
from agentnik.project_tools import ProjectToolError,ProjectTools
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire

class PythonOutlines(unittest.TestCase):
    def test_nested_async_and_no_edit_permission(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'app.py';path.write_text('''class Box:\n    async def open(self):\n        def inside():\n            pass\n        return inside\n\nif True:\n    def conditional():\n        pass\n''',encoding='utf-8')
            files=ProjectFiles(folder);outline=python_outline(files,'app.py');symbols=outline['symbols']
            self.assertEqual([(s['name'],s['kind'],s['line'],s['end_line']) for s in symbols],[('Box','class',1,5),('Box.open','async_function',2,5),('Box.open.inside','function',3,4),('conditional','function',8,9)])
            self.assertFalse(outline['incomplete']);self.assertEqual(files.observed,{})
            with self.assertRaises(ValueError):files.proposal('app.py','replacement')
            with self.assertRaises(ProjectToolError):ProjectTools(files).patch('app.py','pass','return None')

    def test_invalid_excluded_oversized_and_output_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'bad.py').write_text('def broken(:',encoding='utf-8');(root/'data.txt').write_text('x',encoding='utf-8');(root/'.env.py').write_text('x=1',encoding='utf-8')
            (root/'large.py').write_text('x'*(MAX_BYTES+1),encoding='utf-8');(root/'many.py').write_text('\n'.join('def f%d(): pass'%i for i in range(200)),encoding='utf-8')
            files=ProjectFiles(root)
            for name in ('bad.py','data.txt','.env.py','large.py','../outside.py'):
                with self.subTest(name=name),self.assertRaises((ValueError,ProjectToolError)):python_outline(files,name)
            result=python_outline(files,'many.py');self.assertTrue(result['incomplete']);self.assertEqual(len(result['symbols']),150)

    def test_model_can_use_outline_and_read_exact_range(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'app.py').write_text('def hello():\n    return 3\n',encoding='utf-8')
            replies=[Wire(chat(calls=[call('python_outline',{'path':'app.py'})],finish='tool_calls'),False),Wire(chat(calls=[call('read_file_range',{'path':'app.py','start_line':'1','end_line':'2'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            bodies=[];events=[]
            def request(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch('agentnik.core.open_request',side_effect=request):CodingRun(dict(C,stream=False),folder,'Inspect').run(events.append)
            self.assertEqual(events[-1]['status'],'completed');tool=next(json.loads(m['content']) for m in bodies[1]['messages'] if m.get('role')=='tool');self.assertEqual(tool['symbols'][0]['name'],'hello')
            self.assertIn('return 3',json.dumps(bodies[2]))
