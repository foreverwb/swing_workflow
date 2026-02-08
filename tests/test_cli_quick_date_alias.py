import unittest
from unittest.mock import patch

from click.testing import CliRunner

from tests._support import ensure_dependency_stubs
ensure_dependency_stubs()

import app


class QuickCliDateAliasTests(unittest.TestCase):
    def test_quick_accepts_d_as_target_date_alias(self):
        runner = CliRunner()

        with patch("app.setup_logging", return_value=None), \
             patch("commands.QuickCommand.cli_entry", return_value=None) as mock_quick_entry:
            result = runner.invoke(app.cli, ["quick", "NVDA", "-d", "2026-02-06"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0)
        self.assertTrue(mock_quick_entry.called)
        kwargs = mock_quick_entry.call_args.kwargs
        self.assertEqual(kwargs.get("target_date"), "2026-02-06")


if __name__ == "__main__":
    unittest.main()
