"""
命令基类
定义所有命令的通用接口和工具方法
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional
from rich.console import Console
from loguru import logger

from core.model_client import ModelClientManager
from core.workflow import WorkflowEngine


class BaseCommand(ABC):
    """命令基类"""
    
    def __init__(self, console: Console, model_client: ModelClientManager, env_vars: Dict[str, Any]):
        """
        初始化命令
        
        Args:
            console: Rich 控制台
            model_client: 模型客户端管理器
            env_vars: 环境变量
        """
        self.console = console
        self.model_client = model_client
        self.env_vars = env_vars
        
    @abstractmethod
    def execute(
        self, 
        symbol: str, 
        data_folder: Path, 
        state: Dict[str, Any],
        market_params: Dict = None,  
        dyn_params: Dict = None       
    ) -> Dict[str, Any]:
        """
        执行模式 - 子类必须实现
        
        Args:
            symbol: 股票代码
            data_folder: 数据文件夹路径
            state: 当前状态
            market_params: 市场参数 (vix, ivr, iv30, hv20)
            dyn_params: 动态参数 (dyn_strikes, dyn_dte_mid, ...)
            
        Returns:
            执行结果
        """
        pass
    
    # ============= 工具方法 =============
    
    def validate_symbol(self, symbol: str) -> tuple[bool, str]:
        """验证股票代码"""
        from utils.validators import validate_symbol
        return validate_symbol(symbol)
    
    def validate_folder(self, folder_path: Path) -> tuple[bool, str]:
        """验证文件夹"""
        if not folder_path.exists():
            return False, f"文件夹不存在: {folder_path}"
        
        image_count = len(list(folder_path.glob('*.[pP][nN][gG]'))) + \
                     len(list(folder_path.glob('*.[jJ][pP][gG]')))
        
        if image_count == 0:
            return False, f"文件夹中没有找到图片 (png/jpg): {folder_path}"
        
        return True, f"扫描到 {image_count} 张图片"
    
    def validate_cache_file(self, cache_file: Optional[str], symbol: str) -> tuple[bool, str, Dict]:
        """验证缓存文件"""
        from utils.validators import validate_cache_file
        
        if not cache_file:
            return False, "未指定缓存文件", {}
        
        return validate_cache_file(cache_file, symbol)
    
    def create_engine(self, cache_file: Optional[str] = None) -> WorkflowEngine:
        """创建工作流引擎"""
        return WorkflowEngine(
            model_client=self.model_client,
            env_vars=self.env_vars,
            cache_file=cache_file
        )
    
    def print_success(self, message: str):
        """打印成功消息"""
        self.console.print(f"[green]✅ {message}[/green]")
    
    def print_error(self, message: str):
        """打印错误消息"""
        self.console.print(f"[red]❌ {message}[/red]")
    
    def print_warning(self, message: str):
        """打印警告消息"""
        self.console.print(f"[yellow]⚠️ {message}[/yellow]")
    
    def print_info(self, message: str):
        """打印信息消息"""
        self.console.print(f"[cyan]ℹ️ {message}[/cyan]")