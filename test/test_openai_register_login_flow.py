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
        self.calls.append((method.upper(), url, kwargs))
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
        self.assertFalse(any("/api/accounts/password/verify" in url for _, url, _ in session.calls))

    def test_login_authorize_does_not_follow_platform_callback_redirect(self):
        response = FakeResponse(headers={"Location": "https://platform.openai.com/auth/callback?code=abc123&state=st&scope=openid"}, status_code=302)
        session = FakeSession(response)
        registrar = openai_register.PlatformRegistrar.__new__(openai_register.PlatformRegistrar)
        registrar.session = session
        registrar.device_id = "device-1"
        expected_tokens = {"access_token": "access", "refresh_token": "refresh", "id_token": "id"}

        with (
            mock.patch.object(openai_register, "exchange_oauth_callback_params", return_value=expected_tokens, create=True),
            mock.patch.object(openai_register, "build_sentinel_token", return_value="sentinel"),
            mock.patch.object(openai_register, "step"),
        ):
            tokens = registrar._login_and_exchange_tokens("user@example.com", "Password1!", {}, 1)

        self.assertEqual(tokens, expected_tokens)
        authorize_calls = [call for call in session.calls if "/api/accounts/authorize" in call[1]]
        self.assertEqual(len(authorize_calls), 1)
        self.assertFalse(authorize_calls[0][2]["allow_redirects"])

    def test_platform_authorize_does_not_follow_platform_callback_redirect(self):
        response = FakeResponse(headers={"Location": "https://platform.openai.com/auth/callback?code=abc123&state=st&scope=openid"}, status_code=302)
        session = FakeSession(response)
        session.cookies = mock.Mock()
        registrar = openai_register.PlatformRegistrar.__new__(openai_register.PlatformRegistrar)
        registrar.session = session
        registrar.device_id = "device-1"

        with mock.patch.object(openai_register, "step"):
            registrar._platform_authorize("user@example.com", 1)

        authorize_calls = [call for call in session.calls if "/api/accounts/authorize" in call[1]]
        self.assertEqual(len(authorize_calls), 1)
        self.assertFalse(authorize_calls[0][2]["allow_redirects"])

    def test_consent_session_returns_callback_url_without_fetching_platform(self):
        class NoNetworkSession:
            def get(self, *args, **kwargs):
                raise AssertionError("callback URL should be parsed, not fetched")

        params = openai_register.extract_oauth_callback_params_from_consent_session(
            NoNetworkSession(),
            "https://platform.openai.com/auth/callback?code=abc123&state=st&scope=openid",
            "device-1",
        )

        self.assertEqual(params, {"code": "abc123", "state": "st", "scope": "openid"})

    def test_consent_session_retries_transient_navigation_failure(self):
        class ConsentSession:
            def __init__(self):
                self.calls = 0

            def request(self, method, url, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise openai_register.requests.exceptions.ProxyError("proxy closed")
                return FakeResponse(
                    status_code=302,
                    headers={"Location": "https://platform.openai.com/auth/callback?code=abc123&state=st&scope=openid"},
                    url=url,
                )

        session = ConsentSession()

        with mock.patch.object(openai_register.time, "sleep"):
            params = openai_register.extract_oauth_callback_params_from_consent_session(session, "https://auth.openai.com/consent", "device-1")

        self.assertEqual(params, {"code": "abc123", "state": "st", "scope": "openid"})
        self.assertEqual(session.calls, 2)

    def test_exchange_oauth_callback_params_retries_transient_token_failure(self):
        class TokenSession:
            def __init__(self):
                self.calls = 0

            def request(self, method, url, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise openai_register.requests.exceptions.SSLError("unexpected eof")
                return FakeResponse(
                    status_code=200,
                    json_data={
                        "access_token": "header.eyJlbWFpbCI6InVzZXJAZXhhbXBsZS5jb20ifQ.sig",
                        "refresh_token": "refresh",
                        "id_token": "header.eyJlbWFpbCI6InVzZXJAZXhhbXBsZS5jb20ifQ.sig",
                    },
                )

            def close(self):
                pass

        session = TokenSession()

        with (
            mock.patch.object(openai_register, "create_session", return_value=session),
            mock.patch.object(openai_register.time, "sleep"),
        ):
            tokens = openai_register.exchange_oauth_callback_params("verifier", {"code": "abc123"})

        self.assertEqual(tokens["email"], "user@example.com")
        self.assertEqual(session.calls, 2)

    def test_request_with_local_retry_retries_transient_http_status(self):
        class RetrySession:
            def __init__(self):
                self.calls = 0

            def request(self, method, url, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponse(status_code=502, text="bad gateway")
                return FakeResponse(status_code=200)

        session = RetrySession()

        with mock.patch.object(openai_register.time, "sleep"):
            resp, error = openai_register.request_with_local_retry(session, "get", "https://auth.openai.com/x", retry_statuses=(502,))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(error, "")
        self.assertEqual(session.calls, 2)

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
