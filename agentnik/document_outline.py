"""Bounded, non-executing Markdown, JSON, and YAML document outlines."""
import hashlib
import json
import re
from pathlib import Path
import yaml
from .code_symbols import MAX_BYTES,MAX_NODES,MAX_SYMBOLS,MAX_RESULT_BYTES,MAX_DEPTH
from .project_tools import ProjectToolError

FORMATS={'.md':'markdown','.markdown':'markdown','.json':'json','.yaml':'yaml','.yml':'yaml'}


def pointer(parts):
    return ''.join('/'+str(part).replace('~','~0').replace('/','~1') for part in parts)


def markdown_outline(text,check):
    lines=text.splitlines();headings=[];fence=None;incomplete=False;front_end=0
    if lines and lines[0].strip()=='---':
        for i in range(1,min(len(lines),1001)):
            if lines[i].strip() in ('---','...'):
                try:
                    first=None
                    for event in yaml.parse('\n'.join(lines[1:i]),Loader=yaml.SafeLoader):
                        check()
                        if first is None and isinstance(event,(yaml.MappingStartEvent,yaml.SequenceStartEvent,yaml.ScalarEvent)):first=event
                    if isinstance(first,yaml.MappingStartEvent):front_end=i+1
                except (yaml.YAMLError,RecursionError):pass
                break
    previous=None
    for index,line in enumerate(lines):
        check();number=index+1
        if index<front_end:continue
        match=re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$',line)
        if fence:
            if match and match[1][0]==fence[0] and len(match[1])>=len(fence) and not match[2].strip():fence=None
            previous=None;continue
        if match:
            if match[1][0]!='`' or '`' not in match[2]:fence=match[1];previous=None;continue
        heading=re.match(r'^ {0,3}(#{1,6})(?:[ \t]+(.*?)\s*|[ \t]*)$',line)
        if heading:
            title=re.sub(r'[ \t]+#+[ \t]*$','',heading[2] or '').strip();item={'title':title[:200],'level':len(heading[1]),'line':number}
            if len(title)>200:incomplete=True
            headings.append(item);previous=None
        elif re.match(r'^ {0,3}(?:=+[ \t]*|-+[ \t]*)$',line) and previous:
            title,prior=previous;headings.append({'title':title[:200],'level':1 if line.lstrip().startswith('=') else 2,'line':prior});incomplete|=len(title)>200;previous=None
        else:
            previous=(line.strip(),number) if line.strip() and not line.startswith(('    ','\t')) else None
        if len(headings)>MAX_SYMBOLS:incomplete=True;break
    entries=headings[:MAX_SYMBOLS];size=0;limited=[]
    for i,item in enumerate(entries):
        end=len(lines)
        for after in headings[i+1:]:
            if after['level']<=item['level']:end=after['line']-1;break
        else:
            if incomplete:end=None
        item={**item,'end_line':end};cost=len(json.dumps(item,ensure_ascii=False).encode('utf-8'))
        if size+cost>MAX_RESULT_BYTES:incomplete=True;break
        limited.append(item);size+=cost
    return limited,incomplete


def structured_outline(text,kind,check):
    if kind=='json':
        def reject(value):raise ValueError('Nonstandard JSON constant')
        try:json.loads(text,parse_constant=reject)
        except (ValueError,RecursionError):raise ProjectToolError('JSON could not be parsed') from None
    stack=[];entries=[];size=0;nodes=0;incomplete=False;doc=0;skip=0
    def attach(event,typ):
        nonlocal size,incomplete
        if not stack:return (),None
        parent=stack[-1]
        if parent['kind']=='map':
            if parent['key'] is None:raise ProjectToolError('Invalid mapping structure')
            parts=parent['path']+(parent['key'],);line=parent['line'];parent['key']=None
            entry={'document':doc,'path':pointer(parts),'line':line,'end_line':max(line,event.end_mark.line+(1 if event.end_mark.column else 0)),'value_type':typ}
            cost=len(json.dumps(entry,ensure_ascii=True).encode('utf-8'))
            if len(entries)>=MAX_SYMBOLS or size+cost>MAX_RESULT_BYTES:incomplete=True;return parts,None
            entries.append(entry);size+=cost;return parts,entry
        parts=parent['path']+(parent['index'],);parent['index']+=1;return parts,None
    try:
        for event in yaml.parse(text,Loader=yaml.SafeLoader):
            check();nodes+=1
            if nodes>MAX_NODES:incomplete=True;break
            if skip:
                if isinstance(event,(yaml.MappingStartEvent,yaml.SequenceStartEvent)):skip+=1
                elif isinstance(event,(yaml.MappingEndEvent,yaml.SequenceEndEvent)):skip-=1
                continue
            if isinstance(event,yaml.DocumentStartEvent):doc+=1;continue
            if isinstance(event,(yaml.MappingEndEvent,yaml.SequenceEndEvent)):
                frame=stack.pop()
                if frame['entry'] is not None:frame['entry']['end_line']=max(frame['entry']['line'],event.end_mark.line+(1 if event.end_mark.column else 0))
                continue
            if isinstance(event,(yaml.StreamStartEvent,yaml.StreamEndEvent,yaml.DocumentEndEvent)):continue
            if stack and stack[-1]['kind']=='map' and stack[-1]['key'] is None:
                if isinstance(event,yaml.ScalarEvent):
                    key=event.value
                    if len(key)>200:key=key[:200];incomplete=True
                    stack[-1]['key']=key;stack[-1]['line']=event.start_mark.line+1;continue
                # Complex keys are not interpreted or expanded; skip the key node.
                incomplete=True;stack[-1]['key']='<complex key>';stack[-1]['line']=event.start_mark.line+1
                if isinstance(event,(yaml.MappingStartEvent,yaml.SequenceStartEvent)):skip=1
                continue
            if isinstance(event,(yaml.MappingStartEvent,yaml.SequenceStartEvent)):
                typ='mapping' if isinstance(event,yaml.MappingStartEvent) else 'sequence';parts,entry=attach(event,typ)
                if len(stack)>=MAX_DEPTH:incomplete=True;skip=1;continue
                stack.append({'kind':'map' if typ=='mapping' else 'seq','path':parts,'key':None,'line':0,'index':0,'entry':entry})
            elif isinstance(event,(yaml.ScalarEvent,yaml.AliasEvent)):
                attach(event,'alias' if isinstance(event,yaml.AliasEvent) else 'scalar')
                if isinstance(event,yaml.AliasEvent):incomplete=True
            if len(entries)>=MAX_SYMBOLS:incomplete=True;break
    except (yaml.YAMLError,RecursionError,IndexError):raise ProjectToolError(kind.upper()+' could not be parsed') from None
    for frame in stack:
        if frame['entry'] is not None:frame['entry']['end_line']=None
    return entries,incomplete


def document_outline(files,path,check=lambda:None):
    kind=FORMATS.get(Path(path).suffix.lower())
    if not kind:raise ProjectToolError('Document outline supports Markdown, JSON, and YAML files only')
    check()
    try:text=files.read(path,remember=False,max_bytes=MAX_BYTES)
    except (OSError,ValueError,UnicodeError):raise ProjectToolError('File is unavailable, excluded, non-UTF-8, binary, or exceeds 512 KB') from None
    check();entries,incomplete=markdown_outline(text,check) if kind=='markdown' else structured_outline(text,kind,check)
    return {'path':path,'format':kind,'entries':entries,'incomplete':bool(incomplete),'snapshot':hashlib.sha256(text.encode('utf-8')).hexdigest(),'notice':'Structural outline only; content may be omitted. YAML aliases and complex keys are not expanded. This does not authorize edits.'}
