"""Local MCP HTTP fixtures with unambiguous connection lifetime."""
from http.server import BaseHTTPRequestHandler as _BaseHTTPRequestHandler, ThreadingHTTPServer


class BaseHTTPRequestHandler(_BaseHTTPRequestHandler):
    def end_headers(self):
        # HTTP/1.0 handlers close after each response. Make this explicit so
        # clients do not race a closing connection when issuing the next POST.
        self.send_header('Connection', 'close')
        super().end_headers()
