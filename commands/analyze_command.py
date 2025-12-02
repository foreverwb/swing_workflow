"""
Analyze 命令处理器
处理完整分析和增量更新
"""

import sys
from pathlib import Path
from typing import Dict, Any
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

import prompts
from .base import BaseCommand
from core.workflow import AgentExecutor
from utils.console_printer import print_error_summary


class AnalyzeCommand(BaseCommand):
    """Analyze 命令处理器"""
    
    def execute(
        self,
        symbol: str,
        folder: str = None,
        output: str = None,
        mode: str = 'full',
        cache: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行分析命令
        
        Args:
            symbol: 股票代码
            folder: 数据文件夹路径
            output: 输出文件路径
            mode: 运行模式（full/update）
            cache: 缓存文件名
        """
        # 1. 验证股票代码
        is_valid, result = self.validate_symbol(symbol)
        if not is_valid:
            self.print_error(result)
            self.console.print("[yellow]💡 示例: python app.py analyze -s AAPL -f data/uploads/AAPL[/yellow]")
            sys.exit(1)
        
        # 2. 判断模式
        if not folder:
            return self._generate_command_list(symbol)
        else:
            return self._full_analysis(symbol, folder, output, mode, cache)
    
    def _generate_command_list(self, symbol: str) -> Dict[str, Any]:
        """生成命令清单（Agent2）"""
        self.console.print(Panel.fit(
            f"[bold green]📋 生成命令清单: {symbol.upper()}[/bold green]\n"
            f"[dim]未提供数据文件夹，将生成期权数据抓取命令[/dim]",
            border_style="green"
        ))
        
        self.console.print("\n[yellow]📁 加载配置...[/yellow]")
        
        # 创建 Agent Executor
        agent_executor = AgentExecutor(
            self.model_client,
            self.env_vars,
            enable_pretty_print=True
        )
        
        self.console.print(f"\n[green]🚀 开始生成 {symbol.upper()} 的命令清单[/green]\n")
        
        try:
            # 构建消息
            messages = [
                {
                    "role": "system",
                    "content": prompts.agent2_cmdlist.get_system_prompt(self.env_vars)
                },
                {
                    "role": "user",
                    "content": prompts.agent2_cmdlist.get_user_prompt(symbol.upper())
                }
            ]
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                task = progress.add_task("正在生成命令清单...", total=None)
                
                response = agent_executor.execute_agent(
                    agent_name="agent2",
                    messages=messages,
                    description=f"为 {symbol.upper()} 生成命令清单"
                )
                
                progress.update(task, completed=True)
            
            content = response.get("content", "")
            
            self.console.print("\n[green]✅ 命令清单生成完成![/green]\n")
            self.console.print(Panel(
                content,
                title=f"📋 {symbol.upper()} 数据抓取命令清单",
                border_style="green"
            ))
            
            self.console.print(f"\n[yellow]💡 下一步: 根据命令清单抓取数据后，执行:[/yellow]")
            self.console.print(f"[cyan]   python app.py analyze -s {symbol.upper()} -f <数据文件夹路径>[/cyan]")
            
            return {"status": "success", "content": content}
        
        except Exception as e:
            self.print_error(str(e))
            sys.exit(1)
    
    def _full_analysis(
        self,
        symbol: str,
        folder: str,
        output: str,
        mode: str,
        cache: str
    ) -> Dict[str, Any]:
        """执行完整分析"""
        # 验证参数
        if mode == 'update' and not cache:
            self.print_error("update 模式必须指定 --cache 参数")
            self.console.print(f"[yellow]💡 示例:[/yellow]")
            self.console.print(f"[cyan]   python app.py analyze -s {symbol.upper()} -f {folder} --mode update --cache {symbol.upper()}_20251129.json[/cyan]")
            self.console.print(f"\n[dim]提示: 可用的缓存文件位于 data/output/{symbol.upper()}/ 目录下[/dim]")
            sys.exit(1)
        
        # 验证缓存文件
        if cache:
            is_valid, error_msg, cache_info = self.validate_cache_file(cache, symbol)
            
            if not is_valid:
                self.print_error("缓存文件验证失败")
                self.console.print(f"[red]   {error_msg}[/red]")
                sys.exit(1)
            
            self.console.print(f"\n[green]✅ 缓存文件验证通过[/green]")
            self.console.print(f"[dim]   将更新缓存: {cache}[/dim]")
        
        # 打印标题
        mode_desc = "完整分析" if mode == "full" else "增量补齐"
        self.console.print(Panel.fit(
            f"[bold blue]Swing Quant Workflow[/bold blue]\n"
            f"[dim]期权分析策略系统 - {mode_desc}[/dim]",
            border_style="blue"
        ))
        
        # 验证文件夹
        folder_path = Path(folder)
        is_valid, msg = self.validate_folder(folder_path)
        if not is_valid:
            self.print_error(msg)
            sys.exit(1)
        
        self.console.print(f"[dim]📂 {msg}[/dim]")
        
        # 创建引擎
        engine = self.create_engine(cache_file=cache)
        
        self.console.print(f"\n[green]🚀 开始{mode_desc} {symbol.upper()}[/green]\n")
        
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                task = progress.add_task("正在分析...", total=None)
                
                result = engine.run(
                    symbol=symbol.upper(),
                    data_folder=folder_path,
                    mode=mode
                )
                
                progress.update(task, completed=True)
            
            # 处理结果
            return self._handle_result(result, symbol, output)
        
        except Exception as e:
            self.print_error(str(e))
            sys.exit(1)
    
    def _handle_result(
        self,
        result: Dict[str, Any],
        symbol: str,
        output: str
    ) -> Dict[str, Any]:
        """处理分析结果"""
        status = result.get("status")
        
        if status == "incomplete":
            self.console.print("\n[yellow]⚠️ 数据不完整[/yellow]\n")
            self.console.print(result.get("guide", ""))
        
        elif status == "error":
            print_error_summary(result)
            sys.exit(1)
        
        elif status == "success":
            self.console.print("\n[green]✅ 分析完成![/green]\n")
            self.console.print(Panel(
                result.get("report", ""),
                title="📊 分析报告",
                border_style="green"
            ))
            
            # 保存报告
            if output:
                output_path = Path(output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result.get("report", ""))
                
                self.console.print(f"\n[dim]报告已保存至: {output_path}[/dim]")
            
            # 显示事件风险
            event_risk = result.get("event_risk", {})
            if isinstance(event_risk, dict):
                risk_level = event_risk.get("risk_level", "low")
                if risk_level != "low":
                    event_count = event_risk.get("event_count", 0)
                    recommendations = event_risk.get("recommendations", {})
                    note = recommendations.get("note", "")
                    
                    self.console.print(f"\n[red]⚠️ 事件风险: {risk_level.upper()}[/red]")
                    self.console.print(f"[yellow]检测到 {event_count} 个近期事件[/yellow]")
                    if note:
                        self.console.print(f"[dim]{note}[/dim]")
        
        return result