"""Validate bounded MCP resource metadata and text or image responses."""
import base64
import binascii
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


def tool_resource_links(result):
    """Extract bounded, assistant-directed links from a tool result."""
    from .mcp_content import model_tool_result
    try:visible,_,_=model_tool_result(result)
    except (ValueError,TypeError):return []
    links=[];seen=set()
    for block in visible['content']:
        if block.get('type')!='resource_link':continue
        try:items,_=parse_resources({'resources':[block]})
        except (ValueError,TypeError,UnicodeError):continue
        link=items[0]
        if link['uri'] in seen:continue
        seen.add(link['uri']);links.append(link)
        if len(links)>=100:break
    return links


def merge_resource_links(current,incoming):
    result=list(current);known={item['uri'] for item in result}
    for item in incoming:
        if item['uri'] not in known and len(result)<100:result.append(item);known.add(item['uri'])
    return result


def parse_resource_text(result,uri):
    contents=result.get('contents')
    if not isinstance(contents,list) or len(contents)>16:raise ValueError('Invalid MCP resource content')
    safe=[]
    for item in contents:
        if not isinstance(item,dict) or item.get('uri')!=uri or not isinstance(item.get('text'),str) or 'blob' in item or len(item['text'].encode('utf-8'))>32000:raise ValueError('Invalid MCP resource text')
        if 'mimeType' in item and (not isinstance(item['mimeType'],str) or len(item['mimeType'])>256):raise ValueError('Invalid MCP resource type')
        safe.append({key:item[key] for key in ('uri','text','mimeType') if key in item})
    return {'contents':safe}


def text_blob_mime(mime):
    if not isinstance(mime,str):return False
    media=mime.split(';',1)[0].strip().lower()
    return bool(re.fullmatch(r'text/[a-z0-9!#$&^_.+\-]+',media)) or media in ('application/json','application/xml') or bool(re.fullmatch(r'application/[a-z0-9!#$&^_.+\-]+\+(?:json|xml)',media))


def parse_resource_contents(result,uri):
    """Accept text, UTF-8 text blobs, and images for the requested URI."""
    from .image_generation import MAX_IMAGE_BYTES,image_bytes
    contents=result.get('contents')
    if not isinstance(contents,list) or len(contents)>16:raise ValueError('Invalid MCP resource content')
    safe=[]
    for item in contents:
        if not isinstance(item,dict) or item.get('uri')!=uri:raise ValueError('Invalid MCP resource URI')
        if 'blob' not in item:
            safe.extend(parse_resource_text({'contents':[item]},uri)['contents']);continue
        blob=item.get('blob');mime=item.get('mimeType')
        if isinstance(mime,str):
            media,*parameters=mime.lower().split(';')
            media=media.strip()
            if text_blob_mime(mime):
                if 'text' in item or not isinstance(blob,str) or len(blob)>42668 or len(mime)>256 or len(parameters)>1 or any(parameter.strip().replace(' ','') not in ('charset=utf-8','charset="utf-8"','charset=us-ascii','charset="us-ascii"') for parameter in parameters):raise ValueError('Unsupported MCP text resource blob')
                try:
                    data=base64.b64decode(blob,validate=True)
                    if len(data)>32000:raise ValueError()
                    text=data.decode('ascii' if parameters and 'us-ascii' in parameters[0] else 'utf-8')
                except (ValueError,binascii.Error,UnicodeError):raise ValueError('Invalid MCP text resource blob') from None
                safe.append({'uri':uri,'mimeType':mime,'text':text});continue
        if 'text' in item or not isinstance(blob,str) or len(blob)>4*((MAX_IMAGE_BYTES+2)//3) or mime not in ('image/png','image/jpeg','image/webp'):raise ValueError('Unsupported MCP resource blob')
        try:data=base64.b64decode(blob,validate=True);actual,_=image_bytes(data)
        except (ValueError,binascii.Error):raise ValueError('Invalid MCP image resource') from None
        if actual!=mime:raise ValueError('MCP image resource type does not match its content')
        safe.append({'uri':uri,'mimeType':mime,'blob':blob})
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
    """Parse bounded URI template expressions and their variable names."""
    if not isinstance(template,str) or not template or len(template)>2048 or any(ord(ch)<33 or ord(ch)==127 for ch in template):raise ValueError('Invalid resource template')
    parts=[];variables=[];pos=0;literal=0
    while pos<len(template):
        if template[pos]=='}':raise ValueError('Unsupported resource template')
        if template[pos]!='{':pos+=1;continue
        if literal<pos:parts.append((None,template[literal:pos]))
        end=template.find('}',pos+1)
        if end<0:raise ValueError('Unsupported resource template')
        expression=template[pos+1:end];operator=expression[:1] if expression[:1] in ('+','#','.','/',';','?','&') else ''
        specs=expression[1:].split(',') if operator else expression.split(',')
        matches=[re.fullmatch(r'((?:[A-Za-z0-9_]|%[0-9A-Fa-f]{2})(?:\.?(?:[A-Za-z0-9_]|%[0-9A-Fa-f]{2}))*)(?::([1-9][0-9]{0,3})|(\*))?',spec) for spec in specs]
        if any(match is None for match in matches):raise ValueError('Unsupported resource template')
        names=[(match.group(1),int(match.group(2)) if match.group(2) else None,bool(match.group(3))) for match in matches]
        if any(len(name)>128 for name,_,_ in names):raise ValueError('Resource template too complex')
        for name,_,_ in names:
            if name not in variables:variables.append(name)
        if len(variables)>32 or len(names)>32:raise ValueError('Resource template too complex')
        parts.append((operator,names));pos=end+1;literal=pos
    if literal<len(template):parts.append((None,template[literal:]))
    return parts,variables


def template_variables(template):
    return template_parts(template)[1]


def _reserved_quote(value):
    # Reserved expansion preserves URI reserved characters and existing valid
    # percent-encoded triplets, but encodes stray percent signs and Unicode.
    return ''.join(part if re.fullmatch(r'%[0-9A-Fa-f]{2}',part) else quote(part,safe=":/?#[]@!$&'()*+,;=") for part in re.split(r'(%[0-9A-Fa-f]{2})',value))


def _template_prefix(value,limit):
    """Count encoded UTF-8 characters without cutting percent triplets."""
    if limit is None:return value
    pos=0;count=0
    while pos<len(value) and count<limit:
        if re.match(r'%[0-9A-Fa-f]{2}',value[pos:pos+3]):
            first=int(value[pos+1:pos+3],16)
            width=1 if first<128 else 2 if 0xC2<=first<=0xDF else 3 if 0xE0<=first<=0xEF else 4 if 0xF0<=first<=0xF4 else 1
            candidate=value[pos:pos+3*width]
            if width>1 and re.fullmatch(r'(?:%[0-9A-Fa-f]{2})+',candidate) and len(candidate)==3*width:
                try:bytes.fromhex(candidate.replace('%','')).decode('utf-8')
                except UnicodeDecodeError:width=1
            else:width=1
            pos+=3*width
        else:pos+=1
        count+=1
    return value[:pos]


def expand_template(template,arguments):
    parts,names=template_parts(template)
    if not isinstance(arguments,dict) or not set(arguments).issubset(names):raise ValueError('Invalid resource template variables')
    def valid_string(value):return isinstance(value,str) and len(value.encode('utf-8'))<=1024
    for value in arguments.values():
        if value is None or valid_string(value):continue
        if isinstance(value,list) and len(value)<=64 and all(valid_string(item) for item in value):continue
        if isinstance(value,dict) and len(value)<=64 and all(valid_string(key) and valid_string(item) for key,item in value.items()):continue
        raise ValueError('Invalid resource template variables')
    if len(json.dumps(arguments,ensure_ascii=True).encode('ascii'))>16000:raise ValueError('Invalid resource template variables')
    chunks=[];size=0
    for operator,value in parts:
        if operator is None:chunk=value
        else:
            separator={'/':'/','.':'.',';':';','?':'&','&':'&'}.get(operator,',')
            encode=_reserved_quote if operator in ('+','#') else lambda item:quote(item,safe='')
            def named(name,item):return name+('='+item if item or operator!=';' else '')
            expanded=[]
            for name,prefix,explode in value:
                item=arguments.get(name)
                if item is None or item==[] or item=={}:continue
                if isinstance(item,str):
                    encoded=encode(_template_prefix(item,prefix));expanded.append(named(name,encoded) if operator in (';','?','&') else encoded)
                elif prefix is not None:raise ValueError('Invalid resource template variables')
                elif isinstance(item,list):
                    values=[encode(entry) for entry in item]
                    if explode:expanded.extend(named(name,entry) if operator in (';','?','&') else entry for entry in values)
                    else:
                        encoded=','.join(values);expanded.append(named(name,encoded) if operator in (';','?','&') else encoded)
                else:
                    values=[(encode(key),encode(entry)) for key,entry in item.items()]
                    if explode:expanded.extend(named(key,entry) if operator==';' else key+'='+entry for key,entry in values)
                    else:
                        encoded=','.join(part for pair in values for part in pair);expanded.append(named(name,encoded) if operator in (';','?','&') else encoded)
            chunk=(operator if operator in ('#','.','/',';','?','&') else '')+separator.join(expanded) if expanded else ''
        size+=len(chunk)
        if size>2048:raise ValueError('Expanded resource URI is invalid')
        chunks.append(chunk)
    uri=''.join(chunks)
    if not uri or any(ord(ch)<33 or ord(ch)==127 for ch in uri):raise ValueError('Expanded resource URI is invalid')
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
