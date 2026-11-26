"""Contract checks for the settings shared by terminal and desktop Code."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agentnik.code_setup import shared_run_options


class CodeSetupTests(unittest.TestCase):
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
