import io
import unittest
from unittest.mock import patch

from tests._support import ensure_dependency_stubs
ensure_dependency_stubs()

from rich.console import Console

from commands.quick_command import QuickCommand


class QuickOutputDateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.console = Console(file=io.StringIO(), force_terminal=False)
        self.command = QuickCommand(
            console=self.console,
            model_client=None,
            env_vars={"config": {}},
            va_url="http://localhost:8668",
        )

    def test_resolve_output_date(self):
        self.assertEqual(self.command._resolve_output_date("2026-02-06"), "20260206")
        self.assertEqual(self.command._resolve_output_date("20260207"), "20260207")

    def test_execute_passes_output_date_to_analyze(self):
        market_params = {
            "vix": 19.5,
            "ivr": 62,
            "iv30": 44,
            "hv20": 35,
            "iv_path": "Rising",
        }

        with patch.object(self.command, "_fetch_market_context", return_value=(market_params, None)), \
             patch.object(self.command, "_validate_params", return_value=market_params), \
             patch("commands.quick_command.AnalyzeCommand.execute", return_value={"status": "success"}) as mock_analyze_execute:
            self.command.execute(
                symbol="NVDA",
                target_date="2026-02-06",
                folder=None,
                cache=None,
                output=None,
            )

        self.assertTrue(mock_analyze_execute.called)
        kwargs = mock_analyze_execute.call_args.kwargs
        self.assertEqual(kwargs.get("output_date"), "20260206")


if __name__ == "__main__":
    unittest.main()
