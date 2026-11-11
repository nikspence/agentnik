"""Bounded filename globbing and literal or timeout-limited regex search."""
import fnmatch
from functools import lru_cache
import json
import os
import time
from pathlib import Path

MAX_ENTRIES=2000
MAX_DEPTH=12
MAX_RESULTS=100
MAX_OUTPUT=16000
MAX_FILE=2_000_000
MAX_INPUT=4_000_000


def glob_matcher(pattern):
    """Match slash-separated project-relative paths, including recursive **."""
    if not isinstance(pattern,str) or not pattern or len(pattern.encode('utf-8'))>256 or any(ord(ch)<32 or ord(ch)==127 for ch in pattern):
        raise ValueError('Glob pattern must be nonempty and at most 256 UTF-8 bytes')
    pattern=pattern.replace('\\','/')
    parts=pattern.split('/')
    if pattern.startswith('/') or ':' in pattern or any(part in ('','.','..') for part in parts) or len(parts)>24 or parts.count('**')>4 or any('**' in part and part!='**' for part in parts):
        raise ValueError('Use a relative glob with *, ?, character classes, or whole-component **')
    def matches(path):
        names=path.split('/')
        @lru_cache(None)
        def match(i,j):
            if i==len(parts):return j==len(names)
            if parts[i]=='**':return match(i+1,j) or (j<len(names) and match(i,j+1))
            return j<len(names) and fnmatch.fnmatchcase(names[j],parts[i]) and match(i+1,j+1)
        return match(0,0)
    return matches


def walk_files(files,relative,check):
    root=files.path(relative)
    if not root.is_dir():raise ValueError('Directory is unavailable')
    pending=[(root,0)];entries=0;incomplete=False
    while pending:
        check();directory,depth=pending.pop()
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    check();entries+=1
                    if entries>MAX_ENTRIES:return True
                    name=Path(entry.path).relative_to(files.root).as_posix()
                    try:
                        target=files.path(name)
                        if entry.is_dir(follow_symlinks=False):
                            if depth>=MAX_DEPTH:incomplete=True
                            else:pending.append((target,depth+1))
                        elif entry.is_file(follow_symlinks=False):yield name
                    except ValueError:
                        # Excluded or linked paths remain outside the searchable scope.
                        continue
                    except OSError:incomplete=True
        except OSError:incomplete=True
    return incomplete


def glob_files(files,relative,pattern,check=lambda:None):
    matches=glob_matcher(pattern);walker=walk_files(files,relative,check);found=[];size=0;incomplete=False
    while True:
        try:name=next(walker)
        except StopIteration as done:
            incomplete=bool(done.value);break
        if not matches(name):continue
        length=len(json.dumps(name,ensure_ascii=False).encode('utf-8'))
        if len(found)>=MAX_RESULTS or size+length>MAX_OUTPUT:incomplete=True;break
        found.append(name);size+=length
    return {'paths':sorted(found),'incomplete':incomplete,'notice':'Project-relative files; excluded and linked paths are not searched.'}


def grep_files(files,relative,query,pattern,case_sensitive,check=lambda:None,regex_mode=False):
    if not isinstance(query,str) or not query or len(query.encode('utf-8'))>256 or '\n' in query or '\r' in query:
        raise ValueError('Search requires a single-line literal query of at most 256 UTF-8 bytes')
    if case_sensitive not in ('true','false'):raise ValueError('case_sensitive must be true or false')
    matches=glob_matcher(pattern);walker=walk_files(files,relative,check);needle=query if case_sensitive=='true' else query.casefold()
    expression=None;deadline=None;reason=None
    if regex_mode:
        import regex
        try:expression=regex.compile(query,0 if case_sensitive=='true' else regex.IGNORECASE)
        except (regex.error,ValueError,OverflowError):raise ValueError('Invalid regular expression') from None
        deadline=time.monotonic()+2.0
    found=[];scanned=0;input_bytes=0;output_bytes=0;incomplete=False;stop=False
    while True:
        try:name=next(walker)
        except StopIteration as done:
            incomplete=incomplete or bool(done.value);break
        if not matches(name):continue
        try:
            size=files.path(name).stat().st_size
            if size>MAX_FILE or input_bytes+size>MAX_INPUT:incomplete=True;continue
            content=files.read(name,remember=False,max_bytes=MAX_FILE)
        except (OSError,ValueError,UnicodeError):incomplete=True;continue
        size=len(content.encode('utf-8'))
        if input_bytes+size>MAX_INPUT:incomplete=True;continue
        input_bytes+=size;scanned+=1
        for number,line in enumerate(content.splitlines(),1):
            check()
            if expression is not None:
                remaining=deadline-time.monotonic()
                if remaining<=0:incomplete=True;stop=True;reason='Regular expression time limit reached';break
                try:match=expression.search(line,timeout=min(.05,remaining))
                except TimeoutError:incomplete=True;stop=True;reason='Regular expression time limit reached';break
                if match is None:continue
                position=match.start()
            else:
                haystack=line if case_sensitive=='true' else line.casefold()
                if needle not in haystack:continue
                if case_sensitive=='true':position=line.find(query)
                else:
                    folded_position=haystack.find(needle);position=0;offset=0
                    while position<len(line) and offset+len(line[position].casefold())<=folded_position:
                        offset+=len(line[position].casefold());position+=1
            start=max(0,position-100)
            item={'path':name,'line':number,'text':line[start:start+500]}
            length=len(json.dumps(item,ensure_ascii=False).encode('utf-8'))
            if len(found)>=MAX_RESULTS or output_bytes+length>MAX_OUTPUT:incomplete=True;stop=True;break
            found.append(item);output_bytes+=length
            if start or len(line)>start+500:incomplete=True
        if stop:break
    result={'matches':found,'files_scanned':scanned,'incomplete':incomplete,'notice':('Regex' if regex_mode else 'Literal')+' search; excluded, linked, binary, oversized or unreadable files are not searched.'}
    if reason:result['reason']=reason
    return result
