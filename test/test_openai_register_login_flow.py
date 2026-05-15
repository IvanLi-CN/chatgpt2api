import unittest
from unittest import mock

from services.register import openai_register


class FakeResponse:
    def __init__(self, *, url="", status_code=200, headers=None, history=None, json_data=None, text=""):
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
        self.history = history or []
        self._json_data = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json_data


class FakeSession:
    def __init__(self, authorize_response):
        self.authorize_response = authorize_response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method.upper(), url))
        if "/api/accounts/authorize" in url:
            return self.authorize_response
        if "/api/accounts/password/verify" in url:
            raise AssertionError("password verify should not be called when authorize already returned OAuth code")
        raise AssertionError(f"unexpected request {method} {url}")


class OpenAIRegisterLoginFlowTests(unittest.TestCase):
    def test_extract_oauth_callback_params_from_response_uses_redirect_history_location(self):
        response = FakeResponse(
            url="https://auth.openai.com/authorize/done",
            history=[
                FakeResponse(headers={"Location": "https://platform.openai.com/auth/callback?code=abc123&state=st&scope=openid"}),
            ],
        )

        params = openai_register.extract_oauth_callback_params_from_response(response)

        self.assertEqual(params, {"code": "abc123", "state": "st", "scope": "openid"})

    def test_login_exchange_uses_authorize_callback_without_password_verify(self):
        response = FakeResponse(url="https://platform.openai.com/auth/callback?code=abc123&state=st&scope=openid")
        session = FakeSession(response)
        registrar = openai_register.PlatformRegistrar.__new__(openai_register.PlatformRegistrar)
        registrar.session = session
        registrar.device_id = "device-1"
        expected_tokens = {"access_token": "access", "refresh_token": "refresh", "id_token": "id"}

        with (
            mock.patch.object(openai_register, "exchange_oauth_callback_params", return_value=expected_tokens, create=True) as exchange,
            mock.patch.object(openai_register, "build_sentinel_token", return_value="sentinel"),
            mock.patch.object(openai_register, "step"),
        ):
            tokens = registrar._login_and_exchange_tokens("user@example.com", "Password1!", {}, 1)

        self.assertEqual(tokens, expected_tokens)
        exchange.assert_called_once()
        self.assertFalse(any("/api/accounts/password/verify" in url for _, url in session.calls))

    def test_build_sentinel_token_retries_transient_ssl_failure(self):
        class SentinelResponse:
            status_code = 200

            def json(self):
                return {"token": "sentinel-token", "proofofwork": {"required": False}}

        class SentinelSession:
            def __init__(self):
                self.calls = 0

            def post(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise openai_register.requests.exceptions.SSLError("unexpected eof")
                return SentinelResponse()

        session = SentinelSession()

        with mock.patch.object(openai_register.SentinelTokenGenerator, "generate_requirements_token", return_value="req-token"):
            token = openai_register.build_sentinel_token(session, "device-1", "password_verify")

        self.assertIn("sentinel-token", token)
        self.assertEqual(session.calls, 2)


if __name__ == "__main__":
    unittest.main()
