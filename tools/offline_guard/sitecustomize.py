"""Network guard loaded only by the offline test runner, including Python children."""
import ipaddress
import os
import socket
import sys
import threading

if os.environ.get('AGENTNIK_OFFLINE_GUARD') == '1':
    _allowed = set()
    _lock = threading.Lock()
    _bind = socket.socket.bind
    _close = socket.socket.close
    _bound = {}

    def _loopback(address):
        try:
            return ipaddress.ip_address(address).is_loopback
        except (ValueError, TypeError):
            return False

    def _record_bind(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address[0]):
            _reject('bind')
        result = _bind(sock, address)
        if sock.family in (socket.AF_INET, socket.AF_INET6) and _loopback(address[0]):
            bound = sock.getsockname()
            with _lock:
                key = (str(ipaddress.ip_address(bound[0])), bound[1])
                _allowed.add(key)
                _bound[sock] = key
        return result

    def _record_close(sock):
        with _lock:
            key = _bound.pop(sock, None)
            if key is not None:
                _allowed.discard(key)
        return _close(sock)

    socket.socket.bind = _record_bind
    socket.socket.close = _record_close

    def _reject(kind):
        # Never write addresses, credentials, or request data to CI logs.
        with open(os.environ['AGENTNIK_OFFLINE_AUDIT'], 'a', encoding='utf-8') as log:
            log.write(kind + '\n')
        raise OSError('Offline tests blocked an unexpected network operation')

    def _audit(event, args):
        if event == 'socket.getaddrinfo':
            host = args[0]
            if host not in (None, 'localhost', b'localhost') and not _loopback(host):
                _reject('dns')
        elif event in ('socket.gethostbyname', 'socket.gethostbyaddr'):
            host = args[0]
            if host not in ('localhost', b'localhost') and not _loopback(host):
                _reject('dns')
        elif event in ('socket.connect', 'socket.sendto'):
            sock, address = args
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                try:
                    key = (str(ipaddress.ip_address(address[0])), address[1])
                except (ValueError, TypeError, IndexError):
                    _reject('connect')
                with _lock:
                    permitted = key in _allowed
                if not permitted:
                    _reject('connect')

    sys.addaudithook(_audit)
