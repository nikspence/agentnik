"""Offline tests for the shared TLS context factory."""
import ssl
import unittest
from unittest.mock import MagicMock, patch

from agentnik import tls


class TLSContextTests(unittest.TestCase):
    def tearDown(self):
        tls.configure(False)

    def test_qt_request_requires_tls_1_2_and_preserves_stricter_defaults(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtNetwork import QNetworkRequest,QSsl
        for relaxed in (False,True):
            tls.configure(relaxed)
            for initial,expected in ((QSsl.SslProtocol.AnyProtocol,QSsl.SslProtocol.TlsV1_2OrLater),
                                     (QSsl.SslProtocol.TlsV1_1OrLater,QSsl.SslProtocol.TlsV1_2OrLater),
                                     (QSsl.SslProtocol.TlsV1_2,QSsl.SslProtocol.TlsV1_2),
                                     (QSsl.SslProtocol.TlsV1_3OrLater,QSsl.SslProtocol.TlsV1_3OrLater)):
                with self.subTest(relaxed=relaxed,initial=initial):
                    request=QNetworkRequest(QUrl('https://example.org/mcp'));config=request.sslConfiguration();config.setProtocol(initial);request.setSslConfiguration(config)
                    tls.configure_qt_request(request)
                    self.assertEqual(request.sslConfiguration().protocol(),expected)

    def test_context_requires_tls_1_2_even_when_verification_is_relaxed(self):
        for relaxed in (False, True):
            with self.subTest(relaxed=relaxed):
                tls.configure(relaxed)
                context = tls.context()
                self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
                self.assertEqual(context.verify_mode, ssl.CERT_NONE if relaxed else ssl.CERT_REQUIRED)
                self.assertEqual(context.check_hostname, not relaxed)

    def test_context_enforces_minimum_without_weakening_stricter_defaults(self):
        for initial, expected in (
            (ssl.TLSVersion.MINIMUM_SUPPORTED, ssl.TLSVersion.TLSv1_2),
            (ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_2),
            (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_2),
            (ssl.TLSVersion.TLSv1_3, ssl.TLSVersion.TLSv1_3),
        ):
            with self.subTest(initial=initial):
                mock_context = MagicMock(minimum_version=initial)
                with patch.object(ssl, 'create_default_context', return_value=mock_context):
                    self.assertIs(tls.context(), mock_context)
                self.assertEqual(mock_context.minimum_version, expected)
