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
    
    def get_params(self, symbol: str, vix: float = None) -> Dict[str, Any]:
        """
        获取单个 symbol 的市场参数
        
        Args:
            symbol: 股票代码
            vix: VIX 指数（可选，如果不提供需要后续指定）
            
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
        vix: float = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        批量获取多个 symbol 的市场参数
        
        Args:
            symbols: 股票代码列表
            vix: VIX 指数（所有 symbol 共用）
            
        Returns:
            字典，key 为 symbol，value 为参数字典
            
        Raises:
            VAClientError: 获取失败时抛出
        """
        data = self._make_request(
            'POST',
            '/api/swing/params/batch',
            json={'symbols': symbols, 'vix': vix}
        )
        
        if not data.get('success'):
            raise VAClientError(data.get('error', 'Unknown error'))
        
        # 记录错误
        if data.get('errors'):
            for sym, err in data['errors'].items():
                logger.warning(f"获取 {sym} 参数失败: {err}")
        
        return data.get('results', {})
    
    def list_symbols(self) -> List[str]:
        """
        获取所有可用的 symbol 列表
        
        Returns:
            symbol 列表
        """
        data = self._make_request('GET', '/api/swing/symbols')
        return data.get('symbols', [])
    
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


def fetch_market_params(symbol: str, vix: float = None) -> Dict[str, Any]:
    """
    便捷函数：获取市场参数
    
    Args:
        symbol: 股票代码
        vix: VIX 指数
        
    Returns:
        市场参数字典
    """
    return get_default_client().get_params(symbol, vix)


def is_va_service_running() -> bool:
    """检查 VA 服务是否在运行"""
    return get_default_client().is_available()


# ============================================================
# 示例用法
# ============================================================

if __name__ == '__main__':
    # 测试连接
    client = VAClient()
    
    print("=" * 50)
    print("VA API Client 测试")
    print("=" * 50)
    
    # 1. 检查服务可用性
    print(f"\n服务状态: {'✅ 可用' if client.is_available() else '❌ 不可用'}")
    
    if not client.is_available():
        print("\n请先启动 volatility_analysis 服务:")
        print("  cd volatility_analysis && python app.py")
        exit(1)
    
    # 2. 获取可用 symbol 列表
    symbols = client.list_symbols()
    print(f"\n可用 symbols ({len(symbols)}个): {', '.join(symbols[:5])}...")
    
    # 3. 获取单个 symbol 的参数
    if symbols:
        test_symbol = symbols[0]
        try:
            params = client.get_params(test_symbol, vix=18.5)
            print(f"\n{test_symbol} 的市场参数:")
            for k, v in params.items():
                print(f"  {k}: {v}")
        except VAClientError as e:
            print(f"获取 {test_symbol} 参数失败: {e}")
    
    # 4. 批量获取
    if len(symbols) > 1:
        batch_symbols = symbols[:3]
        results = client.get_params_batch(batch_symbols, vix=18.5)
        print(f"\n批量获取结果 ({len(results)}个):")
        for sym, params in results.items():
            print(f"  {sym}: IVR={params['ivr']}, IV30={params['iv30']}")