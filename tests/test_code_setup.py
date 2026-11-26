"""Contract checks for the settings shared by terminal and desktop Code."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agentnik.code_setup import CodeSelectionError, resolve_mcp_profiles, resolve_run_connection, shared_run_options


class CodeSetupTests(unittest.TestCase):
    def test_mcp_profile_resolution_checks_revision_order_and_duplicates(self):
        from agentnik.mcp_support import server_fingerprint

        one = {"name": "One", "command": "fixture", "args": [], "enabled": True}
        two = dict(one, name="Two")
        refs = [{"name": profile["name"], "sha256": server_fingerprint(profile)} for profile in (two, one)]
        config = {"mcp_servers": [one, two]}
        self.assertEqual(resolve_mcp_profiles(config, refs), [two, one])
        with self.assertRaisesRegex(ValueError, "distinct MCP servers"):
            resolve_mcp_profiles(config, [refs[0], refs[0]])
        for changed in (dict(two, enabled=False), dict(two, args=["different"])):
            with self.assertRaisesRegex(ValueError, "changed or is unavailable"):
                resolve_mcp_profiles({"mcp_servers": [one, changed]}, refs)

    def test_model_default_override_and_endpoint_are_validated_without_mutation(self):
        connection = {"url": "https://fixture.invalid/v1", "model": "default", "api_key": "fixture"}
        self.assertEqual(resolve_run_connection(connection), connection)
        self.assertEqual(resolve_run_connection(connection, "override")["model"], "override")
        self.assertEqual(connection["model"], "default")
        with self.assertRaisesRegex(CodeSelectionError, "No model selected"):
            resolve_run_connection(connection, "")
        with self.assertRaisesRegex(CodeSelectionError, "No connection selected"):
            resolve_run_connection(None, "override")
        with self.assertRaisesRegex(ValueError, "without credentials"):
            resolve_run_connection(dict(connection, url="https://user:secret@fixture.invalid"))

    def test_mcp_priority_budgets_and_capability_binding_share_one_policy(self):
        settings = {"coding_limits": {"calls": 0}, "coding_goal_limits": {"steps": 0}}
        store = SimpleNamespace(config={"settings": settings})
        connection = {"model": "override"}
        capability = {"model": "override", "_capability_scope": "fixture"}
        with patch("agentnik.code_setup.code_research_options", side_effect=lambda *a, **k: {}) as research, \
                patch("agentnik.code_setup.unsupported", return_value=True) as unsupported:
            options = shared_run_options(store, "Fixture", connection, web_enabled=True,
                                         has_mcp=True, capability_connection=capability)
            research.assert_called_once_with(store, "Fixture", connection, True, mcp_first=True)
            unsupported.assert_called_once_with(store.config, capability)
            self.assertEqual(options, {"limits": {"calls": 0}, "goal_budget": {"steps": 0},
                                       "mcp_priority": "first", "unsupported_subagent_roles": {"model"}})
            research.reset_mock()
            settings["mcp_priority"] = "last"
            options = shared_run_options(store, "Fixture", connection, web_enabled=True,
                                         has_mcp=True, capability_connection=capability)
            research.assert_called_once_with(store, "Fixture", connection, True, mcp_first=False)
            self.assertEqual(options["mcp_priority"], "last")


class CodeRecoveryTests(unittest.TestCase):
    def test_interruption_is_idempotent_and_keeps_finished_subagents_and_goal_evidence(self):
        from agentnik.sessions import mark_code_interrupted

        session = {"code_state": "awaiting_approval", "coding_last_run_goal": True,
                   "coding_goal": {"status": "active", "detail": "Prior evidence."},
                   "coding_subagents": [{"status": "queued"}, {"status": "completed"}]}
        self.assertTrue(mark_code_interrupted(session, "Check the project.", prepend_goal_detail=True))
        self.assertFalse(mark_code_interrupted(session, "Do not append this."))
        self.assertEqual(session["code_state"], "interrupted")
        self.assertEqual(session["coding_goal"], {"status": "interrupted", "detail": "Check the project.\nPrior evidence."})
        self.assertEqual(session["coding_subagents"], [{"status": "interrupted"}, {"status": "completed"}])
        self.assertEqual(session["code_activity"], [{"kind": "interrupted", "text": "Check the project."}])
