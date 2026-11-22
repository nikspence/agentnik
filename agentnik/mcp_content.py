"""Separate MCP tool content by its server-declared intended audience."""
import copy
import base64
import binascii


def decode_tool_text_resources(result):
    """Decode supported embedded text resources before credential checks."""
    from .mcp_resources import parse_resource_contents,text_blob_mime
    output=copy.deepcopy(result)
    for block in output['content']:
        if not isinstance(block,dict) or block.get('type')!='resource':continue
        resource=block.get('resource')
        if not isinstance(resource,dict) or 'blob' not in resource or not text_blob_mime(resource.get('mimeType')):continue
        uri=resource.get('uri')
        if not isinstance(uri,str) or not uri or len(uri)>2048 or any(ord(ch)<32 or ord(ch)==127 for ch in uri):raise ValueError('Invalid embedded MCP resource URI')
        block['resource']=parse_resource_contents({'contents':[resource]},uri)['contents'][0]
    return output


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
            elif block.get('type')=='resource' and isinstance(block.get('resource'),dict) and isinstance(block['resource'].get('text'),str):user_text.append(block['resource']['text'])
            else:user_nontext+=1
    output=copy.deepcopy(result);output['content']=content
    return output,user_text,user_nontext


def model_images(result,enabled,slots,label):
    """Move assistant-directed MCP images into a bounded visual model input."""
    from .image_generation import MAX_IMAGE_BYTES,image_bytes
    output=copy.deepcopy(result);images=[];content=[]
    for block in output['content']:
        if block.get('type')=='audio':
            content.append({'type':'text','text':'MCP audio content is not supported for model input.'});continue
        if block.get('type')=='resource':
            resource=block.get('resource')
            if not isinstance(resource,dict):
                content.append({'type':'text','text':'The embedded MCP resource was invalid.'});continue
            if 'blob' in resource:
                uri=resource.get('uri');mime=resource.get('mimeType')
                if not isinstance(uri,str) or not uri or len(uri)>2048 or any(ord(ch)<32 or ord(ch)==127 for ch in uri) or 'text' in resource:
                    content.append({'type':'text','text':'The embedded MCP resource was invalid.'});continue
                transformed,visual=model_images({'content':[{'type':'image','data':resource['blob'],'mimeType':mime}]},enabled,max(0,slots-len(images)),label)
                images.extend(visual)
                content.append({'type':'resource','resource':{'uri':uri,'mimeType':mime if isinstance(mime,str) and len(mime)<=256 else '', 'notice':transformed['content'][0]['text']}})
                continue
        if block.get('type')!='image':content.append(block);continue
        reason='Image inspection is disabled or unavailable for this request.'
        if enabled and len(images)<slots:
            try:
                encoded=block.get('data');mime=block.get('mimeType')
                if not isinstance(encoded,str) or len(encoded)>4*((MAX_IMAGE_BYTES+2)//3):raise ValueError()
                data=base64.b64decode(encoded,validate=True);detected,_=image_bytes(data)
                if mime!=detected:raise ValueError()
                images.append((label+' image '+str(len(images)+1),data,detected))
                reason='The image follows as untrusted visual content.'
            except (ValueError,binascii.Error):reason='The MCP image was invalid or unsupported.'
        elif enabled:reason='The image was not included because the image batch limit was reached.'
        content.append({'type':'text','text':reason})
    output['content']=content
    return output,images


def model_resource_contents(contents,enabled,slots,label):
    """Keep resource image bytes out of textual tool output and activity."""
    safe=[];images=[]
    for item in contents:
        if 'blob' not in item:safe.append(copy.deepcopy(item));continue
        block={'type':'image','data':item['blob'],'mimeType':item['mimeType']}
        transformed,visual=model_images({'content':[block]},enabled,max(0,slots-len(images)),label)
        images.extend(visual)
        safe.append({'uri':item['uri'],'mimeType':item['mimeType'],'notice':transformed['content'][0]['text']})
    return safe,images
