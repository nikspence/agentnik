"""Application-wide TLS policy, configured once when the window starts."""
import ssl

_relaxed = False


def configure(relaxed):
    global _relaxed
    _relaxed = relaxed is True


def relaxed():
    return _relaxed


def context():
    result = ssl.create_default_context()
    if _relaxed:
        result.check_hostname = False
        result.verify_mode = ssl.CERT_NONE
    return result
