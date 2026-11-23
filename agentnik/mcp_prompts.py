"""Bounded untrusted MCP prompt templates and text messages."""
import json

class PromptPages:
    def __init__(self):
        self.items=[];self.names=set();self.cursors=set();self.pages=0;self.size=0

    def accept(self,result):
        entries=result.get('prompts');cursor=result.get('nextCursor')
        if not isinstance(entries,list) or len(entries)>100 or (cursor is not None and (not isinstance(cursor,str) or not cursor or len(cursor)>1024 or cursor in self.cursors)):raise ValueError('Invalid MCP prompt list')
        if cursor:self.cursors.add(cursor)
        self.pages+=1;clipped=False
        for entry in entries:
            if not isinstance(entry,dict):raise ValueError('Invalid MCP prompt')
            name=entry.get('name');description=entry.get('description','');arguments=entry.get('arguments',[])
            if not isinstance(name,str) or not name or len(name)>128 or any(ord(c)<32 or ord(c)==127 for c in name) or name in self.names:raise ValueError('Invalid MCP prompt name')
            if not isinstance(description,str) or len(description)>4000 or not isinstance(arguments,list) or len(arguments)>32:raise ValueError('Invalid MCP prompt metadata')
            self.names.add(name);fields=[];field_names=set()
            for arg in arguments:
                if not isinstance(arg,dict):raise ValueError('Invalid MCP prompt argument')
                field=arg.get('name');desc=arg.get('description','');required=arg.get('required',False)
                if not isinstance(field,str) or not field or len(field)>128 or any(ord(c)<32 or ord(c)==127 for c in field) or field in field_names or not isinstance(desc,str) or len(desc)>2000 or type(required) is not bool:raise ValueError('Invalid MCP prompt argument')
                field_names.add(field);fields.append({'name':field,'description':desc,'required':required})
            item={'name':name,'description':description,'arguments':fields};size=len(json.dumps(item,ensure_ascii=True).encode('ascii'))
            if clipped or len(self.items)>=100 or self.size+size>200000:clipped=True;continue
            self.items.append(item);self.size+=size
        more=clipped or bool(cursor)
        return (cursor if cursor and not clipped and len(self.items)<100 and self.pages<5 else None),{'prompts':list(self.items),'more_prompts':more}


def validate_prompt_arguments(prompt,arguments):
    if not isinstance(arguments,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in arguments.items()):raise ValueError('Prompt arguments must be strings.')
    if len(json.dumps(arguments,ensure_ascii=False).encode('utf-8'))>16000:raise ValueError('Prompt arguments exceed the limit.')
    fields={a['name']:a for a in prompt['arguments']}
    if set(arguments)-set(fields) or any(field['required'] and field['name'] not in arguments for field in fields.values()):raise ValueError('Prompt arguments do not match its definition.')
    return True


def parse_prompt_messages(result):
    description=result.get('description','');messages=result.get('messages')
    if not isinstance(description,str) or len(description)>4000 or not isinstance(messages,list) or len(messages)>16:raise ValueError('Invalid MCP prompt result')
    from .mcp_content import model_tool_result
    from .mcp_resources import parse_resource_contents
    safe=[];user_text=[];user_nontext=0
    for message in messages:
        if not isinstance(message,dict) or message.get('role') not in ('user','assistant'):raise ValueError('Invalid MCP prompt message')
        content=message.get('content')
        if not isinstance(content,dict):raise ValueError('Unsupported MCP prompt content')
        if content.get('type')=='text':
            text=content.get('text')
            if not isinstance(text,str) or len(text.encode('utf-8'))>32000:raise ValueError('Unsupported MCP prompt content')
            sanitized={'type':'text','text':text}
        elif content.get('type')=='image':
            from .image_generation import MAX_IMAGE_BYTES
            data=content.get('data');mime=content.get('mimeType')
            if not isinstance(data,str) or not data or len(data)>4*((MAX_IMAGE_BYTES+2)//3) or mime not in ('image/png','image/jpeg','image/webp'):raise ValueError('Invalid MCP prompt image')
            sanitized={'type':'image','data':data,'mimeType':mime}
        elif content.get('type')=='resource':
            resource=content.get('resource')
            if not isinstance(resource,dict):raise ValueError('Invalid embedded MCP resource')
            uri=resource.get('uri')
            if not isinstance(uri,str) or not uri or len(uri)>2048 or any(ord(c)<32 or ord(c)==127 for c in uri):raise ValueError('Invalid embedded MCP resource URI')
            checked=parse_resource_contents({'contents':[resource]},uri)['contents'][0]
            sanitized={'type':'resource','resource':checked}
        else:raise ValueError('Unsupported MCP prompt content')
        if 'annotations' in content:sanitized['annotations']=content['annotations']
        visible,_,_=model_tool_result({'content':[sanitized]})
        if visible['content']:
            safe.append({'role':message['role'],'content':visible['content'][0]})
        elif content.get('annotations',{}).get('audience') and 'user' in content['annotations']['audience']:
            if content['type']=='image' or (content['type']=='resource' and 'blob' in checked):user_nontext+=1
            else:user_text.append(text if content['type']=='text' else checked['text'])
    return {'description':description,'messages':safe,'user_text':user_text,'user_nontext':user_nontext}
