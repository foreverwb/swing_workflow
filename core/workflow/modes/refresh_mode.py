"""
刷新快照模式
仅运行 Agent3 + 计算引擎，保存 Greeks 快照
"""

from pathlib import Path
from typing import Dict, Any
from loguru import logger

from .full_analysis import FullAnalysisMode


class RefreshMode(FullAnalysisMode):
    """刷新快照模式（继承完整分析模式）"""
    
    def execute(self, symbol: str, data_folder: Path, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行刷新快照
        
        Refresh 模式流程：
        1. Agent3 数据校验
        2. 数据聚合
        3. 字段计算
        4. 保存快照（不执行完整分析）
        
        Args:
            symbol: 股票代码
            data_folder: 数据文件夹路径
            state: 当前状态
            
        Returns:
            快照结果
        """
        logger.info(f"📸 [刷新快照模式] 开始刷新 {symbol}")
        
        # 1. 扫描图片
        images = self.scan_images(data_folder)
        
        if not images:
            return {
                "status": "error",
                "message": f"文件夹 {data_folder} 中未找到图片"
            }
        
        logger.info(f"📊 扫描到 {len(images)} 张图片")
        
        # 2. Agent3 数据校验
        agent3_result = self._run_agent3(symbol, images)
        
        # 3. 数据聚合
        aggregated_result = self._run_aggregator(agent3_result, state)
        
        # 4. 解析数据
        aggregated_data = self.safe_parse_json(aggregated_result.get("result"))
        
        # 5. 字段计算
        calculated_data = self._run_calculator(aggregated_data)
        
        # 6. 保存快照
        snapshot_result = self.cache_manager.save_greeks_snapshot(
            symbol=symbol,
            data=calculated_data,
            note="盘中刷新"
        )
        
        # 7. 生成摘要
        snapshot = snapshot_result.get("snapshot", {})
        summary = self._generate_snapshot_summary(snapshot)
        
        logger.success("✅ 快照刷新完成")
        
        return {
            "status": "success",
            "mode": "refresh",
            "snapshot": snapshot,
            "snapshot_summary": summary
        }
    
    def _run_calculator(self, data: Dict) -> Dict:
        """
        运行字段计算器
        
        Args:
            data: 聚合后的数据
            
        Returns:
            计算后的数据
        """
        from code_nodes.field_calculator import main as calculator_main
        
        result = self.agent_executor.execute_code_node(
            node_name="Calculator",
            func=calculator_main,
            aggregated_data=data,
            **self.env_vars
        )
        
        return self.safe_parse_json(result["result"])
    
    def _generate_snapshot_summary(self, snapshot: Dict) -> str:
        """
        生成快照摘要
        
        Args:
            snapshot: 快照数据
            
        Returns:
            摘要字符串
        """
        lines = [
            f"快照 #{snapshot.get('snapshot_id', 0)}",
            f"时间: {snapshot.get('timestamp', '')[:19]}",
            f"类型: {snapshot.get('type', '')}",
            ""
        ]
        
        if snapshot.get('note'):
            lines.append(f"备注: {snapshot['note']}")
            lines.append("")
        
        lines.extend([
            f"现价: ${snapshot.get('spot_price', 'N/A')}",
            f"EM1$: ${snapshot.get('em1_dollar', 'N/A')}",
            f"Vol Trigger: ${snapshot.get('vol_trigger', 'N/A')}",
            f"状态: {snapshot.get('spot_vs_trigger', 'N/A')}",
            f"NET-GEX: {snapshot.get('net_gex', 'N/A')}",
            ""
        ])
        
        if snapshot.get('changes'):
            lines.append("变化:")
            for field, change in snapshot['changes'].items():
                pct_str = f" ({change['change_pct']:+.2f}%)" if 'change_pct' in change else ""
                lines.append(f"  • {field}: {change['old']} → {change['new']}{pct_str}")
        
        return "\n".join(lines)