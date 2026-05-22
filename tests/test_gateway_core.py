import unittest
from unittest import mock
from pathlib import Path
import asyncio
import json


def test_file(name: str) -> Path:
    return Path(__file__).with_name(name)


class GatewayCoreTests(unittest.TestCase):
    def test_extract_bearer_token(self):
        from app.auth import extract_bearer_token

        self.assertEqual(extract_bearer_token("Bearer abc123"), "abc123")
        self.assertIsNone(extract_bearer_token("Basic abc123"))
        self.assertIsNone(extract_bearer_token(None))

    def test_verify_admin_key_prefers_admin_key(self):
        from fastapi import HTTPException
        from app.auth import verify_admin_key
        from app.config import _ENV_CACHE

        with mock.patch.dict(
            "os.environ",
            {"ADMIN_KEY": "admin-secret", "OPENAI_API_KEY": "gateway-secret"},
            clear=False,
        ):
            import app.config as config

            config._ENV_CACHE = {}
            asyncio.run(verify_admin_key("Bearer admin-secret"))
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(verify_admin_key("Bearer gateway-secret"))
            config._ENV_CACHE = _ENV_CACHE

        self.assertEqual(ctx.exception.status_code, 403)

    def test_verify_admin_key_falls_back_to_openai_api_key(self):
        from app.auth import verify_admin_key
        from app.config import _ENV_CACHE

        with mock.patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "gateway-secret"},
            clear=False,
        ):
            import app.config as config

            config._ENV_CACHE = {}
            with mock.patch.dict("os.environ", {"ADMIN_KEY": ""}, clear=False):
                asyncio.run(verify_admin_key("Bearer gateway-secret"))
            config._ENV_CACHE = _ENV_CACHE

    def test_chat_messages_to_responses_input(self):
        from app.adapters.chat_completions import (
            chat_messages_to_responses_input,
        )

        messages = [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Hello"},
        ]
        mapped = chat_messages_to_responses_input(messages)
        self.assertEqual(mapped[0]["role"], "system")
        self.assertEqual(mapped[1]["content"][0]["type"], "input_text")
        self.assertEqual(mapped[1]["content"][0]["text"], "Hello")

    def test_chat_stream_to_done(self):
        from app.adapters.sse import responses_stream_to_chat_stream

        upstream_lines = [
            "event: response.output_text.delta",
            'data: {"delta":"Hi"}',
            "",
            "event: response.completed",
            'data: {"response":{"id":"resp_1","model":"grok-4.3","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Hi"}]}]}}',
            "",
        ]
        out = list(responses_stream_to_chat_stream(upstream_lines, model="grok-4.3"))
        self.assertTrue(any("chat.completion.chunk" in line for line in out))
        self.assertEqual(out[-1], "data: [DONE]\n\n")

    def test_chat_error_stream_is_openai_chunk(self):
        from app.adapters.sse import chat_error_stream

        out = list(chat_error_stream("timeout", model="grok-4.3"))
        self.assertEqual(out[0], "event: error\n")
        self.assertIn('"message": "timeout"', out[1])
        self.assertIn('"type": "upstream_error"', out[1])
        self.assertEqual(out[-1], "data: [DONE]\n\n")

    def test_error_body_uses_openai_shape(self):
        from app.errors import error_body

        body = error_body(
            "bad value",
            error_type="invalid_request_error",
            code="invalid_value",
            param="model",
        )

        self.assertEqual(
            body,
            {
                "error": {
                    "message": "bad value",
                    "type": "invalid_request_error",
                    "code": "invalid_value",
                    "param": "model",
                }
            },
        )

    def test_sse_error_stream_emits_error_event_and_done(self):
        from app.adapters.sse import sse_error_stream

        out = list(sse_error_stream("boom", error_type="server_error"))

        self.assertEqual(out[0], "event: error\n")
        self.assertIn('"message": "boom"', out[1])
        self.assertIn('"type": "server_error"', out[1])
        self.assertEqual(out[-1], "data: [DONE]\n\n")

    def test_http_exception_handler_uses_openai_error_shape(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.config import _ENV_CACHE

        try:
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False):
                import app.config as config

                config._ENV_CACHE = None
                response = TestClient(app).get("/v1/models")
        finally:
            config._ENV_CACHE = _ENV_CACHE

        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())
        self.assertEqual(response.json()["error"]["type"], "invalid_request_error")

    def test_responses_payload_includes_har_default_tools(self):
        from app.adapters.responses import build_responses_payload

        payload = build_responses_payload(
            model="grok-4.3",
            input_val="hello",
            instructions=None,
            stream=True,
            temperature=0.7,
            top_p=0.95,
            max_output_tokens=None,
            tools=None,
            tool_choice=None,
        )
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertFalse(payload["store"])
        self.assertIn("reasoning.encrypted_content", payload["include"])
        self.assertEqual(payload["tools"][0]["type"], "web_search")
        self.assertEqual(payload["tools"][1]["type"], "x_search")
        self.assertTrue(payload["tools"][0]["enable_image_understanding"])
        self.assertTrue(payload["tools"][1]["enable_video_understanding"])
        self.assertEqual(payload["max_output_tokens"], 1000000)

    def test_chat_image_url_maps_to_responses_input_image(self):
        from app.adapters.chat_completions import chat_messages_to_responses_input

        mapped = chat_messages_to_responses_input([
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is in this image?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
                ],
            }
        ])

        self.assertEqual(
            mapped[0]["content"],
            [
                {"type": "input_text", "text": "what is in this image?"},
                {"type": "input_image", "image_url": "data:image/png;base64,AAA"},
            ],
        )

    def test_responses_payload_preserves_user_tools_and_tool_choice(self):
        from app.adapters.responses import build_responses_payload

        tools = [
            {
                "type": "function",
                "name": "lookup_order",
                "description": "Lookup an order",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
        tool_choice = {"type": "function", "name": "lookup_order"}

        payload = build_responses_payload(
            model="grok-4.3",
            input_val="hello",
            instructions=None,
            stream=False,
            temperature=None,
            top_p=None,
            max_output_tokens=None,
            tools=tools,
            tool_choice=tool_choice,
        )

        self.assertIs(payload["tools"], tools)
        self.assertIs(payload["tool_choice"], tool_choice)
        self.assertNotIn("enable_image_understanding", tools[0])

    def test_responses_payload_preserves_reasoning_effort(self):
        from app.adapters.responses import build_responses_payload

        payload = build_responses_payload(
            model="grok-4.3",
            input_val="hello",
            instructions=None,
            stream=False,
            temperature=None,
            top_p=None,
            max_output_tokens=None,
            tools=None,
            tool_choice=None,
            reasoning={"effort": "high"},
        )

        self.assertEqual(payload["reasoning"], {"effort": "high"})

    def test_chat_request_accepts_reasoning_effort(self):
        from app.openai.routes import ChatCompletionRequest

        req = ChatCompletionRequest(
            model="grok-4.3",
            messages=[{"role": "user", "content": "hello"}],
            reasoning_effort="xhigh",
        )

        self.assertEqual(req.reasoning_effort, "xhigh")

    def test_default_models_include_har2_and_voice_models(self):
        from app.config import DEFAULT_MODELS

        self.assertIn("grok-build-0.1", DEFAULT_MODELS)
        self.assertIn("grok-voice-think-fast-1.0", DEFAULT_MODELS)

    def test_account_pool_loads_sso_only_accounts(self):
        from app.accounts import AccountPool

        path = test_file("tmp_sso_accounts.json")
        try:
            path.write_text('[{"name":"a","sso":"sso-a"},{"name":"b","sso":"sso=b"}]', encoding="utf-8")
            pool = AccountPool.from_file(str(path), fallback_sso="fallback")
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual([a.name for a in pool.accounts], ["a", "b"])
        self.assertEqual(pool.accounts[0].cookie_header, "sso=sso-a; sso-rw=sso-a")
        self.assertEqual(pool.accounts[1].cookie_header, "sso=b; sso-rw=b")

    def test_account_pool_loads_sqlite_accounts(self):
        from app.accounts import AccountPool, write_account_records

        path = test_file("tmp_sso_accounts.sqlite3")
        try:
            write_account_records(
                str(path),
                [
                    {"name": "1", "sso": "sso-a", "team_id": "team-a", "status": "active"},
                    {"name": "2", "sso": "sso=b", "team_id": "team-b", "status": "active"},
                ],
            )
            pool = AccountPool.from_file(str(path), fallback_sso="")
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual([a.name for a in pool.accounts], ["1", "2"])
        self.assertEqual(pool.accounts[0].cookie_header, "sso=sso-a; sso-rw=sso-a; last-team-id=team-a")
        self.assertEqual(pool.accounts[1].cookie_header, "sso=b; sso-rw=b; last-team-id=team-b")

    def test_account_pool_migrates_legacy_json_next_to_sqlite(self):
        from app.accounts import AccountPool, load_account_records

        db_path = test_file("tmp_migrate_accounts.sqlite3")
        json_path = db_path.with_suffix(".json")
        try:
            json_path.write_text('[{"name":"1","sso":"legacy","team_id":"team-a"}]', encoding="utf-8")
            pool = AccountPool.from_file(str(db_path), fallback_sso="")
            saved = load_account_records(str(db_path))
        finally:
            db_path.unlink(missing_ok=True)
            json_path.unlink(missing_ok=True)

        self.assertEqual(pool.accounts[0].sso, "legacy")
        self.assertEqual(saved[0]["sso"], "legacy")

    def test_account_pool_round_robin_and_fallback(self):
        from app.accounts import AccountPool

        pool = AccountPool.from_file("missing.json", fallback_sso="fallback")
        self.assertEqual(pool.next_account().name, "env")
        self.assertEqual(pool.next_account().name, "env")

    def test_account_pool_skips_non_selectable_accounts(self):
        from app.accounts import AccountPool

        path = test_file("tmp_status_accounts.json")
        try:
            path.write_text(
                "["
                '{"name":"disabled","sso":"a","status":"disabled"},'
                '{"name":"cooling","sso":"b","status":"cooling"},'
                '{"name":"invalid","sso":"c","status":"invalid"},'
                '{"name":"active","sso":"d","status":"active"}'
                "]",
                encoding="utf-8",
            )
            pool = AccountPool.from_file(str(path), fallback_sso="")
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(pool.next_account().name, "active")
        self.assertEqual(pool.next_account().name, "active")

    def test_account_pool_raises_when_all_accounts_are_non_selectable(self):
        from app.accounts import AccountPool

        path = test_file("tmp_no_selectable_accounts.json")
        try:
            path.write_text(
                '[{"name":"disabled","sso":"a","status":"disabled"}]',
                encoding="utf-8",
            )
            pool = AccountPool.from_file(str(path), fallback_sso="")
        finally:
            path.unlink(missing_ok=True)

        with self.assertRaisesRegex(RuntimeError, "No selectable upstream SSO accounts configured"):
            pool.next_account()

    def test_record_account_success_marks_active_and_clears_error(self):
        from app.accounts import Account, record_account_result

        path = test_file("tmp_account_success.json")
        try:
            path.write_text(
                '[{"name":"a","sso":"token","team_id":"team-1","status":"failed","last_error":"old","use_count":1}]',
                encoding="utf-8",
            )
            record_account_result(
                str(path),
                Account(name="a", sso="token", team_id="team-1"),
                status_code=200,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(saved[0]["status"], "active")
        self.assertEqual(saved[0]["last_error"], "")
        self.assertEqual(saved[0]["use_count"], 2)
        self.assertGreater(saved[0]["last_checked_at"], 0)

    def test_record_account_success_updates_sqlite(self):
        from app.accounts import Account, load_account_events, load_account_records, record_account_result, write_account_records

        path = test_file("tmp_account_success.sqlite3")
        try:
            write_account_records(
                str(path),
                [{"name": "1", "sso": "token", "team_id": "team-1", "status": "failed", "last_error": "old", "use_count": 1}],
            )
            record_account_result(
                str(path),
                Account(name="1", sso="token", team_id="team-1"),
                status_code=200,
            )
            saved = load_account_records(str(path))
            events = load_account_events(str(path))
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(saved[0]["status"], "active")
        self.assertEqual(saved[0]["last_error"], "")
        self.assertEqual(saved[0]["use_count"], 2)
        self.assertGreater(saved[0]["last_checked_at"], 0)
        self.assertEqual(events[-1]["status"], "active")
        self.assertEqual(events[-1]["status_code"], 200)

    def test_record_account_failure_maps_status_and_increments_fail_count(self):
        from app.accounts import Account, record_account_result

        path = test_file("tmp_account_failure.json")
        try:
            path.write_text(
                '[{"name":"a","sso":"token","team_id":"team-1","status":"active","fail_count":2}]',
                encoding="utf-8",
            )
            record_account_result(
                str(path),
                Account(name="a", sso="token", team_id="team-1"),
                status_code=429,
                error="rate limited",
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(saved[0]["status"], "cooling")
        self.assertEqual(saved[0]["last_error"], "rate limited")
        self.assertEqual(saved[0]["fail_count"], 3)

    def test_record_account_failure_matches_sso_with_prefix(self):
        from app.accounts import Account, record_account_result

        path = test_file("tmp_account_prefix.json")
        try:
            path.write_text(
                '[{"name":"a","sso":"sso=token","team_id":"team-1","status":"active"}]',
                encoding="utf-8",
            )
            record_account_result(
                str(path),
                Account(name="a", sso="token", team_id="team-1"),
                status_code=403,
                error="forbidden",
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(saved[0]["status"], "invalid")
        self.assertEqual(saved[0]["last_error"], "forbidden")

    def test_account_pool_prefers_imported_accounts_over_env_fallback(self):
        from app.accounts import AccountPool

        path = test_file("tmp_imported_accounts.json")
        try:
            path.write_text('[{"name":"imported","sso":"imported-token"}]', encoding="utf-8")
            pool = AccountPool.from_file(str(path), fallback_sso="env-token")
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(len(pool.accounts), 1)
        self.assertEqual(pool.next_account().name, "imported")
        self.assertEqual(pool.next_account().cookie_header, "sso=imported-token; sso-rw=imported-token")

    def test_account_pool_loads_team_metadata(self):
        from app.accounts import AccountPool

        path = Path(__file__).with_name("tmp_accounts_metadata.json")
        try:
            path.write_text(
                '[{"name":"a","sso":"token","team_id":"team-1","referer":"https://console.x.ai/team/team-1/chat-playground","status":"ok"}]',
                encoding="utf-8",
            )
            account = AccountPool.from_file(str(path), fallback_sso="").next_account()
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(account.team_id, "team-1")
        self.assertEqual(account.referer, "https://console.x.ai/team/team-1/chat-playground")
        self.assertEqual(account.status, "ok")

    def test_account_pool_generates_referer_from_team_id(self):
        from app.accounts import AccountPool

        path = Path(__file__).with_name("tmp_accounts_team_id.json")
        try:
            path.write_text(
                '[{"name":"a","sso":"token","team_id":"team-1"}]',
                encoding="utf-8",
            )
            account = AccountPool.from_file(str(path), fallback_sso="").next_account()
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(account.team_id, "team-1")
        self.assertEqual(account.referer, "https://console.x.ai/team/team-1/chat-playground")

    def test_account_cookie_header_includes_account_team_id(self):
        from app.accounts import Account

        account = Account(name="a", sso="token", team_id="team-1")

        self.assertEqual(
            account.cookie_header,
            "sso=token; sso-rw=token; last-team-id=team-1",
        )

    def test_settings_auth_accepts_accounts_file(self):
        from app.config import Settings

        path = test_file("tmp_auth_accounts.json")
        try:
            path.write_text('[{"name":"a","sso":"abc123"}]', encoding="utf-8")
            s = Settings(
                host="0.0.0.0",
                port=8787,
                openai_api_key="k",
                upstream_url="https://console.x.ai/v1/responses",
                upstream_cookie="",
                upstream_sso="",
                upstream_cluster="https://us-east-1.api.x.ai",
                upstream_referer="https://console.x.ai/team/x/chat-playground",
                upstream_origin="https://console.x.ai",
                upstream_user_agent="ua",
                upstream_proxy="",
                upstream_impersonate="chrome136",
                upstream_skip_ssl_verify=False,
                upstream_cf_cookies="",
                upstream_cf_clearance="",
                accounts_file=str(path),
                default_temperature=0.7,
                default_top_p=0.95,
                request_timeout_s=120.0,
                model_list=["grok-4.3"],
            )
            self.assertTrue(s.has_upstream_auth())
        finally:
            path.unlink(missing_ok=True)

    def test_upstream_account_pool_is_reused_for_round_robin(self):
        from app.config import Settings
        from app.upstream.xai_client import _ACCOUNT_POOL_CACHE, _account_pool

        path = test_file("tmp_round_robin_accounts.json")
        try:
            path.write_text(
                '[{"name":"a","sso":"a-token"},{"name":"b","sso":"b-token"}]',
                encoding="utf-8",
            )
            s = Settings(
                host="0.0.0.0",
                port=8787,
                openai_api_key="k",
                upstream_url="https://console.x.ai/v1/responses",
                upstream_cookie="",
                upstream_sso="",
                upstream_cluster="https://us-east-1.api.x.ai",
                upstream_referer="https://console.x.ai/team/x/chat-playground",
                upstream_origin="https://console.x.ai",
                upstream_user_agent="ua",
                upstream_proxy="",
                upstream_impersonate="chrome136",
                upstream_skip_ssl_verify=False,
                upstream_cf_cookies="",
                upstream_cf_clearance="",
                accounts_file=str(path),
                default_temperature=0.7,
                default_top_p=0.95,
                request_timeout_s=120.0,
                model_list=["grok-4.3"],
            )

            _ACCOUNT_POOL_CACHE.clear()
            self.assertEqual(_account_pool(s).next_account().name, "a")
            self.assertEqual(_account_pool(s).next_account().name, "b")
        finally:
            path.unlink(missing_ok=True)

    def test_upstream_record_result_updates_file_and_clears_pool_cache(self):
        from app.accounts import Account
        from app.config import Settings
        from app.upstream.xai_client import _ACCOUNT_POOL_CACHE, _record_result

        path = test_file("tmp_record_result_accounts.json")
        try:
            path.write_text(
                '[{"name":"a","sso":"token","team_id":"team-1","status":"active"}]',
                encoding="utf-8",
            )
            settings = Settings(
                host="0.0.0.0",
                port=8787,
                openai_api_key="k",
                upstream_url="https://console.x.ai/v1/responses",
                upstream_cookie="",
                upstream_sso="",
                upstream_cluster="https://us-east-1.api.x.ai",
                upstream_referer="",
                upstream_origin="https://console.x.ai",
                upstream_user_agent="ua",
                upstream_proxy="",
                upstream_impersonate="chrome136",
                upstream_skip_ssl_verify=False,
                upstream_cf_cookies="",
                upstream_cf_clearance="",
                accounts_file=str(path),
                default_temperature=0.7,
                default_top_p=0.95,
                request_timeout_s=120.0,
                model_list=["grok-4.3"],
            )
            _ACCOUNT_POOL_CACHE[("x", "", None, None)] = object()

            _record_result(
                settings,
                Account(name="a", sso="token", team_id="team-1"),
                status_code=403,
                error="forbidden",
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
        finally:
            path.unlink(missing_ok=True)
            _ACCOUNT_POOL_CACHE.clear()

        self.assertEqual(saved[0]["status"], "invalid")
        self.assertEqual(saved[0]["last_error"], "forbidden")
        self.assertEqual(_ACCOUNT_POOL_CACHE, {})

    def test_parse_sso_txt_ignores_blank_lines_and_uses_numeric_names(self):
        from app.admin.routes import parse_sso_txt

        accounts = parse_sso_txt("\n sso=aaa \n\n bbb\n")

        self.assertEqual([a["name"] for a in accounts], ["1", "2"])
        self.assertEqual([a["sso"] for a in accounts], ["aaa", "bbb"])
        self.assertTrue(all(a["status"] == "active" for a in accounts))
        self.assertTrue(all("team_id" in a and "referer" in a for a in accounts))

    def test_parse_sso_txt_accepts_sso_team_id_per_line(self):
        from app.admin.routes import parse_sso_txt

        accounts = parse_sso_txt(
            "\n"
            "sso=aaa,team-a\n"
            "bbb, team-b \n"
            "sso=ccc,\n"
            "ddd\n"
        )

        self.assertEqual([a["sso"] for a in accounts], ["aaa", "bbb", "ccc", "ddd"])
        self.assertEqual([a["team_id"] for a in accounts], ["team-a", "team-b", "", ""])
        self.assertEqual(
            accounts[0]["referer"],
            "https://console.x.ai/team/team-a/chat-playground",
        )
        self.assertEqual(
            accounts[1]["referer"],
            "https://console.x.ai/team/team-b/chat-playground",
        )
        self.assertEqual(accounts[2]["referer"], "")

    def test_parse_sso_txt_deduplicates_by_sso_and_team_id_pair(self):
        from app.admin.routes import parse_sso_txt

        accounts = parse_sso_txt("same,team-a\nsame,team-b\nsame,team-a\n")

        self.assertEqual([a["sso"] for a in accounts], ["same", "same"])
        self.assertEqual([a["team_id"] for a in accounts], ["team-a", "team-b"])

    def test_mask_sso_hides_token_body(self):
        from app.admin.routes import mask_sso

        self.assertEqual(mask_sso("abcdefghijklmnopqrstuvwxyz"), "abcd...wxyz")
        self.assertEqual(mask_sso("short"), "*****")

    def test_account_referer_overrides_global_referer(self):
        from app.accounts import Account
        from app.config import Settings
        from app.upstream.xai_client import _upstream_headers

        settings = Settings(
            host="0.0.0.0",
            port=8787,
            openai_api_key="k",
            upstream_url="https://console.x.ai/v1/responses",
            upstream_cookie="",
            upstream_sso="",
            upstream_cluster="https://us-east-1.api.x.ai",
            upstream_referer="https://console.x.ai/team/global/chat-playground",
            upstream_origin="https://console.x.ai",
            upstream_user_agent="ua",
            upstream_proxy="",
            upstream_impersonate="chrome136",
            upstream_skip_ssl_verify=False,
            upstream_cf_cookies="",
            upstream_cf_clearance="",
            accounts_file="accounts.json",
            default_temperature=0.7,
            default_top_p=0.95,
            request_timeout_s=120.0,
            model_list=["grok-4.3"],
        )
        account = Account(
            name="a",
            sso="token",
            referer="https://console.x.ai/team/account/chat-playground",
        )

        self.assertEqual(_upstream_headers(settings, account)["referer"], "https://console.x.ai/team/account/chat-playground")

    def test_write_accounts_saves_json_and_masks_summary(self):
        from app.admin.routes import _load_account_summary, _write_accounts
        from app.config import _ENV_CACHE

        path = test_file("tmp_write_accounts.json")
        try:
            with mock.patch.dict("os.environ", {"ACCOUNTS_FILE": str(path)}, clear=False):
                import app.config as config

                config._ENV_CACHE = {}
                _write_accounts([{"name": "account-1", "sso": "abcdefghijklmnopqrstuvwxyz"}])
                saved = path.read_text(encoding="utf-8")
                summary = _load_account_summary()
                config._ENV_CACHE = _ENV_CACHE
        finally:
            path.unlink(missing_ok=True)
            path.with_suffix(path.suffix + ".tmp").unlink(missing_ok=True)

        self.assertIn('"sso": "abcdefghijklmnopqrstuvwxyz"', saved)
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["effective_source"], "accounts_file")
        self.assertEqual(summary["accounts"][0]["sso"], "abcd...wxyz")

    def test_write_accounts_saves_sqlite_and_masks_summary(self):
        from app.accounts import load_account_records
        from app.admin.routes import _load_account_summary, _write_accounts
        from app.config import _ENV_CACHE

        path = test_file("tmp_write_accounts.sqlite3")
        try:
            with mock.patch.dict("os.environ", {"ACCOUNTS_FILE": str(path)}, clear=False):
                import app.config as config

                config._ENV_CACHE = {}
                _write_accounts([{"name": "1", "sso": "abcdefghijklmnopqrstuvwxyz", "team_id": "team-a"}])
                saved = load_account_records(str(path))
                summary = _load_account_summary()
                config._ENV_CACHE = _ENV_CACHE
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(saved[0]["sso"], "abcdefghijklmnopqrstuvwxyz")
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["effective_source"], "accounts_file")
        self.assertEqual(summary["accounts"][0]["sso"], "abcd...wxyz")

    def test_account_summary_includes_status_counts_usage_and_error_categories(self):
        from app.admin.routes import _load_account_summary
        from app.config import _ENV_CACHE

        path = test_file("tmp_summary_stats_accounts.json")
        try:
            path.write_text(
                "["
                '{"name":"1","sso":"a","team_id":"team-a","status":"active","use_count":3,"fail_count":1,"last_used_at":10},'
                '{"name":"2","sso":"b","team_id":"team-b","status":"cooling","last_error":"rate limited 429","use_count":1,"fail_count":2},'
                '{"name":"3","sso":"c","team_id":"team-c","status":"invalid","last_error":"Cloudflare challenge","fail_count":5},'
                '{"name":"4","sso":"d","team_id":"team-d","status":"disabled","last_error":"manual"}'
                "]",
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"ACCOUNTS_FILE": str(path)}, clear=False):
                import app.config as config

                config._ENV_CACHE = {}
                summary = _load_account_summary()
                config._ENV_CACHE = _ENV_CACHE
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(summary["status_counts"]["active"], 1)
        self.assertEqual(summary["status_counts"]["cooling"], 1)
        self.assertEqual(summary["status_counts"]["invalid"], 1)
        self.assertEqual(summary["status_counts"]["disabled"], 1)
        self.assertEqual(summary["selectable_count"], 1)
        self.assertEqual(summary["problem_count"], 2)
        self.assertEqual(summary["total_use_count"], 4)
        self.assertEqual(summary["total_fail_count"], 8)
        self.assertEqual(summary["accounts"][0]["use_count"], 3)
        self.assertEqual(summary["accounts"][0]["fail_count"], 1)
        self.assertEqual(summary["accounts"][0]["error_category"], "")
        self.assertEqual(summary["accounts"][1]["error_category"], "rate_limit")
        self.assertEqual(summary["accounts"][2]["error_category"], "cloudflare")

    def test_classify_account_error_groups_common_failures(self):
        from app.admin.routes import classify_account_error

        self.assertEqual(classify_account_error(401, "unauthorized"), "auth")
        self.assertEqual(classify_account_error(403, "forbidden"), "auth")
        self.assertEqual(classify_account_error(429, "too many requests"), "rate_limit")
        self.assertEqual(classify_account_error(None, "proxy connect timeout"), "network")
        self.assertEqual(classify_account_error(502, "Cloudflare cf_clearance challenge"), "cloudflare")
        self.assertEqual(classify_account_error(400, "team not found or organization access denied"), "team")
        self.assertEqual(classify_account_error(400, '{"code":"Client specified an invalid argument"}'), "request")
        self.assertEqual(classify_account_error(None, '{"code":"Client specified an invalid argument"}'), "request")
        self.assertEqual(classify_account_error(500, "upstream exploded"), "upstream")

    def test_check_account_health_uses_regular_responses_payload_shape(self):
        from app.accounts import Account
        from app.config import Settings
        from app.upstream.xai_client import check_account_health

        captured = {}

        class FakeResponse:
            status_code = 200
            text = "{}"

        class FakeSession:
            def __init__(self, **kwargs):
                captured["kwargs"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def post(self, url, *, headers, data, timeout):
                captured["url"] = url
                captured["headers"] = headers
                captured["payload"] = json.loads(data.decode("utf-8"))
                captured["timeout"] = timeout
                return FakeResponse()

        settings = Settings(
            host="0.0.0.0",
            port=8787,
            openai_api_key="k",
            upstream_url="https://console.x.ai/v1/responses",
            upstream_cookie="",
            upstream_sso="",
            upstream_cluster="https://us-east-1.api.x.ai",
            upstream_referer="",
            upstream_origin="https://console.x.ai",
            upstream_user_agent="ua",
            upstream_proxy="",
            upstream_impersonate="chrome136",
            upstream_skip_ssl_verify=False,
            upstream_cf_cookies="",
            upstream_cf_clearance="",
            accounts_file="",
            default_temperature=0.7,
            default_top_p=0.95,
            request_timeout_s=120.0,
            model_list=["grok-4.3"],
        )

        with mock.patch("app.upstream.xai_client.crequests.AsyncSession", FakeSession):
            status_code, error = asyncio.run(
                check_account_health(settings, Account(name="1", sso="token", team_id="team-a"))
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(error, "")
        self.assertEqual(captured["payload"]["tool_choice"], "auto")
        self.assertEqual(
            captured["payload"]["tools"],
            [
                {"type": "web_search", "enable_image_understanding": True},
                {"type": "x_search", "enable_video_understanding": True},
            ],
        )
        self.assertNotEqual(captured["payload"].get("tools"), [])
        self.assertNotEqual(captured["payload"].get("tool_choice"), "none")
        self.assertEqual(captured["payload"]["max_output_tokens"], 16)

    def test_realtime_client_secret_uses_account_cookie(self):
        from app.config import Settings
        from app.upstream.xai_client import create_realtime_client_secret

        captured = {}

        class FakeResponse:
            status_code = 200
            text = '{"client_secret":{"value":"secret-1"}}'

        class FakeSession:
            def __init__(self, **kwargs):
                captured["kwargs"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def post(self, url, *, headers, data, timeout):
                captured["url"] = url
                captured["headers"] = headers
                captured["payload"] = json.loads(data.decode("utf-8"))
                captured["timeout"] = timeout
                return FakeResponse()

        path = test_file("tmp_realtime_accounts.json")
        try:
            path.write_text('[{"name":"1","sso":"token","team_id":"team-a","status":"active"}]', encoding="utf-8")
            settings = Settings(
                host="0.0.0.0",
                port=8787,
                openai_api_key="k",
                upstream_url="https://console.x.ai/v1/responses",
                upstream_cookie="",
                upstream_sso="",
                upstream_cluster="https://us-east-1.api.x.ai",
                upstream_referer="",
                upstream_origin="https://console.x.ai",
                upstream_user_agent="ua",
                upstream_proxy="",
                upstream_impersonate="chrome136",
                upstream_skip_ssl_verify=False,
                upstream_cf_cookies="",
                upstream_cf_clearance="",
                accounts_file=str(path),
                default_temperature=0.7,
                default_top_p=0.95,
                request_timeout_s=120.0,
                model_list=["grok-4.3"],
            )
            with mock.patch("app.upstream.xai_client.crequests.AsyncSession", FakeSession):
                data = asyncio.run(create_realtime_client_secret(settings, {"expires_after": {"seconds": 300}}))
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(data["client_secret"]["value"], "secret-1")
        self.assertEqual(captured["url"], "https://console.x.ai/v1/realtime/client_secrets")
        self.assertEqual(captured["payload"], {"expires_after": {"seconds": 300}})
        self.assertIn("sso=token", captured["headers"]["cookie"])
        self.assertIn("last-team-id=team-a", captured["headers"]["cookie"])

    def test_realtime_route_accepts_client_secret_payload(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.config import _ENV_CACHE

        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key", "UPSTREAM_SSO": "sso-token"}, clear=False):
            import app.config as config

            config._ENV_CACHE = None
            with mock.patch(
                "app.openai.routes.create_realtime_client_secret",
                new=mock.AsyncMock(return_value={"client_secret": {"value": "secret-1"}}),
            ) as create_secret:
                response = TestClient(app).post(
                    "/v1/realtime/client_secrets",
                    headers={"Authorization": "Bearer test-key"},
                    json={"expires_after": {"seconds": 300}},
                )
            config._ENV_CACHE = _ENV_CACHE

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client_secret"]["value"], "secret-1")
        create_secret.assert_awaited_once()
        self.assertEqual(create_secret.await_args.args[1], {"expires_after": {"seconds": 300}})

    def test_realtime_passthrough_keeps_stop_and_reset_events_unchanged(self):
        from app.upstream.realtime import build_realtime_ws_url, prepare_realtime_client_message

        self.assertEqual(
            build_realtime_ws_url("grok-voice-think-fast-1.0"),
            "wss://api.x.ai/v1/realtime?model=grok-voice-think-fast-1.0",
        )
        cancel = '{"type":"response.cancel"}'
        reset = '{"type":"session.update","session":{"instructions":"reset"}}'
        self.assertEqual(prepare_realtime_client_message(cancel), cancel)
        self.assertEqual(prepare_realtime_client_message(reset), reset)

    def test_admin_add_accounts_merges_without_overwriting_existing(self):
        from app.admin.routes import add_accounts
        from app.config import _ENV_CACHE

        path = test_file("tmp_admin_add_accounts.json")
        try:
            path.write_text(
                '[{"name":"account-1","sso":"old","team_id":"team-a","status":"active"}]',
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"ACCOUNTS_FILE": str(path)}, clear=False):
                import app.config as config

                config._ENV_CACHE = {}
                asyncio.run(add_accounts({"text": "old,team-a\nnew,team-b\n"}))
                saved = json.loads(path.read_text(encoding="utf-8"))
                config._ENV_CACHE = _ENV_CACHE
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual([item["sso"] for item in saved], ["old", "new"])
        self.assertEqual([item["name"] for item in saved], ["1", "2"])
        self.assertEqual(saved[0]["status"], "active")
        self.assertEqual(saved[1]["team_id"], "team-b")

    def test_admin_disable_enable_delete_and_refresh_accounts(self):
        from app.admin.routes import delete_accounts, refresh_accounts, toggle_accounts_disabled
        from app.config import _ENV_CACHE

        path = test_file("tmp_admin_batch_accounts.json")
        try:
            path.write_text(
                "["
                '{"name":"account-1","sso":"a","team_id":"team-a","status":"active","last_error":"x"},'
                '{"name":"account-2","sso":"b","team_id":"team-b","status":"failed","last_error":"old"}'
                "]",
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"ACCOUNTS_FILE": str(path)}, clear=False):
                import app.config as config

                config._ENV_CACHE = {}
                asyncio.run(toggle_accounts_disabled({"accounts": [{"sso": "a", "team_id": "team-a"}], "disabled": True}))
                disabled = json.loads(path.read_text(encoding="utf-8"))
                asyncio.run(toggle_accounts_disabled({"accounts": [{"sso": "a", "team_id": "team-a"}], "disabled": False}))
                enabled = json.loads(path.read_text(encoding="utf-8"))
                with mock.patch(
                    "app.admin.routes.check_account_health",
                    new=mock.AsyncMock(return_value=(200, "")),
                ):
                    asyncio.run(refresh_accounts({"accounts": [{"sso": "b", "team_id": "team-b"}]}))
                refreshed = json.loads(path.read_text(encoding="utf-8"))
                asyncio.run(delete_accounts({"accounts": [{"sso": "a", "team_id": "team-a"}]}))
                deleted = json.loads(path.read_text(encoding="utf-8"))
                config._ENV_CACHE = _ENV_CACHE
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(disabled[0]["status"], "disabled")
        self.assertEqual(enabled[0]["status"], "active")
        self.assertEqual(refreshed[1]["status"], "active")
        self.assertEqual(refreshed[1]["last_error"], "")
        self.assertGreater(refreshed[1]["last_checked_at"], 0)
        self.assertEqual([item["sso"] for item in deleted], ["b"])
        self.assertEqual([item["name"] for item in deleted], ["1"])

    def test_account_pool_defaults_missing_names_to_numeric_strings(self):
        from app.accounts import AccountPool

        path = test_file("tmp_numeric_name_accounts.json")
        try:
            path.write_text('[{"sso":"a"},{"sso":"b"}]', encoding="utf-8")
            pool = AccountPool.from_file(str(path), fallback_sso="")
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual([item.name for item in pool.accounts], ["1", "2"])

    def test_admin_batch_actions_accept_account_indexes(self):
        from app.admin.routes import refresh_accounts, toggle_accounts_disabled
        from app.config import _ENV_CACHE

        path = test_file("tmp_admin_batch_index_accounts.json")
        try:
            path.write_text(
                "["
                '{"name":"account-1","sso":"a","team_id":"team-a","status":"active"},'
                '{"name":"account-2","sso":"b","team_id":"team-b","status":"failed","last_error":"old"}'
                "]",
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"ACCOUNTS_FILE": str(path)}, clear=False):
                import app.config as config

                config._ENV_CACHE = {}
                asyncio.run(toggle_accounts_disabled({"indexes": [0], "disabled": True}))
                disabled = json.loads(path.read_text(encoding="utf-8"))
                with mock.patch(
                    "app.admin.routes.check_account_health",
                    new=mock.AsyncMock(return_value=(403, "forbidden")),
                ):
                    asyncio.run(refresh_accounts({"indexes": [1]}))
                refreshed = json.loads(path.read_text(encoding="utf-8"))
                config._ENV_CACHE = _ENV_CACHE
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(disabled[0]["status"], "disabled")
        self.assertEqual(refreshed[1]["status"], "invalid")
        self.assertEqual(refreshed[1]["last_error"], "forbidden")

    def test_admin_refresh_accounts_uses_sqlite_and_health_check(self):
        from app.accounts import load_account_records, write_account_records
        from app.admin.routes import refresh_accounts
        from app.config import _ENV_CACHE

        path = test_file("tmp_admin_refresh_accounts.sqlite3")
        try:
            write_account_records(
                str(path),
                [{"name": "1", "sso": "a", "team_id": "team-a", "status": "failed", "last_error": "old"}],
            )
            with mock.patch.dict("os.environ", {"ACCOUNTS_DB": str(path)}, clear=False):
                import app.config as config

                config._ENV_CACHE = {}
                with mock.patch(
                    "app.admin.routes.check_account_health",
                    new=mock.AsyncMock(return_value=(429, "rate limited")),
                ) as probe:
                    response = asyncio.run(refresh_accounts({"indexes": [0]}))
                saved = load_account_records(str(path))
                config._ENV_CACHE = _ENV_CACHE
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(saved[0]["status"], "cooling")
        self.assertEqual(saved[0]["last_error"], "rate limited")
        self.assertGreater(saved[0]["last_checked_at"], 0)
        self.assertEqual(response.body.count(b'"refreshed"'), 1)
        probe.assert_awaited_once()

    def test_admin_stream_refresh_accounts_emits_progress_and_updates_status(self):
        from app.admin.routes import stream_refresh_accounts
        from app.config import _ENV_CACHE

        path = test_file("tmp_admin_stream_refresh.json")

        async def collect(response):
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

        try:
            path.write_text(
                "["
                '{"name":"1","sso":"a","team_id":"team-a","status":"failed"},'
                '{"name":"2","sso":"b","team_id":"team-b","status":"failed"}'
                "]",
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"ACCOUNTS_FILE": str(path)}, clear=False):
                import app.config as config

                config._ENV_CACHE = {}
                with mock.patch(
                    "app.admin.routes.check_account_health",
                    new=mock.AsyncMock(side_effect=[(200, ""), (403, "forbidden")]),
                ):
                    response = asyncio.run(stream_refresh_accounts({"indexes": [0, 1], "job_id": "job-test"}))
                    body = asyncio.run(collect(response))
                saved = json.loads(path.read_text(encoding="utf-8"))
                config._ENV_CACHE = _ENV_CACHE
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("event: progress", body)
        self.assertIn('"done": 1', body)
        self.assertIn('"done": 2', body)
        self.assertIn('"error_category": "auth"', body)
        self.assertIn('"name": "2"', body)
        self.assertIn("event: complete", body)
        self.assertEqual(saved[0]["status"], "active")
        self.assertEqual(saved[1]["status"], "invalid")

    def test_admin_cancel_stream_refresh_stops_before_probe(self):
        from app.admin.routes import cancel_refresh_accounts, stream_refresh_accounts
        from app.config import _ENV_CACHE

        path = test_file("tmp_admin_stream_cancel.json")

        async def collect(response):
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

        try:
            path.write_text('[{"name":"1","sso":"a","team_id":"team-a","status":"failed"}]', encoding="utf-8")
            with mock.patch.dict("os.environ", {"ACCOUNTS_FILE": str(path)}, clear=False):
                import app.config as config

                config._ENV_CACHE = {}
                asyncio.run(cancel_refresh_accounts({"job_id": "job-cancel"}))
                with mock.patch(
                    "app.admin.routes.check_account_health",
                    new=mock.AsyncMock(return_value=(200, "")),
                ) as probe:
                    response = asyncio.run(stream_refresh_accounts({"indexes": [0], "job_id": "job-cancel"}))
                    body = asyncio.run(collect(response))
                saved = json.loads(path.read_text(encoding="utf-8"))
                config._ENV_CACHE = _ENV_CACHE
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("event: cancelled", body)
        self.assertEqual(saved[0]["status"], "failed")
        probe.assert_not_awaited()

    def test_admin_edit_account_by_index_updates_team_status_and_optional_sso(self):
        from app.admin.routes import edit_account
        from app.config import _ENV_CACHE

        path = test_file("tmp_admin_edit_account.json")
        try:
            path.write_text(
                '[{"name":"1","sso":"old","team_id":"team-a","status":"failed","last_error":"x"}]',
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"ACCOUNTS_FILE": str(path)}, clear=False):
                import app.config as config

                config._ENV_CACHE = {}
                asyncio.run(edit_account({
                    "index": 0,
                    "sso": "new",
                    "team_id": "team-b",
                    "status": "active",
                }))
                saved = json.loads(path.read_text(encoding="utf-8"))
                config._ENV_CACHE = _ENV_CACHE
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(saved[0]["name"], "1")
        self.assertEqual(saved[0]["sso"], "new")
        self.assertEqual(saved[0]["team_id"], "team-b")
        self.assertEqual(saved[0]["referer"], "https://console.x.ai/team/team-b/chat-playground")
        self.assertEqual(saved[0]["status"], "active")
        self.assertEqual(saved[0]["last_error"], "")

    def test_account_summary_reports_env_fallback_when_file_empty(self):
        from app.admin.routes import _load_account_summary
        from app.config import _ENV_CACHE

        path = test_file("tmp_empty_accounts.json")
        try:
            path.write_text("[]", encoding="utf-8")
            with mock.patch.dict(
                "os.environ",
                {"ACCOUNTS_FILE": str(path), "UPSTREAM_SSO": "env-token"},
                clear=False,
            ):
                import app.config as config

                config._ENV_CACHE = {}
                summary = _load_account_summary()
                config._ENV_CACHE = _ENV_CACHE
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(summary["count"], 0)
        self.assertEqual(summary["effective_source"], "env_fallback")

    def test_retryable_status_codes(self):
        from app.accounts import is_retryable_status

        self.assertTrue(is_retryable_status(429))
        self.assertTrue(is_retryable_status(500))
        self.assertFalse(is_retryable_status(400))

    def test_models_from_har(self):
        from app.config import collect_models_from_har

        models = collect_models_from_har(r"D:\Desktop\consolex\console.x.ai.har")
        self.assertIn("grok-4.3", models)
        self.assertIn("grok-4.20-multi-agent-0309", models)
        self.assertIn("grok-build-0.1", models)

    def test_load_settings_with_upstream_proxy(self):
        from app.config import load_settings

        with mock.patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "k",
                "UPSTREAM_SSO": "sso-token",
                "UPSTREAM_PROXY": "http://127.0.0.1:7897",
                "UPSTREAM_IMPERSONATE": "chrome136",
            },
            clear=False,
        ):
            settings = load_settings()
        self.assertEqual(settings.upstream_proxy, "http://127.0.0.1:7897")
        self.assertEqual(settings.upstream_impersonate, "chrome136")

    def test_load_settings_reads_gateway_dotenv(self):
        from app.config import load_settings

        path = test_file("tmp_gateway_read.env")
        defaults = test_file("tmp_gateway_read_defaults.toml")
        runtime = test_file("tmp_gateway_read_runtime.toml")
        try:
            path.write_text("OPENAI_API_KEY=sk-gateway-local-test\n", encoding="utf-8")
            defaults.write_text('[app]\nopenai_api_key = ""\n\n[models]\nids = []\n', encoding="utf-8")
            runtime.write_text("", encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch(
                "app.config._dotenv_path",
                return_value=path,
            ), mock.patch(
                "app.runtime_config.default_config_path",
                return_value=defaults,
            ), mock.patch(
                "app.runtime_config.runtime_config_path",
                return_value=runtime,
            ):
                import app.config as config

                config._ENV_CACHE = None
                settings = load_settings()
        finally:
            path.unlink(missing_ok=True)
            defaults.unlink(missing_ok=True)
            runtime.unlink(missing_ok=True)
            config._ENV_CACHE = None
        self.assertEqual(settings.openai_api_key, "sk-gateway-local-test")

    def test_load_settings_defaults_accounts_to_sqlite(self):
        from app.config import load_settings

        missing_env = test_file("missing_accounts_default.env")
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch(
            "app.config._dotenv_path",
            return_value=missing_env,
        ):
            import app.config as config

            config._ENV_CACHE = None
            settings = load_settings()
            config._ENV_CACHE = None

        self.assertTrue(settings.accounts_file.endswith("\accounts.sqlite3") or settings.accounts_file.endswith("accounts.sqlite3"))

    def test_load_settings_prefers_accounts_db_over_legacy_accounts_file(self):
        from app.config import load_settings

        db_path = str(test_file("preferred.sqlite3"))
        legacy_path = str(test_file("legacy.json"))
        with mock.patch.dict(
            "os.environ",
            {"ACCOUNTS_DB": db_path, "ACCOUNTS_FILE": legacy_path},
            clear=False,
        ):
            import app.config as config

            config._ENV_CACHE = None
            settings = load_settings()
            config._ENV_CACHE = None

        self.assertEqual(settings.accounts_file, db_path)

    def test_runtime_config_merges_defaults_and_runtime_overrides(self):
        from app.runtime_config import load_runtime_config

        defaults = test_file("tmp_config_defaults.toml")
        runtime = test_file("tmp_config_runtime.toml")
        try:
            defaults.write_text(
                '[app]\nopenai_api_key = "default-key"\n\n[chat]\ntimeout = 120\n',
                encoding="utf-8",
            )
            runtime.write_text(
                '[app]\nopenai_api_key = "runtime-key"\n',
                encoding="utf-8",
            )

            data = load_runtime_config(defaults_path=defaults, runtime_path=runtime)
        finally:
            defaults.unlink(missing_ok=True)
            runtime.unlink(missing_ok=True)

        self.assertEqual(data["app"]["openai_api_key"], "runtime-key")
        self.assertEqual(data["chat"]["timeout"], 120)

    def test_load_settings_reads_runtime_config_before_dotenv(self):
        from app.config import load_settings

        defaults = test_file("tmp_config_defaults.toml")
        runtime = test_file("tmp_config_runtime.toml")
        dotenv = test_file("tmp_gateway_runtime_precedence.env")
        try:
            defaults.write_text(
                '[app]\nopenai_api_key = ""\n\n[chat]\ntimeout = 120\n\n[models]\nids = []\n',
                encoding="utf-8",
            )
            runtime.write_text(
                '[app]\nopenai_api_key = "runtime-key"\n\n[chat]\ntimeout = 45\n\n[models]\nids = ["m-runtime"]\n',
                encoding="utf-8",
            )
            dotenv.write_text("OPENAI_API_KEY=dotenv-key\nREQUEST_TIMEOUT_S=300\n", encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch(
                "app.config._dotenv_path",
                return_value=dotenv,
            ), mock.patch(
                "app.runtime_config.default_config_path",
                return_value=defaults,
            ), mock.patch(
                "app.runtime_config.runtime_config_path",
                return_value=runtime,
            ):
                import app.config as config

                config._ENV_CACHE = None
                settings = load_settings()
        finally:
            defaults.unlink(missing_ok=True)
            runtime.unlink(missing_ok=True)
            dotenv.unlink(missing_ok=True)
            config._ENV_CACHE = None

        self.assertEqual(settings.openai_api_key, "runtime-key")
        self.assertEqual(settings.request_timeout_s, 45)
        self.assertEqual(settings.model_list, ["m-runtime"])

    def test_environment_overrides_runtime_config(self):
        from app.config import load_settings

        defaults = test_file("tmp_config_defaults.toml")
        runtime = test_file("tmp_config_runtime.toml")
        missing_env = test_file("missing_runtime_override.env")
        try:
            defaults.write_text('[app]\nopenai_api_key = ""\n', encoding="utf-8")
            runtime.write_text('[app]\nopenai_api_key = "runtime-key"\n', encoding="utf-8")
            with mock.patch.dict(
                "os.environ",
                {"OPENAI_API_KEY": "environment-key"},
                clear=True,
            ), mock.patch(
                "app.config._dotenv_path",
                return_value=missing_env,
            ), mock.patch(
                "app.runtime_config.default_config_path",
                return_value=defaults,
            ), mock.patch(
                "app.runtime_config.runtime_config_path",
                return_value=runtime,
            ):
                import app.config as config

                config._ENV_CACHE = None
                settings = load_settings()
        finally:
            defaults.unlink(missing_ok=True)
            runtime.unlink(missing_ok=True)
            config._ENV_CACHE = None

        self.assertEqual(settings.openai_api_key, "environment-key")

    def test_set_runtime_config_value_writes_nested_toml(self):
        from app.runtime_config import load_runtime_config, set_runtime_config_value

        runtime = test_file("tmp_config_write.toml")
        try:
            set_runtime_config_value("app.openai_api_key", "new-key", path=runtime)
            set_runtime_config_value("chat.timeout", 88, path=runtime)
            data = load_runtime_config(defaults_path=test_file("missing_defaults.toml"), runtime_path=runtime)
        finally:
            runtime.unlink(missing_ok=True)

        self.assertEqual(data["app"]["openai_api_key"], "new-key")
        self.assertEqual(data["chat"]["timeout"], 88)

    def test_admin_update_settings_writes_runtime_config_not_dotenv(self):
        from app.admin.routes import update_admin_settings
        from app.runtime_config import load_runtime_config

        defaults = test_file("tmp_admin_defaults.toml")
        runtime = test_file("tmp_admin_runtime.toml")
        dotenv = test_file("tmp_admin_dotenv.env")
        try:
            defaults.write_text('[app]\nopenai_api_key = ""\n', encoding="utf-8")
            runtime.write_text("", encoding="utf-8")
            dotenv.write_text("OPENAI_API_KEY=dotenv-key\n", encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch(
                "app.config._dotenv_path",
                return_value=dotenv,
            ), mock.patch(
                "app.runtime_config.default_config_path",
                return_value=defaults,
            ), mock.patch(
                "app.runtime_config.runtime_config_path",
                return_value=runtime,
            ):
                import app.config as config

                config._ENV_CACHE = None
                asyncio.run(update_admin_settings({"openai_api_key": "runtime-key"}))
                saved_runtime = load_runtime_config(defaults_path=defaults, runtime_path=runtime)
                saved_dotenv = dotenv.read_text(encoding="utf-8")
        finally:
            defaults.unlink(missing_ok=True)
            runtime.unlink(missing_ok=True)
            dotenv.unlink(missing_ok=True)
            config._ENV_CACHE = None

        self.assertEqual(saved_runtime["app"]["openai_api_key"], "runtime-key")
        self.assertIn("OPENAI_API_KEY=dotenv-key", saved_dotenv)
        self.assertNotIn("OPENAI_API_KEY=runtime-key", saved_dotenv)

    def test_admin_settings_returns_editable_runtime_config(self):
        from app.admin.routes import _load_gateway_settings_summary

        settings = _load_gateway_settings_summary()

        self.assertIn("values", settings)
        self.assertIn("fields", settings)
        field_keys = {field["key"] for group in settings["fields"] for field in group["fields"]}
        self.assertIn("app.openai_api_key", field_keys)
        self.assertIn("app.admin_key", field_keys)
        self.assertIn("upstream.proxy", field_keys)
        self.assertIn("upstream.cf_cookies", field_keys)
        self.assertIn("models.ids", field_keys)
        self.assertIn("chat.timeout", field_keys)

    def test_admin_settings_masks_secret_values(self):
        from app.admin.routes import _load_gateway_settings_summary
        from app.config import _ENV_CACHE

        with mock.patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "gateway-secret",
                "ADMIN_KEY": "admin-secret",
                "UPSTREAM_CF_CLEARANCE": "cf-secret",
            },
            clear=False,
        ):
            import app.config as config

            config._ENV_CACHE = None
            settings = _load_gateway_settings_summary()
            config._ENV_CACHE = _ENV_CACHE

        self.assertEqual(settings["values"]["app.openai_api_key"], "")
        self.assertEqual(settings["values"]["app.admin_key"], "")
        self.assertEqual(settings["values"]["upstream.cf_clearance"], "")
        self.assertEqual(settings["masked_values"]["app.openai_api_key"], "gate...cret")
        self.assertEqual(settings["masked_values"]["app.admin_key"], "admi...cret")

    def test_admin_update_settings_skips_empty_secret_fields(self):
        from app.admin.routes import update_admin_settings
        from app.runtime_config import load_runtime_config

        defaults = test_file("tmp_admin_secret_defaults.toml")
        runtime = test_file("tmp_admin_secret_runtime.toml")
        dotenv = test_file("tmp_admin_secret_dotenv.env")
        try:
            defaults.write_text('[app]\nopenai_api_key = ""\nadmin_key = ""\n', encoding="utf-8")
            runtime.write_text('[app]\nopenai_api_key = "old-key"\nadmin_key = "old-admin"\n', encoding="utf-8")
            dotenv.write_text("", encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch(
                "app.config._dotenv_path",
                return_value=dotenv,
            ), mock.patch(
                "app.runtime_config.default_config_path",
                return_value=defaults,
            ), mock.patch(
                "app.runtime_config.runtime_config_path",
                return_value=runtime,
            ):
                import app.config as config

                config._ENV_CACHE = None
                asyncio.run(update_admin_settings({
                    "values": {
                        "app.openai_api_key": "",
                        "app.admin_key": "new-admin",
                    }
                }))
                saved = load_runtime_config(defaults_path=defaults, runtime_path=runtime)
        finally:
            defaults.unlink(missing_ok=True)
            runtime.unlink(missing_ok=True)
            dotenv.unlink(missing_ok=True)
            config._ENV_CACHE = None

        self.assertEqual(saved["app"]["openai_api_key"], "old-key")
        self.assertEqual(saved["app"]["admin_key"], "new-admin")

    def test_admin_update_settings_writes_multiple_runtime_fields(self):
        from app.admin.routes import update_admin_settings
        from app.runtime_config import load_runtime_config

        defaults = test_file("tmp_admin_multi_defaults.toml")
        runtime = test_file("tmp_admin_multi_runtime.toml")
        dotenv = test_file("tmp_admin_multi_dotenv.env")
        try:
            defaults.write_text(
                '[app]\nopenai_api_key = ""\nadmin_key = ""\n'
                '\n[upstream]\nproxy = ""\ncf_cookies = ""\n'
                '\n[models]\nids = []\n'
                '\n[chat]\ntimeout = 120\n'
                '\n[generation]\ntemperature = 0.7\ntop_p = 0.95\n',
                encoding="utf-8",
            )
            runtime.write_text("", encoding="utf-8")
            dotenv.write_text("OPENAI_API_KEY=dotenv-key\n", encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch(
                "app.config._dotenv_path",
                return_value=dotenv,
            ), mock.patch(
                "app.runtime_config.default_config_path",
                return_value=defaults,
            ), mock.patch(
                "app.runtime_config.runtime_config_path",
                return_value=runtime,
            ):
                import app.config as config

                config._ENV_CACHE = None
                asyncio.run(update_admin_settings({
                    "values": {
                        "app.openai_api_key": "runtime-key",
                        "app.admin_key": "admin-secret",
                        "upstream.proxy": "http://127.0.0.1:7897",
                        "upstream.cf_cookies": "cf_clearance=abc",
                        "models.ids": ["grok-4.3", "grok-4.20-auto"],
                        "chat.timeout": 240,
                        "generation.temperature": 0.2,
                    }
                }))
                saved_runtime = load_runtime_config(defaults_path=defaults, runtime_path=runtime)
        finally:
            defaults.unlink(missing_ok=True)
            runtime.unlink(missing_ok=True)
            dotenv.unlink(missing_ok=True)
            config._ENV_CACHE = None

        self.assertEqual(saved_runtime["app"]["openai_api_key"], "runtime-key")
        self.assertEqual(saved_runtime["app"]["admin_key"], "admin-secret")
        self.assertEqual(saved_runtime["upstream"]["proxy"], "http://127.0.0.1:7897")
        self.assertEqual(saved_runtime["upstream"]["cf_cookies"], "cf_clearance=abc")
        self.assertEqual(saved_runtime["models"]["ids"], ["grok-4.3", "grok-4.20-auto"])
        self.assertEqual(saved_runtime["chat"]["timeout"], 240)
        self.assertEqual(saved_runtime["generation"]["temperature"], 0.2)

    def test_load_settings_reads_admin_key(self):
        from app.config import load_settings

        with mock.patch.dict("os.environ", {"ADMIN_KEY": "admin-secret"}, clear=False):
            settings = load_settings()
        self.assertEqual(settings.admin_key, "admin-secret")

    def test_load_settings_does_not_default_to_fixed_team_referer(self):
        from app.config import load_settings

        missing_env = test_file("missing_gateway.env")
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch(
            "app.config._dotenv_path",
            return_value=missing_env,
        ):
            settings = load_settings()
        self.assertEqual(settings.upstream_referer, "")

    def test_set_dotenv_value_updates_existing_key_and_appends_missing_key(self):
        from app.config import set_dotenv_value

        path = test_file("tmp_gateway.env")
        try:
            path.write_text("OPENAI_API_KEY=old-key\nUPSTREAM_SSO=x\n", encoding="utf-8")
            set_dotenv_value("OPENAI_API_KEY", "new-key", path=path)
            set_dotenv_value("ADMIN_KEY", "admin-key", path=path)
            saved = path.read_text(encoding="utf-8")
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("OPENAI_API_KEY=new-key\n", saved)
        self.assertIn("UPSTREAM_SSO=x\n", saved)
        self.assertIn("ADMIN_KEY=admin-key\n", saved)
        self.assertNotIn("OPENAI_API_KEY=old-key", saved)

    def test_cookie_header_prefers_sso_strategy(self):
        from app.config import Settings

        s = Settings(
            host="0.0.0.0",
            port=8787,
            openai_api_key="k",
            upstream_url="https://console.x.ai/v1/responses",
            upstream_cookie="foo=bar",
            upstream_sso="abc123",
            upstream_cluster="https://us-east-1.api.x.ai",
            upstream_referer="https://console.x.ai/team/x/chat-playground",
            upstream_origin="https://console.x.ai",
            upstream_user_agent="ua",
            upstream_proxy="",
            upstream_impersonate="chrome136",
            upstream_skip_ssl_verify=False,
            upstream_cf_cookies="cf_foo=1",
            upstream_cf_clearance="clear-1",
            accounts_file="accounts.json",
            default_temperature=0.7,
            default_top_p=0.95,
            request_timeout_s=120.0,
            model_list=["grok-4.3"],
        )
        cookie = s.cookie_header
        self.assertIn("sso=abc123", cookie)
        self.assertIn("sso-rw=abc123", cookie)
        self.assertIn("cf_clearance=clear-1", cookie)

    def test_cookie_header_extracts_clearance_from_cf_cookies(self):
        from app.config import Settings

        s = Settings(
            host="0.0.0.0",
            port=8787,
            openai_api_key="k",
            upstream_url="https://console.x.ai/v1/responses",
            upstream_cookie="",
            upstream_sso="abc123",
            upstream_cluster="https://us-east-1.api.x.ai",
            upstream_referer="https://console.x.ai/team/x/chat-playground",
            upstream_origin="https://console.x.ai",
            upstream_user_agent="ua",
            upstream_proxy="",
            upstream_impersonate="chrome136",
            upstream_skip_ssl_verify=False,
            upstream_cf_cookies="cf_clearance=zzz; foo=bar",
            upstream_cf_clearance="",
            accounts_file="accounts.json",
            default_temperature=0.7,
            default_top_p=0.95,
            request_timeout_s=120.0,
            model_list=["grok-4.3"],
        )
        cookie = s.cookie_header
        self.assertIn("cf_clearance=zzz", cookie)

    def test_admin_page_uses_reference_style_management_layout(self):
        from app.admin.routes import admin_static_path

        html = admin_static_path("index.html").read_text(encoding="utf-8")
        js = admin_static_path("admin.js").read_text(encoding="utf-8")
        css = admin_static_path("admin.css").read_text(encoding="utf-8")

        self.assertIn('id="loginView"', html)
        self.assertIn('id="loginAdminKey"', html)
        self.assertIn('id="loginBtn"', html)
        self.assertIn('id="logoutBtn"', html)
        self.assertIn('class="admin-shell hidden"', html)
        self.assertIn('class="admin-sidebar"', html)
        self.assertIn('class="sidebar-actions"', html)
        self.assertIn('class="content-head"', html)
        self.assertNotIn('class="admin-header"', html)
        self.assertIn('class="stat-grid"', html)
        self.assertIn('class="table-card"', html)
        self.assertIn('id="modal-import"', html)
        self.assertNotIn('id="adminKey"', html)
        self.assertIn('id="configForm"', html)
        self.assertIn('data-tab="accounts"', html)
        self.assertIn('data-tab="settings"', html)
        self.assertIn('id="accountsView"', html)
        self.assertIn('id="settingsView"', html)
        self.assertIn('id="selectAllAccounts"', html)
        self.assertIn('id="disableSelectedBtn"', html)
        self.assertIn('id="enableSelectedBtn"', html)
        self.assertIn('id="refreshSelectedBtn"', html)
        self.assertIn('id="cancelRefreshBtn"', html)
        self.assertIn('id="deleteSelectedBtn"', html)
        self.assertIn('id="accountSearch"', html)
        self.assertIn('id="statusFilter"', html)
        self.assertIn('value="problem"', html)
        self.assertIn('data-sort="status"', html)
        self.assertIn('id="refreshJobPanel"', html)
        self.assertIn('id="refreshJobResults"', html)
        self.assertIn('id="editSelectedBtn"', html)
        self.assertIn('id="modal-edit-account"', html)
        self.assertIn('id="modal-account-detail"', html)
        self.assertIn('id="accountDetailBody"', html)
        self.assertIn('data-stat="count"', html)
        self.assertIn('id="selectableCount"', html)
        self.assertIn('id="problemCount"', html)
        self.assertIn('id="totalUseCount"', html)
        self.assertIn('id="totalFailCount"', html)
        self.assertIn('id="accountsTable"', html)
        self.assertIn("fetch('/admin/api/accounts'", js)
        self.assertIn("'/admin/api/accounts/disabled'", js)
        self.assertIn("'/admin/api/accounts/delete'", js)
        self.assertIn("'/admin/api/accounts/refresh/stream'", js)
        self.assertIn("'/admin/api/accounts/refresh/cancel'", js)
        self.assertIn("runStreamRefresh", js)
        self.assertIn("switchTab", js)
        self.assertIn("showLogin", js)
        self.assertIn("showAdmin", js)
        self.assertIn("loginAdminKey", js)
        self.assertIn("logoutBtn", js)
        self.assertIn("setRefreshingState", js)
        self.assertIn("renderConfigForm", js)
        self.assertIn("app.openai_api_key", js)
        self.assertIn("models.ids", js)
        self.assertIn("account-select", js)
        self.assertIn("renderFilteredAccounts", js)
        self.assertIn("formatTime", js)
        self.assertIn("error_category", js)
        self.assertIn("total_use_count", js)
        self.assertIn("openAccountDetail", js)
        self.assertIn("quickRefreshAccount", js)
        self.assertIn("quickToggleAccountDisabled", js)
        self.assertIn("row-actions", js)
        self.assertIn("renderRefreshJobResult", js)
        self.assertIn("sortAccounts", js)
        self.assertIn("sortState", js)
        self.assertIn("masked_values", js)
        self.assertIn("'/admin/api/accounts/edit'", js)
        self.assertIn(".admin-shell", css)
        self.assertIn(".login-view", css)
        self.assertIn(".login-panel", css)
        self.assertIn(".admin-sidebar", css)
        self.assertIn(".content-head", css)
        self.assertIn("--bg:#f7f7f8", css)
        self.assertIn("--panel:#fff", css)
        self.assertNotIn("#FAF9F5", css)
        self.assertNotIn("#f1ece2", css)
        self.assertNotIn("#d9d2c6", css)
        self.assertNotIn(".admin-header", css)
        self.assertIn(".batch-bar", css)
        self.assertIn(".row-actions", css)
        self.assertIn(".detail-grid", css)
        self.assertIn(".job-panel", css)
        self.assertIn(".sort-th", css)
        self.assertIn(".view-panel.hidden", css)
        self.assertNotIn('<h1>Gateway<br>Admin</h1>', html)

if __name__ == "__main__":
    unittest.main()


