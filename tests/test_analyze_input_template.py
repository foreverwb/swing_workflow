import io
import os
import tempfile
import unittest
from pathlib import Path

from tests._support import ensure_dependency_stubs
ensure_dependency_stubs()

from rich.console import Console

from commands.analyze_command import AnalyzeCommand


class AnalyzeInputTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.console = Console(file=io.StringIO(), force_terminal=False)
        self.command = AnalyzeCommand(self.console, model_client=None, env_vars={})
        self.pre_calc = {
            "dyn_strikes": 30,
            "dyn_dte_short": "14 w",
            "dyn_dte_mid": "30 w",
            "dyn_dte_long_backup": "60 m",
            "dyn_window": 60,
        }

    def test_generate_input_template_uses_overridden_base_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_input_dir = Path(tmpdir) / "data" / "input" / "2026-01-04"

            template_path = self.command._generate_input_template(
                symbol="NVDA",
                pre_calc=self.pre_calc,
                market_params={},
                base_input_dir=base_input_dir,
                template_date_str="2026-01-04",
            )

            expected = base_input_dir / "nvda_i_2026-01-04.json"
            self.assertEqual(Path(template_path), expected)
            self.assertTrue(expected.exists())

    def test_generate_input_template_default_base_dir_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            os.chdir(tmpdir)
            try:
                template_path = self.command._generate_input_template(
                    symbol="NVDA",
                    pre_calc=self.pre_calc,
                    market_params={},
                    template_date_str="20260104",
                )
                self.assertEqual(Path(template_path), Path("data/input/nvda_i_20260104.json"))
            finally:
                os.chdir(old_cwd)

            expected = Path(tmpdir) / "data" / "input" / "nvda_i_20260104.json"
            self.assertTrue(expected.exists())


if __name__ == "__main__":
    unittest.main()
