"""
VA API 客户端 - 从 volatility_analysis 服务获取市场参数

使用方法：
    from utils.va_client import VAClient
    
    client = VAClient()
    params = client.get_params('NVDA', vix=18.5)
    # => {'vix': 18.5, 'ivr': 63, 'iv30': 47.2, 'hv20': 40, 'earning_date': '2025-11-19'}
"""

import requests
from typing import Dict, Optional, List, Any
from loguru import logger


class VAClient:
    """
    Volatility Analysis API 客户端
    
    用于从 va 项目获取 swing 分析所需的市场参数
    """
    
    DEFAULT_BASE_URL = "http://localhost:8668"
    
    def __init__(self, base_url: str = None, timeout: int = 10):
        """
        初始化客户端
        
        Args:
            base_url: API 基础 URL，默认 http://localhost:8668
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.timeout = timeout
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        发起 HTTP 请求
        
        Args:
            method: HTTP 方法 (GET/POST)
            endpoint: API 端点路径
            **kwargs: 请求参数
            
        Returns:
            响应 JSON 数据
            
        Raises:
            VAClientError: 请求失败时抛出
        """
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault('timeout', self.timeout)
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, **kwargs)
            elif method.upper() == 'POST':
                response = requests.post(url, **kwargs)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.ConnectionError:
            raise VAClientError(
                f"无法连接到 VA 服务 ({self.base_url})。"
                f"请确保 volatility_analysis 服务正在运行。"
            )
        except requests.exceptions.Timeout:
            raise VAClientError(f"请求超时 ({self.timeout}秒)")
        except requests.exceptions.HTTPError as e:
            try:
                error_data = response.json()
                error_msg = error_data.get('error', str(e))
            except:
                error_msg = str(e)
            raise VAClientError(f"API 请求失败: {error_msg}")
        except Exception as e:
            raise VAClientError(f"请求异常: {str(e)}")

    def get_bridge_snapshot(
        self,
        symbol: str,
        vix: float | None = None,
        date: str | None = None,
    ) -> Dict[str, Any]:
        """
        获取 BridgeSnapshot，用于期限结构 + 市场上下文
        """
        params = {
            'source': 'swing'
        }
        if vix is not None:
            params["vix"] = vix
        if date is not None:
            params["date"] = date

        data = self._make_request(
            "GET",
            f"/api/bridge/params/{symbol.upper()}",
            params=params,
        )

        # VA 可能返回 {"success": true, "snapshot": {...}} 或直接返回 snapshot
        if isinstance(data, dict) and data.get("success") is False:
            raise VAClientError(data.get("error", "Unknown error"))

        if isinstance(data, dict):
            if data.get("snapshot") is not None:
                return data["snapshot"]
            if data.get("bridge") is not None:
                return data["bridge"]

        return data
    
    def get_params(self, symbol: str, vix: float = None, date: str = None) -> Dict[str, Any]:
        """
        获取单个 symbol 的市场参数
        
        Args:
            symbol: 股票代码
            vix: VIX 指数（可选，如果不提供需要后续指定）
            date: 目标日期，格式 YYYY-MM-DD（可选，默认返回最新记录）
            
        Returns:
            市场参数字典，包含:
            - vix: VIX 指数
            - ivr: IV Rank (0-100)
            - iv30: 30日隐含波动率
            - hv20: 20日历史波动率
            - earning_date: 财报日期 (YYYY-MM-DD 或 None)
            
        Raises:
            VAClientError: 获取失败时抛出
        """
        params = {}
        if vix is not None:
            params['vix'] = vix
        if date is not None:
            params['date'] = date
        
        data = self._make_request(
            'GET', 
            f'/api/swing/params/{symbol.upper()}',
            params=params
        )
        
        if not data.get('success'):
            raise VAClientError(data.get('error', 'Unknown error'))
        
        return data['params']
    
    def get_params_batch(
        self,
        symbols: List[str],
        vix: float = None,
        date: str = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        批量获取多个 symbol 的市场参数
        
        Args:
            symbols: 股票代码列表
            vix: VIX 指数（所有 symbol 共用）
            date: 目标日期，格式 YYYY-MM-DD（可选）
            
        Returns:
            字典，key 为 symbol，value 为参数字典
            
        Raises:
            VAClientError: 获取失败时抛出
        """
        payload = {'symbols': symbols}
        if vix is not None:
            payload['vix'] = vix
        if date is not None:
            payload['date'] = date
        
        data = self._make_request(
            'POST',
            '/api/swing/params/batch',
            json=payload
        )
        
        if not data.get('success'):
            raise VAClientError(data.get('error', 'Unknown error'))
        
        # 记录错误
        errors = data.get("errors")
        if errors:
            if isinstance(errors, dict):
                for sym, err in errors.items():
                    logger.warning(f"获取 {sym} 参数失败: {err}")
            elif isinstance(errors, list):
                for item in errors:
                    if isinstance(item, dict):
                        sym = str(item.get("symbol") or item.get("ticker") or "UNKNOWN").upper()
                        err = item.get("error") or item.get("message") or item
                        logger.warning(f"获取 {sym} 参数失败: {err}")
                    else:
                        logger.warning(f"批量参数错误: {item}")
        
        raw_results = data.get('results', {})
        if isinstance(raw_results, dict):
            return raw_results

        # 兼容部分服务返回 list 结构
        if isinstance(raw_results, list):
            normalized: Dict[str, Dict[str, Any]] = {}
            for row in raw_results:
                if not isinstance(row, dict):
                    continue

                symbol = str(row.get("symbol") or "").strip().upper()
                if not symbol:
                    continue

                if isinstance(row.get("params"), dict):
                    normalized[symbol] = row["params"]
                elif isinstance(row.get("market_params"), dict):
                    normalized[symbol] = row["market_params"]
                else:
                    normalized[symbol] = {
                        key: value
                        for key, value in row.items()
                        if key not in ("symbol", "bridge", "snapshot")
                    }
            return normalized

        return {}

    def fetch_market_context(
        self,
        symbol: str,
        vix: float | None = None,
        date: str | None = None,
    ) -> Dict[str, Any]:
        """
        便捷方法：优先获取 BridgeSnapshot，否则退化为市场参数
        """
        try:
            bridge = self.get_bridge_snapshot(symbol, vix=vix, date=date)
        except VAClientError:
            params = self.get_params(symbol, vix=vix, date=date)
            return {
                "market_params": params,
                "bridge": None,
            }

        ms = bridge.get("market_state", {}) or {}
        es = bridge.get("event_state", {}) or {}

        market_params = {
            "vix": vix if vix is not None else ms.get("vix"),
            "ivr": ms.get("ivr"),
            "iv30": ms.get("iv30"),
            "hv20": ms.get("hv20"),
            "iv_path": ms.get("iv_path") or "Insufficient_Data",
        }
        if es.get("earnings_date"):
            market_params["earning_date"] = es["earnings_date"]

        api_params = None
        # 如果 Bridge 缺少关键字段，尝试回退到 swing params 填充
        missing = [k for k in ("vix", "ivr", "iv30", "hv20") if market_params.get(k) is None]
        if missing:
            api_params = self.get_params(symbol, vix=vix, date=date)
            for key in ("vix", "ivr", "iv30", "hv20", "iv_path", "earning_date"):
                if market_params.get(key) is None and key in api_params:
                    market_params[key] = api_params.get(key)

        # 如果 iv_path 仍为空或标记不足，尝试用 swing params 补齐
        if not market_params.get("iv_path") or market_params.get("iv_path") == "Insufficient_Data":
            if api_params is None:
                api_params = self.get_params(symbol, vix=vix, date=date)
            if api_params.get("iv_path"):
                market_params["iv_path"] = api_params["iv_path"]

        return {
            "market_params": market_params,
            "bridge": bridge,
        }

    def fetch_market_context_batch(
        self,
        date: str,
        source: str = "swing",
        vix: float | None = None,
        symbols: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """
        批量获取市场上下文，优先 bridge batch，失败时退化到 swing batch。
        返回统一结构:
        [
          {"symbol": "NVDA", "market_params": {...}, "bridge": {...}|None}
        ]
        """
        payload = {
            "date": date,
            "source": source,
        }
        if vix is not None:
            payload["vix"] = vix
        if symbols:
            payload["symbols"] = [str(s).upper() for s in symbols if str(s).strip()]

        # 1) 优先 bridge batch
        try:
            data = self._make_request("POST", "/api/bridge/batch", json=payload)
            # 业务约定：bridge batch 返回 count=0 时视为“无任务”，直接返回空结果
            if isinstance(data, dict):
                count = data.get("count")
                if count is not None:
                    try:
                        if int(count) == 0:
                            return []
                    except (TypeError, ValueError):
                        pass
            normalized = self._normalize_batch_response(data)
            if normalized:
                return normalized
        except VAClientError as e:
            logger.warning(f"/api/bridge/batch 不可用，尝试 swing batch: {e}")

        # 2) 尝试 swing batch（如果服务支持无 symbols 的批量入口）
        try:
            data = self._make_request("POST", "/api/swing/params/batch", json=payload)
            normalized = self._normalize_batch_response(data)
            if normalized:
                return normalized
        except VAClientError as e:
            logger.warning(f"无 symbols 的 swing batch 不可用，回退 list_symbols+batch: {e}")

        # 3) 回退：先拉 symbols，再调用已存在的 swing params batch
        target_symbols = symbols or self.list_symbols()
        if not target_symbols:
            raise VAClientError("批量请求失败: 无可用 symbols")

        results = self.get_params_batch(symbols=target_symbols, vix=vix, date=date)
        fallback_rows = self._to_market_context_rows(results)
        if fallback_rows:
            return fallback_rows

        raise VAClientError("批量请求失败: 返回结果为空或格式不兼容")

    def _normalize_batch_response(self, data: Any) -> List[Dict[str, Any]]:
        """将多种批量响应格式归一化为统一列表结构"""
        if not data:
            return []

        if isinstance(data, dict) and data.get("success") is False:
            raise VAClientError(data.get("error", "Unknown error"))

        payload = data
        if isinstance(data, dict):
            for key in ("results", "items", "data", "snapshots", "batch"):
                if key in data and data.get(key) is not None:
                    payload = data.get(key)
                    break

        rows = self._coerce_rows(payload)
        normalized_rows = []

        for row in rows:
            if not isinstance(row, dict):
                continue

            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue

            entry = dict(row)
            entry["symbol"] = symbol
            normalized_rows.append(entry)

        return normalized_rows

    def _coerce_rows(self, payload: Any) -> List[Dict[str, Any]]:
        """将 list/dict 映射为统一 row 列表"""
        if isinstance(payload, list):
            return payload

        if not isinstance(payload, dict):
            return []

        # 形如 {"NVDA": {...}, "AAPL": {...}}
        if payload and all(isinstance(v, dict) for v in payload.values()):
            if "symbol" in payload and any(k in payload for k in ("market_params", "bridge", "params", "snapshot")):
                return [payload]

            rows = []
            for symbol, item in payload.items():
                row = dict(item)
                row.setdefault("symbol", symbol)
                rows.append(row)
            return rows

        # 单对象场景
        if "symbol" in payload:
            return [payload]

        return []

    def _to_market_context_rows(self, results: Any) -> List[Dict[str, Any]]:
        """
        将 batch 结果（dict/list）转换为标准 market context 行。
        标准格式:
        [{"symbol": "NVDA", "market_params": {...}, "bridge": {...}|None}]
        """
        rows: List[Dict[str, Any]] = []

        if isinstance(results, dict):
            iterable = results.items()
            for symbol, item in iterable:
                symbol_str = str(symbol or "").strip().upper()
                if not symbol_str or not isinstance(item, dict):
                    continue

                if isinstance(item.get("market_params"), dict):
                    market_params = item["market_params"]
                elif isinstance(item.get("params"), dict):
                    market_params = item["params"]
                else:
                    market_params = item

                bridge = item.get("bridge") if isinstance(item.get("bridge"), dict) else None
                rows.append({
                    "symbol": symbol_str,
                    "market_params": market_params,
                    "bridge": bridge,
                })
            return rows

        if isinstance(results, list):
            for row in results:
                if not isinstance(row, dict):
                    continue

                symbol = str(row.get("symbol") or "").strip().upper()
                if not symbol:
                    continue

                if isinstance(row.get("market_params"), dict):
                    market_params = row["market_params"]
                elif isinstance(row.get("params"), dict):
                    market_params = row["params"]
                else:
                    market_params = {
                        key: value
                        for key, value in row.items()
                        if key not in ("symbol", "bridge", "snapshot")
                    }

                bridge = row.get("bridge") if isinstance(row.get("bridge"), dict) else None
                rows.append({
                    "symbol": symbol,
                    "market_params": market_params,
                    "bridge": bridge,
                })

        return rows
    
    def list_symbols(self) -> List[str]:
        """
        获取所有可用的 symbol 列表
        
        Returns:
            symbol 列表
        """
        data = self._make_request('GET', '/api/swing/symbols')
        return data.get('symbols', [])
    
    def list_symbol_dates(self, symbol: str) -> List[str]:
        """
        获取指定 symbol 的所有可用日期
        
        Args:
            symbol: 股票代码
            
        Returns:
            日期列表（降序排列）
        """
        data = self._make_request('GET', f'/api/swing/dates/{symbol.upper()}')
        return data.get('dates', [])
    
    def is_available(self) -> bool:
        """
        检查 VA 服务是否可用
        
        Returns:
            True 如果服务可用，否则 False
        """
        try:
            self._make_request('GET', '/api/swing/symbols')
            return True
        except VAClientError:
            return False


class VAClientError(Exception):
    """VA API 客户端异常"""
    pass


# ============================================================
# 便捷函数
# ============================================================

_default_client: VAClient = None


def get_default_client() -> VAClient:
    """获取默认客户端实例（单例）"""
    global _default_client
    if _default_client is None:
        _default_client = VAClient()
    return _default_client


def fetch_market_params(symbol: str, vix: float = None, date: str = None) -> Dict[str, Any]:
    """
    便捷函数：获取市场参数
    
    Args:
        symbol: 股票代码
        vix: VIX 指数
        date: 目标日期 (YYYY-MM-DD)
        
    Returns:
        市场参数字典
    """
    return get_default_client().get_params(symbol, vix, date)


def fetch_market_context(symbol: str, vix: float | None = None, date: str | None = None) -> Dict[str, Any]:
    """
    便捷函数：优先获取 BridgeSnapshot，否则退化为市场参数

    Returns:
        {
          "market_params": {...},
          "bridge": BridgeSnapshot or None
        }
    """
    client = get_default_client()
    return client.fetch_market_context(symbol, vix=vix, date=date)


def is_va_service_running() -> bool:
    """检查 VA 服务是否在运行"""
    return get_default_client().is_available()
