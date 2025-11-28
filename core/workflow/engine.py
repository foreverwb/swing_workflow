"""
WorkflowEngine - 工作流引擎（简化版）
职责：流程编排 + 模式路由
"""

from pathlib import Path
from typing import Dict, Any
from loguru import logger

from core.model_client import ModelClientManager
from .state_manager import StateManager
from .cache_manager import CacheManager
from .agent_executor import AgentExecutor


class WorkflowEngine:
    """工作流引擎 - 简化版"""
    
    def __init__(self, model_client: ModelClientManager, env_vars: Dict[str, Any], cache_file: str = None):
        """
        初始化工作流引擎
        
        Args:
            model_client: 模型客户端管理器
            env_vars: 环境变量字典
            cache_file: 指定缓存文件名（如 NVDA_20251127.json）
        """
        self.model_client = model_client
        self.env_vars = env_vars
        self.cache_file = cache_file  # ⭐ 新增：支持指定缓存文件
        
        # 依赖注入
        self.state_manager = StateManager()
        self.cache_manager = CacheManager()
        self.agent_executor = AgentExecutor(
            model_client, 
            env_vars, 
            enable_pretty_print=True,
            show_full_output=False
        )
        
        # 延迟加载模式（避免循环导入）
        self._modes = None
        
        logger.info("✅ 工作流引擎初始化完成")
    
    @property
    def modes(self) -> Dict[str, Any]:
        """延迟加载模式"""
        if self._modes is None:
            from .modes.full_analysis import FullAnalysisMode
            from .modes.update_mode import UpdateMode
            from .modes.refresh_mode import RefreshMode
            
            self._modes = {
                "full": FullAnalysisMode(self),
                "update": UpdateMode(self),
                "refresh": RefreshMode(self)
            }
        
        return self._modes
    
    def run(self, symbol: str, data_folder: Path, mode: str = "full") -> Dict[str, Any]:
        """
        运行工作流 - 核心入口
        
        Args:
            symbol: 股票代码
            data_folder: 数据文件夹路径
            mode: 运行模式（full/update/refresh）
            
        Returns:
            执行结果
        """
        mode_desc = {
            "full": "完整分析",
            "update": "增量补齐",
            "refresh": "刷新快照"
        }.get(mode, "完整分析")
        
        logger.info(f"🚀 开始{mode_desc} {symbol}")
        
        # 1. 加载历史状态
        state = self.state_manager.load_state(symbol)
        
        # 2. 获取模式处理器
        mode_handler = self.modes.get(mode)
        if not mode_handler:
            raise ValueError(f"未知模式: {mode}")
        
        # 3. 执行模式
        try:
            result = mode_handler.execute(symbol, data_folder, state)
            
            # 4. 记录历史
            self.state_manager.add_history_entry(symbol, {
                "mode": mode,
                "status": result.get("status"),
                "result": result
            })
            
            return result
        
        except Exception as e:
            logger.exception(f"❌ 执行失败")
            
            # 记录失败
            self.state_manager.add_history_entry(symbol, {
                "mode": mode,
                "status": "error",
                "error": str(e)
            })
            
            return {
                "status": "error",
                "message": str(e)
            }
    
    def get_history(self, symbol: str) -> list:
        """
        获取执行历史
        
        Args:
            symbol: 股票代码
            
        Returns:
            历史记录列表
        """
        state = self.state_manager.load_state(symbol)
        return state.get("history", [])
    
    def clear_history(self, symbol: str):
        """
        清除历史记录
        
        Args:
            symbol: 股票代码
        """
        self.state_manager.clear_state(symbol)
        logger.info(f"🗑️ 已清除 {symbol} 的历史记录")