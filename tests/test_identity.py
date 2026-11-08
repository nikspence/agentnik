"""Application identity and independent storage contracts."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from agentnik.storage import Store, default_home


class Identity(unittest.TestCase):
    def test_platform_default_homes(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': '/local', 'XDG_DATA_HOME': '/xdg', 'USERPROFILE': '/user'}, clear=True):
            for platform, expected in [('win32', Path('/local/Agentnik')), ('darwin', Path.home()/'Library/Application Support/Agentnik'), ('linux', Path('/xdg/agentnik'))]:
                with self.subTest(platform=platform), patch('agentnik.storage.sys.platform', platform):
                    self.assertEqual(default_home(), expected)

    def test_home_override_and_explicit_directory_are_independent(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'AGENTNIK_HOME': str(Path(root)/'default')}):
            first=Store(); second=Store(Path(root)/'explicit')
            try:
                first.save(first.new_session('chat','test',{'url':'https://example.invalid/v1'}))
                self.assertEqual(first.root, Path(root)/'default')
                self.assertEqual(second.root, Path(root)/'explicit')
                self.assertEqual(second.list_sessions(), [])
            finally:
                first.db.close(); second.db.close()

    def test_credential_store_service_is_scoped(self):
        fake=MagicMock()
        with tempfile.TemporaryDirectory() as root, patch.dict('sys.modules', {'keyring':fake}):
            store=Store(root)
            try:
                store.save_connection('example', {'url':'https://example.invalid/v1','api_key':'test-value'})
                ident=store.config['connections']['example']['credential_id']
                fake.set_password.assert_called_once_with('Agentnik',ident,'test-value')
                store.connections()
                fake.get_password.assert_called_once_with('Agentnik',ident)
                store.delete_connection('example')
                fake.delete_password.assert_called_once_with('Agentnik',ident)
            finally:
                store.db.close()
