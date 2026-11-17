"""Offline credential-store scoping and explicit token operations."""
import unittest
from unittest.mock import patch
from agentnik.git_credentials import credential_key,save_token,load_token,delete_token,SERVICE


class GitCredentialTests(unittest.TestCase):
    def test_exact_destination_and_username_scope(self):
        first=credential_key('https://example.invalid/one.git','user')
        self.assertEqual(first,credential_key('https://example.invalid/one.git','user'))
        self.assertNotEqual(first,credential_key('https://example.invalid/two.git','user'))
        self.assertNotEqual(first,credential_key('https://example.invalid/one.git','other'))
        self.assertNotIn('example.invalid',first);self.assertNotIn('user',first)
        for url in ('http://example.invalid/one','https://user:token@example.invalid/one','https://example.invalid/one?token=x'):
            with self.subTest(url=url),self.assertRaises(ValueError):credential_key(url,'user')

    def test_only_explicit_calls_access_credential_store(self):
        url='https://example.invalid/repo';username='user';token='secret-token';key=credential_key(url,username)
        with patch('keyring.set_password') as put,patch('keyring.get_password',return_value=token) as get,patch('keyring.delete_password') as delete:
            save_token(url,username,token);put.assert_called_once_with(SERVICE,key,token)
            self.assertEqual(load_token(url,username),token);get.assert_called_once_with(SERVICE,key)
            delete_token(url,username);delete.assert_called_once_with(SERVICE,key)
        with patch('keyring.set_password') as put:
            with self.assertRaises(ValueError):save_token(url,username,'bad\ntoken')
            put.assert_not_called()
