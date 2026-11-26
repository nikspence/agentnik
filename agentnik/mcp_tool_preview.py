"""Bounded tool metadata shared by desktop and terminal transports."""
import json

MAX_PAGES=5
MAX_TOOLS=100
MAX_DESCRIPTION=8000
MAX_SCHEMA=32000
MAX_DETAILS=200000

def preview_tool(item):
    """Keep bounded server-provided metadata for display, never execution."""
    description=item.get('description','');schema=item.get('inputSchema')
    execution=item.get('execution',{})
    if not isinstance(execution,dict):raise ValueError('Invalid MCP tool execution metadata')
    task_support=execution.get('taskSupport','forbidden')
    if task_support not in ('forbidden','optional','required'):raise ValueError('Unsupported MCP task execution metadata')
    if not isinstance(description,str):raise ValueError('Invalid MCP tool description')
    if schema is not None and not isinstance(schema,dict):raise ValueError('Invalid MCP input schema')
    description_bytes=description.encode('utf-8');description_clipped=len(description_bytes)>MAX_DESCRIPTION
    description=description_bytes[:MAX_DESCRIPTION].decode('utf-8','ignore')
    detail={'description':description,'description_clipped':description_clipped,'task_support':task_support}
    if 'annotations' in item:
        annotations=item['annotations']
        if not isinstance(annotations,dict):raise ValueError('Invalid MCP tool annotations')
        hints={}
        for key in ('title','readOnlyHint','destructiveHint','idempotentHint','openWorldHint'):
            if key not in annotations:continue
            value=annotations[key]
            if key=='title':
                if not isinstance(value,str) or len(value)>256 or any(ord(ch)<32 or ord(ch)==127 for ch in value):raise ValueError('Invalid MCP tool annotation')
            elif type(value) is not bool:raise ValueError('Invalid MCP tool annotation')
            hints[key]=value
        detail['annotations']=hints
    if 'outputSchema' in item:
        output=item['outputSchema']
        if not isinstance(output,dict):raise ValueError('Invalid MCP output schema')
        encoded_output=json.dumps(output,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('ascii')
        detail['output_schema']=output if len(encoded_output)<=MAX_SCHEMA else None
        detail['output_schema_status']='available' if len(encoded_output)<=MAX_SCHEMA else 'oversized'
    if schema is None:return dict(detail,schema=None,schema_status='missing')
    encoded=json.dumps(schema,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('ascii')
    if len(encoded)>MAX_SCHEMA:return dict(detail,schema=None,schema_status='oversized')
    return dict(detail,schema=schema,schema_status='available')


def contains_secret(value,secret):
    if isinstance(value,str):return secret in value
    if isinstance(value,list):return any(contains_secret(item,secret) for item in value)
    if isinstance(value,dict):return any(contains_secret(key,secret) or contains_secret(item,secret) for key,item in value.items())
    return False


