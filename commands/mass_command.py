"""
MassCommand — swing_workflow
v2.0: 移除硬编码 VA URL，由 VAClient 配置化解析
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from code_nodes.pre_calculator import MarketStateCalculator
from core.workflow.cache_manager import CacheManager
from schemas.agent3_schema import get_schema
from utils.va_client import VAClient, parse_swing_batch_rows

logger = logging.getLogger(__name__)

_BATCH_ALLOWED_KWARGS = {
    "limit",
    "min_direction_score",
    "min_vol_score",
    "vix_override",
    "filtering",
    "sorting",
}


class MassCommand:
    """批量执行 swing 分析"""

    def __init__(self, va_url: Optional[str] = None, **kwargs):
        """
        Args:
            va_url: CLI 传入的 --va-url 参数。
                    为 None 时由 VAClient 自动从 env/config 解析 provider URL。
        
        变更说明 (v2.0):
            旧: self.va_url = va_url or "http://localhost:8668"  # 硬编码绕过配置
            新: self.va_url = va_url  # None 时交由 VAClient._resolve_provider_url()
        """
        # ★ 修复: 不再 or 硬编码, va_url=None 时由 VAClient 从配置自动解析
        self.va_url = va_url
        self.va_client = VAClient(base_url=self.va_url)

        logger.info(
            f"[swing] MassCommand 初始化, provider={self.va_client.base_url}"
        )

    @staticmethod
    def _validate_date(date: Optional[str]) -> str:
        """Validate date input and fallback to today."""
        if not date:
            return datetime.now().strftime("%Y-%m-%d")
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Invalid date format: {date}. Use YYYY-MM-DD.") from exc
        return date

    @staticmethod
    def _normalize_symbols(symbols: Optional[List[str]]) -> Optional[List[str]]:
        """Normalize CLI symbols: split comma, trim, uppercase, dedupe."""
        if not symbols:
            return None

        out: List[str] = []
        for item in symbols:
            if not isinstance(item, str):
                continue
            for part in item.split(","):
                normalized = part.strip().upper()
                if normalized and normalized not in out:
                    out.append(normalized)
        return out or None

    @staticmethod
    def _to_output_date(date: str) -> str:
        return date.replace("-", "")

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalize_market_params(cls, market_params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "vix": cls._safe_float(market_params.get("vix")),
            "ivr": cls._safe_float(market_params.get("ivr")),
            "iv30": cls._safe_float(market_params.get("iv30")),
            "hv20": cls._safe_float(market_params.get("hv20")),
            "iv_path": market_params.get("iv_path"),
            "earning_date": market_params.get("earning_date"),
            "beta": cls._safe_float(market_params.get("beta")),
        }

    @staticmethod
    def _build_template_from_schema(schema: Dict[str, Any], symbol: str) -> Any:
        schema_type = schema.get("type")
        if schema_type == "object":
            result: Dict[str, Any] = {}
            for prop_name, prop_schema in (schema.get("properties") or {}).items():
                if prop_name == "symbol":
                    result[prop_name] = symbol
                else:
                    result[prop_name] = MassCommand._build_template_from_schema(
                        prop_schema,
                        symbol,
                    )
            return result
        if schema_type == "array":
            return []
        if schema_type == "string":
            enum_values = schema.get("enum", [])
            return enum_values[0] if enum_values else None
        if isinstance(schema_type, list):
            valid_types = [t for t in schema_type if t != "null"]
            if valid_types:
                merged = {"type": valid_types[0]}
                merged.update({k: v for k, v in schema.items() if k != "type"})
                return MassCommand._build_template_from_schema(merged, symbol)
            return None
        return None

    @classmethod
    def _write_input_template(
        cls,
        symbol: str,
        date: str,
        market_params: Dict[str, Any],
        dyn_params: Dict[str, Any],
        bridge: Dict[str, Any],
    ) -> Path:
        input_dir = Path("data/input") / date
        input_dir.mkdir(parents=True, exist_ok=True)
        file_path = input_dir / f"{symbol.lower()}_i_{date}.json"

        schema = get_schema()
        template = {
            "spec": cls._build_template_from_schema(schema, symbol),
            "metadata": {
                "as_of": date,
                "strikes": dyn_params.get("dyn_strikes"),
                "market_params": market_params,
                "bridge": bridge,
                "panels": [
                    {"panel_name": "short", "horizon_arg": dyn_params.get("dyn_dte_short"), "rows": []},
                    {"panel_name": "mid", "horizon_arg": dyn_params.get("dyn_dte_mid"), "rows": []},
                    {"panel_name": "long", "horizon_arg": dyn_params.get("dyn_dte_long_backup"), "rows": []},
                ],
            },
        }

        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(template, fh, indent=2, ensure_ascii=False)
        return file_path

    def execute(self, symbols: List[str], date: Optional[str] = None, **kwargs):
        """执行批量分析"""
        if date is None:
            date = kwargs.pop("target_date", None)
        user_provided_date = bool(date)
        effective_date = self._validate_date(date)
        normalized_symbols = self._normalize_symbols(symbols)

        # Drop non-request runtime kwargs and only keep batch contract fields.
        request_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key in _BATCH_ALLOWED_KWARGS and value is not None
        }
        if user_provided_date:
            # For explicit historical runs, do not silently fallback to earlier trade dates.
            filtering = request_kwargs.get("filtering")
            if not isinstance(filtering, dict):
                filtering = {}
            filtering.setdefault("strict_date", True)
            request_kwargs["filtering"] = filtering

        logger.info(
            "[swing] MassCommand.execute: date=%s symbols=%s",
            effective_date,
            normalized_symbols or "ALL",
        )

        batch_result = self.va_client.fetch_market_context_batch(
            symbols=normalized_symbols, date=effective_date, source="swing", **request_kwargs
        )
        if isinstance(batch_result, list):
            batch_result = {"success": True, "results": batch_result, "errors": []}

        results = batch_result.get("results", [])
        errors = batch_result.get("errors", [])
        if not isinstance(errors, list):
            errors = []
        resolved_date = batch_result.get("date")
        if (
            user_provided_date
            and isinstance(resolved_date, str)
            and resolved_date
            and resolved_date != effective_date
        ):
            errors.append(
                {
                    "code": "DATE_MISMATCH",
                    "message": f"requested_date={effective_date}, resolved_date={resolved_date}",
                }
            )
        parsed = parse_swing_batch_rows(results)
        if not parsed:
            logger.warning(
                "[swing] no swing rows generated: requested_date=%s resolved_date=%s fallback_used=%s count=%s",
                effective_date,
                resolved_date,
                batch_result.get("fallback_used"),
                len(results) if isinstance(results, list) else 0,
            )
        cache_manager = CacheManager()
        output_date = self._to_output_date(effective_date)

        for sym, payload in parsed.items():
            bridge = payload["bridge"]
            market_params = self._normalize_market_params(payload["market_params"])

            # ★ 提取 micro_boundary
            micro_boundary = bridge.get("micro_boundary") if isinstance(bridge, dict) else None

            # ★ degradation gate — blocked 模式直接跳过
            if isinstance(micro_boundary, dict):
                deg = micro_boundary.get("degradation") or {}
                deg_mode = deg.get("mode")
                if deg_mode == "blocked":
                    deg_warnings = deg.get("warnings", [])
                    errors.append(
                        {
                            "symbol": sym,
                            "code": "BOUNDARY_BLOCKED",
                            "message": f"micro_boundary blocked: {'; '.join(deg_warnings) if deg_warnings else 'unknown reason'}",
                        }
                    )
                    continue

            required = ["vix", "ivr", "iv30", "hv20"]
            missing = [k for k in required if market_params.get(k) is None]
            if missing:
                errors.append(
                    {
                        "symbol": sym,
                        "code": "INVALID_MARKET_PARAMS",
                        "message": f"missing required market params: {', '.join(missing)}",
                    }
                )
                continue

            try:
                dyn_params = MarketStateCalculator.calculate_fetch_params(
                    vix=market_params["vix"],
                    ivr=market_params["ivr"],
                    iv30=market_params["iv30"],
                    hv20=market_params["hv20"],
                    term_structure=bridge.get("term_structure") if isinstance(bridge, dict) else None,
                    boundary=micro_boundary,
                )
            except Exception as exc:
                errors.append(
                    {
                        "symbol": sym,
                        "code": "DYN_PARAM_CALC_FAILED",
                        "message": str(exc),
                    }
                )
                continue

            input_path = self._write_input_template(
                symbol=sym,
                date=effective_date,
                market_params=market_params,
                dyn_params=dyn_params,
                bridge=bridge,
            )
            cache_path = cache_manager.initialize_cache_with_params(
                symbol=sym,
                market_params=market_params,
                dyn_params=dyn_params,
                start_date=output_date,
                verbose=False,
            )

            exec_state = bridge.get("execution_state", {}) if isinstance(bridge, dict) else {}
            logger.info(
                "[swing] %s: confidence=%s liquidity=%s oi_available=%s boundary_mode=%s strikes=%s input=%s cache=%s",
                sym,
                exec_state.get("confidence"),
                exec_state.get("liquidity"),
                exec_state.get("oi_data_available"),
                dyn_params.get("boundary_mode", "N/A"),
                dyn_params.get("dyn_strikes"),
                input_path,
                cache_path,
            )

        batch_result["errors"] = errors
        if errors:
            logger.warning(f"[swing] batch errors: {errors}")

        return batch_result

    @classmethod
    def cli_entry(cls, va_url: Optional[str] = None, **kwargs):
        """CLI 入口"""
        cmd = cls(va_url=va_url, **kwargs)
        return cmd.execute(**kwargs)
