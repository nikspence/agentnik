"""Checks for the offline runner's network isolation."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class OfflineGuard(unittest.TestCase):
    def test_external_dns_and_unowned_loopback_are_blocked_but_fixtures_work(self):
        guard = Path(__file__).resolve().parents[1] / 'tools' / 'offline_guard'
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / 'audit.txt'
            env = dict(os.environ, AGENTNIK_OFFLINE_GUARD='1', AGENTNIK_OFFLINE_AUDIT=str(audit))
            env['PYTHONPATH'] = os.pathsep.join([str(guard), env.get('PYTHONPATH', '')])
            script = '''
import socket
for action in (lambda: socket.getaddrinfo('example.invalid', 80),
               lambda: socket.create_connection(('127.0.0.1', 1), timeout=.5),
               lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'x', ('192.0.2.1', 53))):
    try: action()
    except OSError as exc: assert 'Offline tests blocked' in str(exc)
    else: raise AssertionError('Network operation was not blocked')
server = socket.socket()
server.bind(('127.0.0.1', 0)); server.listen()
client = socket.create_connection(server.getsockname(), timeout=2)
connection, _ = server.accept()
connection.close(); client.close(); server.close()
'''
            result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(audit.read_text(encoding='utf-8').splitlines(), ['dns', 'connect', 'connect'])


if __name__ == '__main__':
    unittest.main()
