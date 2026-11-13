"""Bounded, non-executing Python symbol outlines for project files."""
import ast
import hashlib
import json
from pathlib import Path
from .project_tools import ProjectToolError

MAX_BYTES=512_000
MAX_NODES=50_000
MAX_SYMBOLS=150
MAX_RESULT_BYTES=16_000
MAX_DEPTH=40


def python_outline(files,path,check=lambda:None):
    if Path(path).suffix.lower() not in ('.py','.pyi'):
        raise ProjectToolError('Python outline supports .py and .pyi files only')
    check()
    try:text=files.read(path,remember=False,max_bytes=MAX_BYTES)
    except (OSError,ValueError,UnicodeError):raise ProjectToolError('Python file is unavailable, excluded, non-UTF-8, binary, or exceeds 512 KB') from None
    check()
    try:tree=ast.parse(text,filename='<project file>',type_comments=False)
    except (SyntaxError,ValueError,RecursionError):raise ProjectToolError('Python syntax could not be parsed; use bounded file reads for incomplete or unsupported syntax') from None
    symbols=[];nodes=0;size=0;incomplete=False;stack=[(tree,(),0)]
    while stack:
        check();node,parents,depth=stack.pop();nodes+=1
        if nodes>MAX_NODES:incomplete=True;break
        current=parents
        if isinstance(node,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
            name=node.name[:200];qualified='.'.join((*parents,name))
            if len(qualified)>500:qualified=qualified[-500:];incomplete=True
            item={'name':qualified,'kind':'class' if isinstance(node,ast.ClassDef) else 'async_function' if isinstance(node,ast.AsyncFunctionDef) else 'function','line':node.lineno,'end_line':node.end_lineno}
            item_size=len(json.dumps(item,ensure_ascii=False).encode('utf-8'))
            if len(symbols)>=MAX_SYMBOLS or size+item_size>MAX_RESULT_BYTES:incomplete=True;break
            symbols.append(item);size+=item_size;current=(*parents,name)
        children=list(ast.iter_child_nodes(node))
        if depth>=MAX_DEPTH:
            if children:incomplete=True
        else:
            stack.extend((child,current,depth+1) for child in reversed(children))
    return {'path':path,'language':'python','symbols':symbols,'incomplete':incomplete,'snapshot':hashlib.sha256(text.encode('utf-8')).hexdigest(),'notice':'Static syntax outline; generated or dynamically defined symbols may be missing. This does not authorize edits.'}
