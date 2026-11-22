import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from agentnik import compat_tools
from agentnik.code_agent import CodingRun,ProjectFiles
from agentnik.subagent_outputs import StagedOutputs
from agentnik.tools import ToolCall
from test_code_agent import C
from test_image_generation import png

class SubagentWrites(unittest.TestCase):
    def test_staged_outputs_do_not_escape_or_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            files=ProjectFiles(root);out=StagedOutputs(files,'out',[('source.png',png(),'image/png')])
            for path in ('../escape','.git/config','AGENTS.md','/absolute'):
                with self.subTest(path=path),self.assertRaises(ValueError):out.write(path,'content')
            out.write('text-layer.json','{}');out.copy_image('source.png','source.png');out.crop_image('source.png','visual/crop.png','0','0','2','1')
            self.assertFalse(Path(root,'out').exists());self.assertEqual(len(out.publish(lambda:None)),3)
            self.assertEqual(Path(root,'out','text-layer.json').read_text(),'{}')
            with self.assertRaises(ValueError):out.write('text-layer.json','changed')

    def test_existing_output_appearing_after_staging_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            staged=StagedOutputs(ProjectFiles(root),'out');staged.write('slide.json','generated')
            Path(root,'out').mkdir();Path(root,'out','slide.json').write_text('user content')
            with self.assertRaises(ValueError):staged.publish(lambda:None)
            self.assertEqual(Path(root,'out','slide.json').read_text(),'user content')

    def test_overlapping_child_output_folders_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            events=[];parent=[0];run=CodingRun(dict(C,stream=False),root,'Create')
            tasks=[{'task':'First','output_dir':'out'},{'task':'Second','output_dir':'out/sub'}]
            def request(c,body,runtime,emit,state,*args,**kwargs):
                parent[0]+=1
                if parent[0]==1:return {'role':'assistant','content':''},[ToolCall('d','delegate_subagents',{'tasks':json.dumps(tasks)})]
                self.assertIn('must not overlap',json.dumps(body));state['text']='Done';return {'role':'assistant','content':'Done'},[]
            with patch.object(compat_tools,'request',side_effect=request):run.run(events.append)
            self.assertFalse(Path(root,'out').exists());self.assertFalse(any(e['kind']=='subagent' for e in events))

    def test_parallel_children_publish_scoped_files_after_success(self):
        with tempfile.TemporaryDirectory() as root:
            events=[];parent_count=[0];counts={};lock=threading.Lock()
            run=CodingRun(dict(C,stream=False),root,'Create two slides')
            tasks=[{'task':'Slide one','output_dir':'editable/slide-01'},{'task':'Slide two','output_dir':'editable/slide-02'}]
            def request(connection,body,runtime,emit,state,*args,**kwargs):
                text=json.dumps(body)
                if 'Independent read-only coding analysis.' not in text and 'Independent coding task.' not in text:
                    parent_count[0]+=1
                    if parent_count[0]==1:return {'role':'assistant','content':''},[ToolCall('d','delegate_subagents',{'tasks':json.dumps(tasks)})]
                    state['text']='Done';return {'role':'assistant','content':'Done'},[]
                task='one' if 'Task: Slide one' in text else 'two'
                with lock:counts[task]=counts.get(task,0)+1;number=counts[task]
                if number==1:
                    return {'role':'assistant','content':''},[ToolCall('w','write_file',{'path':'text-layer.json','content':json.dumps({'slide':task})}),ToolCall('q','write_file',{'path':'qa/qa.md','content':'Checked'})]
                state['text']='Created';return {'role':'assistant','content':'Created'},[]
            with patch.object(compat_tools,'request',side_effect=request):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events)
            for num,word in [('01','one'),('02','two')]:
                folder=Path(root,'editable','slide-'+num)
                self.assertEqual(json.loads((folder/'text-layer.json').read_text())['slide'],word)
                self.assertEqual((folder/'qa'/'qa.md').read_text(),'Checked')
            self.assertTrue(any('wrote:' in e.get('text','') for e in events))

    def test_failed_child_does_not_publish_staged_files(self):
        with tempfile.TemporaryDirectory() as root:
            run=CodingRun(dict(C,stream=False),root,'Create');events=[];parent=[0];child=[0]
            tasks=[{'task':'Broken','output_dir':'out/one'},'Other']
            def request(c,body,runtime,emit,state,*args,**kwargs):
                text=json.dumps(body)
                if 'Independent read-only coding analysis.' not in text and 'Independent coding task.' not in text:
                    parent[0]+=1
                    if parent[0]==1:return {'role':'assistant','content':''},[ToolCall('d','delegate_subagents',{'tasks':json.dumps(tasks)})]
                    state['text']='Done';return {'role':'assistant','content':'Done'},[]
                if 'Task: Other' in text:state['text']='Done';return {'role':'assistant','content':'Done'},[]
                child[0]+=1
                if child[0]==1:return {'role':'assistant','content':''},[ToolCall('w','write_file',{'path':'draft.txt','content':'partial'})]
                raise ValueError('model failed')
            with patch.object(compat_tools,'request',side_effect=request):run.run(events.append)
            self.assertFalse(Path(root,'out','one','draft.txt').exists())
