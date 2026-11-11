"""Read-only discovery of repository-local Agent Skills."""
import re
import hashlib
import os
import yaml
from pathlib import Path


class SkillLoader(yaml.SafeLoader):
    """Safe YAML with bounded graph complexity and no duplicate mapping keys."""
    def __init__(self, stream):
        super().__init__(stream);self.nodes_seen=0;self.depth=0

    def compose_node(self, parent, index):
        self.nodes_seen+=1;self.depth+=1
        if self.nodes_seen>500 or self.depth>30:raise ValueError('Skill metadata is too complex')
        try:return super().compose_node(parent,index)
        finally:self.depth-=1

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node);result={}
        for key_node,value_node in node.value:
            key=self.construct_object(key_node,deep=deep)
            try:
                if key in result:raise ValueError('Duplicate skill metadata key')
                result[key]=self.construct_object(value_node,deep=deep)
            except TypeError:raise ValueError('Invalid skill metadata key') from None
        return result


def parse_frontmatter(text,name):
    text=text.replace('\r\n','\n')
    if not text.startswith('---\n'):return None
    end=re.search(r'^---[ \t]*$',text[4:],re.MULTILINE)
    if not end:return None
    try:metadata=yaml.load(text[4:4+end.start()],Loader=SkillLoader)
    except (yaml.YAMLError,ValueError,RecursionError):return None
    if not isinstance(metadata,dict):return None
    description=metadata.get('description')
    if metadata.get('name')!=name or not isinstance(description,str) or not description.strip() or len(description)>1024:return None
    return description.strip()


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
        description=parse_frontmatter(text,name)
        if description is None:continue
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
    description=parse_frontmatter(text,name)
    if description is None:raise ValueError('Skill is unavailable or invalid')
    skill=dict(skill,description=description)
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



def list_resources(files,name,user_root=None):
    """List bounded, regular files in a selected skill without reading or running them."""
    read_skill(files,name,user_root)
    files,local_name,source=_select_files(files,name,user_root)
    root=files.path(str(Path('.agents/skills')/local_name))
    pending=[(root,0)];found=[];scanned=0;truncated=False
    while pending:
        directory,depth=pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                scanned+=1
                if scanned>200:truncated=True;break
                relative=Path(entry.path).relative_to(root)
                try:target=files.path(str(Path('.agents/skills')/local_name/relative))
                except (OSError,ValueError):continue
                if target.is_dir():
                    if depth<3:pending.append((target,depth+1))
                    else:truncated=True
                elif target.is_file() and relative.as_posix()!='SKILL.md':
                    found.append(relative.as_posix())
                    if len(found)>=100:truncated=True;break
        if scanned>200 or len(found)>=100:break
    return {'skill':name,'resources':sorted(found),'truncated':truncated}


def validate_skill_pins(names,pins):
    if not isinstance(pins,dict) or len(pins)>5 or not set(pins).issubset(set(names)):
        raise ValueError('Invalid selected skill revisions')
    if any(not isinstance(key,str) or not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value) for key,value in pins.items()):
        raise ValueError('Invalid selected skill revisions')
    return dict(pins)


def verify_skill_pins(files,names,pins):
    for ident,digest in validate_skill_pins(names,pins).items():
        try:current=read_skill(files,ident)['sha256']
        except (OSError,ValueError,UnicodeError):raise ValueError('Selected skill is unavailable. Open Skills to review or deselect it: '+ident) from None
        if current!=digest:raise ValueError('Selected skill changed. Open Skills, review it and confirm the selection again: '+ident)
