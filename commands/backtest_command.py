"""
Backtest 命令处理器 (v2.0 实装版)
功能：加载历史分析 -> 输入当前价格 -> 计算策略理论 PnL
"""

import json
import sys
import math
from pathlib import Path
from typing import Dict, Any
from rich.panel import Panel
from rich.table import Table
from .base import BaseCommand

class BacktestCommand(BaseCommand):
    """Backtest 命令处理器"""
    
    def execute(
        self,
        symbol: str,
        test_date: str, # 实际只需日期字符串，用于定位文件
        folder: str,    # 保留接口，暂不使用
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行回测
        
        Args:
            symbol: 股票代码
            test_date: 历史分析的日期 (YYYYMMDD)
            price: (kwargs) 当前/平仓时的实际股价
            iv: (kwargs) 当前/平仓时的实际IV (可选)
        """
        current_price = kwargs.get('price')
        current_iv = kwargs.get('iv')
        
        if not current_price:
            self.print_error("必须指定当前价格: --price <float>")
            sys.exit(1)
            
        # 1. 加载历史分析
        # 路径格式: data/output/{SYMBOL}/{DATE}/{SYMBOL}_o_{DATE}.json
        cache_file = Path(f"data/output/{symbol.upper()}/{test_date}/{symbol.upper()}_o_{test_date}.json")
        
        if not cache_file.exists():
            self.print_error(f"未找到 {test_date} 的历史分析文件: {cache_file}")
            sys.exit(1)
            
        with open(cache_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
            
        source = history.get("source_target", {})
        ranking = source.get("ranking", [])
        initial_data = source.get("data", {}).get("targets", {})
        
        initial_spot = initial_data.get("spot_price")
        if not initial_spot:
            self.print_error("历史数据缺失初始 spot_price，无法回测")
            sys.exit(1)
            
        # 2. 打印回测头信息
        self.console.print(Panel.fit(
            f"[bold magenta]🔬 回测报告: {symbol.upper()}[/bold magenta]\n"
            f"开仓日期: {test_date} | 初始价格: ${initial_spot}\n"
            f"当前价格: ${current_price} | 价格变动: {(float(current_price)-initial_spot)/initial_spot*100:+.2f}%",
            border_style="magenta"
        ))
        
        # 3. 逐个策略计算 PnL
        results = []
        for rank_item in ranking:
            strategy = rank_item.get("strategy", {})
            name = rank_item.get("strategy_name", "Unknown")
            st_type = strategy.get("strategy_type", "")
            
            # 计算 PnL
            pnl_data = self._calculate_strategy_pnl(
                strategy, initial_spot, float(current_price)
            )
            
            results.append({
                "rank": rank_item.get("rank"),
                "name": name,
                "type": st_type,
                "pnl_pct": pnl_data['roi'],
                "status": pnl_data['status'],
                "note": pnl_data['note']
            })
            
        # 4. 显示结果表格
        table = Table(title="策略表现回测")
        table.add_column("排名", justify="center")
        table.add_column("策略名称")
        table.add_column("ROI", justify="right")
        table.add_column("状态", justify="center")
        table.add_column("损益归因")
        
        for res in results:
            roi_style = "green" if res['pnl_pct'] > 0 else "red"
            table.add_row(
                str(res['rank']),
                res['name'],
                f"[{roi_style}]{res['pnl_pct']:+.1f}%[/{roi_style}]",
                res['status'],
                res['note']
            )
            
        self.console.print(table)
        
        return {"status": "success", "results": results}

    def _calculate_strategy_pnl(self, strategy: dict, entry_spot: float, exit_spot: float) -> dict:
        """
        简易 PnL 计算器 (基于内在价值变化 + 胜率估算)
        注意：这是一个简化模型，未包含 Vega/Theta 的精确计算，仅供参考方向。
        """
        st_type = strategy.get("strategy_type", "").lower()
        legs = strategy.get("legs", [])
        
        # 识别策略方向
        is_bullish = "bull" in st_type or "long call" in st_type
        is_bearish = "bear" in st_type or "long put" in st_type
        is_neutral = "condor" in st_type or "butterfly" in st_type
        
        roi = 0.0
        status = "持平"
        note = ""
        
        price_change_pct = (exit_spot - entry_spot) / entry_spot
        
        # 1. 垂直价差 (Vertical Spreads)
        if "spread" in st_type:
            # 简化：假设 Delta ≈ 0.5 * Width
            # 实际上应该解析 legs 的 strike
            max_profit = strategy.get("rr_calculation", {}).get("max_profit", 100)
            max_loss = strategy.get("rr_calculation", {}).get("max_loss", 100)
            
            if is_bullish:
                if exit_spot > entry_spot * 1.02: # 涨幅超过2%
                    roi = 50.0 # 假设获利50%
                    status = "止盈"
                elif exit_spot < entry_spot * 0.98:
                    roi = -50.0
                    status = "止损"
                else:
                    roi = price_change_pct * 10 * 100 # 杠杆效应
            
            elif is_bearish:
                if exit_spot < entry_spot * 0.98:
                    roi = 50.0
                    status = "止盈"
                elif exit_spot > entry_spot * 1.02:
                    roi = -50.0
                    status = "止损"
        
        # 2. 铁鹰/中性 (Iron Condor)
        elif is_neutral:
            # 只要价格没变太多，就是赚钱 (Theta 收益)
            if abs(price_change_pct) < 0.03: # 波动 < 3%
                roi = 30.0 # 收取权利金
                status = "获利"
                note = "区间内，Theta 获利"
            else:
                roi = -40.0 # 突破区间，亏损
                status = "亏损"
                note = "突破区间"
                
        # 3. 单腿 (Long Call/Put)
        else:
            # 高杠杆
            leverage = 20 # 假设20倍杠杆
            roi = price_change_pct * leverage * 100
            if is_bearish: roi = -roi
            
            if roi > 100: roi = 100 # 封顶
            if roi < -100: roi = -100 # 归零
            
            status = "盈利" if roi > 0 else "亏损"
            
        return {
            "roi": round(roi, 2),
            "status": status,
            "note": note
        }