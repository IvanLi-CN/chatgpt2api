import unittest
from unittest import mock

import requests

from services.register.mail_provider import CloudflareTempMailProvider, KaisouMailProvider, YydsMailProvider


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


class YydsMailProviderTests(unittest.TestCase):
    def make_provider(self):
        return YydsMailProvider(
            {"api_base": "https://maliapi.example/v1", "api_key": "key", "domain": ["example.com"]},
            {"request_timeout": 1, "wait_timeout": 1, "wait_interval": 0.2, "user_agent": "ua"},
        )

    def test_create_mailbox_retries_transient_tls_failure(self):
        provider = self.make_provider()
        fake_session = FakeSession([
            requests.exceptions.SSLError("unexpected eof"),
            FakeResponse(data={"data": {"address": "name@example.com", "token": "mail-token"}}),
        ])
        provider.session = fake_session

        with mock.patch("services.register.mail_provider.time.sleep"):
            mailbox = provider.create_mailbox("name")

        self.assertEqual(mailbox["address"], "name@example.com")
        self.assertEqual(mailbox["token"], "mail-token")
        self.assertEqual(len(fake_session.calls), 2)

    def test_request_does_not_retry_bad_request(self):
        provider = self.make_provider()
        fake_session = FakeSession([FakeResponse(status_code=400, text="bad domain")])
        provider.session = fake_session

        with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
            provider.create_mailbox("name")

        self.assertEqual(len(fake_session.calls), 1)


class KaisouMailProviderTests(unittest.TestCase):
    def make_provider(self):
        return KaisouMailProvider(
            {"api_base": "https://km.example/", "api_key": "key"},
            {"request_timeout": 1, "wait_timeout": 1, "wait_interval": 0.2, "user_agent": "ua"},
        )

    def test_create_mailbox_sends_bearer_auth_and_records_mailbox(self):
        provider = self.make_provider()
        self.assertEqual(provider.session.headers["Authorization"], "Bearer key")
        fake_session = FakeSession([
            FakeResponse(data={
                "id": "mbx_1",
                "address": "name@desk.example.com",
                "createdAt": "2026-04-03T12:00:00.000Z",
                "mailDomain": "example.com",
            }),
        ])
        provider.session = fake_session

        mailbox = provider.create_mailbox("name")

        self.assertEqual(mailbox["address"], "name@desk.example.com")
        self.assertEqual(mailbox["mailbox_id"], "mbx_1")
        self.assertEqual(mailbox["created_at"], "2026-04-03T12:00:00.000Z")
        self.assertEqual(mailbox["domain"], "example.com")
        self.assertEqual(fake_session.calls[0][0], "POST")
        self.assertEqual(fake_session.calls[0][1], "https://km.example/api/mailboxes")
        self.assertEqual(fake_session.calls[0][2]["json"], {"localPart": "name", "expiresInMinutes": None})

    def test_wait_for_code_uses_message_verification_code(self):
        provider = self.make_provider()
        provider.session = FakeSession([
            FakeResponse(data={
                "messages": [
                    {
                        "id": "msg_1",
                        "subject": "Code",
                        "fromAddress": "noreply@example.com",
                        "receivedAt": "2026-04-03T12:01:00.000Z",
                        "verification": {"code": "842911", "source": "body", "method": "rules"},
                    }
                ]
            }),
        ])

        code = provider.wait_for_code({"address": "name@desk.example.com", "created_at": "2026-04-03T12:00:00.000Z"})

        self.assertEqual(code, "842911")
        self.assertEqual(provider.session.calls[0][0], "GET")
        self.assertEqual(provider.session.calls[0][1], "https://km.example/api/messages")
        self.assertEqual(provider.session.calls[0][2]["params"], {"mailbox": "name@desk.example.com", "since": "2026-04-03T12:00:00.000Z"})

    def test_wait_for_code_fetches_detail_when_list_has_no_verification(self):
        provider = self.make_provider()
        provider.session = FakeSession([
            FakeResponse(data={
                "messages": [
                    {
                        "id": "msg_1",
                        "subject": "OpenAI verification",
                        "fromAddress": "noreply@example.com",
                        "receivedAt": "2026-04-03T12:01:00.000Z",
                    }
                ]
            }),
            FakeResponse(data={
                "message": {
                    "id": "msg_1",
                    "subject": "OpenAI verification",
                    "text": "Your verification code is 923814",
                    "html": "<p>Your verification code is 923814</p>",
                    "receivedAt": "2026-04-03T12:01:00.000Z",
                }
            }),
        ])

        code = provider.wait_for_code({"address": "name@desk.example.com", "created_at": "2026-04-03T12:00:00.000Z"})

        self.assertEqual(code, "923814")
        self.assertEqual(provider.session.calls[1][0], "GET")
        self.assertEqual(provider.session.calls[1][1], "https://km.example/api/messages/msg_1")

    def test_request_does_not_retry_auth_failure(self):
        provider = self.make_provider()
        fake_session = FakeSession([FakeResponse(status_code=401, text="invalid key")])
        provider.session = fake_session

        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            provider.create_mailbox("name")

        self.assertEqual(len(fake_session.calls), 1)

    def test_request_retries_rate_limit(self):
        provider = self.make_provider()
        fake_session = FakeSession([
            FakeResponse(status_code=429, text="rate limited"),
            FakeResponse(data={"id": "mbx_1", "address": "name@example.com"}),
        ])
        provider.session = fake_session

        with mock.patch("services.register.mail_provider.time.sleep"):
            mailbox = provider.create_mailbox("name")

        self.assertEqual(mailbox["address"], "name@example.com")
        self.assertEqual(len(fake_session.calls), 2)


if __name__ == "__main__":
    unittest.main()
