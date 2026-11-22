"""Synthetic stdio servers for modern-first negotiation."""
import json
import sys
import time
from pathlib import Path

mode,record=sys.argv[1:3]
first=not Path(record).exists()
with Path(record).open('a',encoding='utf-8') as output:output.write('start\n')
if mode=='slow_modern' and first:time.sleep(20)
for line in sys.stdin:
    request=json.loads(line);method=request.get('method');ident=request.get('id')
    with Path(record).open('a',encoding='utf-8') as output:output.write(str(method)+'\n')
    if method=='server/discover':
        if mode=='exit':sys.exit(0)
        if mode=='silent':time.sleep(20);continue
        if mode in ('error','modern_error'):
            error={'code':-32022 if mode=='modern_error' else -32601,'message':'private diagnostic'}
            print(json.dumps({'jsonrpc':'2.0','id':ident,'error':error}),flush=True);continue
        result={'supportedVersions':['2026-07-28','2025-11-25'],'capabilities':{}}
    elif method=='initialize':
        if mode=='slow_modern':print(json.dumps({'jsonrpc':'2.0','id':ident,'error':{'code':-32022,'message':'modern required'}}),flush=True);continue
        result={'protocolVersion':'2025-11-25','serverInfo':{'name':'Legacy','version':'1'},'capabilities':{}}
    elif method=='notifications/initialized':continue
    else:raise RuntimeError(method)
    print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result}),flush=True)
