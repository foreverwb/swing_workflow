"""
Refresh 命令处理器
处理盘中快照刷新
"""

import sys
from pathlib import Path
from typing import Dict, Any
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .base import BaseCommand


class RefreshCommand(BaseCommand):
    """Refresh 命令处理器"""
    
    def execute(
        self,
        symbol: str,
        folder: str,
        cache: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行刷新快照
        
        Args:
            symbol: 股票代码
            folder: 数据文件夹路径
            cache: 缓存文件名（必需）
            
        Returns:
            执行结果字典
        """
        # ============= 1. 参数验证 =============
        
        # 1.1 验证股票代码
        is_valid, result = self.validate_symbol(symbol)
        if not is_valid:
            self.print_error(result)
            sys.exit(1)
        
        # 1.2 验证缓存文件（必需）
        if not cache:
            self.print_error("refresh 模式必须指定 --cache 参数")
            self._print_usage_hint(symbol)
            sys.exit(1)
        
        is_valid, error_msg, cache_info = self.validate_cache_file(cache, symbol)
        if not is_valid:
            self.print_error("缓存文件验证失败")
            self.console.print(f"[red]   {error_msg}[/red]")
            self._print_troubleshooting(symbol, cache)
            sys.exit(1)
        
        # 1.3 验证 source_target 完整性
        if not cache_info["has_source_target"]:
            self.print_error("缓存文件缺少初始分析数据 (source_target)")
            self._print_source_target_missing(cache_info, symbol, cache)
            sys.exit(1)
        
        # 1.4 显示缓存信息
        self._print_cache_info(cache_info)
        
        # 1.5 验证文件夹
        folder_path = Path(folder)
        is_valid, msg = self.validate_folder(folder_path)
        if not is_valid:
            self.print_error(msg)
            sys.exit(1)
        
        # ============= 2. 打印标题 =============
        self.console.print(Panel.fit(
            f"[bold cyan]📸 盘中快照: {symbol.upper()}[/bold cyan]\n"
            f"[dim]仅运行 Agent3 + 计算引擎[/dim]",
            border_style="cyan"
        ))
        
        self.console.print(f"[dim]📊 {msg}[/dim]")
        
        # ============= 3. 执行刷新 =============
        engine = self.create_engine(cache_file=cache)
        
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                task = progress.add_task("正在刷新数据...", total=None)
                
                result = engine.run(
                    symbol=symbol.upper(),
                    data_folder=folder_path,
                    mode="refresh"
                )
                
                progress.update(task, completed=True)
            
            # ============= 4. 显示结果 =============
            return self._handle_result(result, symbol)
        
        except Exception as e:
            self.print_error(str(e))
            sys.exit(1)
    
    # ============= 私有辅助方法 =============
    
    def _print_usage_hint(self, symbol: str):
        """打印使用提示"""
        self.console.print(f"\n[yellow]💡 提示:[/yellow]")
        self.console.print(f"[cyan]   python app.py refresh -s {symbol.upper()} -f <folder> --cache {symbol.upper()}_20251129.json[/cyan]")
        self.console.print(f"\n[dim]提示: 可用的缓存文件位于 data/output/{symbol.upper()}/ 目录下[/dim]")
    
    def _print_troubleshooting(self, symbol: str, cache: str):
        """打印故障排查信息"""
        self.console.print(f"\n[yellow]💡 提示:[/yellow]")
        self.console.print(f"[yellow]   1. 确保文件名格式正确: {{SYMBOL}}_{{YYYYMMDD}}.json[/yellow]")
        self.console.print(f"[yellow]   2. 确保文件存在于: data/output/{symbol.upper()}/[/yellow]")
        self.console.print(f"[yellow]   3. 使用 'python app.py analyze -s {symbol.upper()} -f <folder>' 先创建初始分析[/yellow]")
    
    def _print_source_target_missing(self, cache_info: Dict, symbol: str, cache: str):
        """打印 source_target 缺失信息"""
        self.console.print(f"\n[yellow]⚠️ 当前缓存状态:[/yellow]")
        self.console.print(f"[yellow]   • 文件: {cache}[/yellow]")
        self.console.print(f"[yellow]   • 快照数量: {cache_info['snapshot_count']}[/yellow]")
        self.console.print(f"[yellow]   • source_target: null[/yellow]")
        
        self.console.print(f"\n[yellow]💡 解决方案:[/yellow]")
        self.console.print(f"[yellow]   必须先执行完整分析以生成 source_target:[/yellow]")
        self.console.print(f"[cyan]   python app.py analyze -s {symbol.upper()} -f <初始数据文件夹> --cache {cache}[/cyan]")
        
        self.console.print(f"\n[dim]   说明: refresh 模式用于盘中更新，必须在完整分析后使用[/dim]")
    
    def _print_cache_info(self, cache_info: Dict):
        """打印缓存验证信息"""
        self.console.print(f"\n[green]✅ 缓存文件验证通过[/green]")
        self.console.print(f"[dim]   股票代码: {cache_info['symbol']}[/dim]")
        self.console.print(f"[dim]   分析日期: {cache_info['start_date']}[/dim]")
        self.console.print(f"[dim]   已有快照: {cache_info['snapshot_count']} 个[/dim]")
        self.console.print(f"[dim]   source_target: 完整[/dim]")
    
    def _handle_result(self, result: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        """处理刷新结果"""
        status = result.get("status")
        
        if status != "success":
            self.print_error(f"刷新失败: {result.get('message', '未知错误')}")
            return result
        
        # 显示成功信息
        self.console.print("\n[green]✅ 快照已保存![/green]\n")
        
        # 提取快照摘要
        snapshot = result.get("snapshot", {})
        
        self.console.print(Panel(
            self._format_snapshot_summary(snapshot),
            title="📊 快照摘要",
            border_style="green"
        ))
        
        # 显示变化
        changes = snapshot.get("changes")
        if changes:
            self.console.print("\n[yellow]📈 数据变化:[/yellow]")
            for field, change in changes.items():
                emoji = self._get_change_emoji(change.get("change_pct", 0))
                pct_str = f" ({change['change_pct']:+.2f}%)" if "change_pct" in change else ""
                self.console.print(f"  {emoji} {field}: {change['old']} → {change['new']}{pct_str}")
        else:
            self.console.print("\n[dim]ℹ️ 首次快照，无历史对比[/dim]")
        
        # 提示查看历史
        self.console.print(f"\n[dim]💡 查看历史快照: python app.py history -s {symbol.upper()}[/dim]")
        
        return result
    
    def _format_snapshot_summary(self, snapshot: Dict) -> str:
        """格式化快照摘要"""
        snapshot_id = snapshot.get("snapshot_id", "N/A")
        timestamp = snapshot.get("timestamp", "")[:19]
        
        # 提取 targets 数据
        targets = snapshot.get("targets", {})
        spot_price = targets.get("spot_price", "N/A")
        em1_dollar = targets.get("em1_dollar", "N/A")
        
        gamma_metrics = targets.get("gamma_metrics", {})
        vol_trigger = gamma_metrics.get("vol_trigger", "N/A")
        spot_vs_trigger = gamma_metrics.get("spot_vs_trigger", "N/A")
        
        return (
            f"[bold]快照 #{snapshot_id}[/bold]\n"
            f"时间: {timestamp}\n"
            f"现价: ${spot_price}\n"
            f"EM1$: ${em1_dollar}\n"
            f"Vol Trigger: ${vol_trigger}\n"
            f"状态: {spot_vs_trigger}"
        )
    
    def _get_change_emoji(self, change_pct: float) -> str:
        """根据变化百分比返回表情符号"""
        if change_pct > 0:
            return "🔺"
        elif change_pct < 0:
            return "🔻"
        else:
            return "➡️"