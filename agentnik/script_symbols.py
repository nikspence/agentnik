"""Bounded, non-executing JavaScript and TypeScript outlines."""
import hashlib
import json
from pathlib import Path
from tree_sitter import Language,Parser
import tree_sitter_javascript
import tree_sitter_typescript
from .code_symbols import MAX_BYTES,MAX_NODES,MAX_SYMBOLS,MAX_RESULT_BYTES,MAX_DEPTH
from .project_tools import ProjectToolError

LANGUAGES={'.js':'javascript','.jsx':'jsx','.mjs':'javascript','.cjs':'javascript',
           '.ts':'typescript','.tsx':'tsx','.mts':'typescript','.cts':'typescript'}
KINDS={'class_declaration':'class','abstract_class_declaration':'class','class':'class',
       'function_declaration':'function','generator_function_declaration':'function',
       'method_definition':'method','method_signature':'method',
       'interface_declaration':'interface','type_alias_declaration':'type',
       'enum_declaration':'enum','internal_module':'namespace','module':'namespace',
       'variable_declarator':'variable','export_specifier':'export'}
NAME_TYPES={'identifier','type_identifier','property_identifier','private_property_identifier','string','number'}


def script_outline(files,path,check=lambda:None):
    language=LANGUAGES.get(Path(path).suffix.lower())
    if not language:raise ProjectToolError('Outline supports JavaScript, JSX, TypeScript, and TSX files only')
    check()
    try:text=files.read(path,remember=False,max_bytes=MAX_BYTES)
    except (OSError,ValueError,UnicodeError):raise ProjectToolError('File is unavailable, excluded, non-UTF-8, binary, or exceeds 512 KB') from None
    raw=text.encode('utf-8')
    grammar=tree_sitter_javascript.language() if language in ('javascript','jsx') else tree_sitter_typescript.language_tsx() if language=='tsx' else tree_sitter_typescript.language_typescript()
    parser=Parser(Language(grammar))
    def read(offset,point):
        check();return raw[offset:offset+8192]
    try:tree=parser.parse(read)
    except (ValueError,RecursionError):raise ProjectToolError('Source could not be parsed') from None
    check()
    if tree is None:raise ProjectToolError('Source parsing did not complete')
    symbols=[];nodes=0;size=0;incomplete=tree.root_node.has_error;stack=[(tree.root_node,(),0)]
    while stack:
        check();node,parents,depth=stack.pop();nodes+=1
        if nodes>MAX_NODES:incomplete=True;break
        kind=KINDS.get(node.type);current=parents
        parent=node.parent
        direct_export=bool(parent and (parent.type=='export_statement' or (node.type=='variable_declarator' and parent.parent and parent.parent.type=='export_statement') or node.type=='export_specifier'))
        value=node.child_by_field_name('value')
        if node.type in ('variable_declarator','pair','public_field_definition','field_definition') and value is not None and value.type in ('arrow_function','function_expression','generator_function'):
            kind='function'
        if node.type=='arrow_function' and parent and parent.type=='export_statement':kind='function'
        if kind:
            named=node.child_by_field_name('name') or node.child_by_field_name('key')
            if node.type=='export_specifier':named=node.child_by_field_name('alias') or named
            if named is not None and named.type in NAME_TYPES:
                name=raw[named.start_byte:named.end_byte].decode('utf-8')[:200]
            elif node.type in ('class','arrow_function') and direct_export:name='<default>'
            else:name=''
            if name:
                qualified='.'.join((*parents,name))
                if len(qualified)>500:qualified=qualified[-500:];incomplete=True
                end_line=node.end_point.row+(1 if node.end_point.column else 0)
                item={'name':qualified,'kind':kind,'line':node.start_point.row+1,'end_line':max(node.start_point.row+1,end_line),'exported':direct_export}
                item_size=len(json.dumps(item,ensure_ascii=False).encode('utf-8'))
                if len(symbols)>=MAX_SYMBOLS or size+item_size>MAX_RESULT_BYTES:incomplete=True;break
                symbols.append(item);size+=item_size
                if kind not in ('export',):current=(*parents,name)
        children=node.named_children
        if depth>=MAX_DEPTH:
            if children:incomplete=True
        else:stack.extend((child,current,depth+1) for child in reversed(children))
    return {'path':path,'language':language,'symbols':symbols,'incomplete':incomplete,'syntax_errors':bool(tree.root_node.has_error),'snapshot':hashlib.sha256(raw).hexdigest(),'notice':'Static syntax outline; dynamic, anonymous, destructured, or computed symbols may be missing. This does not authorize edits.'}
