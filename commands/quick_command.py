"""
Quick Command - 快速分析命令
自动从 VA API 获取市场参数，执行分析流程
"""

import sys
from datetime import datetime
from typing import Dict, Any

from rich.console import Console
from loguru import logger

from commands.base import BaseCommand
from commands.analyze_command import AnalyzeCommand
from utils.va_client import VAClient, VAClientError
from core.workflow import CacheManager


class QuickCommand(BaseCommand):
    """Quick 命令处理器"""
    
    def __init__(self, console, model_client, env_vars: Dict[str, Any], va_url: str = None):
        """
        初始化 Quick 命令
        
        Args:
            console: Rich 控制台
            model_client: 模型客户端
            env_vars: 环境变量
            va_url: VA API 服务地址
        """
        super().__init__(console, model_client, env_vars)
        self.va_url = va_url or "http://localhost:8668"
        self.va_client = VAClient(base_url=self.va_url)
    
    @staticmethod
    def cli_entry(
        symbol: str,
        vix: float,
        target_date: str,
        folder: str,
        cache: str,
        output: str,
        va_url: str,
        model_config: str,
        console: Console
    ):
        """
        CLI 入口方法
        
        Args:
            symbol: 股票代码
            vix: VIX 指数
            target_date: 目标日期
            folder: 数据文件夹路径
            cache: 缓存文件名
            output: 输出文件路径
            va_url: VA API 服务地址
            model_config: 模型配置文件路径
            console: Rich 控制台
        """
        from core.model_client import ModelClientFactory
        from utils.config_loader import config
        
        model_client = ModelClientFactory.create_from_config(model_config)
        env_vars = {'config': config}
        
        command = QuickCommand(console, model_client, env_vars, va_url=va_url)
        
        try:
            command.execute(
                symbol=symbol,
                vix=vix,
                target_date=target_date,
                folder=folder,
                cache=cache,
                output=output
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]⚠️ 用户中断[/yellow]")
            sys.exit(0)
    
    def execute(
        self,
        symbol: str,
        vix: float = None,
        target_date: str = None,
        folder: str = None,
        cache: str = None,
        output: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行快速分析命令
        
        Args:
            symbol: 股票代码
            vix: VIX 指数（可选）
            target_date: 目标日期（可选）
            folder: 数据文件夹路径
            cache: 缓存文件名
            output: 输出文件路径
        """
        symbol = symbol.upper()
        
        self.console.print(f"\n[bold cyan]🚀 Swing Quant - 快速分析 {symbol}[/bold cyan]")
        
        # 1. 从 VA API 获取参数
        try:
            market_params, bridge = self._fetch_market_context(symbol, vix, target_date)
        except VAClientError as e:
            self.console.print(f"[red]❌ VA API 调用失败: {e}[/red]")
            return {"status": "error", "message": str(e)}
        
        # 2. 验证参数
        try:
            market_params = self._validate_params(market_params)
            # 验证通过后才打印成功消息
            self.console.print(f"[green]✅ 参数获取成功[/green]")
            self.console.print(f"[dim]   VIX={market_params['vix']}, IVR={market_params['ivr']}, VRP={market_params['iv30']/market_params['hv20']:.2f}[/dim]")
        except ValueError as e:
            self.console.print(f"[red]❌ 参数验证失败: {e}[/red]")
            return {"status": "error", "message": str(e)}
        
        # 3. 准备环境变量
        output_date = self._resolve_output_date(target_date)
        env_vars = self.build_analysis_env(
            market_params=market_params,
            bridge=bridge,
            tag='Meso',
            start_date=output_date,
        )
        
        # 4. 如果有缓存文件，加载动态参数
        if folder and cache:
            try:
                cache_manager = CacheManager()
                cached = cache_manager.load_market_params_from_cache(symbol, cache)
                if cached:
                    env_vars['dyn_params'] = cached.get('dyn_params', {})
            except Exception as e:
                logger.warning(f"加载缓存参数失败: {e}")
        
        # 5. 调用 AnalyzeCommand 执行分析
        analyze_cmd = AnalyzeCommand(self.console, self.model_client, env_vars)
        
        return analyze_cmd.execute(
            symbol=symbol,
            folder=folder,
            output=output,
            mode='full',
            cache=cache,
            market_params=market_params,
            dyn_params=env_vars.get('dyn_params'),
            tag='Meso',
            bridge=bridge,
            output_date=output_date,
        )
    
    def build_analysis_env(
        self,
        market_params: Dict[str, Any],
        bridge: Dict[str, Any] | None = None,
        tag: str = 'Meso',
        dyn_params: Dict[str, Any] | None = None,
        start_date: str | None = None,
    ) -> Dict[str, Any]:
        """构建 AnalyzeCommand 所需环境上下文"""
        env = {
            'config': self.env_vars.get('config'),
            'market_params': market_params,
            'bridge': bridge,
            'tag': tag
        }
        if dyn_params:
            env['dyn_params'] = dyn_params
        if start_date:
            env['start_date'] = start_date
        return env

    def parse_market_context_payload(
        self,
        symbol: str,
        payload: Dict[str, Any],
        vix: float = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
        """
        统一解析市场上下文载荷（用于 quick / mass）
        支持 market_params / bridge snapshot / params 三种形态。
        """
        if not isinstance(payload, dict):
            raise ValueError(f"{symbol}: 无效上下文载荷类型")

        bridge = payload.get("bridge")
        market_params = payload.get("market_params")

        snapshot = payload.get("snapshot")
        if not bridge and isinstance(snapshot, dict):
            bridge = snapshot

        if not bridge and self._looks_like_bridge_snapshot(payload):
            bridge = payload

        if not market_params and isinstance(payload.get("params"), dict):
            market_params = payload.get("params")

        if not market_params and self._looks_like_market_params(payload):
            market_params = payload

        if bridge and not market_params:
            market_params = self._build_market_params_from_bridge(bridge, vix=vix)

        if bridge and market_params:
            bridge_params = self._build_market_params_from_bridge(bridge, vix=vix)
            merged = dict(market_params)
            for key, value in bridge_params.items():
                if merged.get(key) is None:
                    merged[key] = value
            market_params = merged

        if not market_params:
            raise ValueError(f"{symbol}: 上下文中缺少 market_params")

        normalized = self._normalize_market_params(market_params, vix=vix)
        return normalized, bridge
    
    def _fetch_market_context(self, symbol: str, vix: float = None, target_date: str = None) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
        """获取市场上下文（Bridge + 市场参数）"""
        try:
            ctx = self.va_client.fetch_market_context(symbol, vix=vix, date=target_date)
            return self.parse_market_context_payload(symbol, ctx, vix=vix)
        except VAClientError:
            api_params = self.va_client.get_params(symbol, vix=vix, date=target_date)
            return self.parse_market_context_payload(
                symbol=symbol,
                payload={"market_params": api_params},
                vix=vix,
            )

    @staticmethod
    def _looks_like_bridge_snapshot(payload: Dict[str, Any]) -> bool:
        return "market_state" in payload or "term_structure" in payload or "event_state" in payload

    @staticmethod
    def _looks_like_market_params(payload: Dict[str, Any]) -> bool:
        return all(k in payload for k in ("ivr", "iv30", "hv20"))

    @staticmethod
    def _build_market_params_from_bridge(bridge: Dict[str, Any], vix: float = None) -> Dict[str, Any]:
        ms = bridge.get("market_state", {}) or {}
        es = bridge.get("event_state", {}) or {}
        params = {
            "vix": vix if vix is not None else ms.get("vix"),
            "ivr": ms.get("ivr"),
            "iv30": ms.get("iv30"),
            "hv20": ms.get("hv20"),
            "iv_path": ms.get("iv_path") or "Insufficient_Data",
        }
        if es.get("earnings_date"):
            params["earning_date"] = es.get("earnings_date")
        return params

    @staticmethod
    def _normalize_market_params(raw_params: Dict[str, Any], vix: float = None) -> Dict[str, Any]:
        params = {
            "vix": vix if vix is not None else raw_params.get("vix"),
            "ivr": raw_params.get("ivr"),
            "iv30": raw_params.get("iv30"),
            "hv20": raw_params.get("hv20"),
            "iv_path": raw_params.get("iv_path", "Insufficient_Data"),
        }
        if raw_params.get("earning_date"):
            params["earning_date"] = raw_params.get("earning_date")
        return params

    @staticmethod
    def _resolve_output_date(target_date: str | None = None) -> str:
        """
        解析输出目录日期，统一为 YYYYMMDD。
        - 指定 target_date: 支持 YYYY-MM-DD / YYYYMMDD
        - 未指定: 使用当前日期
        """
        if not target_date:
            return datetime.now().strftime("%Y%m%d")

        date_str = str(target_date).strip()
        if not date_str:
            return datetime.now().strftime("%Y%m%d")

        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(date_str, fmt).strftime("%Y%m%d")
            except ValueError:
                continue

        # 兜底保留旧行为（由下游默认当天），同时避免抛错影响 quick
        return datetime.now().strftime("%Y%m%d")
    
    def _validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """验证市场参数"""
        required = ['vix', 'ivr', 'iv30', 'hv20']
        missing = [k for k in required if k not in params or params[k] is None]
        
        if missing:
            # 对 vix 缺失提供更清晰的提示
            if 'vix' in missing:
                raise ValueError(
                    f"缺少必需参数: {', '.join(missing)}。"
                    f"VA API 未返回 VIX 值，请使用 -v 参数手动指定"
                )
            raise ValueError(f"缺少必需参数: {', '.join(missing)}")
        
        params['vix'] = float(params['vix'])
        params['ivr'] = float(params['ivr'])
        params['iv30'] = float(params['iv30'])
        params['hv20'] = float(params['hv20'])
        
        if not (0 <= params['ivr'] <= 100):
            raise ValueError(f"IVR 必须在 0-100 之间，当前值: {params['ivr']}")
        if params['vix'] < 0 or params['iv30'] < 0 or params['hv20'] <= 0:
            raise ValueError("VIX/IV30/HV20 必须为正数")
        
        # 验证 iv_path
        if params.get('iv_path'):
            valid_iv_paths = ['Rising', 'Falling', 'Flat', 'Insufficient_Data']
            iv_path = str(params['iv_path']).strip()
            if iv_path not in valid_iv_paths:
                params['iv_path'] = 'Insufficient_Data'
            else:
                params['iv_path'] = iv_path
        else:
            params['iv_path'] = 'Insufficient_Data'
        
        return params
