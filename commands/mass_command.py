"""
Mass Command - 批量准备命令清单与输入模板
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from rich.console import Console
from loguru import logger

from commands.base import BaseCommand
from commands.analyze_command import AnalyzeCommand
from commands.quick_command import QuickCommand
from utils.va_client import VAClient, VAClientError


class MassCommand(BaseCommand):
    """Mass 命令处理器 - 按日期批量生成输入模板与命令清单"""

    def __init__(self, console, model_client, env_vars: Dict[str, Any], va_url: str = None):
        super().__init__(console, model_client, env_vars)
        self.va_url = va_url or "http://localhost:8668"
        self.va_client = VAClient(base_url=self.va_url)
        # 复用 quick 的解析/校验逻辑
        self.quick_helper = QuickCommand(console, model_client, env_vars, va_url=self.va_url)

    @staticmethod
    def cli_entry(
        target_date: str,
        symbols: list[str] | None,
        va_url: str,
        model_config: str,
        console: Console,
    ):
        """CLI 入口方法"""
        from core.model_client import ModelClientFactory
        from utils.config_loader import config

        model_client = ModelClientFactory.create_from_config(model_config)
        env_vars = {"config": config}

        command = MassCommand(console, model_client, env_vars, va_url=va_url)

        try:
            command.execute(target_date=target_date, symbols=symbols)
        except KeyboardInterrupt:
            console.print("\n[yellow]⚠️ 用户中断[/yellow]")
            sys.exit(0)
        except ValueError as e:
            console.print(f"[red]❌ 参数错误: {e}[/red]")
            sys.exit(1)

    def execute(
        self,
        target_date: str,
        symbols: list[str] | None = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """执行批量准备流程（仅生成命令清单/输入模板）"""
        date_str = self._validate_date(target_date)
        source = "swing"
        target_symbols = self._normalize_symbols(symbols)

        try:
            rows = self.va_client.fetch_market_context_batch(
                date=date_str,
                source=source,
                symbols=target_symbols or None,
            )
        except VAClientError as e:
            self.console.print(f"[red]❌ 批量拉取失败: {e}[/red]")
            return {"status": "error", "message": str(e)}

        # 兜底过滤：即使后端返回全量，这里也只处理指定 symbols
        if target_symbols:
            target_set = set(target_symbols)
            rows = [
                row for row in rows
                if str((row or {}).get("symbol") or "").strip().upper() in target_set
            ]

        if not rows:
            self.console.print("[yellow]⚠️ 未获取到可处理的 symbols[/yellow]")
            return {
                "status": "success",
                "date": date_str,
                "source": source,
                "symbols": target_symbols,
                "processed": [],
                "failed": {},
            }

        base_input_dir = Path("data/input") / date_str
        processed = []
        failed = {}

        for row in rows:
            symbol = str((row or {}).get("symbol") or "").strip().upper()
            if not symbol:
                continue

            try:
                market_params, bridge = self.quick_helper.parse_market_context_payload(symbol, row)
                market_params = self.quick_helper._validate_params(market_params)

                env_vars = self.quick_helper.build_analysis_env(
                    market_params=market_params,
                    bridge=bridge,
                    tag="Meso"
                )

                analyze_cmd = AnalyzeCommand(self.console, self.model_client, env_vars)
                result = analyze_cmd.execute(
                    symbol=symbol,
                    mode='full',
                    market_params=market_params,
                    tag='Meso',
                    bridge=bridge,
                    base_input_dir=base_input_dir,
                    template_date_str=date_str,
                    output_date=date_str.replace("-", ""),
                    show_command_list=False,
                    show_precalc_log=False,
                    compact_output=True,
                )

                processed.append({
                    "symbol": symbol,
                    "template_path": result.get("template_path"),
                    "cache_path": result.get("cache_path"),
                    "analysis_command": result.get("analysis_command"),
                })
            except SystemExit as e:
                failed[symbol] = f"SystemExit({e.code})"
                logger.warning(f"批处理 {symbol} 失败: {failed[symbol]}")
            except Exception as e:
                failed[symbol] = str(e)
                logger.warning(f"批处理 {symbol} 失败: {e}")

        status = "success" if not failed else ("partial" if processed else "error")

        if processed:
            self.console.print("\n[green]✅ 缓存已创建:[/green]")
            for item in processed:
                cache_path = item.get("cache_path")
                symbol = item.get("symbol", "UNKNOWN")
                if cache_path:
                    self.console.print(f"[green]   {symbol}: {cache_path}[/green]")

            self.console.print("\n[cyan]命令执行分析:[/cyan]")
            for item in processed:
                command = item.get("analysis_command")
                symbol = item.get("symbol", "UNKNOWN")
                if command:
                    self.console.print(f"[cyan]   {symbol}: {command}[/cyan]")

        if status == "error":
            self.console.print(f"\n[red]❌ 批量准备失败: {len(failed)} symbols[/red]")
        elif status == "partial":
            self.console.print(f"\n[yellow]⚠️ 部分失败: {len(failed)} symbols[/yellow]")

        return {
            "status": status,
            "date": date_str,
            "source": source,
            "symbols": target_symbols,
            "processed": processed,
            "failed": failed,
            "input_dir": str(base_input_dir),
        }

    def _normalize_symbols(self, symbols: list[str] | None) -> List[str]:
        """标准化 symbols 输入（支持重复 -s 和逗号分隔）。"""
        if not symbols:
            return []

        normalized: List[str] = []
        seen = set()

        for item in symbols:
            if not item:
                continue

            for token in str(item).split(","):
                symbol = token.strip().upper()
                if not symbol or symbol in seen:
                    continue

                is_valid, _ = self.validate_symbol(symbol)
                if not is_valid:
                    raise ValueError(f"无效 symbol: {symbol}")

                seen.add(symbol)
                normalized.append(symbol)

        return normalized

    @staticmethod
    def _validate_date(target_date: str) -> str:
        if not target_date:
            return datetime.now().strftime("%Y-%m-%d")

        try:
            datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"date 必须为 YYYY-MM-DD: {target_date}") from e

        return target_date
