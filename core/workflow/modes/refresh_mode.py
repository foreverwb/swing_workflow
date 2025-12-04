"""
刷新快照模式
仅运行 Agent3 + 计算引擎，保存 Greeks 快照
"""

from pathlib import Path
from typing import Dict, Any
from loguru import logger

from .full_analysis import FullAnalysisMode
from code_nodes.field_calculator import main as calculator_main

class RefreshMode(FullAnalysisMode):
    """刷新快照模式（继承完整分析模式）"""
    
    def execute(self, symbol: str, data_folder: Path, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行刷新快照
        
        Refresh 模式流程：Agent3 → Calculator → 保存快照
        
        特点：
        - 不使用 Aggregator（不合并历史数据）
        - 直接对当前数据进行计算
        - 保存为新的快照（snapshots_N）
        
        Args:
            symbol: 股票代码
            data_folder: 数据文件夹路径
            state: 当前状态（保留兼容）
            
        Returns:
            快照结果
        """
        logger.info(f"📸 [刷新快照模式] 开始刷新 {symbol}")
        
        try:
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
            
            # 3. 字段计算（Refresh 专用，跳过 Aggregator）
            calculated_result = self._run_calculator_for_refresh(agent3_result, symbol)
            
            # 4. 检查数据完整性
            data_status = calculated_result.get("data_status")
            
            if data_status != "ready":
                return {
                    "status": "error",
                    "message": "数据不完整，无法保存快照",
                    "data_status": data_status,
                    "validation": calculated_result.get("validation", {}),
                    "missing_fields": calculated_result.get("validation", {}).get("missing_fields", [])
                }
            
            # 5. 保存快照（作为 snapshots_N）
            snapshot_result = self.cache_manager.save_greeks_snapshot(
                symbol=symbol,
                data=calculated_result,
                note="盘中刷新",
                is_initial=False,  # refresh 不是初始数据
                cache_file_name=self.engine.cache_file
            )
            
            # 6. 生成摘要
            snapshot = snapshot_result.get("snapshot", {})
            summary = self._generate_snapshot_summary(snapshot)
            
            logger.success("✅ 快照刷新完成")
            
            return {
                "status": "success",
                "mode": "refresh",
                "snapshot": snapshot,
                "snapshot_summary": summary,
                "total_snapshots": snapshot_result.get("total_snapshots", 0)
            }
        
        except Exception as e:
            logger.exception("❌ 刷新快照失败")
            return {
                "status": "error",
                "message": f"刷新失败: {str(e)}"
            }
    
    def _run_calculator_for_refresh(self, agent3_result: Dict, symbol: str) -> Dict:
        """
        运行字段计算器（Refresh 专用）
        
        与 FullAnalysisMode._run_calculator 的区别：
        - 跳过 Aggregator（不合并历史数据）
        - 直接对 Agent3 结果进行计算
        
        Args:
            agent3_result: Agent3 返回的原始数据
            symbol: 股票代码
            
        Returns:
            计算后的数据
        """
        
        logger.info("🔧 [Refresh] 计算衍生字段（跳过 Aggregator）")
        
        # 构造 Calculator 期望的输入格式
        # Calculator 期望 aggregated_data 参数
        calculator_input = {
            "result": agent3_result  # 模拟 Aggregator 的输出格式
        }
        
        try:
            result = self.agent_executor.execute_code_node(
                node_name="Calculator",
                func=calculator_main,
                description="计算 EM1$, gap_distance_em1, cluster_strength_ratio",
                aggregated_data=calculator_input,
                symbol=symbol,
                **self.env_vars
            )
            
            logger.success("✅ [Refresh] 字段计算完成")
            return result
        
        except Exception as e:
            logger.error(f"❌ [Refresh] Calculator 执行失败: {str(e)}")
            return {
                "data_status": "error",
                "error_message": str(e)
            }
    
    def _generate_snapshot_summary(self, snapshot: Dict) -> str:
        """
        生成快照摘要
        
        Args:
            snapshot: 快照数据
            
        Returns:
            摘要字符串
        """
        lines = [
            f"快照时间: {snapshot.get('timestamp', '')[:19]}",
            ""
        ]
        
        if snapshot.get('note'):
            lines.append(f"备注: {snapshot['note']}")
            lines.append("")
        
        # 提取 targets 数据
        targets = snapshot.get("targets", {})
        
        if targets:
            gamma_metrics = targets.get('gamma_metrics', {})
            
            lines.extend([
                f"现价: ${targets.get('spot_price', 'N/A')}",
                f"EM1$: ${targets.get('em1_dollar', 'N/A')}",
                f"Vol Trigger: ${gamma_metrics.get('vol_trigger', 'N/A')}",
                f"Gamma 状态: {gamma_metrics.get('spot_vs_trigger', 'N/A')}",
                f"NET-GEX: {gamma_metrics.get('net_gex', 'N/A')}",
                ""
            ])
        
        # 如果有变化记录
        if snapshot.get('changes'):
            lines.append("📈 数据变化:")
            for field, change in snapshot['changes'].items():
                pct_str = f" ({change['change_pct']:+.2f}%)" if 'change_pct' in change else ""
                lines.append(f"  • {field}: {change['old']} → {change['new']}{pct_str}")
        
        return "\n".join(lines)