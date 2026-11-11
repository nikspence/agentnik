"""Offline TLS policy coverage; no external requests."""
import json
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.request import HTTPSHandler

from agentnik import core, tls, web
from agentnik.mcp_remote import RemoteProbe
from agentnik.storage import ConfigurationError, load_config


class TLSPolicy(unittest.TestCase):
    def tearDown(self):
        tls.configure(False)

    def test_model_transport_keeps_redirect_policy_and_opt_in_context(self):
        with patch.object(core.urllib.request, 'build_opener') as build:
            tls.configure(False)
            core.open_request({}, 'https://example.com')
            self.assertEqual(len(build.call_args.args), 1)
            self.assertIsInstance(build.call_args.args[0], core.NoRedirect)
            tls.configure(True)
            core.open_request({}, 'https://example.com')
            redirect, handler = build.call_args.args
            self.assertIsInstance(redirect, core.NoRedirect)
            self.assertIsInstance(handler, HTTPSHandler)
            self.assertEqual(handler._context.verify_mode, ssl.CERT_NONE)
            self.assertFalse(handler._context.check_hostname)

    def test_public_provider_transport_respects_global_setting(self):
        sock = MagicMock(); observed = []
        addresses = [(2, 1, 6, '', ('8.8.8.8', 443))]
        def wrap(context, socket, server_hostname=None):
            observed.append((context.verify_mode, context.check_hostname)); return MagicMock()
        with patch.object(web.socket, 'socket', return_value=sock), patch.object(ssl.SSLContext, 'wrap_socket', wrap):
            tls.configure(False); web.PinnedConnection('https://example.com', addresses, 5).connect()
            tls.configure(True); web.PinnedConnection('https://example.com', addresses, 5).connect()
        self.assertEqual(observed, [(ssl.CERT_REQUIRED, True), (ssl.CERT_NONE, False)])

    def test_remote_mcp_only_ignores_errors_when_enabled(self):
        probe = MagicMock(); reply = probe.reply
        tls.configure(False); RemoteProbe.configure_reply(probe)
        reply.sslErrors.connect.assert_not_called()
        tls.configure(True); RemoteProbe.configure_reply(probe)
        callback = reply.sslErrors.connect.call_args.args[0]
        callback([]); reply.ignoreSslErrors.assert_called_once_with()

    def test_setting_is_boolean_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'connections.json'
            path.write_text(json.dumps({'settings': {'relaxed_tls': True}}))
            self.assertTrue(load_config(path)['settings']['relaxed_tls'])
            path.write_text(json.dumps({'settings': {'relaxed_tls': 'true'}}))
            with self.assertRaises(ConfigurationError): load_config(path)
