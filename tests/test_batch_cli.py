import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tests._support import ensure_dependency_stubs
ensure_dependency_stubs()

import app
from commands.mass_command import MassCommand


class MassCliTests(unittest.TestCase):
    def test_mass_date_defaults_to_today_when_omitted(self):
        date_str = MassCommand._validate_date(None)
        self.assertRegex(date_str, r"^\d{4}-\d{2}-\d{2}$")

    def test_mass_creates_date_scoped_templates_for_multiple_symbols(self):
        runner = CliRunner()
        mock_batch_rows = [
            {
                "symbol": "NVDA",
                "market_params": {
                    "vix": 19.5,
                    "ivr": 62,
                    "iv30": 44,
                    "hv20": 35,
                    "iv_path": "Rising",
                },
            },
            {
                "symbol": "AAPL",
                "market_params": {
                    "vix": 19.5,
                    "ivr": 40,
                    "iv30": 28,
                    "hv20": 24,
                    "iv_path": "Flat",
                },
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            os.chdir(tmpdir)
            try:
                with patch("app.setup_logging", return_value=None), \
                     patch("core.model_client.ModelClientFactory.create_from_config", return_value=object()), \
                     patch("commands.mass_command.VAClient.fetch_market_context_batch", return_value=mock_batch_rows) as mock_fetch:
                    result = runner.invoke(
                        app.cli,
                        ["mass", "-d", "2026-01-04"],
                        catch_exceptions=False,
                    )

                self.assertEqual(result.exit_code, 0)
                mock_fetch.assert_called_once_with(date="2026-01-04", source="swing", symbols=None)

                base_dir = Path(tmpdir) / "data" / "input" / "2026-01-04"
                self.assertTrue((base_dir / "nvda_i_2026-01-04.json").exists())
                self.assertTrue((base_dir / "aapl_i_2026-01-04.json").exists())

                # 输出缓存目录应使用命令日期（YYYYMMDD）
                self.assertTrue((Path(tmpdir) / "data" / "output" / "NVDA" / "20260104" / "NVDA_o_20260104.json").exists())
                self.assertTrue((Path(tmpdir) / "data" / "output" / "AAPL" / "20260104" / "AAPL_o_20260104.json").exists())
            finally:
                os.chdir(old_cwd)

    def test_mass_symbol_option_filters_symbols(self):
        runner = CliRunner()
        mock_batch_rows = [
            {
                "symbol": "NVDA",
                "market_params": {
                    "vix": 19.5,
                    "ivr": 62,
                    "iv30": 44,
                    "hv20": 35,
                    "iv_path": "Rising",
                },
            },
            {
                "symbol": "AAPL",
                "market_params": {
                    "vix": 19.5,
                    "ivr": 40,
                    "iv30": 28,
                    "hv20": 24,
                    "iv_path": "Flat",
                },
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            os.chdir(tmpdir)
            try:
                with patch("app.setup_logging", return_value=None), \
                     patch("core.model_client.ModelClientFactory.create_from_config", return_value=object()), \
                     patch("commands.mass_command.VAClient.fetch_market_context_batch", return_value=mock_batch_rows) as mock_fetch:
                    result = runner.invoke(
                        app.cli,
                        ["mass", "-d", "2026-01-04", "-s", "NVDA"],
                        catch_exceptions=False,
                    )

                self.assertEqual(result.exit_code, 0)
                mock_fetch.assert_called_once_with(
                    date="2026-01-04",
                    source="swing",
                    symbols=["NVDA"],
                )

                base_dir = Path(tmpdir) / "data" / "input" / "2026-01-04"
                self.assertTrue((base_dir / "nvda_i_2026-01-04.json").exists())
                self.assertFalse((base_dir / "aapl_i_2026-01-04.json").exists())
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
