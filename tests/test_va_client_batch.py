import unittest
from unittest.mock import patch

from tests._support import ensure_dependency_stubs
ensure_dependency_stubs()

from utils.va_client import VAClient, VAClientError


class VAClientBatchTests(unittest.TestCase):
    def test_get_params_batch_normalizes_list_results(self):
        client = VAClient(base_url="http://localhost:8668")

        mock_response = {
            "success": True,
            "results": [
                {
                    "symbol": "NVDA",
                    "vix": 19.5,
                    "ivr": 62,
                    "iv30": 44,
                    "hv20": 35,
                    "iv_path": "Rising",
                },
                {
                    "symbol": "AAPL",
                    "params": {
                        "vix": 19.5,
                        "ivr": 40,
                        "iv30": 28,
                        "hv20": 24,
                        "iv_path": "Flat",
                    },
                },
            ],
        }

        with patch.object(client, "_make_request", return_value=mock_response):
            results = client.get_params_batch(symbols=["NVDA", "AAPL"], date="2026-01-04")

        self.assertIn("NVDA", results)
        self.assertIn("AAPL", results)
        self.assertEqual(results["NVDA"]["ivr"], 62)
        self.assertEqual(results["AAPL"]["iv_path"], "Flat")

    def test_fetch_market_context_batch_fallback_handles_list_result(self):
        client = VAClient(base_url="http://localhost:8668")

        def fake_make_request(method, endpoint, **kwargs):
            if endpoint == "/api/bridge/batch":
                raise VAClientError("bridge unavailable")

            if endpoint == "/api/swing/params/batch":
                payload = kwargs.get("json", {})
                # 第一跳：无 symbols 的批量接口不支持
                if not payload.get("symbols"):
                    raise VAClientError("symbols must be a non-empty list")

                # 第二跳：list_symbols 后回退的 batch 返回 list 结构
                return {
                    "success": True,
                    "results": [
                        {
                            "symbol": "NVDA",
                            "vix": 19.5,
                            "ivr": 62,
                            "iv30": 44,
                            "hv20": 35,
                            "iv_path": "Rising",
                        }
                    ],
                }

            if endpoint == "/api/swing/symbols":
                return {"symbols": ["NVDA"]}

            raise AssertionError(f"Unexpected endpoint: {endpoint}")

        with patch.object(client, "_make_request", side_effect=fake_make_request):
            rows = client.fetch_market_context_batch(date="2026-01-04", source="swing")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "NVDA")
        self.assertEqual(rows[0]["market_params"]["ivr"], 62)

    def test_get_params_batch_accepts_errors_list(self):
        client = VAClient(base_url="http://localhost:8668")

        mock_response = {
            "success": True,
            "errors": [
                {"symbol": "TSLA", "error": "missing iv30"},
                "generic error",
            ],
            "results": {
                "NVDA": {
                    "vix": 19.5,
                    "ivr": 62,
                    "iv30": 44,
                    "hv20": 35,
                }
            },
        }

        with patch.object(client, "_make_request", return_value=mock_response):
            results = client.get_params_batch(symbols=["NVDA", "TSLA"], date="2026-01-04")

        self.assertIn("NVDA", results)
        self.assertEqual(results["NVDA"]["ivr"], 62)

    def test_bridge_batch_count_zero_returns_empty_without_fallback(self):
        client = VAClient(base_url="http://localhost:8668")

        def fake_make_request(method, endpoint, **kwargs):
            if endpoint == "/api/bridge/batch":
                return {"success": True, "count": 0, "results": []}
            raise AssertionError(f"Should not call fallback endpoint: {endpoint}")

        with patch.object(client, "_make_request", side_effect=fake_make_request):
            rows = client.fetch_market_context_batch(date="2026-02-02", source="swing")

        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
