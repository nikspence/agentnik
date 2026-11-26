"""Structured Git operations with explicitly reviewed remote transfers."""
import difflib
import hashlib
import json
import time
import io
import re
from urllib.parse import urlsplit
from dulwich.file import GitFile
from dulwich.index import write_index_dict
from pathlib import Path
from dulwich.repo import Repo
from dulwich.objects import Blob, Commit, Tree
from dulwich.index import index_entry_from_stat
from dulwich.refs import check_ref_format
from dulwich.ignore import IgnoreFilterManager

FETCH_PACK_LIMIT=32_000_000
PUSH_PACK_LIMIT=32_000_000


def fetch_client(url,check,timeout,credentials=None):
    """HTTPS with optional ephemeral Basic authentication, bound to one origin."""
    import urllib3
    from dulwich.client import HttpGitClient
    origin=urlsplit(url);expected_origin=(origin.scheme,origin.hostname,origin.port or 443)
    class Pool(urllib3.PoolManager):
        def request(self,method,url,**kwargs):
            check();target=urlsplit(url)
            if target.username is not None or target.password is not None or (target.scheme,target.hostname,target.port or 443)!=expected_origin:raise ValueError('Git request changed origin')
            kwargs.update(redirect=False,retries=False)
            body=kwargs.get('body')
            if body is not None and not isinstance(body,(bytes,str)):
                def bounded_body():
                    total=0
                    for chunk in body:
                        check();total+=len(chunk)
                        if total>PUSH_PACK_LIMIT:raise ValueError('Push request exceeds 32 MB limit')
                        yield chunk
                kwargs['body']=bounded_body()
            return super().request(method,url,**kwargs)
    class Client(HttpGitClient):
        def _http_request(self,*args,**kwargs):
            response,read=super()._http_request(*args,**kwargs)
            total=0
            def bounded_read(size):
                nonlocal total
                check();data=read(size);total+=len(data)
                if total>FETCH_PACK_LIMIT+2_000_000:raise ValueError('Fetch response exceeds size limit')
                check();return data
            return response,bounded_read
        def fetch_pack(self,path,determine_wants,graph_walker,pack_data,**kwargs):
            size=0
            def write(data):
                nonlocal size
                check();size+=len(data)
                if size>FETCH_PACK_LIMIT:raise ValueError('Fetch pack exceeds 32 MB limit')
                return pack_data(data)
            return super().fetch_pack(path,determine_wants,graph_walker,write,**kwargs)
    username,password=credentials if credentials else (None,None)
    return Client(url,pool_manager=Pool(),timeout=timeout,thin_packs=False,quiet=True,username=username,password=password)


class GitService:
    def __init__(self, files, author=None):
        from .repositories import validate_git_author
        self.author=validate_git_author(author)
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

    def fetch_destination(self,remote,branch):
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,100}',remote) or remote in ('.','..'):raise ValueError('Invalid remote name')
        if not branch or len(branch.encode())>200 or not check_ref_format(b'refs/heads/'+branch.encode()) or branch.startswith('-'):raise ValueError('Invalid branch name')
        with self.repo() as repo:
            try:urls=list(repo.get_config().get_multivar((b'remote',remote.encode()),b'url'))
            except KeyError:raise ValueError('Remote has no configured fetch URL') from None
            if len(urls)!=1:raise ValueError('Fetch requires exactly one configured remote URL')
            try:url=urls[0].decode('ascii')
            except UnicodeError:raise ValueError('Fetch URL must be an ASCII HTTPS URL') from None
            parts=urlsplit(url)
            if (parts.scheme!='https' or not parts.hostname or parts.username is not None or parts.password is not None or parts.query or parts.fragment or any(ord(c)<33 or ord(c)>126 for c in url)):
                raise ValueError('Fetch supports credential-free HTTPS URLs without query or fragment only')
            try:parts.port
            except ValueError:raise ValueError('Invalid remote URL port') from None
            target=b'refs/remotes/'+remote.encode()+b'/'+branch.encode()
            if not check_ref_format(target):raise ValueError('Invalid remote-tracking reference')
            self.check_fetch_ref(repo,target)
            old=repo.refs.read_ref(target)
            if old is not None and not re.fullmatch(rb'[0-9a-f]{40}',old):raise ValueError('Remote-tracking reference is not a direct commit ID')
            return {'operation':'git_fetch_connect','cwd':str(self.root),'remote':remote,'branch':branch,'url':url,'target':target.decode(),'previous':old.decode() if old else ''}

    def check_fetch_ref(self,repo,target):
        metadata=Path(repo.controldir());path=metadata/target.decode()
        for part in (path,*path.parents):
            if part==metadata.parent:break
            if part.is_symlink() or getattr(part,'is_junction',lambda:False)():raise ValueError('Linked Git references are unavailable')
        if (metadata/'packed-refs').is_symlink() or getattr(metadata/'packed-refs','is_junction',lambda:False)():raise ValueError('Linked Git references are unavailable')

    def fetch_preview(self,proposal,check,timeout,credentials=None):
        check()
        if self.fetch_destination(proposal['remote'],proposal['branch'])!=proposal:raise ValueError('Remote configuration or tracking reference changed after review')
        client=fetch_client(proposal['url'],check,timeout,credentials)
        refs=client.get_refs(proposal['url']).refs;check()
        sha=refs.get(('refs/heads/'+proposal['branch']).encode())
        if not isinstance(sha,bytes) or not re.fullmatch(rb'[0-9a-f]{40}',sha):raise ValueError('Remote branch was not found or uses an unsupported object format')
        return {**proposal,'operation':'git_fetch','commit':sha.decode()}

    def fetch_apply(self,proposal,check,timeout,credentials=None):
        before={**proposal,'operation':'git_fetch_connect'};before.pop('commit')
        check()
        if self.fetch_destination(proposal['remote'],proposal['branch'])!=before:raise ValueError('Remote configuration or tracking reference changed after review')
        source=('refs/heads/'+proposal['branch']).encode();expected=proposal['commit'].encode();target=proposal['target'].encode()
        client=fetch_client(proposal['url'],check,timeout,credentials)
        with self.repo() as repo:
            def wants(refs,*args,**kwargs):
                check()
                if refs.get(source)!=expected:raise ValueError('Remote branch changed after review; fetch again to review the new commit')
                return [] if expected in repo.object_store else [expected]
            client.fetch(proposal['url'],repo,determine_wants=wants,progress=lambda _:check(),ref_prefix=[source])
            check()
            if self.fetch_destination(proposal['remote'],proposal['branch'])!=before:raise ValueError('Remote configuration or tracking reference changed during fetch')
            if expected not in repo.object_store or not isinstance(repo[expected],Commit):raise ValueError('Fetched commit is unavailable')
            self.check_fetch_ref(repo,target);check()
            changed=(repo.refs.set_if_equals(target,proposal['previous'].encode(),expected) if proposal['previous'] else repo.refs.add_if_new(target,expected))
            if not changed:raise ValueError('Remote-tracking reference changed during fetch')
        return {'fetched':True,'remote':proposal['remote'],'branch':proposal['branch'],'commit':proposal['commit'],'tracking_ref':proposal['target'],'working_files_changed':False}

    def push_destination(self,remote,branch,local_branch):
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,100}',remote) or remote in ('.','..'):raise ValueError('Invalid remote name')
        for name in (branch,local_branch):
            if not name or len(name.encode())>200 or name.startswith('-') or not check_ref_format(b'refs/heads/'+name.encode()):raise ValueError('Invalid branch name')
        with self.repo() as repo:
            config=repo.get_config();section=(b'remote',remote.encode())
            try:urls=list(config.get_multivar(section,b'pushurl'))
            except KeyError:urls=[]
            if not urls:
                try:urls=list(config.get_multivar(section,b'url'))
                except KeyError:raise ValueError('Remote has no configured push URL') from None
            if len(urls)!=1:raise ValueError('Push requires exactly one configured destination URL')
            try:url=urls[0].decode('ascii')
            except UnicodeError:raise ValueError('Push URL must be an ASCII HTTPS URL') from None
            parts=urlsplit(url)
            if parts.scheme!='https' or not parts.hostname or parts.username is not None or parts.password is not None or parts.query or parts.fragment or any(ord(c)<33 or ord(c)>126 for c in url):raise ValueError('Push supports credential-free HTTPS URLs without query or fragment only')
            try:parts.port
            except ValueError:raise ValueError('Invalid remote URL port') from None
            source=b'refs/heads/'+local_branch.encode();self.check_fetch_ref(repo,source);sha=repo.refs.read_ref(source)
            if sha is None or not re.fullmatch(rb'[0-9a-f]{40}',sha) or not isinstance(repo[sha],Commit):raise ValueError('Local branch must name an existing direct commit')
            return {'operation':'git_push_connect','cwd':str(self.root),'remote':remote,'branch':branch,'local_branch':local_branch,'url':url,'commit':sha.decode(),'target':'refs/heads/'+branch}

    def push_preview(self,destination,check,timeout,credentials=None):
        check()
        if self.push_destination(destination['remote'],destination['branch'],destination['local_branch'])!=destination:raise ValueError('Push destination or local branch changed after review')
        try:refs=fetch_client(destination['url'],check,timeout,credentials).get_refs(destination['url']).refs
        except ValueError:raise ValueError('Remote branch inspection returned an invalid response.') from None
        check()
        old=refs.get(destination['target'].encode())
        if old is not None and (not isinstance(old,bytes) or not re.fullmatch(rb'[0-9a-f]{40}',old)):raise ValueError('Remote branch uses an unsupported object format')
        with self.repo() as repo:
            if old:
                target=destination['commit'].encode();pending=[target];visited=set();found=False
                while pending:
                    check();sha=pending.pop()
                    if sha==old:found=True;break
                    if sha in visited:continue
                    visited.add(sha)
                    if len(visited)>10000:raise ValueError('Commit history exceeds push review limit')
                    try:commit=repo[sha]
                    except KeyError:raise ValueError('Local history is incomplete; fetch the remote branch first') from None
                    if not isinstance(commit,Commit):raise ValueError('Invalid commit history')
                    pending.extend(commit.parents)
                if not found:raise ValueError('Push is not a verified fast-forward; fetch and reconcile first')
        if old==destination['commit'].encode():raise ValueError('Remote branch already points to this commit')
        return {**destination,'operation':'git_push','previous':old.decode() if old else ''}

    def push_apply(self,proposal,check,timeout,credentials=None):
        before={**proposal,'operation':'git_push_connect'};before.pop('previous')
        check()
        if self.push_destination(proposal['remote'],proposal['branch'],proposal['local_branch'])!=before:raise ValueError('Push destination or local branch changed after review')
        target=proposal['target'].encode();expected=proposal['previous'].encode() if proposal['previous'] else None;commit=proposal['commit'].encode()
        client=fetch_client(proposal['url'],check,timeout,credentials)
        with self.repo() as repo:
            def update(refs):
                check()
                if refs.get(target)!=expected:raise ValueError('Remote branch changed after review')
                if self.push_destination(proposal['remote'],proposal['branch'],proposal['local_branch'])!=before:raise ValueError('Push destination or local branch changed after review')
                return {target:commit}
            result=client.send_pack(proposal['url'],update,repo.generate_pack_data,progress=lambda _:check())
            check()
            if not isinstance(result.ref_status,dict) or target not in result.ref_status or result.ref_status[target] is not None:raise ValueError('Remote did not confirm the branch update')
        return {'pushed':True,'remote':proposal['remote'],'branch':proposal['branch'],'commit':proposal['commit'],'previous':proposal['previous']}

    def remote_branches(self,check=lambda:None):
        with self.repo() as repo:
            names=sorted(repo.refs.keys(b'refs/remotes'));items=[];omitted=0
            for name in names:
                check();ref=b'refs/remotes/'+name
                try:
                    if not check_ref_format(ref):raise ValueError()
                    self.check_fetch_ref(repo,ref);sha=repo.refs.read_ref(ref)
                    if not isinstance(sha,bytes) or not re.fullmatch(rb'[0-9a-f]{40}',sha):raise ValueError()
                    decoded=ref.decode('utf-8')
                except (ValueError,UnicodeError,OSError):omitted+=1;continue
                if len(items)>=128:omitted+=1;continue
                items.append({'ref':decoded,'commit':sha.decode('ascii')})
            return {'branches':items,'omitted':omitted,'notice':'Local remote-tracking references only; they may be stale. Symbolic or unsupported refs are omitted.'}

    def checked_ref(self,repo,name):
        if not isinstance(name,str) or not name.startswith(('refs/heads/','refs/remotes/')) or len(name.encode('utf-8'))>512:raise ValueError('Use exact refs/heads/... or refs/remotes/... reference names')
        ref=name.encode('utf-8')
        if not check_ref_format(ref):raise ValueError('Invalid branch reference')
        self.check_fetch_ref(repo,ref);sha=repo.refs.read_ref(ref)
        if not isinstance(sha,bytes) or not re.fullmatch(rb'[0-9a-f]{40}',sha):raise ValueError('Branch reference is missing, symbolic, or has an unsupported object format')
        return sha

    def ref_commits(self,repo,left,right):
        left_sha=self.checked_ref(repo,left);right_sha=self.checked_ref(repo,right)
        try:commits=(repo[left_sha],repo[right_sha])
        except KeyError:raise ValueError('Branch commit is missing; fetch complete history first') from None
        if not all(isinstance(commit,Commit) for commit in commits):raise ValueError('Branch reference does not point to a commit')
        return left_sha,right_sha,commits

    def check_ref_snapshot(self,repo,left,right,left_sha,right_sha):
        if self.checked_ref(repo,left)!=left_sha or self.checked_ref(repo,right)!=right_sha:raise ValueError('Branch references changed during comparison; inspect them again')

    def changed_files(self,left,right,check=lambda:None):
        from dulwich.diff_tree import tree_changes
        with self.repo() as repo:
            check();left_sha,right_sha,commits=self.ref_commits(repo,left,right);items=[];omitted=0;truncated=False;scanned=0
            try:
                for change in tree_changes(repo.object_store,commits[0].tree,commits[1].tree):
                    check();scanned+=1
                    if scanned>2000:truncated=True;break
                    entry=change.new if change.new is not None else change.old
                    try:
                        path=entry.path.decode('utf-8');self.files.path(path)
                    except (ValueError,UnicodeError,OSError):omitted+=1;continue
                    if len(items)>=128:truncated=True;break
                    items.append({'path':path,'status':change.type,'left_mode':change.old.mode if change.old else None,'right_mode':change.new.mode if change.new else None})
            except KeyError:raise ValueError('A branch tree is unavailable locally') from None
            check();self.check_ref_snapshot(repo,left,right,left_sha,right_sha)
            return {'left':{'ref':left,'commit':left_sha.decode()},'right':{'ref':right,'commit':right_sha.decode()},'changes':items,'omitted':omitted,'truncated':truncated,'notice':'Local committed trees only. Renames appear as deletion and addition; excluded paths are omitted. Tracking refs may be stale.'}

    def diff_refs(self,left,right,path,check=lambda:None):
        with self.repo() as repo:
            self.files.path(path);key=self.key(path);check();left_sha,right_sha,commits=self.ref_commits(repo,left,right)
            def file_at(commit):
                def load_tree(sha):
                    try:tree=repo.object_store[sha]
                    except KeyError:raise ValueError('A branch tree is unavailable locally') from None
                    if not isinstance(tree,Tree):raise ValueError('Invalid branch tree')
                    return tree
                try:mode,sha=load_tree(commit.tree).lookup_path(load_tree,key)
                except KeyError:return None,None
                if mode not in (0o100644,0o100755):raise ValueError('Only regular UTF-8 files can be compared')
                try:blob=repo[sha]
                except KeyError:raise ValueError('File content is unavailable locally') from None
                if not isinstance(blob,Blob) or len(blob.data)>32000 or b'\x00' in blob.data:raise ValueError('File is binary, unavailable or exceeds the diff budget')
                try:return blob.data.decode('utf-8'),mode
                except UnicodeError:raise ValueError('Only UTF-8 files can be compared') from None
            before,left_mode=file_at(commits[0]);after,right_mode=file_at(commits[1])
            if before is None and after is None:raise ValueError('File does not exist in either branch')
            result={'path':path,'left':{'ref':left,'commit':left_sha.decode(),'present':before is not None,'mode':left_mode},'right':{'ref':right,'commit':right_sha.decode(),'present':after is not None,'mode':right_mode},'diff':self.diff(before or '',after or '',path),'notice':'Local committed contents only; tracking refs may be stale. This does not authorize edits.'}
            check();self.check_ref_snapshot(repo,left,right,left_sha,right_sha);return result

    def compare_refs(self,left,right,check=lambda:None):
        """Compare locally available branch histories without network access."""
        with self.repo() as repo:
            check()
            if repo.get_shallow():raise ValueError('Cannot compare shallow history reliably; obtain complete history first')
            left_sha=self.checked_ref(repo,left);right_sha=self.checked_ref(repo,right)
            def ancestors(head):
                pending=[head];seen=set()
                while pending:
                    check();sha=pending.pop()
                    if sha in seen:continue
                    if len(seen)>=10000:raise ValueError('Commit history exceeds comparison limit')
                    try:commit=repo[sha]
                    except KeyError:raise ValueError('Commit history is incomplete; fetch complete history first') from None
                    if not isinstance(commit,Commit):raise ValueError('Branch history contains a non-commit object')
                    if len(commit.parents)>128 or len(pending)+len(commit.parents)>20000:raise ValueError('Commit history exceeds comparison limit')
                    seen.add(sha);pending.extend(commit.parents)
                return seen
            left_set=ancestors(left_sha);right_set=ancestors(right_sha)
            self.check_ref_snapshot(repo,left,right,left_sha,right_sha)
            left_only=left_set-right_set;right_only=right_set-left_set
            def samples(items):
                return [sha.decode('ascii') for sha in sorted(items)[:20]]
            return {'left':{'ref':left,'commit':left_sha.decode(),'only_count':len(left_only),'example_commits':samples(left_only)},
                    'right':{'ref':right,'commit':right_sha.decode(),'only_count':len(right_only),'example_commits':samples(right_only)},
                    'relationship':('equal' if not left_only and not right_only else 'left_ahead' if left_only and not right_only else 'right_ahead' if right_only and not left_only else 'diverged'),
                    'notice':'Local references and objects only; remote-tracking refs may be stale. Commit examples are sorted by ID, not time.'}

    def inspect(self, action, path=''):
        with self.repo() as repo:
            if action == 'git_remotes':
                # Read only this repository's config; do not follow includes or
                # expose URLs, which can contain credentials in any component.
                config=repo.get_config();remotes=[];omitted=0
                for section in config.sections():
                    if len(section)!=2 or section[0].lower()!=b'remote':continue
                    name=section[1].decode('utf-8','replace')
                    if not re.fullmatch(r'[A-Za-z0-9._-]{1,100}',name) or len(remotes)>=32:
                        omitted+=1;continue
                    def transports(key):
                        try: values=list(config.get_multivar(section,key))
                        except KeyError: return []
                        kinds=[]
                        for value in values[:16]:
                            value=value.strip()
                            match=re.match(rb'^([A-Za-z][A-Za-z0-9+.-]*)://',value)
                            if match:
                                scheme=match.group(1).lower()
                                kind=scheme.decode() if scheme in (b'http',b'https',b'ssh',b'git',b'file') else 'other'
                            elif re.match(rb'^[^/\\\s:]+@?[^/\\\s:]*:',value) and not re.match(rb'^[A-Za-z]:[/\\]',value):kind='ssh'
                            else:kind='local-or-other'
                            kinds.append(kind)
                        return kinds
                    remotes.append({'name':name,'fetch_transports':transports(b'url'),'push_transports':transports(b'pushurl')})
                return {'remotes':remotes,'omitted':omitted,'scope':'Local repository config only; URLs and rewrite rules are not shown. Empty push transports use Git defaults; no network request was made.'}
            try:
                head = repo.head()
            except KeyError:
                if action not in ('git_status', 'git_diff', 'git_diff_staged'):
                    raise
                head = None
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
                base={e.path:e.sha for e in iter_tree_contents(repo.object_store,repo[head].tree)} if head is not None else {}
                staged=[p for p in set(base)|set(index) if base.get(p)!=(index[p].sha if p in index else None)]
                unstaged=[]
                for key in list(index)[:128]:
                    try:
                        target=self.files.path(key.decode('utf-8'))
                        if not target.exists() or Blob.from_string(self.files.read(key.decode('utf-8'),remember=False).encode()).id!=index[key].sha:unstaged.append(key.decode('utf-8'))
                    except (ValueError,UnicodeError):continue
                return {'head':head.decode() if head is not None else None,'staged':[p.decode('utf-8','replace') for p in staged[:128]],'unstaged':unstaged,'scope':'First 128 tracked paths; untracked files not enumerated'}
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

    def identity(self,repo):
        if self.author:return (self.author['name']+' <'+self.author['email']+'>').encode('utf-8')
        config=repo.get_config_stack()
        return config.get((b'user',),b'name')+b' <'+config.get((b'user',),b'email')+b'>'

    def proposal(self, paths, message):
        paths = self.paths(paths)
        if not message.strip() or len(message.encode())>2000: raise ValueError('Invalid commit message')
        with self.repo() as repo:
            state=self.state(repo);self.validate_state(repo,state)
            index = repo.open_index()
            if index.commit(repo.object_store)!=repo[repo.head()].tree: raise ValueError('Existing staged changes must be handled first')
            if (Path(repo.controldir())/'MERGE_HEAD').exists(): raise ValueError('Merge in progress')
            identity = self.identity(repo)
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
                identity=self.identity(repo)
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
