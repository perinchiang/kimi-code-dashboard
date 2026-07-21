import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import services.session_titles as session_titles
from app import create_app
from routes import sessions as sessions_route


class SessionTitlesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.sessions_dir = root / "sessions"
        self.sidecar_dir = root / "sidecars"
        self.session_dir = self.sessions_dir / "workspace" / "session_test-1"
        agent_dir = self.session_dir / "agents" / "main"
        agent_dir.mkdir(parents=True)
        (self.session_dir / "state.json").write_text(
            json.dumps({"title": "Untitled", "createdAt": 1, "updatedAt": 2, "isCustomTitle": False}),
            encoding="utf-8",
        )
        (agent_dir / "wire.jsonl").write_text(
            "\n".join([
                json.dumps({"type": "turn.prompt", "input": [{"type": "text", "text": "排查模型配置"}], "origin": {"kind": "user"}}),
                json.dumps({"type": "context.append_message", "message": {"role": "user", "content": [{"type": "text", "text": "排查模型配置"}]}}),
                json.dumps({"type": "context.apply_compaction", "contextSummary": "排查 Provider 路由和模型配置加载问题", "keptUserMessageCount": 10, "time": 3}),
            ]) + "\n",
            encoding="utf-8",
        )
        self.loop_session_dir = self.sessions_dir / "workspace" / "session_loop-2"
        loop_session_dir = self.loop_session_dir
        loop_agent_dir = loop_session_dir / "agents" / "main"
        loop_agent_dir.mkdir(parents=True)
        (loop_session_dir / "state.json").write_text(
            json.dumps({"title": "Untitled", "createdAt": 1, "updatedAt": 2, "isCustomTitle": False}),
            encoding="utf-8",
        )
        (loop_agent_dir / "wire.jsonl").write_text(
            "\n".join([
                json.dumps({"type": "context.append_message", "message": {"role": "user", "content": [{"type": "text", "text": "第一次提问"}]}}),
                json.dumps({"type": "context.append_message", "message": {"role": "user", "content": [{"type": "text", "text": "<kimi-skill-loaded>内部 Skill 指令</kimi-skill-loaded>"}]}}),
                json.dumps({"type": "context.append_loop_event", "event": {"type": "step.begin", "step": 1}}),
                json.dumps({"type": "context.append_loop_event", "event": {"type": "content.part", "part": {"type": "text", "text": "这是第一次回答。"}}}),
                json.dumps({"type": "context.append_loop_event", "event": {"type": "step.end", "finishReason": "end_turn"}}),
            ]) + "\n",
            encoding="utf-8",
        )
        self.old_sessions_dir = session_titles.SESSIONS_DIR
        self.old_sidecar_dir = session_titles.SESSION_TITLE_DIR
        session_titles.SESSIONS_DIR = self.sessions_dir
        session_titles.SESSION_TITLE_DIR = self.sidecar_dir
        session_titles._scan_cache.clear()
        session_titles._jobs.clear()
        session_titles._auto_attempts.clear()
        session_titles._auto_retry_counts.clear()
        session_titles._auto_retry_timers.clear()

    def tearDown(self):
        session_titles.SESSIONS_DIR = self.old_sessions_dir
        session_titles.SESSION_TITLE_DIR = self.old_sidecar_dir
        session_titles._scan_cache.clear()
        session_titles._jobs.clear()
        session_titles._auto_attempts.clear()
        session_titles._auto_retry_counts.clear()
        session_titles._auto_retry_timers.clear()
        self.temp_dir.cleanup()

    def test_compaction_summary_has_priority(self):
        result = session_titles.list_sessions(limit=10)
        self.assertEqual(result["total"], 2)
        item = session_titles.get_session("session_test-1")
        self.assertEqual(item["source_kind"], "contextSummary")
        self.assertEqual(item["user_message_count"], 10)
        self.assertIn("Provider", item["source_context"])

    def test_loop_events_detect_completed_first_exchange(self):
        item = session_titles.get_session("session_loop-2")
        self.assertEqual(item["user_message_count"], 1)
        self.assertEqual(item["last_message_role"], "assistant")
        self.assertIn("这是第一次回答", item["source_context"])
        with patch.object(session_titles, "get_title_settings", return_value={
            "enabled": False, "auto_generate": True, "every_exchanges": 10, "max_title_length": 80,
        }), patch.object(session_titles, "queue_title_generation") as queue:
            session_titles.maybe_auto_queue(item)
        queue.assert_called_once_with("session_loop-2", 80, source="auto")

    def test_watcher_detects_new_session_without_rescanning_old_sessions(self):
        initial = session_titles._watcher_signatures([self.session_dir])
        current, changed = session_titles._watcher_changes(
            initial,
            [self.session_dir, self.loop_session_dir],
        )
        self.assertEqual(set(current), {"session_test-1", "session_loop-2"})
        self.assertEqual([path.name for path in changed], ["session_loop-2"])

    def test_second_process_does_not_start_duplicate_watcher(self):
        old_thread = session_titles._watcher_thread
        session_titles._watcher_thread = None
        try:
            with patch.object(session_titles, "_acquire_watcher_process_lock", return_value=False), \
                    patch.object(session_titles.threading, "Thread") as thread:
                session_titles.start_title_watcher()
            thread.assert_not_called()
        finally:
            session_titles._watcher_thread = old_thread

    def test_auto_title_queues_after_first_completed_exchange(self):
        record = {
            "session_id": "session_test-1",
            "last_message_role": "assistant",
            "user_message_count": 1,
            "source_context": "user: 排查模型配置\\nassistant: 已完成",
            "source_fingerprint": "first",
            "original_title": "Untitled",
        }
        with patch.object(session_titles, "get_title_settings", return_value={
            "enabled": True, "auto_generate": True, "every_exchanges": 10, "max_title_length": 80,
        }), patch.object(session_titles, "queue_title_generation") as queue:
            session_titles.maybe_auto_queue(record)
        queue.assert_called_once_with("session_test-1", 80, source="auto")

    def test_auto_title_uses_single_auto_generate_setting(self):
        record = {
            "session_id": "session_test-1",
            "last_message_role": "assistant",
            "user_message_count": 1,
            "source_context": "user: 验证自动标题",
            "source_fingerprint": "single-toggle",
            "original_title": "Untitled",
        }
        with patch.object(session_titles, "get_title_settings", return_value={
            "enabled": False, "auto_generate": True, "every_exchanges": 10, "max_title_length": 80,
        }), patch.object(session_titles, "queue_title_generation") as queue:
            session_titles.maybe_auto_queue(record)
        queue.assert_called_once_with("session_test-1", 80, source="auto")

    def test_auto_title_refreshes_only_at_configured_interval(self):
        record = {
            "session_id": "session_test-1",
            "last_message_role": "assistant",
            "user_message_count": 2,
            "source_context": "user: 继续排查\\nassistant: 已完成",
            "source_fingerprint": "second",
            "original_title": "Untitled",
        }
        with patch.object(session_titles, "get_title_settings", return_value={
            "enabled": True, "auto_generate": True, "every_exchanges": 10, "max_title_length": 80,
        }), patch.object(session_titles, "queue_title_generation") as queue:
            session_titles.maybe_auto_queue(record)
            queue.assert_not_called()
            record["user_message_count"] = 10
            session_titles.maybe_auto_queue(record)
        queue.assert_called_once_with("session_test-1", 80, source="auto")

    def test_auto_queue_failure_does_not_stick_source_fingerprint(self):
        record = {
            "session_id": "session_test-1",
            "last_message_role": "assistant",
            "user_message_count": 1,
            "source_context": "user: 首轮问题\\nassistant: 已完成",
            "source_fingerprint": "queue-failure",
            "original_title": "Untitled",
        }
        with patch.object(session_titles, "get_title_settings", return_value={
            "auto_generate": True, "every_exchanges": 10, "max_title_length": 80,
        }), patch.object(session_titles, "queue_title_generation", return_value={"status": "error"}) as queue, \
                patch.object(session_titles, "_schedule_auto_retry") as retry:
            session_titles.maybe_auto_queue(record)
            session_titles.maybe_auto_queue(record)
        retry.assert_any_call("session_test-1", "queue-failure")
        self.assertEqual(queue.call_count, 2)
        self.assertNotIn("session_test-1", session_titles._auto_attempts)

    def test_auto_job_failure_clears_attempt_and_schedules_retry(self):
        record = {
            "session_id": "session_test-1",
            "source_context": "user: 首轮问题\\nassistant: 已完成",
            "source_fingerprint": "job-failure",
            "original_title": "Untitled",
        }
        session_titles._auto_attempts["session_test-1"] = "job-failure"
        with patch.object(session_titles, "get_session", return_value=record), \
                patch.object(session_titles, "_load_sidecar", return_value={}), \
                patch.object(session_titles, "_generate_title_with_retry", side_effect=RuntimeError("测试失败")), \
                patch.object(session_titles, "_schedule_auto_retry") as retry:
            session_titles._run_title_job("session_test-1", "job-failure", 80, "auto")
        self.assertNotIn("session_test-1", session_titles._auto_attempts)
        retry.assert_called_once_with("session_test-1", "job-failure")

    def test_manual_sidecar_title_blocks_auto_generation(self):
        sidecar = {"session_id": "session_test-1", "title": "手动标题", "manual": True}
        (self.sidecar_dir / "session_test-1.json").parent.mkdir(parents=True, exist_ok=True)
        (self.sidecar_dir / "session_test-1.json").write_text(json.dumps(sidecar), encoding="utf-8")
        record = {
            "session_id": "session_test-1", "last_message_role": "assistant", "user_message_count": 1,
            "source_context": "user: test", "source_fingerprint": "manual", "original_title": "手动标题",
        }
        with patch.object(session_titles, "get_title_settings", return_value={
            "enabled": True, "auto_generate": True, "every_exchanges": 10,
        }), patch.object(session_titles, "queue_title_generation") as queue:
            session_titles.maybe_auto_queue(record)
        queue.assert_not_called()

    def test_manual_title_is_sidecar_only_and_protected(self):
        original_state = (self.session_dir / "state.json").read_text(encoding="utf-8")
        result = session_titles.set_manual_title("session_test-1", "Provider 路由排查")
        self.assertEqual(result["title"], "Provider 路由排查")
        self.assertTrue(result["manual_title"])
        self.assertEqual((self.session_dir / "state.json").read_text(encoding="utf-8"), original_state)
        sidecar = json.loads((self.sidecar_dir / "session_test-1.json").read_text(encoding="utf-8"))
        self.assertTrue(sidecar["manual"])

    def test_native_kimi_custom_title_blocks_auto_generation(self):
        (self.session_dir / "state.json").write_text(
            json.dumps({"title": "我手动命名的会话", "isCustomTitle": True}),
            encoding="utf-8",
        )
        record = {
            "session_id": "session_test-1",
            "last_message_role": "assistant",
            "user_message_count": 1,
            "source_context": "user: test",
            "source_fingerprint": "native-manual",
            "original_title": "我手动命名的会话",
            "kimi_custom_title": True,
        }
        with patch.object(session_titles, "get_title_settings", return_value={
            "enabled": True, "auto_generate": True, "every_exchanges": 10,
        }), patch.object(session_titles, "queue_title_generation") as queue:
            session_titles.maybe_auto_queue(record)
        queue.assert_not_called()

    def test_kimi_title_writes_state_without_overwriting_other_fields(self):
        session_titles._write_kimi_title("session_test-1", "Provider 路由排查")
        state = json.loads((self.session_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["title"], "Provider 路由排查")
        self.assertTrue(state["isCustomTitle"])
        self.assertEqual(state["createdAt"], 1)
        self.assertEqual(state["updatedAt"], 2)

    def test_invalid_session_id_is_rejected(self):
        self.assertIsNone(session_titles.get_session("../state"))
        self.assertFalse(session_titles.is_safe_session_id("session_../x"))

    def test_archive_filter_and_restore_endpoint(self):
        state_path = self.session_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["archived"] = True
        state_path.write_text(json.dumps(state), encoding="utf-8")
        session_titles._invalidate_scan("session_test-1")

        active = session_titles.list_sessions(limit=10, archived="active")
        archived = session_titles.list_sessions(limit=10, archived="archived")
        all_sessions = session_titles.list_sessions(limit=10, archived="all")
        self.assertEqual(active["total"], 1)
        self.assertEqual(archived["total"], 1)
        self.assertEqual(all_sessions["total"], 2)
        self.assertEqual(archived["sessions"][0]["session_id"], "session_test-1")

        response = create_app().test_client().post("/api/sessions/session_test-1/restore")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["restored"])
        restored_state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertFalse(restored_state["archived"])
        self.assertEqual(session_titles.list_sessions(limit=10, archived="archived")["total"], 0)

        idempotent = create_app().test_client().post("/api/sessions/session_test-1/restore")
        self.assertEqual(idempotent.status_code, 200)
        self.assertFalse(idempotent.get_json()["restored"])

    def test_title_model_validation_allows_default_and_configured_alias(self):
        with patch.object(session_titles, "_load_kimi_config", return_value={"models": {"writer": {}}}):
            self.assertEqual(session_titles.validate_title_model(""), "")
            self.assertEqual(session_titles.validate_title_model("writer"), "writer")
            with self.assertRaisesRegex(ValueError, "未在 Kimi Code 中配置"):
                session_titles.validate_title_model("missing")

    def test_title_model_response_is_cleaned(self):
        response = MagicMock()
        response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "\"Provider 配置排查\"\n"}}],
        }).encode("utf-8")
        response.__enter__.return_value = response
        with patch.object(session_titles, "_load_llm_config", return_value=(
            "openai", "title-model", "https://provider.test/v1", "test-key", {},
        )), patch.object(session_titles.urllib.request, "urlopen", return_value=response):
            title = session_titles._generate_title_with_llm("user: test", 80)
        self.assertEqual(title, "Provider 配置排查")

    def test_title_model_retries_transient_rate_limit(self):
        with patch.object(session_titles, "_generate_title_with_llm", side_effect=[
            session_titles.TitleProviderError("Provider 返回 HTTP 429", status_code=429),
            "重试成功标题",
        ]), patch.object(session_titles.time, "sleep") as sleep:
            title = session_titles._generate_title_with_retry("user: test", 80, "session_test-1", "auto")
        self.assertEqual(title, "重试成功标题")
        sleep.assert_called_once_with(5.0)

    def test_session_list_does_not_queue_auto_titles(self):
        app = create_app()
        payload = {"sessions": [], "total": 0, "offset": 0, "limit": 50}
        with patch.object(sessions_route, "list_sessions", return_value=payload), \
                patch.object(sessions_route, "maybe_auto_queue", create=True) as auto_queue:
            response = app.test_client().get("/api/sessions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), payload)
        auto_queue.assert_not_called()

    def test_manual_title_generation_works_when_auto_generation_is_off(self):
        app = create_app()
        result = {"session_id": "session_test-1", "status": "running"}
        with patch.object(sessions_route, "get_title_settings", return_value={
            "enabled": False, "auto_generate": False, "max_title_length": 80,
        }), patch.object(sessions_route, "queue_title_generation", return_value=result) as queue:
            response = app.test_client().post("/api/sessions/session_test-1/title/generate", json={})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), result)
        queue.assert_called_once_with("session_test-1", max_title_length=80, source="manual")

    def test_title_settings_api_rejects_unconfigured_model(self):
        app = create_app()
        with patch.object(sessions_route, "load_dashboard_config", return_value={"session_titles": {"model": ""}}), \
                patch.object(sessions_route, "validate_title_model", side_effect=ValueError("标题模型未配置")), \
                patch.object(sessions_route, "save_dashboard_config") as save_config:
            response = app.test_client().post("/api/session-title-settings", json={"model": "missing"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("未配置", response.get_json()["error"])
        save_config.assert_not_called()

    def test_title_settings_api_uses_current_default_model_when_enabled(self):
        app = create_app()
        saved = {"session_titles": {"enabled": True, "model": ""}}
        with patch.object(sessions_route, "load_dashboard_config", return_value={"session_titles": {"enabled": False, "model": ""}}), \
                patch.object(sessions_route, "save_dashboard_config", return_value=saved) as save_config:
            response = app.test_client().post("/api/session-title-settings", json={"enabled": True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["enabled"])
        self.assertEqual(response.get_json()["model"], "")
        save_config.assert_called_once()


if __name__ == "__main__":
    unittest.main()
