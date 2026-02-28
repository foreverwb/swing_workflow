"""
QuickCommand — swing_workflow
v2.0: 移除硬编码 VA URL，由 VAClient 配置化解析
"""

import logging
from typing import Optional

from utils.va_client import (
    VAClient,
    REQUEST_SOURCE,
    SWING_MARKET_PARAM_FIELDS,
    parse_swing_batch_rows,
)

logger = logging.getLogger(__name__)


class QuickCommand:
    """单 symbol 快速分析"""

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
            f"[swing] QuickCommand 初始化, provider={self.va_client.base_url}"
        )

        # ... 其余初始化逻辑保持不变 ...

    def execute(self, symbol: str, **kwargs):
        """执行单 symbol 分析"""
        logger.info(f"[swing] QuickCommand.execute: {symbol}")

        date = kwargs.pop("target_date", None) or kwargs.pop("date", None)
        source = kwargs.pop("source", REQUEST_SOURCE)
        batch_result = self.va_client.fetch_bridge_batch(
            source=source,
            date=date,
            symbols=[symbol],
            **kwargs,
        )
        rows = batch_result.get("results", [])
        parsed = parse_swing_batch_rows(rows)
        if not parsed:
            err = {"symbol": symbol, "error": "bridge data unavailable"}
            logger.error(f"[swing] {symbol} 获取失败: {err['error']}")
            return err

        first_symbol = next(iter(parsed))
        payload = parsed[first_symbol]
        bridge = payload["bridge"]
        market_params = payload["market_params"]
        normalized_market_params = {
            field: market_params.get(field) for field in SWING_MARKET_PARAM_FIELDS
        }

        exec_state = bridge.get("execution_state", {})
        logger.info(
            f"[swing] {symbol}: confidence={exec_state.get('confidence')}, "
            f"liquidity={exec_state.get('liquidity')}, "
            f"oi_available={exec_state.get('oi_data_available')}"
        )

        return {
            "symbol": first_symbol,
            "market_params": normalized_market_params,
            "bridge": bridge,
        }

    @classmethod
    def cli_entry(cls, va_url: Optional[str] = None, symbol: str = "", **kwargs):
        """CLI 入口"""
        cmd = cls(va_url=va_url, **kwargs)
        return cmd.execute(symbol=symbol, **kwargs)
