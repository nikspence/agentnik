"""Synthetic modern-only MCP stdio server for offline tests."""
import json
import sys
import time

pending=None;subscription_count=0;modern_task_kind=None;modern_task_polls=0;modern_task_updates=0
for line in sys.stdin:
    message=json.loads(line);method=message.get('method');ident=message.get('id')
    if method=='notifications/cancelled' and pending is not None:
        with open(sys.argv[1],'w',encoding='utf-8') as file:json.dump({'requestId':message['params']['requestId'],'original':pending},file)
        continue
    if ident is None:continue
    if method=='initialize' and '--ignore-initialize' in sys.argv:continue
    if method=='initialize' and '--delay-reject' in sys.argv:time.sleep(1.3)
    if method=='initialize':
        init_code=next((int(arg.split('=',1)[1]) for arg in sys.argv[1:] if arg.startswith('--init-error=')),-32022)
        response={'error':{'code':init_code,'message':'modern protocol required','data':{'supported':['2026-07-28']}}}
    else:
        metadata=message.get('params',{}).get('_meta',{})
        if metadata.get('io.modelcontextprotocol/protocolVersion')!='2026-07-28':response={'error':{'code':-32602,'message':'missing metadata'}}
        elif method=='server/discover':
            capabilities={'tools':{}}
            if '--modern-tasks' in sys.argv:capabilities['extensions']={'io.modelcontextprotocol/tasks':{}}
            if '--subscriptions' in sys.argv:capabilities.update(resources={'listChanged':True},prompts={'listChanged':True})
            if '--resource-input' in sys.argv:capabilities['resources']={}
            if '--prompt-input' in sys.argv:capabilities['prompts']={}
            response={'result':{'supportedVersions':['2026-07-28'],'capabilities':capabilities}}
        elif method=='resources/list':response={'result':{'resources':[{'uri':'test://resource','name':'Resource'}]}}
        elif method=='prompts/list':response={'result':{'prompts':[{'name':'prompt','arguments':[]}]}}
        elif method in ('resources/read','prompts/get'):
            if 'inputResponses' in message['params']:
                assert message['params']['requestState']=='private-state'
                assert message['params']['inputResponses']['question']=={'action':'accept','content':{'choice':'yes'}}
                response={'result':{'contents':[{'uri':'test://resource','text':'continued'}]} if method=='resources/read' else {'messages':[{'role':'user','content':{'type':'text','text':'continued'}}]}}
            else:response={'result':{'resultType':'input_required','inputRequests':{'question':{'method':'elicitation/create','params':{'message':'private-server-text','requestedSchema':{'type':'object','properties':{'choice':{'type':'string'}},'required':['choice']}}}},'requestState':'private-state'}}
        elif method=='subscriptions/listen':
            subscription=ident;subscription_count+=1
            print(json.dumps({'jsonrpc':'2.0','method':'notifications/subscriptions/acknowledged','params':{'notifications':message['params']['notifications'],'_meta':{'io.modelcontextprotocol/subscriptionId':ident}}}),flush=True)
            if '--end-first-subscription' in sys.argv and subscription_count==1:print(json.dumps({'jsonrpc':'2.0','id':ident,'result':{}}),flush=True)
            continue
        elif method=='tools/list':response={'result':{'tools':[{'name':'echo','inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}]}}
        elif method=='tools/call':
            if message['params']['arguments']['text'] in ('task','task_input','task_wait','task_failed','task_leak','task_error_leak'):
                assert metadata['io.modelcontextprotocol/clientCapabilities']['extensions']['io.modelcontextprotocol/tasks']=={}
                modern_task_kind=message['params']['arguments']['text'];modern_task_polls=0;modern_task_updates=0
                response={'result':{'resultType':'task','taskId':'private-task-id','status':'working','createdAt':'2026-01-01T00:00:00Z','lastUpdatedAt':'2026-01-01T00:00:00Z','ttlMs':None,'pollIntervalMs':100}}
                print(json.dumps(dict(response,jsonrpc='2.0',id=ident)),flush=True);continue
            if message['params']['arguments']['text']=='url':
                if 'inputResponses' in message['params']:
                    assert message['params']['requestState']=='private-state'
                    assert message['params']['inputResponses']['question']=={'action':'accept'}
                    response={'result':{'content':[{'type':'text','text':'url continued'}]}}
                else:response={'result':{'resultType':'input_required','inputRequests':{'question':{'method':'elicitation/create','params':{'mode':'url','message':'Open browser','url':'https://example.test/private'}}},'requestState':'private-state'}}
                print(json.dumps(dict(response,jsonrpc='2.0',id=ident)),flush=True);continue
            if message['params']['arguments']['text']=='input':
                if 'inputResponses' in message['params']:
                    assert message['params']['requestState']=='private-state'
                    answer=message['params']['inputResponses']['question']
                    assert answer in ({'action':'accept','content':{'choice':'yes'}},{'action':'decline'})
                    response={'result':{'content':[{'type':'text','text':'declined' if answer['action']=='decline' else 'continued'}]}}
                else:
                    response={'result':{'resultType':'input_required','inputRequests':{'question':{'method':'elicitation/create','params':{'message':'private-server-text','requestedSchema':{'type':'object','properties':{'choice':{'type':'string','enum':['yes','no']}},'required':['choice']}}}},'requestState':'private-state'}}
                print(json.dumps(dict(response,jsonrpc='2.0',id=ident)),flush=True);continue
            if message['params']['arguments']['text']=='notify':
                for kind in ('resources','prompts'):
                    print(json.dumps({'jsonrpc':'2.0','method':'notifications/'+kind+'/list_changed','params':{'_meta':{'io.modelcontextprotocol/subscriptionId':subscription}}}),flush=True)
            if message['params']['arguments']['text']=='wait':
                pending=ident;print(json.dumps({'jsonrpc':'2.0','method':'notifications/progress','params':{'progressToken':message['params']['_meta']['progressToken'],'progress':1,'total':2}}),flush=True);continue
            response={'result':{'content':[{'type':'text','text':message['params']['arguments']['text']}]}}
        elif method in ('tasks/get','tasks/update','tasks/cancel'):
            assert metadata['io.modelcontextprotocol/clientCapabilities']['extensions']['io.modelcontextprotocol/tasks']=={}
            assert message['params']['taskId']=='private-task-id'
            state={'resultType':'complete','taskId':'private-task-id','status':'working','createdAt':'2026-01-01T00:00:00Z','lastUpdatedAt':'2026-01-01T00:00:00Z','ttlMs':None,'pollIntervalMs':100}
            if method=='tasks/cancel':
                record=next((arg.split('=',1)[1] for arg in sys.argv[1:] if arg.startswith('--cancel-record=')),None)
                if record:
                    with open(record,'w',encoding='utf-8') as file:json.dump({'method':method},file)
                response={'result':{'resultType':'complete'}}
            elif method=='tasks/update':
                assert message['params']['inputResponses']=={'question':{'action':'accept','content':{'choice':'yes'}}}
                modern_task_updates+=1;response={'result':{'resultType':'complete'}}
            else:
                modern_task_polls+=1
                if modern_task_kind in ('task_failed','task_error_leak'):state.update(status='failed',error={'code':-32603,'message':'private-task-id' if modern_task_kind=='task_error_leak' else 'synthetic task failure','data':{'private':'secret'}})
                elif modern_task_kind=='task_input' and modern_task_polls<=2:
                    state.update(status='input_required',inputRequests={'question':{'method':'elicitation/create','params':{'message':'Choose','requestedSchema':{'type':'object','properties':{'choice':{'type':'string'}},'required':['choice']}}}})
                elif modern_task_kind!='task_wait':
                    if modern_task_kind=='task_input':assert modern_task_updates==1
                    state.update(status='completed',result={'content':[{'type':'text','text':'private-task-id' if modern_task_kind=='task_leak' else 'task complete'}]})
                response={'result':state}
        else:response={'error':{'code':-32601,'message':'unknown method'}}
    print(json.dumps(dict(response,jsonrpc='2.0',id=ident)),flush=True)
