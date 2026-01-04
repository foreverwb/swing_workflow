"""
Refresh Command - 刷新快照命令
盘中数据更新，基于已有缓存进行增量分析
"""
import sys
from pathlib import Path
from typing import Dict, Any
from rich.console import Console
from loguru import logger
from commands.base import BaseCommand
from core.workflow import CacheManager
from utils.validators import resolve_input_file_path

class RefreshCommand(BaseCommand):
    """Refresh 命令处理器 - 盘中数据刷新"""
    
    @staticmethod
    def cli_entry(
        symbol: str,
        folder: str,
        input_file: str,
        cache: str,
        model_config: str,
        console: Console
    ):
        """
        CLI 入口方法
        
        Args:
            symbol: 股票代码
            folder: 数据文件夹路径
            input_file: 输入JSON文件路径
            cache: 缓存文件名（必需）
            model_config: 模型配置文件路径
            console: Rich 控制台
        """
        symbol = symbol.upper()
        
        # 参数互斥检查
        if input_file and folder:
            console.print("[red]❌ 参数错误: -i 和 -f 参数互斥[/red]")
            sys.exit(1)
        
        # 必须指定输入源
        if not input_file and not folder:
            console.print("[red]❌ 参数错误: 必须指定 -f (图片文件夹) 或 -i (JSON文件)[/red]")
            sys.exit(1)
        
        from core.model_client import ModelClientFactory
        from utils.config_loader import config
        
        model_client = ModelClientFactory.create_from_config(model_config)
        
        # 从缓存加载参数
        cache_manager = CacheManager()
        cached = cache_manager.load_market_params_from_cache(symbol, cache)
        if not cached:
            console.print(f"[red]❌ 无法从缓存 {cache} 读取参数[/red]")
            console.print(f"[yellow]💡 请先使用 'analyze' 或 'quick' 命令建立基准缓存[/yellow]")
            sys.exit(1)
        
        env_vars = {
            'config': config,
            'market_params': cached.get('market_params', {}),
            'dyn_params': cached.get('dyn_params', {})
        }
        
        console.print(f"\n[bold cyan]📸 Swing Quant - 刷新快照 {symbol}[/bold cyan]")
        
        command = RefreshCommand(console, model_client, env_vars)
        
        try:
            command.execute(
                symbol=symbol,
                folder=folder,
                input_file=input_file,
                cache=cache
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]⚠️ 用户中断[/yellow]")
            sys.exit(0)
    
    def execute(
        self,
        symbol: str,
        folder: str = None,
        input_file: str = None,
        cache: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行刷新命令
        
        Args:
            symbol: 股票代码
            folder: 数据文件夹路径 (图片模式)
            input_file: 输入JSON文件路径 (文件模式)
            cache: 缓存文件名
        """
        symbol = symbol.upper()
        
        # 验证缓存文件
        is_valid, error_msg, _ = self.validate_cache_file(cache, symbol)
        if not is_valid:
            self.print_error(f"缓存验证失败: {error_msg}")
            sys.exit(1)
        self.console.print(f"[green]✅ 缓存文件验证通过[/green]")
        
        # 获取参数
        market_params = self.env_vars.get('market_params', {})
        dyn_params = self.env_vars.get('dyn_params', {})
        
        # 创建引擎
        engine = self.create_engine(cache_file=cache)
        
        try:
            if input_file:
                resolved_path, error_msg = resolve_input_file_path(input_file, symbol)
            
                if not resolved_path:
                    self.print_error(error_msg)
                    sys.exit(1)
                
                self.console.print(f"[dim]   输入文件: {resolved_path}[/dim]")
                # [Fix] 使用解析后的完整路径，而不是原始的 input_file
                data_source = resolved_path
                mode = 'refresh_file'
            else:
                # 图片模式: 从文件夹扫描
                self.console.print(f"[dim]   数据文件夹: {folder}[/dim]")
                data_source = Path(folder)
                mode = 'refresh'
                
                # 验证文件夹
                is_valid, msg = self.validate_folder(data_source)
                if not is_valid:
                    self.print_error(msg)
                    sys.exit(1)
            
            self.console.print(f"\n[green]🔄 开始刷新快照...[/green]\n")
            
            # 执行刷新
            result = engine.run(
                symbol=symbol,
                data_folder=data_source,
                mode=mode,
                market_params=market_params,
                dyn_params=dyn_params
            )
            
            return self._handle_result(result, symbol)
            
        except Exception as e:
            self.print_error(str(e))
            logger.exception("Refresh 命令执行异常")
            sys.exit(1)
    
    def _handle_result(self, result: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        """处理刷新结果"""
        status = result.get("status")
        
        if status == "error":
            self.print_error(result.get("message", "未知错误"))
            sys.exit(1)
        
        elif status == "success":
            self.console.print("\n[green]✅ 快照刷新完成![/green]")
            
            drift_report = result.get("drift_report", {})
            if drift_report:
                summary = drift_report.get("summary", "")
                if summary:
                    self.console.print(f"[cyan]   状态: {summary}[/cyan]")
        
        return result