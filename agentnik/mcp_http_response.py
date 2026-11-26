"""Shared JSON and SSE response parsing for MCP HTTP clients."""
import json

from .mcp_support import MCPListChangedError


def response_message(data,content_type,expected_id,on_list_changed=None,on_server_request=None):
    if content_type=='application/json':messages=[data]
    elif content_type=='text/event-stream':
        messages=[];parts=[]
        if data.startswith(b'\xef\xbb\xbf'):data=data[3:]
        # Normalize the three SSE line terminators; a blank line dispatches an event.
        lines=data.replace(b'\r\n',b'\n').replace(b'\r',b'\n').split(b'\n')
        for line in lines[:-1]:
            if not line:
                if parts and any(parts):messages.append(b'\n'.join(parts))
                parts=[];continue
            if line.startswith(b':'):continue
            field,separator,value=line.partition(b':')
            if field==b'data':
                if separator and value.startswith(b' '):value=value[1:]
                parts.append(value)
        # Never accept an unterminated data event, even after a valid response.
        if parts or lines[-1].partition(b':')[0]==b'data':raise ValueError('Incomplete MCP event stream')
    else:raise ValueError('Unsupported MCP response type')
    found=[]
    for raw in messages:
        try:message=json.loads(raw)
        except (ValueError,UnicodeError,RecursionError):raise ValueError('Invalid MCP response') from None
        if not isinstance(message,dict) or message.get('jsonrpc')!='2.0':raise ValueError('Invalid MCP response')
        if 'id' in message and 'method' in message:
            if on_server_request is None:raise ValueError('Unsupported server request or unexpected response')
            on_server_request(message)
        elif message.get('id')==expected_id and type(message.get('id')) is int:found.append(message)
        elif 'id' in message:raise ValueError('Unsupported server request or unexpected response')
        elif message.get('method') in ('notifications/tools/list_changed','notifications/resources/list_changed','notifications/prompts/list_changed'):
            if on_list_changed is None:raise MCPListChangedError('MCP server list changed')
            on_list_changed(message['method'])
    if len(found)!=1:raise ValueError('Missing or duplicate MCP response')
    return found[0]


