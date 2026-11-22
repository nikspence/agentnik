"""Small 2025 MCP server that waits for an elicitation response."""
import json
import sys
import threading
import time

pending=None;calls=0
for line in sys.stdin:
    request=json.loads(line);method=request.get('method');ident=request.get('id')
    if method=='initialize':
        assert request['params']['capabilities']['elicitation']=={'form':{},'url':{}}
        result={'protocolVersion':sys.argv[1] if len(sys.argv)>1 else '2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'Legacy','version':'1'}}
    elif method=='tools/list':result={'tools':[{'name':'echo','inputSchema':{'type':'object','properties':{},'additionalProperties':False}}]}
    elif method=='tools/call':
        calls+=1
        if len(sys.argv)>2 and sys.argv[2] in ('required','required-notification'):
            if calls==1:
                error={'code':-32042,'message':'External action required','data':{'elicitations':[{'mode':'url','elicitationId':'synthetic-id','message':'Review','url':'https://example.test/consent'}]}}
                print(json.dumps({'jsonrpc':'2.0','id':ident,'error':error}),flush=True)
                if sys.argv[2]=='required-notification':
                    def notify():
                        time.sleep(.4)
                        for value in ('unknown','synthetic-id','synthetic-id'):
                            print(json.dumps({'jsonrpc':'2.0','method':'notifications/elicitation/complete','params':{'elicitationId':value}}),flush=True)
                    threading.Thread(target=notify,daemon=True).start()
            else:print(json.dumps({'jsonrpc':'2.0','id':ident,'result':{'content':[{'type':'text','text':'retried'}]}}),flush=True)
            continue
        pending=ident
        params={'mode':'url','elicitationId':'synthetic-id','message':'Review','url':'https://example.test/consent'} if len(sys.argv)>2 and sys.argv[2]=='url' else {'message':'Choose','requestedSchema':{'type':'object','properties':{'choice':{'type':'string'}},'required':['choice']}}
        print(json.dumps({'jsonrpc':'2.0','id':'input-1','method':'elicitation/create','params':params}),flush=True)
        continue
    elif method is None and ident=='input-1':
        answer=request.get('result')
        assert answer in ({'action':'accept','content':{'choice':'yes'}},{'action':'accept'},{'action':'decline'})
        print(json.dumps({'jsonrpc':'2.0','id':pending,'result':{'content':[{'type':'text','text':answer['action']}]}}),flush=True)
        continue
    else:continue
    print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result}),flush=True)
