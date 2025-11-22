"""
状态管理器
负责工作流状态的持久化和恢复
"""

import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
from loguru import logger


class StateManager:
    """状态管理器"""
    
    def __init__(self, cache_dir: Path = Path("data/temp")):
        """
        初始化状态管理器
        
        Args:
            cache_dir: 缓存目录
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def load_state(self, symbol: str) -> Dict[str, Any]:
        """
        加载状态
        
        Args:
            symbol: 股票代码
            
        Returns:
            状态字典
        """
        cache_file = self.cache_dir / f"{symbol}_workflow_state.json"
        
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                logger.info(f"📂 已加载 {symbol} 的历史状态")
                return state
            except Exception as e:
                logger.error(f"加载状态失败: {e}")
                return self._get_default_state(symbol)
        
        return self._get_default_state(symbol)
    
    def save_state(self, symbol: str, state: Dict[str, Any]):
        """
        保存状态
        
        Args:
            symbol: 股票代码
            state: 状态字典
        """
        cache_file = self.cache_dir / f"{symbol}_workflow_state.json"
        
        try:
            # 更新时间戳
            state["last_updated"] = datetime.now().isoformat()
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"💾 已保存 {symbol} 的状态")
        except Exception as e:
            logger.error(f"保存状态失败: {e}")
    
    def clear_state(self, symbol: str):
        """
        清除状态
        
        Args:
            symbol: 股票代码
        """
        cache_file = self.cache_dir / f"{symbol}_workflow_state.json"
        
        if cache_file.exists():
            cache_file.unlink()
            logger.info(f"🗑️ 已清除 {symbol} 的状态")
    
    def update_conversation_vars(self, symbol: str, **kwargs):
        """
        更新会话变量
        
        Args:
            symbol: 股票代码
            **kwargs: 要更新的键值对
        """
        state = self.load_state(symbol)
        
        for key, value in kwargs.items():
            state["conversation_vars"][key] = value
        
        self.save_state(symbol, state)
    
    def get_conversation_vars(self, symbol: str) -> Dict[str, Any]:
        """
        获取会话变量
        
        Args:
            symbol: 股票代码
            
        Returns:
            会话变量字典
        """
        state = self.load_state(symbol)
        return state.get("conversation_vars", {})
    
    def _get_default_state(self, symbol: str) -> Dict[str, Any]:
        """
        获取默认状态
        
        Args:
            symbol: 股票代码
            
        Returns:
            默认状态字典
        """
        return {
            "symbol": symbol,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "conversation_vars": {
                "missing_count": 0,
                "data_status": "initial",
                "current_symbol": symbol,
                "first_parse_data": ""
            },
            "history": []
        }
    
    def add_history_entry(self, symbol: str, entry: Dict[str, Any]):
        """
        添加历史记录
        
        Args:
            symbol: 股票代码
            entry: 历史记录条目
        """
        state = self.load_state(symbol)
        
        if "history" not in state:
            state["history"] = []
        
        entry["timestamp"] = datetime.now().isoformat()
        state["history"].append(entry)
        
        # 限制历史记录数量（保留最近50条）
        if len(state["history"]) > 50:
            state["history"] = state["history"][-50:]
        
        self.save_state(symbol, state)
    
    def get_last_analysis(self, symbol: str) -> Dict[str, Any]:
        """
        获取最后一次分析结果
        
        Args:
            symbol: 股票代码
            
        Returns:
            最后一次分析结果
        """
        state = self.load_state(symbol)
        history = state.get("history", [])
        
        if not history:
            return {}
        
        # 查找最后一次成功的完整分析
        for entry in reversed(history):
            if entry.get("mode") == "full" and entry.get("status") == "success":
                return entry.get("result", {})
        
        return {}