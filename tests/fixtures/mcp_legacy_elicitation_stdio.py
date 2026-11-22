"""Small 2025 MCP server that waits for an elicitation response."""
import json
import sys

pending=None
for line in sys.stdin:
    request=json.loads(line);method=request.get('method');ident=request.get('id')
    if method=='initialize':
        assert request['params']['capabilities']['elicitation']=={}
        result={'protocolVersion':sys.argv[1] if len(sys.argv)>1 else '2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'Legacy','version':'1'}}
    elif method=='tools/list':result={'tools':[{'name':'echo','inputSchema':{'type':'object','properties':{},'additionalProperties':False}}]}
    elif method=='tools/call':
        pending=ident
        print(json.dumps({'jsonrpc':'2.0','id':'input-1','method':'elicitation/create','params':{'message':'Choose','requestedSchema':{'type':'object','properties':{'choice':{'type':'string'}},'required':['choice']}}}),flush=True)
        continue
    elif method is None and ident=='input-1':
        answer=request.get('result')
        assert answer in ({'action':'accept','content':{'choice':'yes'}},{'action':'decline'})
        print(json.dumps({'jsonrpc':'2.0','id':pending,'result':{'content':[{'type':'text','text':answer['action']}]}}),flush=True)
        continue
    else:continue
    print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result}),flush=True)
