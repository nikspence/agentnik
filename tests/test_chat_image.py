import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from agentnik import core, research, image_generation
from agentnik.chat_image import ChatImageTool
from agentnik.storage import Store
from test_code_agent import call
from test_compat_tools import chat
from test_routing import Wire
from test_image_generation import png

class ChatImageTests(unittest.TestCase):
    def test_generated_image_is_saved_and_editable_without_leaking_path(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root); source=store.attach(data=png())
            tool=ChatImageTool({'connection':{'api_key':'image-secret'},'model':'image/model','endpoint':''},store,[{'role':'user','text':'Edit','images':[source]}])
            replies=[Wire(chat(calls=[call('image_gen',{'request':json.dumps({'prompt':'Make blue','references':['attachment:1']})})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            bodies=[];events=[]
            def send(c,url,body,timeout): bodies.append(copy.deepcopy(body)); return replies.pop(0)
            generated={'data':png(),'suffix':'.png','cost':0.1}
            with patch.object(core,'open_request',side_effect=send),patch.object(image_generation,'generate',return_value=generated) as gen:
                result=research.run({'url':'https://example.org/v1','model':'text','protocol':'chat','stream':False},[{'role':'user','text':'Edit','images':[source]}],'',events.append,threading.Event(),config={'local_tools':True,'web_enabled':False},image_tool=tool)
            self.assertEqual(result['status'],'ok',result.get('error'))
            self.assertTrue(Path(result['images'][0]).is_file());self.assertEqual(gen.call_args.args[3],[png()])
            session={'id':'image-session','mode':'chat','connection':{},'messages':[{'role':'user','text':'Edit','images':[source]},{'role':'assistant',**result}]}
            store.save(session); restored=store.list_sessions()[0]
            self.assertEqual(restored['messages'][-1]['images'],result['images']);store.collect_attachments()
            self.assertTrue(Path(result['images'][0]).exists())
            self.assertIn('generated:1',json.dumps(bodies[1]));self.assertNotIn(source,json.dumps(bodies[1]));self.assertNotIn('image-secret',json.dumps(result))
            self.assertTrue(any(e.get('images') for e in events))
            self.assertEqual(tool.prepare(json.dumps({'prompt':'again','references':['generated:1']}))[1],[png()])
            with self.assertRaises(ValueError):tool.prepare(json.dumps({'prompt':'bad','references':['../../secret']}))
            store.db.close()

    def test_uncertain_submission_does_not_retry(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);tool=ChatImageTool({'connection':{},'model':'m','endpoint':''},store,[{'role':'user','text':'Draw'}])
            reply=Wire(chat(calls=[call('image_gen',{'request':'{"prompt":"draw"}'})],finish='tool_calls'),False)
            with patch.object(core,'open_request',return_value=reply),patch.object(image_generation,'generate',side_effect=image_generation.ImageRequestUncertain('unknown')) as generate:
                result=research.run({'url':'https://example.org/v1','model':'text','protocol':'chat','stream':False},[{'role':'user','text':'Draw'}],'',lambda _:None,threading.Event(),config={'local_tools':True,'web_enabled':False},image_tool=tool)
            self.assertEqual(result['research']['failure']['kind'],'uncertain');self.assertFalse(result['research']['failure']['fallback_allowed']);generate.assert_called_once();store.db.close()

    def test_assistant_images_are_not_sent_as_user_input(self):
        for protocol in ('chat','responses','messages'):
            body=core.chat_body({'url':'https://example.org/v1','model':'text','protocol':protocol},[{'role':'assistant','text':'Created','images':['missing.png']}])
            self.assertNotIn('missing.png',json.dumps(body))

