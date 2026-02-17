"""
VA / Bridge Provider Client — swing_workflow
v2.0: 配置化 bridge provider URL, execution_state 字段支持
"""

import os
import logging
import yaml
import httpx
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8668"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "env_config.yaml")

# 请求来源标识 — option_provider 日志中显示为 [swing]
REQUEST_SOURCE = "swing"


class VAClient:
    """Bridge / VA 数据客户端，支持配置化 provider URL 和 fallback"""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0):
        """
        Args:
            base_url: 显式指定 URL（CLI --va-url 传入）。为 None 时自动从配置解析。
            timeout: 请求超时秒数
        """
        if base_url:
            self.base_url = base_url.rstrip("/")
            logger.info(f"[swing] VAClient 使用显式 URL: {self.base_url}")
        else:
            self.base_url = self._resolve_provider_url()
            logger.info(f"[swing] VAClient 使用配置解析 URL: {self.base_url}")

        self.fallback_url = self._resolve_fallback_url()
        self.timeout = timeout
        self.source = REQUEST_SOURCE

    # ------------------------------------------------------------------
    # URL 解析
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_provider_url() -> str:
        """
        优先级:
        1. 环境变量 BRIDGE_PROVIDER_URL
        2. config/env_config.yaml → bridge_provider.url
        3. 硬编码默认值 DEFAULT_BASE_URL
        """
        # 1) 环境变量
        env_url = os.environ.get("BRIDGE_PROVIDER_URL")
        if env_url:
            logger.info(f"[swing] Provider URL 来自环境变量: {env_url}")
            return env_url.rstrip("/")

        # 2) 配置文件
        try:
            config_file = os.path.abspath(CONFIG_PATH)
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                bridge_cfg = cfg.get("bridge_provider", {})
                url = bridge_cfg.get("url")
                if url:
                    logger.info(f"[swing] Provider URL 来自配置文件: {url}")
                    return url.rstrip("/")
        except Exception as e:
            logger.warning(f"[swing] 读取配置文件失败: {e}")

        # 3) 默认值
        logger.info(f"[swing] Provider URL 使用默认值: {DEFAULT_BASE_URL}")
        return DEFAULT_BASE_URL

    @staticmethod
    def _resolve_fallback_url() -> Optional[str]:
        """解析 fallback URL"""
        env_url = os.environ.get("BRIDGE_FALLBACK_URL")
        if env_url:
            return env_url.rstrip("/")
        try:
            config_file = os.path.abspath(CONFIG_PATH)
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                bridge_cfg = cfg.get("bridge_provider", {})
                return bridge_cfg.get("fallback_url", "").rstrip("/") or None
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # HTTP 请求（带来源标识 + fallback）
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """
        发送请求，自动附加 X-Request-Source 头。
        主 URL 失败时尝试 fallback。
        """
        headers = kwargs.pop("headers", {})
        headers["X-Request-Source"] = self.source

        url = f"{self.base_url}{path}"
        try:
            logger.debug(f"[swing] {method.upper()} {url}")
            resp = httpx.request(
                method, url, headers=headers, timeout=self.timeout, **kwargs
            )
            resp.raise_for_status()
            return resp
        except (httpx.HTTPError, httpx.ConnectError) as e:
            logger.warning(f"[swing] 主 URL 请求失败: {url} -> {e}")
            if self.fallback_url and self.fallback_url != self.base_url:
                fallback = f"{self.fallback_url}{path}"
                logger.info(f"[swing] 尝试 fallback: {fallback}")
                resp = httpx.request(
                    method, fallback, headers=headers, timeout=self.timeout, **kwargs
                )
                resp.raise_for_status()
                return resp
            raise

    # ------------------------------------------------------------------
    # Bridge API 调用
    # ------------------------------------------------------------------

    def fetch_bridge_snapshot(self, symbol: str, **params) -> Optional[Dict[str, Any]]:
        """获取单个 symbol 的 bridge 快照"""
        try:
            resp = self._request("GET", f"/api/bridge/snapshot/{symbol}", params=params)
            data = resp.json()
            logger.info(f"[swing] bridge snapshot 获取成功: {symbol}")
            return data
        except Exception as e:
            logger.error(f"[swing] bridge snapshot 获取失败 {symbol}: {e}")
            return None

    def fetch_bridge_batch(
        self, symbols: List[str], date: Optional[str] = None, **params
    ) -> Dict[str, Any]:
        """批量获取 bridge 数据"""
        body: Dict[str, Any] = {"symbols": symbols}
        if date:
            body["date"] = date
        body.update(params)

        try:
            resp = self._request("POST", "/api/bridge/batch", json=body)
            data = resp.json()
            logger.info(f"[swing] bridge batch 获取成功: {len(symbols)} symbols")
            return data
        except Exception as e:
            logger.error(f"[swing] bridge batch 获取失败: {e}")
            return {"results": {}, "errors": [str(e)]}

    def fetch_bridge_params(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取 swing params"""
        try:
            resp = self._request("GET", f"/api/bridge/params/{symbol}")
            return resp.json()
        except Exception as e:
            logger.error(f"[swing] bridge params 获取失败 {symbol}: {e}")
            return None

    # ------------------------------------------------------------------
    # execution_state 提取
    # ------------------------------------------------------------------

    @staticmethod
    def extract_execution_state(bridge_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 bridge 响应中提取 execution_state 字段:
        - confidence: float
        - liquidity: str (e.g. "high", "medium", "low")
        - oi_data_available: bool
        """
        exec_state = bridge_data.get("execution_state", {})
        if isinstance(exec_state, dict):
            return {
                "confidence": exec_state.get("confidence", 0.0),
                "liquidity": exec_state.get("liquidity", "unknown"),
                "oi_data_available": exec_state.get("oi_data_available", False),
            }

        # 兼容旧格式：从顶层字段提取
        return {
            "confidence": bridge_data.get("confidence", 0.0),
            "liquidity": bridge_data.get("liquidity", "unknown"),
            "oi_data_available": bridge_data.get("oi_data_available", False),
        }

    # ------------------------------------------------------------------
    # 高层封装 — fetch_market_context
    # ------------------------------------------------------------------

    def fetch_market_context(self, symbol: str, **params) -> Dict[str, Any]:
        """
        获取完整市场上下文，包含 execution_state
        """
        bridge = self.fetch_bridge_snapshot(symbol, **params)
        if not bridge:
            return {"symbol": symbol, "error": "bridge data unavailable"}

        execution_state = self.extract_execution_state(bridge)
        bridge["execution_state"] = execution_state

        logger.info(
            f"[swing] {symbol} execution_state: "
            f"confidence={execution_state['confidence']}, "
            f"liquidity={execution_state['liquidity']}, "
            f"oi_available={execution_state['oi_data_available']}"
        )
        return bridge

    def fetch_market_context_batch(
        self, symbols: List[str], date: Optional[str] = None, **params
    ) -> Dict[str, Any]:
        """
        批量获取市场上下文，每条结果附加 execution_state
        """
        batch_resp = self.fetch_bridge_batch(symbols, date=date, **params)
        results = batch_resp.get("results", {})

        for sym, bridge in results.items():
            if isinstance(bridge, dict) and "error" not in bridge:
                bridge["execution_state"] = self.extract_execution_state(bridge)

        return batch_resp
