import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from dulwich import porcelain
from agentnik.code_agent import ProjectFiles
from agentnik.git_service import GitService

class GitServiceTests(unittest.TestCase):
    def test_remote_inspection_hides_urls_and_never_connects(self):
        with tempfile.TemporaryDirectory() as folder:
            repo=porcelain.init(folder)
            try:
                config=repo.get_config()
                config.set((b'remote',b'origin'),b'url',b'https://user:secret@example.invalid/private-token?key=secret')
                config.set((b'remote',b'origin'),b'pushurl',b'git@example.invalid:private-token')
                config.set((b'remote',b'local'),b'url',b'C:/private-token/repo')
                config.write_to_path()
                with patch('subprocess.Popen',side_effect=AssertionError('No subprocesses')):
                    result=GitService(ProjectFiles(Path(folder))).inspect('git_remotes')
                self.assertEqual({r['name']:r['fetch_transports'] for r in result['remotes']},{'origin':['https'],'local':['local-or-other']})
                self.assertEqual(result['remotes'][0]['push_transports'],['ssh'])
                self.assertNotIn('secret',str(result));self.assertNotIn('private-token',str(result));self.assertNotIn('example.invalid',str(result))
            finally:repo.close()

    def test_review_commit_and_conflicts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repo=porcelain.init(folder)
            config=repo.get_config();config.set((b'user',),b'name',b'Test');config.set((b'user',),b'email',b'test@example.invalid');config.write_to_path()
            (root/'one.txt').write_text('old');porcelain.add(repo,['one.txt']);porcelain.commit(repo,message=b'Initial',no_verify=True,sign=False)
            service=GitService(ProjectFiles(root));(root/'one.txt').write_text('new')
            proposal=service.proposal('["one.txt"]','Update one')
            self.assertIn('-old',proposal['diff'])
            (root/'one.txt').write_text('changed')
            with self.assertRaises(ValueError):service.commit(proposal,lambda:None)
            (root/'one.txt').write_text('new')
            with patch('subprocess.Popen',side_effect=AssertionError('Git tools must not spawn processes')):
                result=service.commit(proposal,lambda:None)
            self.assertTrue(result['committed']);self.assertEqual(service.inspect('git_status')['staged'],[])
            self.assertEqual(service.inspect('git_status')['unstaged'],[])
            self.assertEqual(service.inspect('git_log')['commits'][0]['message'],'Update one')
            (root/'two.txt').write_text('two');porcelain.add(repo,['two.txt'])
            with self.assertRaises(ValueError):service.proposal('["one.txt"]','Do not include staged')
            with self.assertRaises(ValueError):service.inspect('git_diff','../outside')
            repo.close()


class GitFetchTests(unittest.TestCase):
    def test_https_transport_rejects_redirects_and_bounds_pack(self):
        from unittest.mock import Mock
        from agentnik.git_service import fetch_client
        from dulwich.client import HttpGitClient,GitProtocolError
        client=fetch_client('https://example.invalid/repo',lambda:None,10)
        response=Mock(status=302,headers={},geturl=lambda:'https://example.invalid/repo')
        with patch('urllib3.PoolManager.request',return_value=response) as request:
            with self.assertRaises(GitProtocolError):client._http_request('https://example.invalid/repo')
            self.assertFalse(request.call_args.kwargs['redirect']);self.assertFalse(request.call_args.kwargs['retries'])
        def transfer(instance,path,wants,walker,write,**kwargs):write(b'12345')
        with patch('agentnik.git_service.FETCH_PACK_LIMIT',4),patch.object(HttpGitClient,'fetch_pack',transfer):
            with self.assertRaisesRegex(ValueError,'pack exceeds'):client.fetch_pack('path',lambda *_:[],None,lambda _:None)
        def consume(pool,method,url,**kwargs):return list(kwargs['body'])
        with patch('agentnik.git_service.PUSH_PACK_LIMIT',4),patch('urllib3.PoolManager.request',consume):
            with self.assertRaisesRegex(ValueError,'Push request exceeds'):client.pool_manager.request('POST','https://example.invalid',body=iter([b'123',b'45']))

    def test_fetch_review_and_stale_remote_or_tracking_reference(self):
        from dulwich.client import LocalGitClient
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';target=root/'target';source.mkdir();target.mkdir()
            remote=porcelain.init(str(source));local=porcelain.init(str(target))
            try:
                config=remote.get_config();config.set((b'user',),b'name',b'Test');config.set((b'user',),b'email',b'test@example.invalid');config.write_to_path()
                (source/'file.txt').write_text('first');porcelain.add(remote,['file.txt']);porcelain.commit(remote,message=b'first',no_verify=True,sign=False)
                branch=remote.refs.follow(b'HEAD')[0][-1].decode().removeprefix('refs/heads/')
                config=local.get_config();config.set((b'remote',b'origin'),b'url',b'https://example.invalid/project.git');config.write_to_path()
                service=GitService(ProjectFiles(target));calls=[]
                class Fixture:
                    def get_refs(self,path):calls.append('refs');return LocalGitClient().get_refs(str(source))
                    def fetch(self,path,repo,**kwargs):calls.append('fetch');return LocalGitClient().fetch(str(source),repo,**kwargs)
                with patch('agentnik.git_service.fetch_client',return_value=Fixture()):
                    destination=service.fetch_destination('origin',branch);self.assertEqual(calls,[])
                    proposal=service.fetch_preview(destination,lambda:None,10);self.assertEqual(proposal['commit'],remote.head().decode())
                    result=service.fetch_apply(proposal,lambda:None,10)
                    self.assertTrue(result['fetched']);self.assertEqual(local.refs[result['tracking_ref'].encode()],remote.head())
                    self.assertFalse((target/'file.txt').exists())
                    proposal=service.fetch_preview(service.fetch_destination('origin',branch),lambda:None,10)
                    (source/'file.txt').write_text('second');porcelain.add(remote,['file.txt']);porcelain.commit(remote,message=b'second',no_verify=True,sign=False)
                    with self.assertRaisesRegex(ValueError,'changed after review'):service.fetch_apply(proposal,lambda:None,10)
                    proposal=service.fetch_preview(service.fetch_destination('origin',branch),lambda:None,10)
                    local.refs[result['tracking_ref'].encode()]=remote.head()
                    with self.assertRaisesRegex(ValueError,'changed after review'):service.fetch_apply(proposal,lambda:None,10)
            finally:remote.close();local.close()

    def test_fetch_rejects_credentials_and_unapproved_transports(self):
        with tempfile.TemporaryDirectory() as folder:
            repo=porcelain.init(folder)
            try:
                config=repo.get_config();service=GitService(ProjectFiles(Path(folder)))
                for url in (b'https://user:password@example.com/repo',b'https://example.com/repo?token=secret',b'http://example.com/repo',b'git@example.com:repo',b'/tmp/repo'):
                    config.set((b'remote',b'origin'),b'url',url);config.write_to_path()
                    with self.subTest(url=url),self.assertRaises(ValueError):service.fetch_destination('origin','main')
            finally:repo.close()


class GitPushTests(unittest.TestCase):
    def test_unconfirmed_remote_status_is_not_reported_as_success(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repo=porcelain.init(folder)
            try:
                config=repo.get_config();config.set((b'user',),b'name',b'Test');config.set((b'user',),b'email',b'test@example.invalid');config.set((b'remote',b'origin'),b'url',b'https://example.invalid/repo');config.write_to_path()
                (root/'f').write_text('one');porcelain.add(repo,['f']);porcelain.commit(repo,message=b'one',no_verify=True,sign=False)
                branch=repo.refs.follow(b'HEAD')[0][-1].decode().removeprefix('refs/heads/');service=GitService(ProjectFiles(root));destination=service.push_destination('origin','new',branch)
                proposal={**destination,'operation':'git_push','previous':''};client=Mock();client.send_pack.return_value=Mock(ref_status=None)
                with patch('agentnik.git_service.fetch_client',return_value=client):
                    with self.assertRaisesRegex(ValueError,'did not confirm'):service.push_apply(proposal,lambda:None,10)
            finally:repo.close()

    def test_push_new_and_fast_forward_with_stale_checks(self):
        from dulwich.client import LocalGitClient
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';target=root/'target';source.mkdir();target.mkdir()
            local=porcelain.init(str(source));remote=porcelain.init(str(target),bare=True)
            try:
                config=local.get_config();config.set((b'user',),b'name',b'Test');config.set((b'user',),b'email',b'test@example.invalid');config.set((b'remote',b'origin'),b'url',b'https://example.invalid/project.git');config.write_to_path()
                (source/'file.txt').write_text('first');porcelain.add(local,['file.txt']);porcelain.commit(local,message=b'first',no_verify=True,sign=False)
                branch=local.refs.follow(b'HEAD')[0][-1].decode().removeprefix('refs/heads/');service=GitService(ProjectFiles(source));calls=[]
                class Fixture:
                    def get_refs(self,path):calls.append('refs');return LocalGitClient().get_refs(str(target))
                    def send_pack(self,path,update_refs,generate_pack_data,progress=None):
                        calls.append('push');result=LocalGitClient().send_pack(str(target),update_refs,generate_pack_data,progress=progress)
                        if not result.ref_status:result.ref_status={name:None for name in result.refs}
                        return result
                with patch('agentnik.git_service.fetch_client',return_value=Fixture()):
                    destination=service.push_destination('origin','main',branch);self.assertEqual(calls,[])
                    proposal=service.push_preview(destination,lambda:None,10);self.assertEqual(proposal['previous'],'')
                    result=service.push_apply(proposal,lambda:None,10);self.assertTrue(result['pushed']);self.assertEqual(remote.refs[b'refs/heads/main'],local.head())
                    old=local.head();(source/'file.txt').write_text('second');porcelain.add(local,['file.txt']);porcelain.commit(local,message=b'second',no_verify=True,sign=False)
                    proposal=service.push_preview(service.push_destination('origin','main',branch),lambda:None,10);self.assertEqual(proposal['previous'],old.decode())
                    result=service.push_apply(proposal,lambda:None,10);self.assertEqual(remote.refs[b'refs/heads/main'],local.head())
                    (source/'file.txt').write_text('third');porcelain.add(local,['file.txt']);porcelain.commit(local,message=b'third',no_verify=True,sign=False)
                    proposal=service.push_preview(service.push_destination('origin','main',branch),lambda:None,10)
                    remote.refs[b'refs/heads/main']=old
                    with self.assertRaisesRegex(ValueError,'Remote branch changed'):service.push_apply(proposal,lambda:None,10)
                    self.assertEqual(remote.refs[b'refs/heads/main'],old)
                    proposal=service.push_preview(service.push_destination('origin','main',branch),lambda:None,10)
                    (source/'file.txt').write_text('fourth');porcelain.add(local,['file.txt']);porcelain.commit(local,message=b'fourth',no_verify=True,sign=False)
                    with self.assertRaisesRegex(ValueError,'local branch changed'):service.push_apply(proposal,lambda:None,10)
            finally:local.close();remote.close()

    def test_rejects_non_fast_forward(self):
        from dulwich.client import LocalGitClient
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';target=root/'target';source.mkdir();target.mkdir();local=porcelain.init(str(source));remote=porcelain.init(str(target))
            try:
                for repo in (local,remote):
                    c=repo.get_config();c.set((b'user',),b'name',b'Test');c.set((b'user',),b'email',b'test@example.invalid');c.write_to_path()
                config=local.get_config();config.set((b'remote',b'origin'),b'url',b'https://example.invalid/repo');config.write_to_path()
                for repo,path in ((local,source),(remote,target)):
                    (path/'f').write_text(str(path));porcelain.add(repo,['f']);porcelain.commit(repo,message=b'initial',no_verify=True,sign=False)
                branch=local.refs.follow(b'HEAD')[0][-1].decode().removeprefix('refs/heads/');remote_branch=remote.refs.follow(b'HEAD')[0][-1].decode().removeprefix('refs/heads/')
                class Fixture:
                    def get_refs(self,path):return LocalGitClient().get_refs(str(target))
                with patch('agentnik.git_service.fetch_client',return_value=Fixture()):
                    service=GitService(ProjectFiles(source))
                    with self.assertRaisesRegex(ValueError,'fast-forward'):service.push_preview(service.push_destination('origin',remote_branch,branch),lambda:None,10)
            finally:local.close();remote.close()


class GitLocalWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=porcelain.init(str(self.root));self.addCleanup(self.repo.close)
        config=self.repo.get_config();config.set((b'user',),b'name',b'Test');config.set((b'user',),b'email',b'test@example.invalid');config.write_to_path()
        (self.root/'one.txt').write_text('old\n');porcelain.add(self.repo,['one.txt']);porcelain.commit(self.repo,message=b'Initial',no_verify=True,sign=False)
        self.git=GitService(ProjectFiles(self.root))

    def test_stage_staged_commit_preserves_later_working_edits(self):
        (self.root/'one.txt').write_text('staged\n',newline='\n')
        with patch('subprocess.Popen',side_effect=AssertionError('No subprocesses')):
            proposal=self.git.local_proposal('git_stage','["one.txt"]');self.git.apply(proposal,lambda:None)
            self.assertIn('+staged',self.git.inspect('git_diff_staged','one.txt')['diff'])
            proposal=self.git.local_proposal('git_commit_staged','["one.txt"]',message='Staged snapshot')
            (self.root/'one.txt').write_text('later edit\n')
            result=self.git.apply(proposal,lambda:None)
        self.assertTrue(result['committed']);self.assertEqual((self.root/'one.txt').read_text(),'later edit\n')
        self.assertEqual(self.git.base(self.repo,'one.txt'),'staged\n')
        self.assertEqual(self.git.inspect('git_status')['staged'],[])
        self.assertEqual(self.git.inspect('git_status')['unstaged'],['one.txt'])

    def test_unstage_preserves_working_files_and_other_staged_entries(self):
        (self.root/'one.txt').write_text('changed\n');(self.root/'two.txt').write_text('two\n')
        self.git.apply(self.git.local_proposal('git_stage','["one.txt","two.txt"]'),lambda:None)
        with self.assertRaises(ValueError):self.git.local_proposal('git_commit_staged','["one.txt"]',message='Incomplete')
        self.git.apply(self.git.local_proposal('git_unstage','["one.txt"]'),lambda:None)
        self.assertEqual(self.git.inspect('git_status')['staged'],['two.txt'])
        self.assertEqual((self.root/'one.txt').read_text(),'changed\n')
        self.git.apply(self.git.local_proposal('git_unstage','["two.txt"]'),lambda:None)
        self.assertTrue((self.root/'two.txt').exists());self.assertEqual(self.git.inspect('git_status')['staged'],[])

    def test_branch_creation_conflicts_and_branch_bound_approval(self):
        head=self.repo.head();symbolic=self.repo.refs.read_ref(b'HEAD')
        proposal=self.git.local_proposal('git_create_branch',name='feature/review')
        self.git.apply(proposal,lambda:None)
        self.assertEqual(self.repo.refs[b'refs/heads/feature/review'],head)
        self.assertEqual(self.repo.refs.read_ref(b'HEAD'),symbolic)
        with self.assertRaises(ValueError):self.git.local_proposal('git_create_branch',name='feature/review')
        for name in ('../escape','bad..name','-option','name.lock'):
            with self.assertRaises(ValueError):self.git.local_proposal('git_create_branch',name=name)
        (self.root/'one.txt').write_text('change\n');proposal=self.git.proposal('["one.txt"]','Branch-bound')
        self.repo.refs.set_symbolic_ref(b'HEAD',b'refs/heads/feature/review')
        with self.assertRaises(ValueError):self.git.commit(proposal,lambda:None)
        self.assertEqual(self.repo.head(),head)

    def test_staging_conflicts_ignored_paths_and_cancellation(self):
        (self.root/'one.txt').write_text('change\n');proposal=self.git.local_proposal('git_stage','["one.txt"]')
        (self.root/'one.txt').write_text('later\n')
        with self.assertRaises(ValueError):self.git.apply(proposal,lambda:None)
        (self.root/'.gitignore').write_text('ignored.txt\n');(self.root/'ignored.txt').write_text('ignored')
        for paths in ('["ignored.txt"]','[".env"]','["../escape"]','["one.txt","./one.txt"]'):
            with self.assertRaises(ValueError):self.git.local_proposal('git_stage',paths)
        proposal=self.git.local_proposal('git_stage','["one.txt"]')
        def cancelled():raise RuntimeError('Cancelled')
        with self.assertRaises(RuntimeError):self.git.apply(proposal,cancelled)
        self.assertFalse((self.root/'.git/index.lock').exists());self.assertEqual(self.git.inspect('git_status')['staged'],[])

    def test_deletion_and_index_publication_failure(self):
        (self.root/'one.txt').unlink()
        self.git.apply(self.git.local_proposal('git_stage','["one.txt"]'),lambda:None)
        proposal=self.git.local_proposal('git_commit_staged','["one.txt"]',message='Delete one')
        self.git.apply(proposal,lambda:None)
        self.assertEqual(self.git.inspect('git_status')['staged'],[])
        (self.root/'two.txt').write_text('new')
        proposal=self.git.proposal('["two.txt"]','Add two')
        import agentnik.git_service as module
        original=module.GitFile
        class FailedPublication:
            def __init__(self,*args,**kwargs):self.file=original(*args,**kwargs)
            def write(self,data):return self.file.write(data)
            def abort(self):return self.file.abort()
            def close(self):raise OSError('Simulated index publication failure')
        with patch.object(module,'GitFile',FailedPublication):result=self.git.commit(proposal,lambda:None)
        self.assertTrue(result['committed']);self.assertFalse(result['index_updated']);self.assertEqual(self.repo.head().decode(),result['id'])
