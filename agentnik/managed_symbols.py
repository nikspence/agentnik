"""Bounded, non-executing C# and Java symbol outlines."""
import hashlib
import json
from pathlib import Path
from tree_sitter import Language,Parser
import tree_sitter_c_sharp
import tree_sitter_java
from .code_symbols import MAX_BYTES,MAX_NODES,MAX_SYMBOLS,MAX_RESULT_BYTES,MAX_DEPTH
from .project_tools import ProjectToolError
from .tools import LimitError

KINDS={'namespace_declaration':'namespace','file_scoped_namespace_declaration':'namespace','package_declaration':'package',
       'class_declaration':'class','interface_declaration':'interface','struct_declaration':'struct','record_declaration':'record',
       'enum_declaration':'enum','enum_member_declaration':'enum_member','enum_constant':'enum_member',
       'delegate_declaration':'delegate','annotation_type_declaration':'annotation',
       'method_declaration':'method','constructor_declaration':'constructor','destructor_declaration':'destructor',
       'property_declaration':'property','event_declaration':'event','variable_declarator':'field'}
SCOPES={'namespace','class','interface','struct','record','enum','annotation','method','constructor','destructor'}


def managed_outline(files,path,check=lambda:None):
    language={'.cs':'csharp','.java':'java'}.get(Path(path).suffix.lower())
    if not language:raise ProjectToolError('Outline supports C# and Java files only')
    check()
    try:text=files.read(path,remember=False,max_bytes=MAX_BYTES)
    except (OSError,ValueError,UnicodeError):raise ProjectToolError('File is unavailable, excluded, non-UTF-8, binary, or exceeds 512 KB') from None
    raw=text.encode('utf-8');parser=Parser(Language(tree_sitter_c_sharp.language() if language=='csharp' else tree_sitter_java.language()))
    def read(offset,point):check();return raw[offset:offset+8192]
    try:tree=parser.parse(read)
    except LimitError:raise
    except (ValueError,RecursionError):raise ProjectToolError('Source could not be parsed') from None
    check()
    if tree is None:raise ProjectToolError('Source parsing did not complete')
    incomplete=tree.root_node.has_error
    def field_text(node):
        nonlocal incomplete
        if node is None:return ''
        value=' '.join(raw[node.start_byte:node.end_byte].decode('utf-8').split())
        if len(value)>200:incomplete=True
        return value[:200]
    prefix=''
    for child in tree.root_node.named_children:
        if child.type=='file_scoped_namespace_declaration':prefix=field_text(child.child_by_field_name('name'));break
        if child.type=='package_declaration':
            prefix=field_text(next((part for part in child.named_children if part.type in ('identifier','scoped_identifier')),None));break
    symbols=[];nodes=0;size=0;stack=[(tree.root_node,(),0)]
    while stack:
        check();node,parents,depth=stack.pop();nodes+=1
        if nodes>MAX_NODES:incomplete=True;break
        kind=KINDS.get(node.type);current=parents
        if kind=='field':
            parent=node.parent;container=parent.parent if parent and parent.type=='variable_declaration' else parent
            if not container or container.type not in ('field_declaration','event_field_declaration','constant_declaration'):kind=None
            elif container.type=='event_field_declaration':kind='event'
        if kind:
            named=node.child_by_field_name('name')
            if node.type=='package_declaration':named=next((part for part in node.named_children if part.type in ('identifier','scoped_identifier')),None)
            name=field_text(named)
            if name:
                base=parents
                if not base and prefix and node.type not in ('package_declaration','file_scoped_namespace_declaration'):base=(prefix,)
                qualified='.'.join((*base,name))
                if len(qualified)>500:qualified=qualified[-500:];incomplete=True
                end=node.end_point.row+(1 if node.end_point.column else 0)
                item={'name':qualified,'kind':kind,'line':node.start_point.row+1,'end_line':max(node.start_point.row+1,end)}
                cost=len(json.dumps(item,ensure_ascii=False).encode('utf-8'))
                if len(symbols)>=MAX_SYMBOLS or size+cost>MAX_RESULT_BYTES:incomplete=True;break
                symbols.append(item);size+=cost
                if kind in SCOPES and node.type!='file_scoped_namespace_declaration':current=(*base,name)
        children=node.named_children
        if depth>=MAX_DEPTH:
            if children:incomplete=True
        else:stack.extend((child,current,depth+1) for child in reversed(children))
    return {'path':path,'language':language,'symbols':symbols,'incomplete':bool(incomplete),'syntax_errors':bool(tree.root_node.has_error),'snapshot':hashlib.sha256(raw).hexdigest(),'notice':'Static syntax outline; generated declarations and conditional compilation may differ. This does not authorize edits.'}
