"""Synthetic task requiring a related elicitation request."""
import json
import sys

pending=None
for line in sys.stdin:
    request=json.loads(line);method=request.get('method');ident=request.get('id')
    if method=='initialize':result={'protocolVersion':'2025-11-25','serverInfo':{'name':'Fixture','version':'1'},'capabilities':{'tools':{},'tasks':{'requests':{'tools':{'call':{}}}}}}
    elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'},'execution':{'taskSupport':'required'}}]}
    elif method=='tools/call':result={'task':{'taskId':'task-1','status':'working','createdAt':'2026-01-01T00:00:00Z','lastUpdatedAt':'2026-01-01T00:00:00Z','ttl':None}}
    elif method=='tasks/result':
        pending=ident
        params={'message':'Choose','requestedSchema':{'type':'object','properties':{'choice':{'type':'string'}},'required':['choice']},'_meta':{'io.modelcontextprotocol/related-task':{'taskId':'other' if sys.argv[1]=='mismatch' else 'task-1'}}}
        print(json.dumps({'jsonrpc':'2.0','id':'input','method':'elicitation/create','params':params}),flush=True);continue
    elif method is None and ident=='input':
        if sys.argv[1]=='mismatch':assert request['error']['code']==-32602
        else:assert request['result']=={'action':'accept','content':{'choice':'yes'},'_meta':{'io.modelcontextprotocol/related-task':{'taskId':'task-1'}}}
        result={'content':[{'type':'text','text':'done'}],'_meta':{'io.modelcontextprotocol/related-task':{'taskId':'task-1'}}};ident=pending
    else:continue
    print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result}),flush=True)
