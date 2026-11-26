import base64
import hashlib
import json
import socket
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from agentnik.mcp_oauth_signin import _callback_code, sign_in


class TerminalSignInTests(unittest.TestCase):
    issuer = "https://auth.example"
    resource = "https://mcp.example/api"

    def test_loopback_signin_binds_exchange_to_pkce_and_resource(self):
        for dynamic in (False, True):
            with self.subTest(dynamic=dynamic):
                self.check_signin(dynamic)

    def check_signin(self, dynamic):
        observed = {}
        metadata = {
            "issuer": self.issuer,
            "authorization_endpoint": self.issuer + "/authorize",
            "token_endpoint": self.issuer + "/token",
            "registration_endpoint": self.issuer + "/register",
            "pkce_s256": True,
            "public_client_supported": True,
            "authorization_response_iss_parameter_supported": True,
        }

        def present(url, port):
            observed.update(parse_qs(urlsplit(url).query))
            self.assertEqual(observed["redirect_uri"], [f"http://127.0.0.1:{port}/callback"])
            self.assertEqual(observed["code_challenge_method"], ["S256"])
            query = urlencode(dict(state=observed["state"][0], code="example-code", iss=self.issuer))
            with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
                client.sendall(f"GET /callback?{query} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())

        with patch("agentnik.mcp_oauth_signin.discover_authorization", return_value=metadata), patch(
            "agentnik.mcp_oauth_signin._read",
            side_effect=([b'{"client_id":"public-client","token_endpoint_auth_method":"none"}'] if dynamic else []) +
                        [b'{"access_token":"example-token","token_type":"Bearer","expires_in":3600}'],
        ) as exchange:
            sign_in(self.resource, "" if dynamic else "public-client", "read", present)
        self.assertEqual(exchange.call_count, 2 if dynamic else 1)
        if dynamic:
            registration = exchange.call_args_list[0]
            self.assertEqual(registration.args[1], metadata["registration_endpoint"])
            self.assertTrue(registration.kwargs["registration"])
            registration_body = json.loads(registration.args[2])
            self.assertEqual(registration_body["redirect_uris"], observed["redirect_uri"])
            self.assertEqual(registration_body["token_endpoint_auth_method"], "none")
        self.assertEqual(observed["client_id"], ["public-client"])
        _, endpoint, body, _ = exchange.call_args.args
        form = parse_qs(body.decode())
        self.assertEqual(endpoint, metadata["token_endpoint"])
        for field in ("client_id", "resource", "redirect_uri"):
            self.assertEqual(form[field], observed[field])
        self.assertEqual(form["code"], ["example-code"])
        digest = hashlib.sha256(form["code_verifier"][0].encode()).digest()
        self.assertEqual(observed["code_challenge"], [base64.urlsafe_b64encode(digest).decode().rstrip("=")])

    def test_callback_rejects_wrong_or_duplicate_state_and_unexpected_issuer(self):
        for query in ("state=wrong&code=x", "state=ok&state=ok&code=x", "state=ok&code=x",
                      "state=ok&code=x&iss=https://other.example"):
            with self.subTest(query=query):
                self.assertIsNone(_callback_code(f"GET /callback?{query} HTTP/1.1\r\n".encode(),
                                               "ok", self.issuer, True))
