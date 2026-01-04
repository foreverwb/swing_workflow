"""
Analyze Command - 初始分析命令 (Phase 3 Final Merged)
特性：
1. [Mode A] 生成命令清单 & 输入模板 (无输入源时)
2. [Mode B] 完整视觉分析 (基于图片文件夹)
3. [Mode C] 直接文件分析 (基于 JSON 输入文件, Bypass Vision)
4. [Core] 建立 T=0 时刻的基准缓存 (Initial Snapshot)
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from loguru import logger

from commands.base import BaseCommand
from core.workflow import CacheManager
from code_nodes.pre_calculator import MarketStateCalculator
from code_nodes.code0_cmdlist import CommandListGenerator
from utils.console_printer import print_error_summary
from code_nodes.field_calculator import main as calculator_main
from code_nodes.code_input_calc import InputFileCalculator
from core.workflow.agent_executor import AgentExecutor
from core.workflow.pipeline import AnalysisPipeline
from core.error_handler import ErrorHandler
from utils.validators import resolve_input_file_path

class AnalyzeCommand(BaseCommand):
    """Analyze 命令处理器（全功能版）"""
    
    @staticmethod
    def cli_entry(
        symbol: str,
        folder: str,
        input_file: str,
        params_input: str,
        cache: str,
        output: str,
        calc_only: bool,
        model_config: str,
        console: Console
    ):
        """
        CLI 入口方法
        
        Args:
            symbol: 股票代码
            folder: 数据文件夹路径
            input_file: 输入JSON文件路径
            params_input: 市场参数 JSON 或文件路径
            cache: 缓存文件名
            output: 输出文件路径
            calc_only: 仅计算模式
            model_config: 模型配置文件路径
            console: Rich 控制台
        """
        symbol = symbol.upper()
        
        # 参数互斥检查
        if input_file and folder:
            console.print("[red]❌ 参数错误: -i 和 -f 参数互斥[/red]")
            sys.exit(1)
        
        from core.model_client import ModelClientFactory
        from utils.config_loader import config
        
        model_client = ModelClientFactory.create_from_config(model_config)
        env_vars = {'config': config}
        
        # 根据模式准备参数
        if not folder and not input_file:
            # 模式1: 生成命令清单
            if not params_input:
                console.print("[red]❌ 生成命令清单需要指定市场参数 -p[/red]")
                sys.exit(1)
            params = AnalyzeCommand._load_params(params_input)
            params = AnalyzeCommand._validate_market_params(params)
            env_vars['market_params'] = params
            
        elif folder:
            # 模式2: 完整分析
            if not cache:
                console.print(f"[red]❌ 完整分析需要指定缓存文件 --cache[/red]")
                sys.exit(1)
            cache_manager = CacheManager()
            cached = cache_manager.load_market_params_from_cache(symbol, cache)
            if not cached:
                console.print(f"[red]❌ 无法从缓存 {cache} 读取参数[/red]")
                sys.exit(1)
            env_vars['market_params'] = cached.get('market_params', {})
            env_vars['dyn_params'] = cached.get('dyn_params', {})
        
        console.print(f"\n[bold cyan]📊 Swing Quant - 分析 {symbol}[/bold cyan]")
        
        command = AnalyzeCommand(console, model_client, env_vars)
        
        try:
            command.execute(
                symbol=symbol,
                folder=folder,
                input_file=input_file,
                output=output,
                mode='full',
                cache=cache,
                market_params=env_vars.get('market_params'),
                dyn_params=env_vars.get('dyn_params')
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]⚠️ 用户中断[/yellow]")
            sys.exit(0)
    
    @staticmethod
    def _load_params(params_input: str) -> dict:
        """加载市场参数"""
        if not params_input:
            return {}
        
        if params_input.endswith('.json') or Path(params_input).exists():
            path = Path(params_input)
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data.pop('_comment', None)
                    return data
            else:
                raise ValueError(f"参数文件不存在: {params_input}")
        
        try:
            return json.loads(params_input)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败: {e}")
    
    @staticmethod
    def _validate_market_params(params: dict) -> dict:
        """验证市场参数"""
        required = ['vix', 'ivr', 'iv30', 'hv20']
        missing = [k for k in required if k not in params or params[k] is None]
        
        if missing:
            raise ValueError(f"缺少必需参数: {', '.join(missing)}")
        
        params['vix'] = float(params['vix'])
        params['ivr'] = float(params['ivr'])
        params['iv30'] = float(params['iv30'])
        params['hv20'] = float(params['hv20'])
        
        if not (0 <= params['ivr'] <= 100):
            raise ValueError(f"IVR 必须在 0-100 之间")
        if params['vix'] < 0 or params['iv30'] < 0 or params['hv20'] <= 0:
            raise ValueError("VIX/IV30/HV20 必须为正数")
        
        if 'iv_path' not in params or not params['iv_path']:
            params['iv_path'] = 'Insufficient_Data'
        
        return params
    
    def execute(
        self,
        symbol: str,
        folder: str = None,
        input_file: str = None,
        output: str = None,
        mode: str = 'full',
        cache: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行分析命令
        
        Args:
            symbol: 股票代码
            folder: 数据文件夹路径 (图片模式)
            input_file: 输入JSON文件路径 (文件模式)
            output: 输出文件路径
            mode: 运行模式（full/update）
            cache: 缓存文件名
            **kwargs: 额外参数
                - market_params: 市场参数 (vix, ivr, iv30, hv20)
                - dyn_params: 动态参数 (从缓存加载)
                - tag: 工作流标识
        """
        # 1. 验证股票代码
        is_valid, result = self.validate_symbol(symbol)
        if not is_valid:
            self.print_error(result)
            self.console.print("[yellow]💡 示例: python app.py analyze -s AAPL --vix 18.5 --ivr 50[/yellow]")
            sys.exit(1)
        
        # 2. 提取参数
        market_params = kwargs.get('market_params')
        dyn_params = kwargs.get('dyn_params')
        tag = kwargs.get('tag')
        
        # 3. 路由逻辑
        
        # [Mode A] 生成命令清单 (无输入源)
        if not folder and not input_file:
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
        
        # [Mode C] 直接文件分析 (有 JSON 输入, Phase 3 New)
        elif input_file:
            logger.info(f"启动文件分析模式: {symbol} Input={input_file}")
            return self._execute_file_analysis(symbol, input_file, cache, output, market_params)
            
        # [Mode B] 完整视觉分析 (有图片文件夹)
        else:
            # 动态参数处理逻辑
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
                except ValueError as e:
                    self.print_error(f"市场参数验证失败: {e}")
                    sys.exit(1)
            else:
                self.print_error("缺少市场参数，请指定 --cache 参数从缓存加载或手动指定")
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

    def _execute_file_analysis(
        self,
        symbol: str,
        input_file: str,
        cache: str,
        output: str,
        market_params: Dict = None
    ) -> Dict[str, Any]:
        """执行基于文件的直接分析 (建立基准)"""
        
        self.console.print(Panel.fit(
            f"[bold green]📊 初始分析: {symbol.upper()}[/bold green]\n"
            f"[dim]模式: JSON文件直读 (建立基准)[/dim]",
            border_style="green"
        ))
        
        try:
            # 1. 加载输入文件
            input_path, error_msg = resolve_input_file_path(input_file, symbol)
            if not input_path:
                self.print_error(error_msg)
                sys.exit(1)
            
            self.console.print(f"[dim]   📄 输入文件: {input_path}[/dim]")
            
            # [Fix] 使用 InputFileCalculator 预计算 micro_structure (ECR/SER/TSR)
            input_calculator = InputFileCalculator(str(input_path))
            input_calculator.load()
            calc_result = input_calculator.calculate()
            
            # 获取计算后的数据（包含 micro_structure）
            raw_data = input_calculator.data
            spec = raw_data.get("spec", {})
            targets = spec.get("targets", {})
            file_market_params = spec.get("market_override", {})
            
            # [Fix] 将计算出的 micro_structure 注入到 targets.gamma_metrics 中
            if "gamma_metrics" not in targets:
                targets["gamma_metrics"] = {}
            if calc_result.get("micro_structure"):
                targets["gamma_metrics"]["micro_structure"] = calc_result["micro_structure"]
            
            if not targets:
                raise ValueError("输入文件无效: 缺少 spec.targets")

            # 2. 合并市场参数 (CLI > File)
            # Analyze 模式下，这是 T=0 时刻，我们确立这些参数为基准
            current_market_params = file_market_params.copy()
            if market_params:
                current_market_params.update(market_params)
            
            # 补全默认值
            if 'vix' not in current_market_params: current_market_params['vix'] = 20.0
                
            self.console.print(f"[dim]   加载数据: {input_path.name}[/dim]")
            self.console.print(f"[dim]   确立基准参数: VIX={current_market_params.get('vix')}[/dim]")
            
            # 3. 执行计算 (Field Calculator)
            calc_input = {"result": {"targets": targets}}
            
            # 模拟 Event Data (Analyze 模式可能需要从外部获取，此处留空)
            event_data = {} 
            
            calculated_result = calculator_main(
                aggregated_data=calc_input,
                symbol=symbol,
                market_params=current_market_params,
                event_data=event_data
            )
            
            if calculated_result.get("data_status") != "ready":
                 val = calculated_result.get("validation", {})
                 raise ValueError(f"计算失败: {val.get('missing_fields')}")

            # 4. 初始化缓存 (Establish Baseline)
            cache_manager = CacheManager()
            
            # 注入 Market Params 以便缓存记录
            calculated_result["market_params"] = current_market_params
            
            # 自动生成缓存文件名
            if not cache:
                date_str = datetime.now().strftime("%Y%m%d")
                cache = f"{symbol.upper()}_{date_str}.json"
                
            # 保存为 Initial Snapshot
            snapshot_result = cache_manager.save_greeks_snapshot(
                symbol=symbol,
                data=calculated_result,
                note="Initial Analysis (File Mode)",
                is_initial=True, # 标记为初始快照
                cache_file_name=cache
            )
            
            self.console.print(f"\n[green]✅ 分析完成! 基准已建立[/green]")
            self.console.print(f"[dim]   缓存文件: {snapshot_result.get('file_path')}[/dim]")
            
            # 5. 执行完整 pipeline (Fix: 继续下游分析)
            self.console.print(f"\n[bold cyan]🚀 启动完整分析流程...[/bold cyan]")
            
            error_handler = ErrorHandler(symbol)
            agent_executor = AgentExecutor(
                self.model_client, 
                self.env_vars,
                enable_pretty_print=True
            )
            
            pipeline = AnalysisPipeline(
                agent_executor=agent_executor,
                cache_manager=cache_manager,
                env_vars=self.env_vars,
                enable_pretty_print=True,
                cache_file=cache,
                error_handler=error_handler,
                market_params=current_market_params
            )
            
            pipeline_result = pipeline.run(calculated_result)
            
            # 合并 snapshot 信息 (可选)
            if isinstance(pipeline_result, dict):
                pipeline_result["snapshot"] = snapshot_result
            
            return self._handle_result(pipeline_result, symbol, output)
            
        except Exception as e:
            import traceback
            self.console.print(f"[bold red]文件分析失败:[/bold red] {str(e)}")
            self.console.print(traceback.format_exc())
            sys.exit(1)
    
    def _generate_command_list(self, symbol: str, pre_calc: Dict, tag: str = None) -> Dict[str, Any]:
        """生成命令清单 (包含输入模板生成)"""
        self.console.print(Panel.fit(
            f"[bold green]📋 生成命令清单: {symbol.upper()}[/bold green]\n"
            f"[dim]市场场景: {pre_calc['scenario']}[/dim]\n"
            f"[dim]动态参数: Strikes={pre_calc['dyn_strikes']} DTE={pre_calc['dyn_dte_mid']} Window={pre_calc['dyn_window']}[/dim]",
            border_style="green"
        ))
        
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
                title=f"📋 {symbol.upper()} 数据抓取命令清单",
                border_style="green"
            ))
            
            # [Restored] 生成输入文件模板
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
                
                self.console.print(f"\n[yellow]💡 提示：抓取数据后，请使用以下命令执行分析:[/yellow]")
                if tag == 'Meso':
                    self.console.print(
                        f"[cyan]   python app.py q {symbol.upper()} -v <VIX> -f <Folder> -c {cache_filename}[/cyan]"
                    )
                else:
                    self.console.print(
                        f"[cyan]   python app.py analyze {symbol.upper()} -f <Folder> --cache {cache_filename}[/cyan]"
                    )
            else:
                self.console.print("[red]⚠️ 缓存初始化失败（可能已存在）[/red]")
            
            return {
                "status": "success", 
                "content": content, 
                "pre_calc": pre_calc,
                "cache_path": str(cache_path) if cache_path else None,
                "template_path": template_path
            }
        
        except Exception as e:
            self.print_error(str(e))
            sys.exit(1)

    def _generate_input_template(self, symbol: str, pre_calc: Dict, market_params: Dict) -> str:
        """[恢复] 生成标准输入文件模板"""
        from schemas.agent3_schema import get_schema
        
        input_dir = Path("data/input")
        input_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{symbol.lower()}_i_{datetime.now().strftime('%Y%m%d')}.json"
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
                    {"panel_name": "short", "horizon_arg": pre_calc.get('dyn_dte_short'), "rows": []},
                    {"panel_name": "mid", "horizon_arg": pre_calc.get('dyn_dte_mid'), "rows": []},
                    {"panel_name": "long", "horizon_arg": pre_calc.get('dyn_dte_long_backup'), "rows": []}
                ]
            }
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
        
        return str(filepath)

    def _build_template_from_schema(self, schema: Dict, symbol: str = None) -> Any:
        """根据 JSON Schema 递归构建模板"""
        schema_type = schema.get("type")
        
        if schema_type == "object":
            result = {}
            properties = schema.get("properties", {})
            for prop_name, prop_schema in properties.items():
                if prop_name == "symbol" and symbol:
                    result[prop_name] = symbol.upper()
                else:
                    result[prop_name] = self._build_template_from_schema(prop_schema, symbol)
            return result
        elif schema_type == "array":
            return []
        elif schema_type == "string":
            enum_values = schema.get("enum", [])
            return enum_values[0] if enum_values else None
        elif isinstance(schema_type, list):
             # 处理 ["string", "null"] 等情况
            valid_types = [t for t in schema_type if t != "null"]
            if valid_types:
                return self._build_template_from_schema({"type": valid_types[0], **{k:v for k,v in schema.items() if k!="type"}}, symbol)
            return None
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
        """执行完整视觉分析"""
        if mode == 'update' and not cache:
            self.print_error("update 模式必须指定 --cache 参数")
            sys.exit(1)
        
        if cache:
            is_valid, error_msg, _ = self.validate_cache_file(cache, symbol)
            if not is_valid:
                self.print_error(f"缓存验证失败: {error_msg}")
                sys.exit(1)
            self.console.print(f"\n[green]✅ 缓存文件验证通过[/green]")
        
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
            
            # 事件风险展示
            event_risk = result.get("event_risk", {})
            if isinstance(event_risk, dict) and event_risk.get("risk_level", "low") != "low":
                self.console.print(f"\n[red]⚠️ 事件风险: {event_risk.get('risk_level').upper()}[/red]")
        
        return result