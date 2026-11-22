"""Synthetic modern-only MCP stdio server for offline tests."""
import json
import sys

pending=None
for line in sys.stdin:
    message=json.loads(line);method=message.get('method');ident=message.get('id')
    if method=='notifications/cancelled' and pending is not None:
        with open(sys.argv[1],'w',encoding='utf-8') as file:json.dump({'requestId':message['params']['requestId'],'original':pending},file)
        continue
    if ident is None:continue
    if method=='initialize':response={'error':{'code':-32022,'message':'modern protocol required','data':{'supported':['2026-07-28']}}}
    else:
        metadata=message.get('params',{}).get('_meta',{})
        if metadata.get('io.modelcontextprotocol/protocolVersion')!='2026-07-28':response={'error':{'code':-32602,'message':'missing metadata'}}
        elif method=='server/discover':response={'result':{'supportedVersions':['2026-07-28'],'capabilities':{'tools':{}}}}
        elif method=='tools/list':response={'result':{'tools':[{'name':'echo','inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}]}}
        elif method=='tools/call':
            if message['params']['arguments']['text']=='wait':
                pending=ident;print(json.dumps({'jsonrpc':'2.0','method':'notifications/progress','params':{'progressToken':message['params']['_meta']['progressToken'],'progress':1,'total':2}}),flush=True);continue
            response={'result':{'content':[{'type':'text','text':message['params']['arguments']['text']}]}}
        else:response={'error':{'code':-32601,'message':'unknown method'}}
    print(json.dumps(dict(response,jsonrpc='2.0',id=ident)),flush=True)
