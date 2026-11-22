"""Validate MCP prompt and resource-template argument completion."""
import json
from .mcp_resources import template_variables


def completion_params(kind,target,argument,value,context):
    if kind=='prompt':
        if not isinstance(target,dict) or not isinstance(target.get('name'),str) or not isinstance(target.get('arguments'),list):raise ValueError('Invalid MCP prompt reference')
        fields=[item.get('name') for item in target['arguments'] if isinstance(item,dict)]
        if len(fields)!=len(target['arguments']) or any(not isinstance(name,str) for name in fields):raise ValueError('Invalid MCP prompt arguments')
        ref={'type':'ref/prompt','name':target['name']}
    elif kind=='resource':
        if not isinstance(target,dict) or target.get('supported') is not True:raise ValueError('Invalid MCP resource template')
        template=target.get('uriTemplate');fields=template_variables(template);ref={'type':'ref/resource','uri':template}
    else:raise ValueError('Invalid MCP completion reference')
    if not isinstance(argument,str) or argument not in fields or not isinstance(value,str) or not isinstance(context,dict):raise ValueError('Invalid MCP completion arguments')
    if any(not isinstance(key,str) or key not in fields or not isinstance(item,str) for key,item in context.items()):raise ValueError('Invalid MCP completion context')
    if len(json.dumps({'value':value,'context':context},ensure_ascii=False).encode('utf-8'))>16000:raise ValueError('MCP completion arguments exceed the limit')
    params={'ref':ref,'argument':{'name':argument,'value':value}}
    if context:params['context']={'arguments':dict(context)}
    return params


def parse_completion(result):
    completion=result.get('completion') if isinstance(result,dict) else None
    if not isinstance(completion,dict):raise ValueError('Invalid MCP completion result')
    values=completion.get('values');total=completion.get('total');more=completion.get('hasMore')
    if not isinstance(values,list) or len(values)>100 or any(not isinstance(value,str) for value in values):raise ValueError('Invalid MCP completion values')
    if total is not None and (type(total) is not int or total<0):raise ValueError('Invalid MCP completion total')
    if more is not None and type(more) is not bool:raise ValueError('Invalid MCP completion indicator')
    result={'values':values}
    if total is not None:result['total']=total
    if more is not None:result['hasMore']=more
    return result
