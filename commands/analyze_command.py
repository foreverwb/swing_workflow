"""
Analyze 命令处理器 - 集成市场状态计算
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from loguru import logger

import prompts
from commands.base import BaseCommand
from core.workflow import AgentExecutor, CacheManager
from code_nodes.pre_calculator import MarketStateCalculator
from code_nodes.code0_cmdlist import CommandListGenerator
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
        dyn_params = kwargs.get('dyn_params')
        tag = kwargs.get('tag')
        
        # 3. 判断模式
        if not folder:
            # ========== 模式A: 生成命令清单（Agent2）==========
            if not market_params:
                self.print_error("生成命令清单时必须指定市场参数 (--vix, --ivr, --iv30, --hv20)")
                sys.exit(1)
            
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
            
            return self._generate_command_list(symbol, pre_calc_params, tag=tag)
        
        else:
            # ========== 模式B: 完整分析（Agent3 → Pipeline）==========
            if dyn_params:
                pre_calc_params = dyn_params
                logger.info(f"✅ 使用缓存中的动态参数: {pre_calc_params.get('scenario', 'N/A')}")
            elif market_params:
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
                market_params=market_params
            )
    
    def _generate_command_list(self, symbol: str, pre_calc: Dict, tag: str = None) -> Dict[str, Any]:
        """
        生成命令清单（Code Node 实现，替代原 Agent2）
        
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
        
        market_params = self.env_vars.get('market_params', {})
        
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                task = progress.add_task("正在生成命令清单...", total=None)
                
                generator = CommandListGenerator()
                result = generator.generate(
                    symbol=symbol.upper(),
                    pre_calc=pre_calc,
                    market_params=market_params
                )
                
                progress.update(task, completed=True)
            
            content = result.get("content", "")
            summary = result.get("summary", {})
            
            self.console.print("\n[green]✅ 动态命令清单生成完成![/green]\n")
            self.console.print(f"[dim]   共生成 {summary.get('total_commands', 0)} 条命令[/dim]")
            self.console.print(Panel(
                content,
                title=f"📋 {symbol.upper()} 数据抓取命令清单 (基于 {pre_calc['scenario']})",
                border_style="green"
            ))
            
            # ========== 新增: 生成输入文件模板 ==========
            self.console.print("\n[yellow]📝 生成输入文件模板...[/yellow]")
            template_path = self._generate_input_template(symbol, pre_calc, market_params)
            if template_path:
                self.console.print(f"[green]✅ 模板已生成: {template_path}[/green]")
                self.console.print(f"[dim]   请填充数据后使用 'refresh' 命令[/dim]")
            
            self.console.print("\n[yellow]💾 初始化缓存文件...[/yellow]")
            cache_manager = CacheManager()
        
            cache_path = cache_manager.initialize_cache_with_params(
                symbol=symbol.upper(),
                market_params=market_params,
                dyn_params=pre_calc,
                tag=tag
            )
            if cache_path:
                cache_filename = Path(cache_path).name
                
                self.console.print(f"[green]✅ 缓存已创建: {cache_path}[/green]")
                if tag:
                    self.console.print(f"[dim]   工作流标识: tag={tag}[/dim]")
                self.console.print(f"[dim]   后续分析将自动从此文件读取市场参数[/dim]")
                
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
                        f"[cyan]   python app.py analyze {symbol.upper()} "
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
                "tag": tag,
                "summary": summary,
                "template_path": template_path
            }
        
        except Exception as e:
            self.print_error(str(e))
            sys.exit(1)
    
    def _generate_input_template(self, symbol: str, pre_calc: Dict, market_params: Dict) -> str:
        """
        生成输入文件模板（从 agent3_schema 自动生成）
        
        Args:
            symbol: 股票代码
            pre_calc: 动态参数
            market_params: 市场参数
            
        Returns:
            生成的文件路径
        """
        from schemas.agent3_schema import get_schema
        
        # 创建目录
        input_dir = Path("data/input")
        input_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名: symbol_datetime.json
        current_datetime = datetime.now().strftime("%Y%m%d")
        filename = f"{symbol.lower()}_{current_datetime}.json"
        filepath = input_dir / filename
        
        # 从 schema 自动生成 spec 结构
        schema = get_schema()
        spec_template = self._build_template_from_schema(schema, symbol)
        
        # 构造完整模板
        template = {
            "spec": spec_template,
            "metadata": {
                "as_of": datetime.now().strftime("%Y-%m-%d"),
                "strikes": pre_calc.get('dyn_strikes'),
                "panels": [
                    {
                        "panel_name": "short",
                        "horizon_arg": pre_calc.get('dyn_dte_short'),
                        "rows": []
                    },
                    {
                        "panel_name": "mid",
                        "horizon_arg": pre_calc.get('dyn_dte_mid'),
                        "rows": []
                    },
                    {
                        "panel_name": "long",
                        "horizon_arg": pre_calc.get('dyn_dte_long_backup'),
                        "rows": []
                    }
                ]
            }
        }
        
        # 写入文件
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
        
        return str(filepath)
    
    def _build_template_from_schema(self, schema: Dict, symbol: str = None) -> Dict:
        """
        根据 JSON Schema 递归构建模板
        
        Args:
            schema: JSON Schema 定义
            symbol: 股票代码（用于填充 targets.symbol）
            
        Returns:
            模板数据结构
        """
        schema_type = schema.get("type")
        
        # 处理对象类型
        if schema_type == "object":
            result = {}
            properties = schema.get("properties", {})
            pattern_properties = schema.get("patternProperties", {})
            
            # 处理普通属性
            for prop_name, prop_schema in properties.items():
                # 特殊处理：为 targets.symbol 填充实际值
                if prop_name == "symbol" and symbol:
                    result[prop_name] = symbol.upper()
                else:
                    result[prop_name] = self._build_template_from_schema(prop_schema, symbol)
            
            # 处理 patternProperties (如 indices 的动态键)
            if pattern_properties:
                # indices 留空，由用户填充
                pass
            
            return result
        
        # 处理数组类型
        elif schema_type == "array":
            # 返回空数组，由用户填充
            return []
        
        # 处理字符串类型
        elif schema_type == "string":
            enum_values = schema.get("enum", [])
            if enum_values:
                # 如果有枚举值，选择第一个作为默认值或 N/A
                return "N/A" if "N/A" in enum_values else enum_values[0]
            return None
        
        # 处理数字类型
        elif schema_type == "number":
            return None
        
        # 处理联合类型 (如 ["string", "null"])
        elif isinstance(schema_type, list):
            # 优先使用非 null 的类型
            for t in schema_type:
                if t != "null":
                    return self._build_template_from_schema({"type": t, **{k: v for k, v in schema.items() if k != "type"}}, symbol)
            return None
        
        # 默认返回 None
        return None
    
    def _full_analysis(
        self,
        symbol: str,
        folder: str,
        output: str,
        mode: str,
        cache: str,
        pre_calc: Dict,
        market_params: Dict = None
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
        if mode == 'update' and not cache:
            self.print_error("update 模式必须指定 --cache 参数")
            self.console.print(f"[yellow]💡 示例:[/yellow]")
            self.console.print(f"[cyan]   python app.py analyze -s {symbol.upper()} -f {folder} --mode update --cache {symbol.upper()}_20251129.json[/cyan]")
            sys.exit(1)
        
        if cache:
            is_valid, error_msg, cache_info = self.validate_cache_file(cache, symbol)
            
            if not is_valid:
                self.print_error("缓存文件验证失败")
                self.console.print(f"[red]   {error_msg}[/red]")
                sys.exit(1)
            
            self.console.print(f"\n[green]✅ 缓存文件验证通过[/green]")
            self.console.print(f"[dim]   将更新缓存: {cache}[/dim]")
        
        mode_desc = "完整分析" if mode == "full" else "增量补齐"
        scenario = pre_calc.get('scenario', 'N/A')
        self.console.print(Panel.fit(
            f"[bold blue]Swing Quant Workflow[/bold blue]\n"
            f"[dim]期权分析策略系统 - {mode_desc}[/dim]\n"
            f"[dim]市场场景: {scenario}[/dim]",
            border_style="blue"
        ))
        
        folder_path = Path(folder)
        is_valid, msg = self.validate_folder(folder_path)
        if not is_valid:
            self.print_error(msg)
            sys.exit(1)
        
        self.console.print(f"[dim]📂 {msg}[/dim]")
        
        engine = self.create_engine(cache_file=cache)
        
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
                
                result = engine.run(
                    symbol=symbol.upper(),
                    data_folder=folder_path,
                    mode=mode,
                    market_params=market_params,
                    dyn_params=pre_calc
                )
                
                progress.update(task, completed=True)
            
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
            
            if output:
                output_path = Path(output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result.get("report", ""))
                
                self.console.print(f"\n[dim]报告已保存至: {output_path}[/dim]")
            
            if "pre_calc" in result:
                pre_calc = result["pre_calc"]
                self.console.print(f"\n[cyan]📊 市场状态: {pre_calc.get('scenario')}[/cyan]")
                self.console.print(f"[dim]   VRP={pre_calc.get('vrp', 0):.2f} | Strikes={pre_calc.get('dyn_strikes')} | DTE={pre_calc.get('dyn_dte_mid')}[/dim]")
            
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