"""Browser-based OAuth sign-in for terminal-only MCP clients."""

import base64
import hashlib
import hmac
import json
import secrets
import socket
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPSHandler, Request, build_opener

from . import tls
from .core import NoRedirect
from .mcp_oauth import (
    _MAX_RESPONSE, _endpoint, _object_pairs, authorization_server_metadata_urls,
    parse_public_registration, parse_token_response, protected_resource_metadata_urls,
    public_registration_body, valid_public_client_id,
)
from .mcp_oauth_metadata import MAX_METADATA, parse_authorization_metadata, parse_resource_metadata
from .mcp_oauth_record import make_record
from .tools import Limits, Runtime


def _read(runtime, url, body=None, max_bytes=MAX_METADATA, *, registration=False):
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json" if registration else "application/x-www-form-urlencoded"
    request = Request(url, data=body, headers=headers)
    opener = build_opener(NoRedirect(), HTTPSHandler(context=tls.context()))
    with opener.open(request, timeout=runtime.timeout()) as response:
        data = response.read(max_bytes + 1)
        if (len(data) > max_bytes or response.status not in ((200, 201) if registration else (200,))
                or response.headers.get_content_type() != "application/json"):
            raise ValueError("Invalid OAuth endpoint response")
        return data


def discover_authorization(resource):
    runtime = Runtime(limits=Limits(request_seconds=15, turn_seconds=15))

    def metadata(urls):
        for url in urls:
            try:
                return json.loads(_read(runtime, url), object_pairs_hook=_object_pairs)
            except HTTPError as exc:
                status = exc.code
                exc.close()
                if status not in (404, 405):
                    raise
        return None

    def discover():
        document = metadata(protected_resource_metadata_urls(resource))
        details = parse_resource_metadata(document, resource)
        for issuer in details["issuers"]:
            document = metadata(authorization_server_metadata_urls(issuer))
            if document is not None:
                return parse_authorization_metadata(document, issuer)
        raise ValueError("No OAuth issuer metadata was found")

    try:
        return runtime.wait(discover)
    except Exception:
        raise ValueError("Could not validate OAuth metadata for this MCP server.") from None
    finally:
        runtime.closed = True


def _callback_code(request, state, issuer, require_issuer):
    try:
        method, target, version = request.split(b"\r\n", 1)[0].decode("ascii").split()
        parts = urlsplit(target)
        if method != "GET" or version not in ("HTTP/1.0", "HTTP/1.1") or parts.path != "/callback":
            return None
        if parts.scheme or parts.netloc or parts.fragment:
            return None
        query = parse_qs(parts.query, keep_blank_values=True, max_num_fields=24)
        received = query.get("state", [])
        if len(received) != 1 or not received[0].isascii() or not hmac.compare_digest(received[0], state):
            return None
        received_issuer = query.get("iss", [])
        if (require_issuer or received_issuer) and received_issuer != [issuer]:
            return None
        codes = query.get("code", [])
        if "error" in query or len(codes) != 1 or not 0 < len(codes[0]) <= 4096:
            return None
        return codes[0] if all(33 <= ord(ch) <= 126 for ch in codes[0]) else None
    except (ValueError, UnicodeError):
        return None


def _wait_for_callback(listener, state, issuer, require_issuer):
    deadline = time.monotonic() + 180
    while (remaining := deadline - time.monotonic()) > 0:
        listener.settimeout(min(1, remaining))
        try:
            client, _ = listener.accept()
        except TimeoutError:
            continue
        with client:
            cutoff = min(deadline, time.monotonic() + 2)
            data = bytearray()
            try:
                while len(data) <= 8192 and b"\r\n\r\n" not in data and (remaining := cutoff - time.monotonic()) > 0:
                    client.settimeout(remaining)
                    chunk = client.recv(min(2048, 8193 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                code = (_callback_code(data, state, issuer, require_issuer)
                        if len(data) <= 8192 and b"\r\n\r\n" in data else None)
                status = b"200 OK" if code else b"400 Bad Request"
                text = b"Return to Agentnik to finish sign-in." if code else b"Invalid OAuth callback."
                client.settimeout(0.5)
                client.sendall(b"HTTP/1.1 " + status + b"\r\nContent-Type: text/plain\r\n"
                               b"Cache-Control: no-store\r\nConnection: close\r\n\r\n" + text)
            except OSError:
                continue
            if code:
                return code
    raise ValueError("OAuth sign-in timed out.")


def register_public_client(metadata, redirect):
    endpoint = metadata.get("registration_endpoint")
    if not endpoint:
        raise ValueError("This issuer requires a registered public OAuth client ID.")
    body = public_registration_body(redirect, metadata.get("refresh_grant_supported"))
    runtime = Runtime(limits=Limits(request_seconds=15, turn_seconds=15))
    try:
        url = _endpoint(endpoint).geturl()
        raw = runtime.wait(lambda: _read(runtime, url, body, _MAX_RESPONSE, registration=True))
        return parse_public_registration(raw, redirect)
    except Exception:
        raise ValueError("OAuth client registration did not finish safely. It was not retried.") from None
    finally:
        runtime.closed = True


def sign_in(resource, client_id, scope, present):
    if client_id != "" and not valid_public_client_id(client_id):
        raise ValueError("Enter the public OAuth client ID registered with this provider.")
    if len(scope) > 4096 or any(not 32 <= ord(ch) <= 126 or ch in '"\\' for ch in scope):
        raise ValueError("Invalid OAuth scopes.")
    metadata = discover_authorization(resource)
    if not metadata["pkce_s256"] or not metadata["public_client_supported"]:
        raise ValueError("The OAuth issuer does not advertise public clients with S256 PKCE.")
    authorization = _endpoint(metadata["authorization_endpoint"])
    token_endpoint = _endpoint(metadata["token_endpoint"]).geturl()
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    client_expiry = None
    with socket.create_server(("127.0.0.1", 0)) as listener:
        port = listener.getsockname()[1]
        redirect = f"http://127.0.0.1:{port}/callback"
        if not client_id:
            client_id, client_expiry = register_public_client(metadata, redirect)
        params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect, "state": state,
                  "code_challenge": challenge, "code_challenge_method": "S256", "resource": resource}
        if scope:
            params["scope"] = scope
        query = (authorization.query + "&" if authorization.query else "") + urlencode(params)
        url = urlunsplit((authorization.scheme, authorization.netloc, authorization.path, query, ""))
        present(url, port)
        code = _wait_for_callback(listener, state, metadata["issuer"],
                                  metadata["authorization_response_iss_parameter_supported"])
    form = urlencode({"grant_type": "authorization_code", "client_id": client_id, "redirect_uri": redirect,
                      "code": code, "code_verifier": verifier, "resource": resource}).encode("ascii")
    runtime = Runtime(limits=Limits(request_seconds=15, turn_seconds=15))
    try:
        raw = runtime.wait(lambda: _read(runtime, token_endpoint, form, _MAX_RESPONSE))
        result = parse_token_response(raw, 200, "application/json")
        return make_record(resource, metadata["issuer"], token_endpoint, client_id, result,
                           client_id_expires_at=client_expiry)
    except Exception:
        raise ValueError("OAuth token exchange did not finish safely. It was not retried.") from None
    finally:
        runtime.closed = True
