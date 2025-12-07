"""
Analyze 命令处理器 - 集成市场状态计算
"""

import sys
from pathlib import Path
from typing import Dict, Any
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from loguru import logger

import prompts
from commands.base import BaseCommand
from core.workflow import AgentExecutor, CacheManager
from code_nodes.pre_calculator import MarketStateCalculator
from utils.console_printer import print_error_summary



class AnalyzeCommand(BaseCommand):
    """Analyze 命令处理器（扩展版）"""
    
    def execute(
        self,
        symbol: str,
        folder: str = None,
        output: str = None,
        mode: str = 'full',
        cache: str = None,
        **kwargs  # 接收额外参数（包括 market_params, dyn_params, tag）
    ) -> Dict[str, Any]:
        """
        执行分析命令
        
        Args:
            symbol: 股票代码
            folder: 数据文件夹路径
            output: 输出文件路径
            mode: 运行模式（full/update）
            cache: 缓存文件名
            **kwargs: 额外参数
                - market_params: Dict[str, float] (vix, ivr, iv30, hv20)
                - dyn_params: Dict (从缓存加载的动态参数，仅完整分析模式)
                - tag: str (工作流标识，如 'Meso')
        """
        # 1. 验证股票代码
        is_valid, result = self.validate_symbol(symbol)
        if not is_valid:
            self.print_error(result)
            self.console.print("[yellow]💡 示例: python app.py analyze -s AAPL --vix 18.5 --ivr 50 --iv30 30 --hv20 25[/yellow]")
            sys.exit(1)
        
        # 2. 提取市场参数
        market_params = kwargs.get('market_params')
        dyn_params = kwargs.get('dyn_params')  #  从缓存加载的动态参数
        tag = kwargs.get('tag')  # 工作流标识
        
        # 3. 判断模式
        if not folder:
            # ========== 模式A: 生成命令清单（Agent2）==========
            # 必须有市场参数
            if not market_params:
                self.print_error("生成命令清单时必须指定市场参数 (--vix, --ivr, --iv30, --hv20)")
                sys.exit(1)
            
            try:
                # 验证参数合法性
                MarketStateCalculator.validate_params(market_params)
                
                # 计算动态参数
                pre_calc_params = MarketStateCalculator.calculate_fetch_params(
                    vix=market_params['vix'],
                    ivr=market_params['ivr'],
                    iv30=market_params['iv30'],
                    hv20=market_params['hv20']
                )
                
                logger.info(f"✅ 市场状态计算完成: {pre_calc_params['scenario']}")
                
            except ValueError as e:
                self.print_error(f"市场参数验证失败: {e}")
                sys.exit(1)
            
            return self._generate_command_list(symbol, pre_calc_params, tag=tag)
        
        else:
            # ========== 模式B: 完整分析（Agent3 → Pipeline）==========
            # 优先使用从缓存加载的动态参数
            if dyn_params:
                # 从缓存加载的参数
                pre_calc_params = dyn_params
                logger.info(f"✅ 使用缓存中的动态参数: {pre_calc_params.get('scenario', 'N/A')}")
            elif market_params:
                # 如果用户显式提供了市场参数，重新计算（兼容旧用法）
                try:
                    MarketStateCalculator.validate_params(market_params)
                    pre_calc_params = MarketStateCalculator.calculate_fetch_params(
                        vix=market_params['vix'],
                        ivr=market_params['ivr'],
                        iv30=market_params['iv30'],
                        hv20=market_params['hv20']
                    )
                    logger.info(f"✅ 市场状态计算完成: {pre_calc_params['scenario']}")
                except ValueError as e:
                    self.print_error(f"市场参数验证失败: {e}")
                    sys.exit(1)
            else:
                self.print_error("缺少市场参数，请指定 --cache 参数从缓存加载")
                sys.exit(1)
            
            return self._full_analysis(
                symbol=symbol,
                folder=folder,
                output=output,
                mode=mode,
                cache=cache,
                pre_calc=pre_calc_params,
                market_params=market_params  #  传递市场参数用于保存
            )
    
    def _generate_command_list(self, symbol: str, pre_calc: Dict, tag: str = None) -> Dict[str, Any]:
        """
        生成命令清单（Agent2）
        
        Args:
            symbol: 股票代码
            pre_calc: MarketStateCalculator 计算的动态参数
            tag: 工作流标识（如 'Meso'）
        """
        self.console.print(Panel.fit(
            f"[bold green]📋 生成命令清单: {symbol.upper()}[/bold green]\n"
            f"[dim]市场场景: {pre_calc['scenario']}[/dim]\n"
            f"[dim]动态参数: Strikes={pre_calc['dyn_strikes']} DTE={pre_calc['dyn_dte_mid']} Window={pre_calc['dyn_window']}[/dim]",
            border_style="green"
        ))
        
        self.console.print("\n[yellow]📁 加载配置...[/yellow]")
        
        # 创建 Agent Executor
        agent_executor = AgentExecutor(
            self.model_client,
            self.env_vars,
            enable_pretty_print=False
        )
        
        self.console.print(f"\n[green]🚀 开始生成 {symbol.upper()} 的动态命令清单[/green]\n")
        
        try:
            from prompts.agent2_cmdlist import get_system_prompt, get_user_prompt
            sys_prompt = get_system_prompt(symbol=symbol.upper(), pre_calc=pre_calc)
            user_prompt = get_user_prompt(symbol=symbol.upper())
            market_params = self.env_vars.get('market_params', {})
            messages = [
                {
                    "role": "system",
                    "content": sys_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
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
                    description=f"为 {symbol.upper()} 生成动态命令清单"
                )
                
                progress.update(task, completed=True)
            
            content = response.get("content", "")
            
            self.console.print("\n[green]✅ 动态命令清单生成完成![/green]\n")
            self.console.print(Panel(
                content,
                title=f"📋 {symbol.upper()} 数据抓取命令清单 (基于 {pre_calc['scenario']})",
                border_style="green"
            ))
            self.console.print("\n[yellow]💾 初始化缓存文件...[/yellow]")
            cache_manager = CacheManager()
        
            cache_path = cache_manager.initialize_cache_with_params(
                symbol=symbol.upper(),
                market_params=market_params,
                dyn_params=pre_calc,
                tag=tag  # 传递 tag 参数到缓存管理器
            )
            if cache_path:
                # 提取文件名
                cache_filename = Path(cache_path).name
                
                self.console.print(f"[green]✅ 缓存已创建: {cache_path}[/green]")
                if tag:
                    self.console.print(f"[dim]   工作流标识: tag={tag}[/dim]")
                self.console.print(f"[dim]   后续分析将自动从此文件读取市场参数[/dim]")
                
                #  简化的命令提示（根据 tag 显示不同的命令）
                self.console.print(f"\n[yellow]💡 提示：抓取数据后，请使用以下命令执行分析:[/yellow]")
                if tag == 'Meso':
                    self.console.print(
                        f"[cyan]   python app.py q {symbol.upper()} "
                        f"-v <VIX值> "
                        f"-f <数据文件夹路径> "
                        f"-c {cache_filename}[/cyan]"
                    )
                else:
                    self.console.print(
                        f"[cyan]   python app.py analyze -s {symbol.upper()} "
                        f"-f <数据文件夹路径> "
                        f"--cache {cache_filename}[/cyan]"
                    )
            else:
                self.console.print("[red]⚠️ 缓存初始化失败（可能已存在）[/red]")
            
            return {
                "status": "success", 
                "content": content, 
                "pre_calc": pre_calc,
                "cache_path": str(cache_path) if cache_path else None,
                "tag": tag
            }
        
        except Exception as e:
            self.print_error(str(e))
            sys.exit(1)
    
    def _full_analysis(
        self,
        symbol: str,
        folder: str,
        output: str,
        mode: str,
        cache: str,
        pre_calc: Dict,
        market_params: Dict = None  #  新增参数
    ) -> Dict[str, Any]:
        """
        执行完整分析
        
        Args:
            symbol: 股票代码
            folder: 数据文件夹路径
            output: 输出文件路径
            mode: 运行模式
            cache: 缓存文件名
            pre_calc: 动态参数字典
            market_params: 市场参数（可选，用于保存到缓存）
        """
        # 验证参数
        if mode == 'update' and not cache:
            self.print_error("update 模式必须指定 --cache 参数")
            self.console.print(f"[yellow]💡 示例:[/yellow]")
            self.console.print(f"[cyan]   python app.py analyze -s {symbol.upper()} -f {folder} --mode update --cache {symbol.upper()}_20251129.json[/cyan]")
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
        scenario = pre_calc.get('scenario', 'N/A')
        self.console.print(Panel.fit(
            f"[bold blue]Swing Quant Workflow[/bold blue]\n"
            f"[dim]期权分析策略系统 - {mode_desc}[/dim]\n"
            f"[dim]市场场景: {scenario}[/dim]",
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
        
        #  优先使用传入的 market_params，否则从 env_vars 获取
        if not market_params:
            market_params = self.env_vars.get('market_params', {})
        
        self.console.print(f"\n[green]🚀 开始{mode_desc} {symbol.upper()}[/green]\n")
        
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                task = progress.add_task("正在分析...", total=None)
                
                #  传递市场参数和动态参数
                result = engine.run(
                    symbol=symbol.upper(),
                    data_folder=folder_path,
                    mode=mode,
                    market_params=market_params,
                    dyn_params=pre_calc  #  pre_calc 作为 dyn_params 传递
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
            
            #显示市场状态信息
            if "pre_calc" in result:
                pre_calc = result["pre_calc"]
                self.console.print(f"\n[cyan]📊 市场状态: {pre_calc.get('scenario')}[/cyan]")
                self.console.print(f"[dim]   VRP={pre_calc.get('vrp', 0):.2f} | Strikes={pre_calc.get('dyn_strikes')} | DTE={pre_calc.get('dyn_dte_mid')}[/dim]")
            
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