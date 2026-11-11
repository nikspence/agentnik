"""Validate bounded MCP resource metadata and text responses."""
import json
import re
from urllib.parse import quote

def parse_resources(result):
    entries=result.get('resources');cursor=result.get('nextCursor')
    if not isinstance(entries,list) or len(entries)>100 or (cursor is not None and (not isinstance(cursor,str) or not cursor or len(cursor)>1024)):raise ValueError('Invalid MCP resource list')
    resources=[];seen=set()
    for item in entries:
        if not isinstance(item,dict):raise ValueError('Invalid MCP resource')
        uri=item.get('uri');name=item.get('name');description=item.get('description','');mime=item.get('mimeType','')
        if not isinstance(uri,str) or not uri or len(uri)>2048 or any(ord(ch)<32 or ord(ch)==127 for ch in uri) or uri in seen:raise ValueError('Invalid MCP resource URI')
        if not isinstance(name,str) or not name or len(name)>256 or not isinstance(description,str) or len(description)>4000 or not isinstance(mime,str) or len(mime)>256:raise ValueError('Invalid MCP resource metadata')
        seen.add(uri);resources.append({'uri':uri,'name':name,'description':description,'mimeType':mime})
    return resources,cursor


def parse_resource_text(result,uri):
    contents=result.get('contents')
    if not isinstance(contents,list) or len(contents)>16:raise ValueError('Invalid MCP resource content')
    safe=[]
    for item in contents:
        if not isinstance(item,dict) or item.get('uri')!=uri or not isinstance(item.get('text'),str) or 'blob' in item or len(item['text'].encode('utf-8'))>32000:raise ValueError('Invalid MCP resource text')
        if 'mimeType' in item and (not isinstance(item['mimeType'],str) or len(item['mimeType'])>256):raise ValueError('Invalid MCP resource type')
        safe.append({key:item[key] for key in ('uri','text','mimeType') if key in item})
    return {'contents':safe}


class ResourcePages:
    """Accumulate a bounded listing while treating server cursors as opaque."""
    def __init__(self):
        self.items=[];self.cursors=set();self.uris=set();self.pages=0;self.size=0

    def accept(self,result):
        items,cursor=parse_resources(result);self.pages+=1
        if cursor is not None:
            if cursor in self.cursors:raise ValueError('Repeated MCP resource cursor')
            self.cursors.add(cursor)
        clipped=False
        for item in items:
            if item['uri'] in self.uris:raise ValueError('Duplicate MCP resource URI')
            self.uris.add(item['uri'])
            size=len(json.dumps(item,ensure_ascii=True).encode('ascii'))
            if clipped or len(self.items)>=100 or self.size+size>200000:
                clipped=True;continue
            self.items.append(item);self.size+=size
        more=clipped or bool(cursor)
        next_cursor=cursor if cursor and not clipped and len(self.items)<100 and self.pages<5 else None
        return next_cursor,{'resources':list(self.items),'more_resources':more}


def template_parts(template):
    """Parse a bounded scalar subset of RFC 6570 without reserved expansion."""
    if not isinstance(template,str) or not template or len(template)>2048 or any(ord(ch)<33 or ord(ch)==127 for ch in template):raise ValueError('Invalid resource template')
    parts=[];variables=[];pos=0;literal=0
    while pos<len(template):
        if template[pos]=='}':raise ValueError('Unsupported resource template')
        if template[pos]!='{':pos+=1;continue
        if literal<pos:parts.append((None,template[literal:pos]))
        end=template.find('}',pos+1)
        if end<0:raise ValueError('Unsupported resource template')
        expression=template[pos+1:end];operator=expression[:1] if expression[:1] in ('/','?','&') else ''
        names=expression[1:].split(',') if operator else expression.split(',')
        if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',name) for name in names):raise ValueError('Unsupported resource template')
        for name in names:
            if name not in variables:variables.append(name)
        if len(variables)>32 or len(names)>32:raise ValueError('Resource template too complex')
        parts.append((operator,names));pos=end+1;literal=pos
    if literal<len(template):parts.append((None,template[literal:]))
    return parts,variables


def template_variables(template):
    return template_parts(template)[1]


def expand_template(template,arguments):
    parts,names=template_parts(template)
    if not isinstance(arguments,dict) or set(arguments)!=set(names) or any(not isinstance(value,str) or len(value.encode('utf-8'))>1024 for value in arguments.values()):raise ValueError('Invalid resource template variables')
    chunks=[];size=0
    for operator,value in parts:
        if operator is None:chunk=value
        else:
            encoded=[quote(arguments[name],safe='') for name in value]
            if operator in ('?','&'):chunk=operator+'&'.join(name+'='+item for name,item in zip(value,encoded))
            elif operator=='/':chunk='/'+'/'.join(encoded)
            else:chunk=','.join(encoded)
        size+=len(chunk)
        if size>2048:raise ValueError('Expanded resource URI is invalid')
        chunks.append(chunk)
    uri=''.join(chunks)
    if any(ord(ch)<33 or ord(ch)==127 for ch in uri):raise ValueError('Expanded resource URI is invalid')
    return uri


class TemplatePages:
    def __init__(self):
        self.items=[];self.cursors=set();self.names=set();self.pages=0;self.size=0

    def accept(self,result):
        entries=result.get('resourceTemplates');cursor=result.get('nextCursor')
        if not isinstance(entries,list) or len(entries)>100 or (cursor is not None and (not isinstance(cursor,str) or not cursor or len(cursor)>1024 or cursor in self.cursors)):raise ValueError('Invalid resource template list')
        if cursor:self.cursors.add(cursor)
        self.pages+=1;clipped=False
        for item in entries:
            if not isinstance(item,dict):raise ValueError('Invalid resource template')
            template=item.get('uriTemplate');name=item.get('name');description=item.get('description','');mime=item.get('mimeType','')
            if not isinstance(template,str) or not template or len(template)>2048 or any(ord(ch)<33 or ord(ch)==127 for ch in template) or template in self.names:raise ValueError('Invalid resource template')
            if not isinstance(name,str) or not name or len(name)>256 or not isinstance(description,str) or len(description)>4000 or not isinstance(mime,str) or len(mime)>256:raise ValueError('Invalid resource template metadata')
            self.names.add(template)
            try:variables=template_variables(template);supported=True
            except ValueError:variables=[];supported=False
            detail={'uriTemplate':template,'name':name,'description':description,'mimeType':mime,'supported':supported,'variables':variables}
            size=len(json.dumps(detail,ensure_ascii=True).encode('ascii'))
            if clipped or len(self.items)>=100 or self.size+size>200000:clipped=True;continue
            self.items.append(detail);self.size+=size
        return (cursor if cursor and not clipped and len(self.items)<100 and self.pages<5 else None),{'templates':list(self.items),'more_templates':clipped or bool(cursor)}
