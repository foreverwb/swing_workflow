"""
VA / Bridge Provider Client — swing_workflow
v2.1: 全量收敛到 /api/bridge/batch（source=swing）并做协议强校验
"""

import os
import logging
import yaml
import httpx
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8668"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "env_config.yaml")

# 请求来源标识 — option_provider 日志中显示为 [swing]
REQUEST_SOURCE = "swing"
SWING_MARKET_PARAM_FIELDS = (
    "vix",
    "ivr",
    "iv30",
    "hv20",
    "iv_path",
    "earning_date",
    "beta",
)


class VAClientError(RuntimeError):
    """Base error for VAClient failures."""


class VAClientRequestError(VAClientError):
    """HTTP transport/request error."""


class VAClientProtocolError(VAClientError):
    """Raised when API response violates expected contract."""


def parse_swing_batch_rows(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    将 batch results(list) 解析为 {SYMBOL: {"market_params": ..., "bridge": ...}}。

    协议约束:
    - results 必须是 list
    - 每个 row 必须包含 symbol(str), market_params(dict), bridge(dict)
    """
    if not isinstance(results, list):
        raise VAClientProtocolError("Protocol violation: 'results' must be a list")

    parsed: Dict[str, Dict[str, Any]] = {}
    for idx, row in enumerate(results):
        if not isinstance(row, dict):
            raise VAClientProtocolError(f"Batch row[{idx}] must be an object")

        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise VAClientProtocolError(f"Batch row[{idx}] missing valid 'symbol'")

        market_params = row.get("market_params")
        if not isinstance(market_params, dict):
            raise VAClientProtocolError(
                f"Batch row[{idx}] missing required 'market_params' object"
            )

        bridge = row.get("bridge")
        if not isinstance(bridge, dict):
            raise VAClientProtocolError(
                f"Batch row[{idx}] missing required 'bridge' object"
            )

        parsed[symbol.strip().upper()] = {
            "market_params": market_params,
            "bridge": bridge,
        }
    return parsed


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

    @staticmethod
    def _resolve_trust_env(url: str, explicit_trust_env: Optional[bool] = None) -> bool:
        """
        Disable proxy env for localhost/loopback by default.
        This avoids local provider requests being routed to corporate HTTP proxies.
        """
        if explicit_trust_env is not None:
            return explicit_trust_env

        host = urlparse(url).hostname
        if host in {"localhost", "127.0.0.1", "::1"}:
            return False
        return True

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """
        发送请求，自动附加 X-Request-Source 头。
        主 URL 失败时尝试 fallback。
        """
        headers = kwargs.pop("headers", {})
        headers["X-Request-Source"] = self.source
        explicit_trust_env = kwargs.pop("trust_env", None)

        url = f"{self.base_url}{path}"
        try:
            logger.debug(f"[swing] {method.upper()} {url}")
            resp = httpx.request(
                method,
                url,
                headers=headers,
                timeout=self.timeout,
                trust_env=self._resolve_trust_env(url, explicit_trust_env),
                **kwargs,
            )
            resp.raise_for_status()
            return resp
        except (httpx.HTTPError, httpx.ConnectError) as e:
            logger.warning(f"[swing] 主 URL 请求失败: {url} -> {e}")
            if self.fallback_url and self.fallback_url != self.base_url:
                fallback = f"{self.fallback_url}{path}"
                logger.info(f"[swing] 尝试 fallback: {fallback}")
                resp = httpx.request(
                    method,
                    fallback,
                    headers=headers,
                    timeout=self.timeout,
                    trust_env=self._resolve_trust_env(fallback, explicit_trust_env),
                    **kwargs,
                )
                resp.raise_for_status()
                return resp
            raise

    def _request_json(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = self._request(method, path, **kwargs)
            return resp.json()
        except (httpx.HTTPError, httpx.ConnectError) as exc:
            raise VAClientRequestError(str(exc)) from exc
        except ValueError as exc:
            raise VAClientProtocolError(f"Invalid JSON from {path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Bridge API 调用
    # ------------------------------------------------------------------

    def fetch_bridge_batch(
        self,
        source: str = REQUEST_SOURCE,
        date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        统一批量入口：POST /api/bridge/batch

        强制协议:
        - 响应必须是 dict
        - results 必须是 list（否则抛 VAClientProtocolError）
        """
        body: Dict[str, Any] = {"source": source}
        if date:
            body["date"] = date
        if symbols is not None:
            body["symbols"] = symbols
        body.update(kwargs)

        data = self._request_json("POST", "/api/bridge/batch", json=body)
        if not isinstance(data, dict):
            raise VAClientProtocolError("Batch response must be an object")
        results = data.get("results", [])
        if not isinstance(results, list):
            raise VAClientProtocolError("Protocol violation: 'results' must be a list")
        data["results"] = results
        logger.info(f"[swing] bridge batch 获取成功: source={source} count={len(results)}")
        return data

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
    # 高层封装 — fetch_market_context_batch
    # ------------------------------------------------------------------

    def fetch_market_context_batch(
        self,
        symbols: List[str],
        date: Optional[str] = None,
        source: str = REQUEST_SOURCE,
        **params,
    ) -> Dict[str, Any]:
        """
        批量获取市场上下文，每条 row.bridge 附加 execution_state。
        """
        batch_resp = self.fetch_bridge_batch(
            source=source,
            date=date,
            symbols=symbols,
            **params,
        )
        parsed = parse_swing_batch_rows(batch_resp.get("results", []))
        for payload in parsed.values():
            bridge = payload["bridge"]
            if "error" not in bridge:
                bridge["execution_state"] = self.extract_execution_state(bridge)

        return batch_resp