"""Bounded, non-executing Go and Rust symbol outlines."""
import hashlib
import json
from pathlib import Path
from tree_sitter import Language,Parser
import tree_sitter_go
import tree_sitter_rust
from .code_symbols import MAX_BYTES,MAX_NODES,MAX_SYMBOLS,MAX_RESULT_BYTES,MAX_DEPTH
from .project_tools import ProjectToolError

GO={'package_clause':'package','type_spec':'type','type_alias':'type','function_declaration':'function','method_declaration':'method','method_elem':'method','const_spec':'constant','var_spec':'variable'}
RUST={'mod_item':'module','struct_item':'struct','enum_item':'enum','trait_item':'trait','impl_item':'implementation','function_item':'function','function_signature_item':'function','type_item':'type','const_item':'constant','static_item':'static','union_item':'union'}


def systems_outline(files,path,check=lambda:None):
    suffix=Path(path).suffix.lower();language={'.go':'go','.rs':'rust'}.get(suffix)
    if not language:raise ProjectToolError('Outline supports Go and Rust files only')
    check()
    try:text=files.read(path,remember=False,max_bytes=MAX_BYTES)
    except (OSError,ValueError,UnicodeError):raise ProjectToolError('File is unavailable, excluded, non-UTF-8, binary, or exceeds 512 KB') from None
    raw=text.encode('utf-8');grammar=tree_sitter_go.language() if language=='go' else tree_sitter_rust.language();parser=Parser(Language(grammar))
    def read(offset,point):check();return raw[offset:offset+8192]
    try:tree=parser.parse(read)
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
    symbols=[];nodes=0;size=0;macros=False;stack=[(tree.root_node,(),0)]
    while stack:
        check();node,parents,depth=stack.pop();nodes+=1
        if nodes>MAX_NODES:incomplete=True;break
        if language=='rust' and node.type in ('macro_invocation','macro_definition'):macros=True
        kind=(GO if language=='go' else RUST).get(node.type);current=parents
        if kind:
            named=node.child_by_field_name('name')
            if node.type=='package_clause':named=next((child for child in node.named_children if child.type=='package_identifier'),None)
            name=field_text(named)
            if node.type=='type_spec':
                value=node.child_by_field_name('type');kind='struct' if value and value.type=='struct_type' else 'interface' if value and value.type=='interface_type' else 'type'
            if node.type=='method_declaration':
                receiver=node.child_by_field_name('receiver');parameter=next((child for child in receiver.named_children if child.type=='parameter_declaration'),None) if receiver else None
                typ=field_text(parameter.child_by_field_name('type')) if parameter else ''
                if typ:name=typ.lstrip('*')+'.'+name
                else:incomplete=True
            if node.type=='impl_item':
                target=field_text(node.child_by_field_name('type'));trait=field_text(node.child_by_field_name('trait'))
                name=('impl '+trait+' for '+target) if trait and target else ('impl '+target) if target else ''
            names=[name] if name else []
            if node.type in ('const_spec','var_spec'):
                names=[field_text(child) for index,child in enumerate(node.children) if child.is_named and node.field_name_for_child(index)=='name']
            for name in names:
                qualified='.'.join((*parents,name))
                if len(qualified)>500:qualified=qualified[-500:];incomplete=True
                end=node.end_point.row+(1 if node.end_point.column else 0)
                item={'name':qualified,'kind':kind,'line':node.start_point.row+1,'end_line':max(node.start_point.row+1,end)}
                cost=len(json.dumps(item,ensure_ascii=False).encode('utf-8'))
                if len(symbols)>=MAX_SYMBOLS or size+cost>MAX_RESULT_BYTES:incomplete=True;break
                symbols.append(item);size+=cost
                if kind in ('module','struct','interface','trait','implementation','function','method'):current=(*parents,name)
            if incomplete and (len(symbols)>=MAX_SYMBOLS or size>=MAX_RESULT_BYTES):break
        children=node.named_children
        if depth>=MAX_DEPTH:
            if children:incomplete=True
        else:stack.extend((child,current,depth+1) for child in reversed(children))
    return {'path':path,'language':language,'symbols':symbols,'incomplete':bool(incomplete),'syntax_errors':bool(tree.root_node.has_error),'macro_expansion_omitted':macros,'snapshot':hashlib.sha256(raw).hexdigest(),'notice':'Static syntax outline; macro-generated and dynamic declarations may be missing. This does not authorize edits.'}
