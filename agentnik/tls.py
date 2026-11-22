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


def configure_qt_request(request):
    """Enforce the TLS floor on Qt requests, preserving stricter defaults."""
    from PySide6.QtNetwork import QSsl
    config=request.sslConfiguration();protocol=config.protocol()
    if protocol not in (QSsl.SslProtocol.TlsV1_2,QSsl.SslProtocol.TlsV1_2OrLater,
                        QSsl.SslProtocol.TlsV1_3,QSsl.SslProtocol.TlsV1_3OrLater):
        config.setProtocol(QSsl.SslProtocol.TlsV1_2OrLater)
    request.setSslConfiguration(config)
