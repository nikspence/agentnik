"""Go and Rust syntax outlines and coding-tool integration."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentnik.code_agent import ProjectFiles,CodingRun
from agentnik.systems_symbols import systems_outline
from agentnik.project_tools import ProjectToolError,ProjectTools
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire

class SystemsOutlines(unittest.TestCase):
    def test_go_package_types_receivers_and_multiple_names(self):
        text='''package demo
type Reader interface { Read(p []byte) error }
type Box struct{}
func (b *Box) Open() {}
func main() {}
const one, two = 1, 2
var x, y int
'''
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'main.go').write_text(text,encoding='utf-8');files=ProjectFiles(root);result=systems_outline(files,'main.go')
            self.assertEqual([(x['name'],x['kind']) for x in result['symbols']],[('demo','package'),('Reader','interface'),('Reader.Read','method'),('Box','struct'),('Box.Open','method'),('main','function'),('one','constant'),('two','constant'),('x','variable'),('y','variable')])
            self.assertEqual(result['symbols'][4]['line'],4);self.assertFalse(result['incomplete']);self.assertFalse(files.observed)
            with self.assertRaises(ValueError):files.proposal('main.go','replacement')
            with self.assertRaises(ProjectToolError):ProjectTools(files).patch('main.go','func main() {}','func main() { panic(1) }')

    def test_rust_modules_traits_impl_and_macro_indicator(self):
        text='''pub mod api {
 pub struct Box {}
 pub trait Reader { fn read(&self); }
 impl Reader for Box { fn read(&self) {} }
 impl Box { pub fn open(&self) { println!("ready"); } }
 pub enum State { On, Off }
 pub type Id = u32;
}
'''
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'lib.rs').write_text(text,encoding='utf-8');result=systems_outline(ProjectFiles(root),'lib.rs');names=[x['name'] for x in result['symbols']]
            for name in ('api','api.Box','api.Reader','api.Reader.read','api.impl Reader for Box','api.impl Reader for Box.read','api.impl Box.open','api.State','api.Id'):self.assertIn(name,names)
            self.assertTrue(result['macro_expansion_omitted']);self.assertFalse(result['syntax_errors'])

    def test_malformed_bounded_protected_and_cancellation(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);(root/'broken.rs').write_text('fn ok() {}\nfn broken(',encoding='utf-8');(root/'many.go').write_text('package p\n'+'\n'.join('func f%d() {}'%i for i in range(200)),encoding='utf-8');(root/'.env.go').write_text('package p',encoding='utf-8')
            files=ProjectFiles(root);broken=systems_outline(files,'broken.rs');self.assertTrue(broken['syntax_errors']);self.assertTrue(broken['incomplete']);self.assertIn('ok',[x['name'] for x in broken['symbols']])
            result=systems_outline(files,'many.go');self.assertTrue(result['incomplete']);self.assertEqual(len(result['symbols']),150)
            for path in ('.env.go','../outside.go','bad.py'):
                with self.subTest(path=path),self.assertRaises((ValueError,ProjectToolError)):systems_outline(files,path)
            with self.assertRaises(InterruptedError):systems_outline(files,'many.go',lambda:(_ for _ in ()).throw(InterruptedError()))
            calls=[0]
            def cancel_during_parse():
                calls[0]+=1
                if calls[0]>=3:raise InterruptedError('cancelled during parsing')
            with self.assertRaises(InterruptedError):systems_outline(files,'many.go',cancel_during_parse)


    def test_model_tool_call_and_targeted_read(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'lib.rs').write_text('pub fn hello() -> u32 { 42 }\n',encoding='utf-8')
            replies=[Wire(chat(calls=[call('systems_outline',{'path':'lib.rs'})],finish='tool_calls'),False),Wire(chat(calls=[call('read_file_range',{'path':'lib.rs','start_line':'1','end_line':'1'})],finish='tool_calls'),False),Wire(chat('Done'),False)];bodies=[];events=[]
            def request(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch('agentnik.core.open_request',side_effect=request):CodingRun(dict(C,stream=False),root,'Inspect').run(events.append)
            self.assertEqual(events[-1]['status'],'completed');result=next(json.loads(m['content']) for m in bodies[1]['messages'] if m.get('role')=='tool');self.assertEqual(result['symbols'][0]['name'],'hello');self.assertIn('42',json.dumps(bodies[2]))
