import unittest
from unittest import mock

import requests

from services.register.mail_provider import CloudflareTempMailProvider


class FakeResponse:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.text = text

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def close(self):
        self.closed = True


class CloudflareTempMailProviderTests(unittest.TestCase):
    def make_provider(self):
        return CloudflareTempMailProvider(
            {"api_base": "https://mail.example", "admin_password": "pw", "domain": ["example.com"]},
            {"request_timeout": 1, "wait_timeout": 1, "wait_interval": 0.2, "user_agent": "ua"},
        )

    def test_create_mailbox_retries_transient_tls_failure(self):
        provider = self.make_provider()
        fake_session = FakeSession([
            requests.exceptions.SSLError("TLS connect error"),
            FakeResponse(data={"address": "name@example.com", "jwt": "jwt-token"}),
        ])
        provider.session = fake_session

        with mock.patch("services.register.mail_provider.time.sleep"):
            mailbox = provider.create_mailbox("name")

        self.assertEqual(mailbox["address"], "name@example.com")
        self.assertEqual(mailbox["token"], "jwt-token")
        self.assertEqual(len(fake_session.calls), 2)

    def test_request_does_not_retry_invalid_domain(self):
        provider = self.make_provider()
        fake_session = FakeSession([FakeResponse(status_code=400, text="Failed to create address: Invalid domain")])
        provider.session = fake_session

        with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
            provider.create_mailbox("name")

        self.assertEqual(len(fake_session.calls), 1)


if __name__ == "__main__":
    unittest.main()
