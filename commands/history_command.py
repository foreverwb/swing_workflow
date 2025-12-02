"""
History 命令处理器
查看历史快照
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any
from rich.table import Table

from .base import BaseCommand


class HistoryCommand(BaseCommand):
    """History 命令处理器"""
    
    def execute(
        self,
        symbol: str,
        format: str = 'table',
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行查看历史快照
        
        Args:
            symbol: 股票代码
            format: 输出格式（table/json）
            
        Returns:
            执行结果字典
        """
        # ============= 1. 验证股票代码 =============
        is_valid, result = self.validate_symbol(symbol)
        if not is_valid:
            self.print_error(result)
            sys.exit(1)
        
        # ============= 2. 加载缓存文件 =============
        cache_file = Path(f"data/cache/{symbol.upper()}_analysis.json")
        
        if not cache_file.exists():
            self.print_error(f"未找到 {symbol.upper()} 的历史数据")
            self.console.print(f"[dim]请先运行: python app.py analyze -s {symbol.upper()} -f <folder>[/dim]")
            sys.exit(1)
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            cached = json.load(f)
        
        # ============= 3. 提取快照数据 =============
        snapshots = cached.get("greeks_snapshots", [])
        
        if not snapshots:
            self.print_warning(f"{symbol.upper()} 尚无快照记录")
            return {"status": "success", "snapshots": []}
        
        # ============= 4. 显示结果 =============
        if format == 'json':
            self._print_json_format(snapshots)
        else:
            self._print_table_format(symbol, snapshots, cached)
        
        return {"status": "success", "snapshots": snapshots}
    
    # ============= 私有辅助方法 =============
    
    def _print_json_format(self, snapshots: list):
        """打印 JSON 格式"""
        self.console.print_json(data=snapshots)
    
    def _print_table_format(self, symbol: str, snapshots: list, cached: dict):
        """打印表格格式"""
        table = Table(title=f"📊 {symbol.upper()} 快照历史 ({len(snapshots)} 条记录)")
        
        # 添加列
        table.add_column("ID", justify="center", style="cyan")
        table.add_column("时间", style="dim")
        table.add_column("现价", justify="right", style="green")
        table.add_column("EM1$", justify="right")
        table.add_column("Vol Trigger", justify="right")
        table.add_column("状态", justify="center")
        table.add_column("备注")
        
        # 添加行
        for snap in snapshots:
            table.add_row(
                str(snap["snapshot_id"]),
                snap["timestamp"][:16],
                f"${snap.get('spot_price', 0):.2f}" if snap.get('spot_price') else "N/A",
                f"${snap.get('em1_dollar', 0):.2f}" if snap.get('em1_dollar') else "N/A",
                f"${snap.get('vol_trigger', 0):.2f}" if snap.get('vol_trigger') else "N/A",
                snap.get("spot_vs_trigger", "N/A"),
                snap.get("note", "")
            )
        
        self.console.print(table)
        
        # 显示统计
        self.console.print(f"\n[dim]创建时间: {cached.get('created_at', 'N/A')}")
        self.console.print(f"最后更新: {cached.get('last_updated', 'N/A')}[/dim]")