"""Offline research-setting validation and credential-scope regression checks."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock,patch
from agentnik import core,research,routing
from agentnik.storage import Store,ConfigurationError
from agentnik.research_settings import invalidate_capabilities

C={'url':'https://gateway.example/v1','protocol':'chat','model':'mock','api_key':'test-secret'}


class ResearchSettings(unittest.TestCase):
    def test_invalid_nested_preferences_preserve_original(self):
        key=research.capability_key(C);default=routing.defaults_key('test',C)
        cases=[{'research_defaults':{default:[]}},
               {'research_defaults':{default:{'policy':'unexpected'}}},
               {'research_defaults':{default:{'access_policy':'unrestricted'}}},
               {'research_defaults':{'malformed':{}}},
               {'research_capabilities':{key:{'managed_tools':{'state':'invented'}}}},
               {'research_capabilities':{key:{'managed_tools':{'state':'verified','evidence':42}}}},
               {'research_capabilities':{key:{'managed_tools':{'state':'verified','unknown_field':'private'}}}},
               {'research_capabilities':{key:{'shell':{'state':'verified'}}}}]
        for data in cases:
            with self.subTest(data=data),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'connections.json';original=json.dumps(dict(connections={},**data));path.write_text(original)
                with self.assertRaises(ConfigurationError) as caught: Store(directory)
                self.assertEqual(path.read_text(),original);self.assertNotIn('private',str(caught.exception))

    def test_valid_research_settings_and_opaque_scopes_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            c=dict(C,_capability_scope='opaque-scope')
            for field in ('managed_tools','hosted_search'): research.set_capability(store.config,c,'configured','Explicitly enabled',field)
            routing.save_defaults(store.config,'test',c,'Agentnik only','strict_public')
            store.flush();store.db.close()
            store=Store(directory)
            try:
                self.assertEqual(research.capability(store.config,c).state,'configured')
                self.assertEqual(routing.connection_defaults(store.config,'test',c)['access_policy'],'strict_public')
            finally: store.db.close()

    def test_scope_isolated_and_invalidation_preserves_opt_in_only(self):
        config={};a=dict(C,_capability_scope='account-a');b=dict(C,_capability_scope='account-b')
        research.set_capability(config,a,'verified','Observed tools')
        research.set_capability(config,a,'unsupported','Rejected hosted','hosted_search')
        self.assertEqual(research.capability(config,b).state,'unknown')
        other=dict(C,url='https://other.example/v1')
        research.set_capability(config,other,'verified','Other endpoint')
        invalidate_capabilities(config,[a])
        self.assertEqual(research.capability(config,a).state,'configured')
        self.assertEqual(research.capability(config,a,'hosted_search').state,'unknown')
        self.assertEqual(research.capability(config,other).state,'verified')

    def test_rotation_new_account_and_failed_key_save(self):
        secrets={};fake=MagicMock()
        fake.set_password.side_effect=lambda service,ident,key: secrets.__setitem__((service,ident),key)
        fake.get_password.side_effect=lambda service,ident: secrets.get((service,ident))
        with tempfile.TemporaryDirectory() as directory,patch.dict('sys.modules',{'keyring':fake}):
            store=Store(directory)
            try:
                store.save_connection('A',C);a=store.connections()['A']
                research.set_capability(store.config,a,'verified','Observed tools')
                store.save_connection('A',C)
                self.assertEqual(store.connections()['A']['_capability_scope'],a['_capability_scope'])
                self.assertEqual(research.capability(store.config,a).state,'verified')
                fake.set_password.side_effect=RuntimeError('key store unavailable')
                before=copy.deepcopy(store.config)
                with self.assertRaises(RuntimeError): store.save_connection('A',dict(C,api_key='replacement-secret'))
                self.assertEqual(store.config,before)
                fake.set_password.side_effect=lambda service,ident,key: secrets.__setitem__((service,ident),key)
                store.save_connection('A',dict(C,api_key='replacement-secret'))
                rotated=store.connections()['A']
                self.assertNotEqual(rotated['_capability_scope'],a['_capability_scope'])
                self.assertEqual(research.capability(store.config,rotated).state,'unknown')
                self.assertNotIn('replacement-secret',store.config_path.read_text())
                store.save_connection('B',C)
                self.assertNotEqual(store.connections()['B']['_capability_scope'],rotated['_capability_scope'])
            finally: store.db.close()

    def test_legacy_credential_scopes_do_not_reuse_unbound_verification(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict('sys.modules',{'keyring':MagicMock()}):
            config={'connections':{'old':dict(C,api_key='')}}
            research.set_capability(config,C,'verified','Legacy unbound result')
            Path(directory,'connections.json').write_text(json.dumps(config))
            store=Store(directory)
            try:
                c=store.connections()['old'];self.assertEqual(research.capability(store.config,c).state,'unknown')
                self.assertEqual(c['_capability_scope'],store.connections()['old']['_capability_scope'])
                self.assertNotIn('_capability_scope',store.config['connections']['old'])
            finally: store.db.close()


class ScopeUI(unittest.TestCase):
    def test_environment_rotation_and_session_override_use_new_scopes(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        env={'env:test':dict(C)}
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',side_effect=lambda:copy.deepcopy(env)),patch.object(core,'models',return_value=[]):
            store=Store(directory);window=Window(store)
            try:
                first=window.connections['env:test'];research.set_capability(store.config,first,'verified','Observed')
                window.reload_connections();self.assertEqual(window.connections['env:test']['_capability_scope'],first['_capability_scope'])
                env['env:test']['api_key']='changed';window.reload_connections()
                second=window.connections['env:test'];self.assertNotEqual(second['_capability_scope'],first['_capability_scope'])
                self.assertEqual(research.capability(store.config,second).state,'unknown')
                window.new_session('chat','env:test');tab=window.tabs.currentWidget()
                tab.credentials['api_key']='session-only';override=tab.active_connection()
                self.assertNotEqual(override['_capability_scope'],second['_capability_scope'])
                self.assertEqual(override['_capability_scope'],tab.active_connection()['_capability_scope'])
                app.processEvents()
            finally: window.close();app.processEvents();store.db.close()


    def test_late_completion_cannot_verify_changed_credentials(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(directory);window=Window(store)
            try:
                store.config['connections']={'test':dict(C)}
                window.reload_connections()
                window.new_session('chat','test');tab=window.tabs.currentWidget();app.processEvents()
                tab.pending={'role':'user','text':'Test','images':[]}
                tab.research_connection=tab.active_connection()
                store.config['connections']['test']['api_key']='rotated-after-submission'
                window.reload_connections()
                result={'status':'ok','text':'Answer','thinking':'','metrics':{},'research':{
                    'version':2,'status':'completed','route':'managed','sources':[],'events':[],
                    'capability_updates':[{'field':'managed_tools','state':'verified','evidence':'Old request completed'}]}}
                with patch.object(core,'open_request') as outbound:
                    tab.complete_research(result);app.processEvents();outbound.assert_not_called()
                self.assertEqual(research.capability(store.config,tab.research_connection).state,'unknown')
                self.assertEqual(tab.session['messages'][-1]['text'],'Answer')
            finally: window.close();app.processEvents();store.db.close()


if __name__=='__main__': unittest.main()
