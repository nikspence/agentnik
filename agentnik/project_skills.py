"""Read-only discovery of repository-local Agent Skills."""
import re
import hashlib
import os
import ast
from pathlib import Path


def _list_skills(files):
    root=files.path('.agents/skills')
    if not root.exists(): return []
    if not root.is_dir(): raise ValueError('Skill library is not a directory')
    result=[]
    with os.scandir(root) as entries:
        names=[]
        for entry in entries:
            names.append(entry.name)
            if len(names)>200: raise ValueError('Skill library exceeds 200 entries')
    for name in sorted(names):
        if len(result)>=50: raise ValueError('Skill library exceeds 50 valid skills')
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name) or len(name)>64: continue
        try:
            text=files.read('.agents/skills/'+name+'/SKILL.md',remember=False,max_bytes=16000)
        except (OSError,ValueError,UnicodeError): continue
        text=text.replace('\r\n','\n')
        if not text.startswith('---\n'): continue
        end=text.find('\n---',4)
        if end<0: continue
        header=text[4:end]
        metadata={};lines=header.splitlines();index=0
        while index<len(lines):
            line=lines[index];index+=1
            match=re.match(r'^([a-z][a-z0-9-]*):(?:[ \t]+(.*))?$',line)
            if not match:continue
            key,value=match.group(1),match.group(2) or ''
            if key not in ('name','description'):continue
            if key in metadata:metadata={};break
            if value in ('|','|-','|+','>','>-','>+'):
                chunks=[]
                while index<len(lines) and (lines[index].startswith((' ', '\t')) or not lines[index].strip()):
                    chunks.append(lines[index].strip());index+=1
                value=(' ' if value.startswith('>') else '\n').join(chunks).strip()
            elif value.startswith('"'):
                try:value=ast.literal_eval(value)
                except (SyntaxError,ValueError):metadata={};break
            elif value.startswith("'"):
                if len(value)<2 or not value.endswith("'"):metadata={};break
                value=value[1:-1].replace("''", "'")
            else:value=re.split(r'\s+#',value,maxsplit=1)[0].strip()
            if not isinstance(value,str):metadata={};break
            metadata[key]=value
        description=metadata.get('description','')
        if metadata.get('name')!=name or not description.strip() or len(description)>1024:continue
        result.append({'name':name,'description':description,'path':'.agents/skills/'+name+'/SKILL.md'})
    return result


def list_skills(files, user_root=None):
    result=[dict(item,id=item['name'],source='repository') for item in _list_skills(files)]
    root=Path(user_root) if user_root is not None else Path.home()
    if (root/'.agents'/'skills').exists():
        from .code_agent import ProjectFiles
        user_files=ProjectFiles(root)
        result.extend(dict(item,id='user:'+item['name'],source='user') for item in _list_skills(user_files))
    return result


def _select_files(files,ident,user_root=None):
    if ident.startswith('user:'):
        from .code_agent import ProjectFiles
        return ProjectFiles(Path(user_root) if user_root is not None else Path.home()),ident[5:],'user'
    return files,ident,'repository'


def read_skill(files,name,user_root=None):
    files,name,source=_select_files(files,name,user_root)
    skills={item['name']:item for item in _list_skills(files)}
    if name not in skills:raise ValueError('Skill is unavailable or invalid')
    skill=skills[name]
    text=files.read(skill['path'],remember=False,max_bytes=16000)
    return dict(skill,id=('user:'+name if source=='user' else name),source=source,instructions=text,sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())


def read_resource(files,name,path,user_root=None):
    skill=read_skill(files,name,user_root)
    files,local_name,source=_select_files(files,name,user_root)
    if not isinstance(path,str) or not path or len(path)>512:raise ValueError('Invalid skill resource path')
    relative=Path(path)
    if relative.is_absolute() or relative.drive or '..' in relative.parts:raise ValueError('Use a skill-relative resource path')
    target=Path('.agents/skills')/local_name/relative
    content=files.read(str(target),remember=False,max_bytes=16000)
    return {'skill':name,'path':path,'content':content,'sha256':hashlib.sha256(content.encode('utf-8')).hexdigest()}
