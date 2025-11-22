"""
增量更新模式
在现有数据基础上补齐缺失字段
"""

from pathlib import Path
from typing import Dict, Any
from loguru import logger

from .full_analysis import FullAnalysisMode


class UpdateMode(FullAnalysisMode):
    """增量更新模式（继承完整分析模式）"""
    
    def execute(self, symbol: str, data_folder: Path, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行增量更新
        
        Update 模式与 Full 模式的主要区别：
        1. 保留历史数据
        2. 仅补齐缺失字段
        3. 更新会话变量
        
        Args:
            symbol: 股票代码
            data_folder: 数据文件夹路径
            state: 当前状态
            
        Returns:
            更新结果
        """
        logger.info(f"🔄 [增量更新模式] 开始更新 {symbol}")
        
        # 检查是否有历史数据
        conv_vars = state.get("conversation_vars", {})
        first_parse_data = conv_vars.get("first_parse_data", "")
        
        if not first_parse_data:
            logger.warning("⚠️ 无历史数据，切换到完整分析模式")
            return super().execute(symbol, data_folder, state)
        
        logger.info("📂 检测到历史数据，进入增量补齐模式")
        
        # 使用父类的完整分析逻辑
        # Aggregator 会自动处理增量合并
        result = super().execute(symbol, data_folder, state)
        
        # 更新模式标识
        if result.get("status") == "success":
            result["mode"] = "update"
            logger.success("✅ 增量更新完成")
        
        return result