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
