"""Local structured Git operations; no subprocesses or network transports."""
import difflib
import hashlib
import json
import time
import io
from dulwich.file import GitFile
from dulwich.index import write_index_dict
from pathlib import Path
from dulwich.repo import Repo
from dulwich.objects import Blob, Commit
from dulwich.index import index_entry_from_stat
from dulwich.refs import check_ref_format
from dulwich.ignore import IgnoreFilterManager


class GitService:
    def __init__(self, files):
        self.files = files
        self.root = files.root

    def repo(self):
        # A registered ordinary folder must not implicitly operate on a parent repo.
        if not (self.root / '.git').is_dir() or (self.root / '.git').is_symlink():
            raise ValueError('Select a repository root with a local .git directory')
        metadata=self.root/'.git'
        if getattr(metadata,'is_junction',lambda:False)():raise ValueError('Linked Git metadata is unavailable')
        for name in ('index','objects','refs','HEAD','config'):
            item=metadata/name
            if item.is_symlink() or getattr(item,'is_junction',lambda:False)(): raise ValueError('Linked Git metadata is unavailable')
        return Repo(str(self.root))

    def inspect(self, action, path=''):
        with self.repo() as repo:
            head = repo.head()
            if action == 'git_diff_staged':
                key=self.key(path);index=repo.open_index()
                return {'path':path,'diff':self.diff(self.base(repo,path),self.index_text(repo,index,key),path)}
            if action == 'git_log':
                return {'commits': [{'id': e.commit.id.decode(), 'message': e.commit.message.decode('utf-8', 'replace')[:1000]} for e in repo.get_walker(max_entries=20)]}
            if action == 'git_branches':
                return {'branches': [r.decode('utf-8', 'replace') for r in repo.refs.keys() if r.startswith(b'refs/heads/')][:128]}
            if action == 'git_status':
                index=repo.open_index()
                from dulwich.object_store import iter_tree_contents
                base={e.path:e.sha for e in iter_tree_contents(repo.object_store,repo[head].tree)}
                staged=[p for p in set(base)|set(index) if base.get(p)!=(index[p].sha if p in index else None)]
                unstaged=[]
                for key in list(index)[:128]:
                    try:
                        target=self.files.path(key.decode('utf-8'))
                        if not target.exists() or Blob.from_string(self.files.read(key.decode('utf-8'),remember=False).encode()).id!=index[key].sha:unstaged.append(key.decode('utf-8'))
                    except (ValueError,UnicodeError):continue
                return {'head':head.decode(),'staged':[p.decode('utf-8','replace') for p in staged[:128]],'unstaged':unstaged,'scope':'First 128 tracked paths; untracked files not enumerated'}
            self.files.path(path)
            before = self.base(repo, path)
            after = self.files.read(path, remember=False) if self.files.path(path).exists() else ''
            diff = self.diff(before,after,path)
            return {'path': path, 'diff': diff}

    def base(self, repo, path):
        try:
            mode, sha = repo[repo[repo.head()].tree].lookup_path(repo.object_store.__getitem__, path.replace('\\','/').encode())
        except KeyError: return ''
        if mode not in (0o100644,0o100755):raise ValueError('Only regular UTF-8 files are supported')
        data = repo[sha].data
        if len(data)>32000 or b'\x00' in data: raise ValueError('Git base is oversized or binary')
        return data.decode('utf-8')

    def proposal(self, paths, message):
        paths = self.paths(paths)
        if not message.strip() or len(message.encode())>2000: raise ValueError('Invalid commit message')
        with self.repo() as repo:
            state=self.state(repo);self.validate_state(repo,state)
            index = repo.open_index()
            if index.commit(repo.object_store)!=repo[repo.head()].tree: raise ValueError('Existing staged changes must be handled first')
            if (Path(repo.controldir())/'MERGE_HEAD').exists(): raise ValueError('Merge in progress')
            config = repo.get_config_stack()
            identity = config.get((b'user',),b'name')+b' <'+config.get((b'user',),b'email')+b'>'
            snapshots = {}; diffs=[]
            for path in paths:
                target=self.files.path(path)
                text=self.files.read(path,remember=False) if target.exists() else None
                snapshots[path]=None if text is None else hashlib.sha256(text.encode()).hexdigest()
                if self.key(path) not in index and IgnoreFilterManager.from_repo(repo).is_ignored(path):raise ValueError('Ignored files cannot be committed')
                diffs.append(self.diff(self.base(repo,path),text or '',path))
            diff=''.join(diffs)
            if not diff: raise ValueError('No changes selected')
            if len(diff.encode())>64000: raise ValueError('Commit diff exceeds review budget')
            self.validate_state(repo,state)
            return {'operation':'git_commit','cwd':str(self.root),'path':', '.join(paths),'paths':paths,'message':message,'identity':identity.decode('utf-8'),**state,'snapshots':snapshots,'diff':diff}

    def key(self, path):
        target=self.files.path(path)
        if target==self.root:raise ValueError('Select individual files')
        return target.relative_to(self.root).as_posix().encode('utf-8')

    @staticmethod
    def diff(before,after,path):
        diff=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='before/'+path,tofile='after/'+path))
        diff=''.join(line if line.endswith('\n') else line+'\n\\ No newline at end of file\n' for line in diff.splitlines(True))
        if len(diff.encode())>64000:raise ValueError('Git diff exceeds review budget')
        return diff

    @staticmethod
    def index_text(repo,index,key):
        if key not in index:return ''
        if index[key].mode not in (0o100644,0o100755):raise ValueError('Only regular UTF-8 files are supported')
        data=repo[index[key].sha].data
        if len(data)>32000 or b'\x00' in data:raise ValueError('Index file is oversized or binary')
        return data.decode('utf-8')

    def state(self,repo):
        return {'head':repo.head().decode(),'reference':repo.refs.follow(b'HEAD')[0][-1].decode(),
                'index':hashlib.sha256(Path(repo.index_path()).read_bytes()).hexdigest()}

    def validate_state(self,repo,proposal):
        reference=Path(repo.controldir())/proposal['reference']
        for item in (reference,*reference.parents):
            if item==Path(repo.controldir()).parent:break
            if item.is_symlink() or getattr(item,'is_junction',lambda:False)():raise ValueError('Linked Git references are unavailable')
        if self.state(repo)!={k:proposal[k] for k in ('head','reference','index')}:raise ValueError('Repository changed after review')
        metadata=Path(repo.controldir())
        if any((metadata/name).exists() for name in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply')):raise ValueError('Finish the in-progress Git operation first')

    def paths(self,encoded):
        paths=json.loads(encoded)
        if not isinstance(paths,list) or not 1<=len(paths)<=32 or any(not isinstance(p,str) for p in paths):raise ValueError('Specify 1–32 individual paths')
        normalized=[self.key(p).decode() for p in paths]
        if len(set(normalized))!=len(normalized):raise ValueError('Duplicate paths')
        return normalized

    def local_proposal(self,operation,paths='[]',name='',message=''):
        with self.repo() as repo:
            state=self.state(repo);self.validate_state(repo,state)
            proposal={'operation':operation,'cwd':str(self.root),'path':'','diff':'',**state}
            if operation=='git_create_branch':
                ref=b'refs/heads/'+name.encode('utf-8')
                if len(name.encode())>200 or not name or not check_ref_format(ref) or name.startswith('-'):raise ValueError('Invalid branch name')
                for parent in (Path(repo.controldir())/ref.decode()).parents:
                    if parent==Path(repo.controldir()):break
                    if parent.is_symlink() or getattr(parent,'is_junction',lambda:False)():raise ValueError('Linked Git references are unavailable')
                if ref in repo.refs:raise ValueError('Branch already exists')
                proposal.update(name=name,path=name)
                return proposal
            paths=self.paths(paths);index=repo.open_index();diffs=[];snapshots={}
            for path in paths:
                key=self.key(path);before=self.index_text(repo,index,key)
                if operation=='git_stage':
                    target=self.files.path(path)
                    if key not in index and IgnoreFilterManager.from_repo(repo).is_ignored(path):raise ValueError('Ignored files cannot be staged')
                    text=self.files.read(path,remember=False) if target.exists() else None
                    if text is None and key not in index:raise ValueError('File is not tracked or present')
                    snapshots[path]=None if text is None else hashlib.sha256(text.encode()).hexdigest()
                    after=text or ''
                elif operation=='git_unstage':after=self.base(repo,path)
                elif operation=='git_commit_staged':
                    after=before;before=self.base(repo,path)
                else:raise ValueError('Unknown Git operation')
                diffs.append(self.diff(before,after,path))
            diff=''.join(diffs)
            if not diff or len(diff.encode())>64000:raise ValueError('No reviewable changes or diff exceeds budget')
            proposal.update(paths=paths,path=', '.join(paths),diff=diff,snapshots=snapshots)
            if operation=='git_commit_staged':
                from dulwich.object_store import iter_tree_contents
                base={entry.path:(entry.mode,entry.sha) for entry in iter_tree_contents(repo.object_store,repo[repo.head()].tree)}
                staged={key for key in set(base)|set(index) if base.get(key)!=( (index[key].mode,index[key].sha) if key in index else None)}
                if staged!={self.key(path) for path in paths}:raise ValueError('Explicit paths must include every staged change')
                if not message.strip() or len(message.encode())>2000:raise ValueError('Invalid commit message')
                config=repo.get_config_stack()
                identity=config.get((b'user',),b'name')+b' <'+config.get((b'user',),b'email')+b'>'
                proposal.update(message=message,identity=identity.decode('utf-8'))
            return proposal

    def commit(self,proposal,check):
        return self.apply(proposal,check)

    def apply(self,proposal,check):
        with self.repo() as repo:
            locked=GitFile(repo.index_path(),'wb')
            try:
                check();self.validate_state(repo,proposal)
                operation=proposal['operation']
                if operation=='git_create_branch':
                    ref=b'refs/heads/'+proposal['name'].encode()
                    for parent in (Path(repo.controldir())/ref.decode()).parents:
                        if parent==Path(repo.controldir()):break
                        if parent.is_symlink() or getattr(parent,'is_junction',lambda:False)():raise ValueError('Linked Git references are unavailable')
                    check();self.validate_state(repo,proposal)
                    if not repo.refs.add_if_new(ref,proposal['head'].encode()):raise ValueError('Branch appeared after review')
                    return {'created':True,'branch':proposal['name'],'id':proposal['head'],'checked_out':False}
                index=repo.open_index()
                if operation in ('git_commit','git_stage'):
                    for path,expected in proposal['snapshots'].items():
                        target=self.files.path(path);raw=self.files.read(path,remember=False).encode() if target.exists() else None
                        if (None if raw is None else hashlib.sha256(raw).hexdigest())!=expected:raise ValueError('File changed after review')
                        key=self.key(path)
                        if raw is None:del index[key]
                        else:
                            blob=Blob.from_string(raw);repo.object_store.add_object(blob)
                            index[key]=index_entry_from_stat(target.stat(),blob.id,mode=index[key].mode if key in index else None)
                elif operation=='git_unstage':
                    tree=repo[repo[repo.head()].tree]
                    for path in proposal['paths']:
                        key=self.key(path)
                        try:mode,sha=tree.lookup_path(repo.object_store.__getitem__,key)
                        except KeyError:
                            if key in index:del index[key]
                            continue
                        from dulwich.index import IndexEntry
                        blob=repo[sha]
                        index[key]=IndexEntry(0,0,0,0,mode,0,0,len(blob.data),sha)
                elif operation!='git_commit_staged':raise ValueError('Unknown Git operation')
                # Prepare index bytes under its lock before publishing any reference.
                buffer=io.BytesIO();write_index_dict(buffer,dict(index.items()))
                data=buffer.getvalue();locked.write(data+hashlib.sha1(data).digest())
                check();self.validate_state(repo,proposal)
                if operation in ('git_commit','git_commit_staged'):
                    commit=Commit();commit.tree=index.commit(repo.object_store);commit.parents=[proposal['head'].encode()]
                    commit.author=commit.committer=proposal['identity'].encode();commit.message=proposal['message'].encode()
                    commit.author_time=commit.commit_time=int(time.time());commit.author_timezone=commit.commit_timezone=0
                    check();repo.object_store.add_object(commit)
                    if not repo.refs.set_if_equals(proposal['reference'].encode(),proposal['head'].encode(),commit.id):raise ValueError('Branch changed after review')
                    try:locked.close()
                    except OSError:
                        return {'committed':True,'id':commit.id.decode(),'index_updated':False,'warning':'Commit exists but index publication failed. Inspect repository before further changes; do not retry commit.'}
                    return {'committed':True,'id':commit.id.decode(),'paths':proposal['paths'],'index_updated':True}
                locked.close()
                return {'applied':True,'operation':operation,'paths':proposal['paths'],'working_files_changed':False}
            finally:locked.abort()
