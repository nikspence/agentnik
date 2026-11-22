"""Synthetic modern-only MCP stdio server for offline tests."""
import json
import sys
import time

pending=None;subscription_count=0
for line in sys.stdin:
    message=json.loads(line);method=message.get('method');ident=message.get('id')
    if method=='notifications/cancelled' and pending is not None:
        with open(sys.argv[1],'w',encoding='utf-8') as file:json.dump({'requestId':message['params']['requestId'],'original':pending},file)
        continue
    if ident is None:continue
    if method=='initialize' and '--ignore-initialize' in sys.argv:continue
    if method=='initialize' and '--delay-reject' in sys.argv:time.sleep(1.3)
    if method=='initialize':response={'error':{'code':-32022,'message':'modern protocol required','data':{'supported':['2026-07-28']}}}
    else:
        metadata=message.get('params',{}).get('_meta',{})
        if metadata.get('io.modelcontextprotocol/protocolVersion')!='2026-07-28':response={'error':{'code':-32602,'message':'missing metadata'}}
        elif method=='server/discover':
            capabilities={'tools':{}}
            if '--subscriptions' in sys.argv:capabilities.update(resources={'listChanged':True},prompts={'listChanged':True})
            if '--resource-input' in sys.argv:capabilities['resources']={}
            if '--prompt-input' in sys.argv:capabilities['prompts']={}
            response={'result':{'supportedVersions':['2026-07-28'],'capabilities':capabilities}}
        elif method=='resources/list':response={'result':{'resources':[{'uri':'test://resource','name':'Resource'}]}}
        elif method=='prompts/list':response={'result':{'prompts':[{'name':'prompt','arguments':[]}]}}
        elif method in ('resources/read','prompts/get'):response={'result':{'resultType':'input_required','inputRequests':{'question':{'method':'elicitation/create','params':{'message':'private-server-text'}}},'requestState':'private-state'}}
        elif method=='subscriptions/listen':
            subscription=ident;subscription_count+=1
            print(json.dumps({'jsonrpc':'2.0','method':'notifications/subscriptions/acknowledged','params':{'notifications':message['params']['notifications'],'_meta':{'io.modelcontextprotocol/subscriptionId':ident}}}),flush=True)
            if '--end-first-subscription' in sys.argv and subscription_count==1:print(json.dumps({'jsonrpc':'2.0','id':ident,'result':{}}),flush=True)
            continue
        elif method=='tools/list':response={'result':{'tools':[{'name':'echo','inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}]}}
        elif method=='tools/call':
            if message['params']['arguments']['text']=='input':
                response={'result':{'resultType':'input_required','inputRequests':{'question':{'method':'elicitation/create','params':{'message':'private-server-text'}}},'requestState':'private-state'}}
                print(json.dumps(dict(response,jsonrpc='2.0',id=ident)),flush=True);continue
            if message['params']['arguments']['text']=='notify':
                for kind in ('resources','prompts'):
                    print(json.dumps({'jsonrpc':'2.0','method':'notifications/'+kind+'/list_changed','params':{'_meta':{'io.modelcontextprotocol/subscriptionId':subscription}}}),flush=True)
            if message['params']['arguments']['text']=='wait':
                pending=ident;print(json.dumps({'jsonrpc':'2.0','method':'notifications/progress','params':{'progressToken':message['params']['_meta']['progressToken'],'progress':1,'total':2}}),flush=True);continue
            response={'result':{'content':[{'type':'text','text':message['params']['arguments']['text']}]}}
        else:response={'error':{'code':-32601,'message':'unknown method'}}
    print(json.dumps(dict(response,jsonrpc='2.0',id=ident)),flush=True)
