"""Explicit one-shot OAuth renewal for terminal MCP profiles."""

from urllib.parse import urlencode
from urllib.request import HTTPSHandler, Request, build_opener

from . import tls
from .core import NoRedirect
from .mcp_oauth import _MAX_RESPONSE, parse_token_response
from .mcp_oauth_record import credential_state, make_record, oauth_refresh_lease, read_record, write_record
from .mcp_support import server_timeout
from .tools import Limits, Runtime


def renew_mcp_credential(server, confirm):
    ident, resource = server["credential_id"], server["url"]
    with oauth_refresh_lease(ident):
        try:
            record = read_record(ident, resource)
        except Exception:
            raise ValueError("OAuth sign-in is unavailable. Sign in again in desktop settings.") from None
        state = credential_state(record)
        if state == "ready":
            return "OAuth sign-in is still active. No request was made."
        if state != "refresh":
            raise ValueError("The OAuth sign-in cannot be renewed. Sign in again in desktop settings.")
        if not confirm(record["token_endpoint"]):
            return "OAuth renewal cancelled. No request was made."
        marked = dict(record, refresh_pending=True)
        try:
            if read_record(ident, resource) != record:
                raise ValueError("OAuth credential changed")
            write_record(ident, marked)
        except Exception:
            raise ValueError("Could not prepare the OAuth credential. No request was made.") from None
        seconds = min(server_timeout(server), 30)
        runtime = Runtime(limits=Limits(request_seconds=seconds, turn_seconds=seconds))

        def exchange():
            body = urlencode({
                "grant_type": "refresh_token", "client_id": record["client_id"],
                "refresh_token": record["refresh_token"], "resource": resource,
            }).encode("ascii")
            request = Request(record["token_endpoint"], data=body,
                              headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
            opener = build_opener(NoRedirect(), HTTPSHandler(context=tls.context()))
            with opener.open(request, timeout=runtime.timeout()) as response:
                raw = response.read(_MAX_RESPONSE + 1)
                if len(raw) > _MAX_RESPONSE:
                    raise ValueError("OAuth response too large")
                return parse_token_response(raw, response.status, response.headers.get_content_type())

        try:
            result = runtime.wait(exchange)
            updated = make_record(resource, record["issuer"], record["token_endpoint"], record["client_id"], result,
                                  previous_refresh=record["refresh_token"],
                                  client_id_expires_at=record.get("client_id_expires_at"))
            if read_record(ident, resource) != marked:
                raise ValueError("OAuth credential changed")
            write_record(ident, updated)
        except Exception:
            raise ValueError("OAuth renewal did not finish safely. Sign in again. The request was not retried.") from None
        finally:
            runtime.closed = True
        return "Renewed MCP OAuth sign-in."
