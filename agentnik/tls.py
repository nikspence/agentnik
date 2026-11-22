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
    # Keep a stricter system default, but never allow TLS versions before 1.2.
    if result.minimum_version < ssl.TLSVersion.TLSv1_2:
        result.minimum_version = ssl.TLSVersion.TLSv1_2
    if _relaxed:
        result.check_hostname = False
        result.verify_mode = ssl.CERT_NONE
    return result
