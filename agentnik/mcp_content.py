"""Separate MCP tool content by its server-declared intended audience."""
import copy


def model_tool_result(result):
    """Return model-facing output and user-directed text from a validated call result.

    Audience annotations apply to content blocks, not structuredContent or _meta.
    They are server-provided hints and cannot guarantee that data is not repeated
    in other fields or blocks.
    """
    if not isinstance(result,dict) or not isinstance(result.get('content'),list):
        raise ValueError('Invalid MCP tool result content.')
    content=[];user_text=[];user_nontext=0
    for block in result['content']:
        if not isinstance(block,dict):raise ValueError('Invalid MCP tool content block.')
        annotations=block.get('annotations',{})
        if not isinstance(annotations,dict):raise ValueError('Invalid MCP content annotations.')
        audience=annotations.get('audience')
        if 'audience' in annotations and (not isinstance(audience,list) or any(not isinstance(role,str) or role not in ('user','assistant') for role in audience)):
            raise ValueError('Invalid MCP content audience.')
        if audience is None or 'assistant' in audience:content.append(copy.deepcopy(block))
        elif 'user' in audience:
            if block.get('type')=='text' and isinstance(block.get('text'),str):user_text.append(block['text'])
            else:user_nontext+=1
    output=copy.deepcopy(result);output['content']=content
    return output,user_text,user_nontext
