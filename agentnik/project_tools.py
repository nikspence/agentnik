"""Bounded project inspection and exact-match patch proposals; never execute metadata."""
import difflib
import hashlib
import json
import os
import re
import tomllib

from .code_limits import PATCH_FILE_BYTES,RANGE_TEXT_BYTES,PATCH_TEXT_BYTES
MAX_FILE=PATCH_FILE_BYTES


class ProjectToolError(ValueError):
    pass


class ProjectTools:
    def __init__(self,files):self.files=files;self.views={}

    def read_range(self,path,start_line,end_line):
        if any(not isinstance(n,str) or not re.fullmatch(r'[1-9][0-9]{0,7}',n) for n in (start_line,end_line)):raise ProjectToolError('Line numbers must be positive decimal strings')
        start,end=int(start_line),int(end_line)
        if end<start or end-start>=1000:raise ProjectToolError('Request an inclusive range of at most 1000 lines')
        text=self.files.read(path,remember=False,max_bytes=MAX_FILE);lines=text.splitlines(True)
        if start>len(lines):raise ProjectToolError('Start line is beyond the end of the file')
        rows=[];size=0;position=sum(map(len,lines[:start-1]));begin=position
        for number in range(start,min(end,len(lines))+1):
            line=lines[number-1];length=len(line.encode())
            if size+length>RANGE_TEXT_BYTES:
                if not rows:raise ProjectToolError('One line exceeds the 64 KB range budget')
                break
            rows.append({'line':number,'text':line});size+=length;position+=len(line)
        digest=hashlib.sha256(text.encode()).hexdigest();key=str(self.files.path(path));old=self.views.get(key,{})
        ranges=old.get('ranges',[]) if old.get('hash')==digest else []
        ranges=sorted([*ranges,(begin,position)]);merged=[]
        for left,right in ranges:
            if merged and left<=merged[-1][1]:merged[-1]=(merged[-1][0],max(right,merged[-1][1]))
            else:merged.append((left,right))
        self.views[key]={'hash':digest,'ranges':merged[-32:]}
        last=rows[-1]['line']
        return {'path':path,'start_line':start,'end_line':last,'total_lines':len(lines),'lines':rows,'snapshot':digest,'truncated':last<min(end,len(lines)),'next_line':last+1 if last<len(lines) else None}

    def patch(self,path,old_text,new_text):
        if not old_text or old_text==new_text or any(not isinstance(v,str) or len(v.encode())>PATCH_TEXT_BYTES or '\x00' in v for v in (old_text,new_text)):raise ProjectToolError('Supply different old/new UTF-8 text of at most 64 KB, with a nonempty exact old match')
        target=self.files.path(path);text=self.files.read(path,remember=False,max_bytes=MAX_FILE);digest=hashlib.sha256(text.encode()).hexdigest()
        index=text.find(old_text)
        if index<0:raise ProjectToolError('Old text was not found; read the current lines again')
        if text.find(old_text,index+1)>=0:raise ProjectToolError('Old text is ambiguous; include more surrounding text')
        view=self.views.get(str(target),{})
        seen=self.files.observed.get(str(target))==digest or (view.get('hash')==digest and any(left<=index and index+len(old_text)<=right for left,right in view.get('ranges',[])))
        if not seen:raise ProjectToolError('Read the exact target region at its current file version before patching')
        content=text[:index]+new_text+text[index+len(old_text):]
        if len(content.encode())>MAX_FILE:raise ProjectToolError('Patched file exceeds the 10 MB budget')
        # Diff only the affected lines. Comparing the whole file can turn a tiny
        # edit in a repetitive large file into a multi-megabyte diff.
        start=text.rfind('\n',0,index)+1;end=text.find('\n',index+len(old_text))
        end=len(text) if end<0 else end+1
        before=text[start:end];after=text[start:index]+new_text+text[index+len(old_text):end]
        offset=text.count('\n',0,start)
        diff=''.join(line if line.endswith('\n') else line+'\n\\ No newline at end of file\n' for line in difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+path,tofile='b/'+path,n=0))
        diff=re.sub(r'^@@ -(\d+)(,\d+)? \+(\d+)(,\d+)? @@',lambda match:'@@ -'+str(int(match[1])+offset)+(match[2] or '')+' +'+str(int(match[3])+offset)+(match[4] or '')+' @@',diff,flags=re.MULTILINE)
        if len(diff.encode())>300000:raise ProjectToolError('Patch diff exceeds the activity budget')
        return {'operation':'apply_patch','path':path,'content':content,'base':digest,'diff':diff,'cwd':str(self.files.root),'max_bytes':MAX_FILE}

    def overview(self,check=lambda:None):
        root=self.files.root;pending=[(root,0)];entries=0;files=0;extensions={};sample=[];directories=[];incomplete=False
        while pending and entries<500:
            directory,depth=pending.pop();check()
            try:iterator=os.scandir(directory)
            except OSError:incomplete=True;continue
            with iterator:
                for item in iterator:
                    check();entries+=1
                    if entries>500:incomplete=True;break
                    relative=os.path.relpath(item.path,root)
                    try:target=self.files.path(relative)
                    except (OSError,ValueError):continue
                    if item.is_dir(follow_symlinks=False):
                        if depth==0 and len(directories)<20:directories.append(item.name[:100])
                        if depth<3:pending.append((target,depth+1))
                        else:incomplete=True
                    elif item.is_file(follow_symlinks=False):
                        files+=1;extension=target.suffix.lower() or '(none)';extensions[extension]=extensions.get(extension,0)+1
                        if len(sample)<40:sample.append(relative[:160])
        incomplete=incomplete or bool(pending)
        manifests=[];dependencies=set();scripts=set();tests=[]
        for name in ('pyproject.toml','package.json','requirements.txt','Cargo.toml','go.mod','pytest.ini','tox.ini','setup.cfg'):
            check()
            if not (root/name).is_file():continue
            try:
                text=self.files.read(name,remember=False);manifests.append(name)
                if name in ('pyproject.toml','Cargo.toml'):
                    data=tomllib.loads(text)
                    if name=='pyproject.toml':
                        project=data.get('project',{});requirements=project.get('dependencies',[])
                        if isinstance(requirements,list):
                            for entry in requirements[:80]:
                                match=re.match(r'[A-Za-z0-9_.-]+',entry) if isinstance(entry,str) else None
                                if match:dependencies.add(match.group()[:100])
                        for field in ('scripts','gui-scripts'):
                            values=project.get(field,{})
                            if isinstance(values,dict):scripts.update(str(k)[:100] for k in list(values)[:20])
                        if 'pytest' in data.get('tool',{}):tests.append('pyproject.toml: tool.pytest')
                    elif isinstance(data.get('dependencies'),dict):dependencies.update(str(k)[:100] for k in list(data['dependencies'])[:80])
                elif name=='package.json':
                    data=json.loads(text)
                    for field in ('dependencies','devDependencies'):
                        values=data.get(field,{})
                        if isinstance(values,dict):dependencies.update(str(k)[:100] for k in list(values)[:80])
                    values=data.get('scripts',{})
                    if isinstance(values,dict):
                        scripts.update(str(k)[:100] for k in list(values)[:20])
                        if 'test' in values:tests.append('package.json: test script')
                elif name=='requirements.txt':
                    for line in text.splitlines()[:100]:
                        match=re.match(r'[A-Za-z0-9_.-]+',line)
                        if match and '://' not in line:dependencies.add(match.group()[:100])
                if name in ('pytest.ini','tox.ini'):tests.append(name)
            except (OSError,ValueError,TypeError,AttributeError):incomplete=True
        for name in ('tests','test','__tests__'):
            try:
                if self.files.path(name).is_dir():tests.append(name+'/')
            except (OSError,ValueError):pass
        languages={'.py':'Python','.js':'JavaScript','.jsx':'JavaScript','.ts':'TypeScript','.tsx':'TypeScript','.rs':'Rust','.go':'Go','.cs':'C#','.java':'Java','.cpp':'C++','.c':'C'}
        counts={}
        for suffix,count in extensions.items():
            if suffix in languages:counts[languages[suffix]]=counts.get(languages[suffix],0)+count
        return {'files_scanned':files,'entries_scanned':min(entries,500),'incomplete':incomplete,'languages':counts,'top_directories':sorted(directories),'sample_files':sorted(sample),'manifests':manifests,'dependency_names':sorted(dependencies)[:40],'script_or_entry_point_names':sorted(scripts)[:20],'test_configuration':tests,'notice':'Bounded inventory only; metadata was not executed and test commands were not validated.'}
