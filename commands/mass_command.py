"""
MassCommand — swing_workflow
v2.0: 移除硬编码 VA URL，由 VAClient 配置化解析
"""

import logging
from typing import Optional, List

from utils.va_client import VAClient

logger = logging.getLogger(__name__)


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

        # ... 其余初始化逻辑保持不变 ...

    def execute(self, symbols: List[str], date: Optional[str] = None, **kwargs):
        """执行批量分析"""
        logger.info(f"[swing] MassCommand.execute: {len(symbols)} symbols")

        batch_result = self.va_client.fetch_market_context_batch(
            symbols=symbols, date=date, **kwargs
        )

        results = batch_result.get("results", {})
        errors = batch_result.get("errors", [])

        for sym, bridge in results.items():
            exec_state = bridge.get("execution_state", {})
            logger.info(
                f"[swing] {sym}: confidence={exec_state.get('confidence')}, "
                f"liquidity={exec_state.get('liquidity')}, "
                f"oi_available={exec_state.get('oi_data_available')}"
            )

        if errors:
            logger.warning(f"[swing] batch errors: {errors}")

        return batch_result

    @classmethod
    def cli_entry(cls, va_url: Optional[str] = None, **kwargs):
        """CLI 入口"""
        cmd = cls(va_url=va_url, **kwargs)
        return cmd.execute(**kwargs)
