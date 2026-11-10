import tempfile
import unittest
from pathlib import Path
from agentnik.code_agent import ProjectFiles
from agentnik.project_skills import list_skills,read_skill,read_resource

class ProjectSkills(unittest.TestCase):
    def test_discovery_is_bounded_to_valid_project_skill_and_does_not_authorize_edits(self):
        with tempfile.TemporaryDirectory() as root:
            skill=Path(root)/'.agents/skills/review';skill.mkdir(parents=True)
            (skill/'SKILL.md').write_text('---\nname: review\ndescription: Review changes\n---\nCheck tests.',encoding='utf-8')
            files=ProjectFiles(root)
            self.assertEqual(list_skills(files)[0]['name'],'review')
            self.assertIn('Check tests',read_skill(files,'review')['instructions'])
            self.assertFalse(files.observed)
            with self.assertRaises(ValueError):read_skill(files,'../review')

    def test_selected_skill_is_sent_to_model(self):
        import copy
        from unittest.mock import patch
        from agentnik import core
        from agentnik.code_agent import CodingRun
        from test_compat_tools import chat
        from test_routing import Wire
        with tempfile.TemporaryDirectory() as root:
            skill=Path(root)/'.agents/skills/review';skill.mkdir(parents=True)
            (skill/'SKILL.md').write_text('---\nname: review\ndescription: Review changes\n---\nCheck the tests.',encoding='utf-8')
            bodies=[];events=[]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun({'url':'https://example.org/v1','model':'test','protocol':'chat','stream':False},root,'Review',skills=['review']).run(events.append)
            self.assertIn('Check the tests.',bodies[0]['messages'][0]['content'])
            self.assertEqual(events[-1]['status'],'completed')
            self.assertTrue(any('Selected skill: review' in e.get('text','') for e in events))

    def test_skill_reference_is_confined_and_does_not_authorize_editing(self):
        with tempfile.TemporaryDirectory() as root:
            skill=Path(root)/'.agents/skills/review';(skill/'references').mkdir(parents=True)
            (skill/'SKILL.md').write_text('---\nname: review\ndescription: Review changes\n---\nUse references.',encoding='utf-8')
            (skill/'references/guide.md').write_text('Useful detail',encoding='utf-8')
            files=ProjectFiles(root);result=read_resource(files,'review','references/guide.md')
            self.assertEqual(result['content'],'Useful detail');self.assertEqual(len(result['sha256']),64);self.assertFalse(files.observed)
            with self.assertRaises(ValueError):read_resource(files,'review','../../../../secret')

    def test_user_and_repository_skills_have_distinct_ids_and_confined_references(self):
        with tempfile.TemporaryDirectory() as project,tempfile.TemporaryDirectory() as user:
            for folder,text in ((project,'Project instructions'),(user,'User instructions')):
                skill=Path(folder)/'.agents/skills/review';skill.mkdir(parents=True)
                (skill/'SKILL.md').write_text('---\nname: review\ndescription: Review\n---\n'+text,encoding='utf-8')
                (skill/'ref.md').write_text(text,encoding='utf-8')
            files=ProjectFiles(project);items=list_skills(files,user_root=user)
            self.assertEqual([item['id'] for item in items],['review','user:review'])
            self.assertIn('User instructions',read_skill(files,'user:review',user_root=user)['instructions'])
            self.assertEqual(read_resource(files,'user:review','ref.md',user_root=user)['content'],'User instructions')
            with self.assertRaises(ValueError):read_resource(files,'user:review','../../outside',user_root=user)

    def test_multiline_frontmatter_and_duplicate_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            skill=Path(root)/'.agents/skills/review';skill.mkdir(parents=True)
            path=skill/'SKILL.md';path.write_text('---\nname: "review"\ndescription: >-\n  Review changed files.\n  Check their tests.\nmetadata:\n  owner: example\n---\nInstructions.',encoding='utf-8')
            items=list_skills(ProjectFiles(root),user_root=Path(root)/'empty')
            self.assertEqual(items[0]['description'],'Review changed files. Check their tests.')
            path.write_text('---\nname: review\nname: other\ndescription: duplicate\n---\nInstructions.',encoding='utf-8')
            self.assertFalse(list_skills(ProjectFiles(root),user_root=Path(root)/'empty'))

    def test_revision_event_and_session_validation(self):
        import hashlib
        from unittest.mock import patch
        from agentnik import core
        from agentnik.code_agent import CodingRun
        from agentnik.repositories import RepositoryRegistry
        from agentnik.storage import Store
        from agentnik.sessions import validate_session,SessionError
        from test_compat_tools import chat
        from test_routing import Wire
        with tempfile.TemporaryDirectory() as root:
            project=Path(root)/'project';skill=project/'.agents/skills/review';skill.mkdir(parents=True)
            text='---\nname: review\ndescription: Review\n---\nInstructions.';(skill/'SKILL.md').write_text(text,encoding='utf-8')
            events=[]
            with patch.object(core,'open_request',return_value=Wire(chat('Done'),False)):
                CodingRun({'url':'https://example.org/v1','model':'test','protocol':'chat','stream':False},project,'Review',skills=['review']).run(events.append)
            revision=next(event['skill'] for event in events if event['kind']=='skill_revision')
            self.assertEqual(revision['sha256'],hashlib.sha256((skill/'SKILL.md').read_bytes()).hexdigest())
            store=Store(Path(root)/'data')
            try:
                registry=RepositoryRegistry(store);session=registry.session(registry.put(project));session['coding_skill_revisions']=[revision]
                store.save(session);self.assertEqual(store.list_sessions()[0]['coding_skill_revisions'],[revision])
                session['coding_skill_revisions']=[dict(revision,sha256='bad')]
                with self.assertRaises(SessionError):validate_session(session)
            finally:store.db.close()
