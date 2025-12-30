#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Swing Quant Workflow - 主程序入口（完整版）
期权分析策略系统

命令列表：
- analyze NVDA -p params.json          # 生成命令清单
- analyze NVDA -f ./data --cache XX    # 完整分析
- quick NVDA -v 18.5                   # 快速分析（自动获取参数）
- update NVDA -f ./data --cache XX     # 增量更新
- refresh NVDA -f ./data --cache XX    # 刷新快照
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime
import click
from rich.console import Console
from loguru import logger
from core.model_client import ModelClientFactory
from commands import AnalyzeCommand, RefreshCommand
from utils.config_loader import config
from utils.va_client import VAClient, VAClientError

# ⭐ 关键修复：确保在任意目录运行时都能正确找到项目资源
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_CONFIG = str(PROJECT_ROOT / "config" / "model_config.yaml")

# 切换工作目录到项目根目录
os.chdir(PROJECT_ROOT)
console = Console()


def setup_logging():
    """配置日志（仅控制台输出）"""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
    logger.info("✅ 日志系统初始化完成")


def load_params(params_input: str) -> dict:
    """加载市场参数（支持 JSON 字符串或文件路径）"""
    if not params_input:
        return {}
    
    # 尝试作为文件路径
    if params_input.endswith('.json') or Path(params_input).exists():
        path = Path(params_input)
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                data.pop('_comment', None)
                return data
        else:
            raise click.ClickException(f"参数文件不存在: {params_input}")
    
    # 尝试作为 JSON 字符串解析
    try:
        return json.loads(params_input)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"JSON 解析失败: {e}")


def validate_market_params(params: dict) -> dict:
    """验证市场参数"""
    required = ['vix', 'ivr', 'iv30', 'hv20']
    missing = [k for k in required if k not in params or params[k] is None]
    
    if missing:
        raise click.ClickException(f"缺少必需参数: {', '.join(missing)}")
    
    try:
        params['vix'] = float(params['vix'])
        params['ivr'] = float(params['ivr'])
        params['iv30'] = float(params['iv30'])
        params['hv20'] = float(params['hv20'])
        
        if not (0 <= params['ivr'] <= 100):
            raise ValueError(f"IVR 必须在 0-100 之间，当前值: {params['ivr']}")
        if params['vix'] < 0 or params['iv30'] < 0 or params['hv20'] <= 0:
            raise ValueError("VIX/IV30/HV20 必须为正数")
        
        if 'beta' in params and params['beta'] is not None:
            params['beta'] = float(params['beta'])
            if params['beta'] <= 0:
                raise ValueError(f"Beta 必须为正数，当前值: {params['beta']}")
        
        if 'earning_date' in params and params['earning_date']:
            datetime.strptime(params['earning_date'], "%Y-%m-%d")
            
        if 'iv_path' in params and params['iv_path']:
            valid_iv_paths = ['Rising', 'Falling', 'Flat', 'Insufficient_Data']
            iv_path = str(params['iv_path']).strip()
            
            if iv_path not in valid_iv_paths:
                raise ValueError(
                    f"iv_path 必须是以下值之一: {', '.join(valid_iv_paths)}, "
                    f"当前值: {iv_path}"
                )
            
            params['iv_path'] = iv_path  # 确保是字符串类型
        else:
            # 如果未提供 iv_path，设置默认值
            params['iv_path'] = 'Insufficient_Data'
            
    except ValueError as e:
        raise click.ClickException(f"参数验证失败: {e}")
    
    return params


def load_cache_params(symbol: str, cache: str) -> dict:
    """从缓存加载市场参数"""
    from core.workflow import CacheManager
    cache_manager = CacheManager()
    
    cached = cache_manager.load_market_params_from_cache(symbol.upper(), cache)
    if not cached:
        raise click.ClickException(f"无法从缓存文件 {cache} 读取市场参数")
    
    return cached


# ============================================================
# CLI 命令组
# ============================================================

@click.group()
@click.version_option(version='2.0.0', prog_name='Swing Quant')
def cli():
    """
    Swing Quant Workflow - 期权分析策略系统
    
    \b
    命令列表:
      analyze   完整分析或生成命令清单
      quick     快速分析（自动获取参数）
      update    增量更新（补齐缺失字段）
      refresh   刷新快照（盘中更新）
      params    生成参数模板
    
    \b
    快速开始:
      analyze NVDA -p '{"vix":18,"ivr":65,"iv30":42,"hv20":38}'
      quick NVDA -v 18.5 -f ./data -c NVDA_20251206.json
      refresh NVDA -f ./data -c NVDA_20251206.json
    """
    pass


# ============================================================
# analyze 命令 - 智能分析
# ============================================================

@cli.command()
@click.argument('symbol')
@click.option('-f', '--folder', type=click.Path(exists=True), help='数据文件夹路径')
@click.option('-i', '--input', 'input_file', type=click.Path(), help='输入JSON文件路径 (与 -f 互斥)')
@click.option('-p', '--params', 'params_input', help='市场参数 JSON 或文件路径')
@click.option('-c', '--cache', help='缓存文件名 (如 NVDA_20251206.json)')
@click.option('-o', '--output', type=click.Path(), help='输出文件路径')
@click.option('--calc-only', is_flag=True, help='仅计算 cluster_strength_ratio，不执行下游节点')
@click.option('--model-config', default=DEFAULT_MODEL_CONFIG, help='模型配置文件')
def analyze(symbol: str, folder: str, input_file: str, params_input: str, cache: str, output: str, calc_only: bool, model_config: str):
    """
    智能分析命令
    
    \b
    三种模式：
    1. 生成命令清单（无 -f）：需要 -p 指定市场参数
    2. 完整分析（有 -f）：需要 --cache 指定缓存文件
    3. 输入文件分析（有 -i）：从JSON读取数据，执行完整分析流程
       - 添加 --calc-only 仅计算 cluster_strength_ratio
    
    \b
    注意: -f 和 -i 参数互斥，不能同时使用
    
    \b
    示例:
      # 生成命令清单
      analyze NVDA -p '{"vix":18,"ivr":65,"iv30":42,"hv20":38}'
      
      # 完整分析
      analyze NVDA -f ./data/images --cache NVDA_20251206.json
      
      # 输入文件分析（完整流程）
      analyze AAPL -i ./data/input/symbol_datetime.json --cache AAPL_20251215.json
      
      # 输入文件计算（仅计算 cluster_strength_ratio）
      analyze AAPL -i ./data/input/symbol_datetime.json --calc-only
    """
    setup_logging()
    symbol = symbol.upper()
    
    # 检查 -i 和 -f 参数互斥
    if input_file and folder:
        console.print("[red]❌ 参数错误: -i 和 -f 参数互斥，不能同时使用[/red]")
        console.print("[yellow]💡 提示:[/yellow]")
        console.print("[dim]   使用 -f 进行完整分析（从图片提取数据）[/dim]")
        console.print("[dim]   使用 -i 进行输入文件分析（从JSON读取数据）[/dim]")
        sys.exit(1)
    
    # ========== 模式3: 输入文件分析（-i 参数）==========
    if input_file:
        from code_nodes.code_input_calc import InputFileCalculator, load_json_with_comments
        from code_nodes import calculator_main
        from core.workflow.pipeline import AnalysisPipeline
        from core.workflow import AgentExecutor, CacheManager
        
        console.print(f"\n[bold cyan]📊 Swing Quant - 输入文件分析 {symbol}[/bold cyan]")
        console.print(f"[dim]输入文件: {input_file}[/dim]")
        
        try:
            # Step 1: 加载 JSON 文件
            calculator = InputFileCalculator(input_file)
            calculator.load()
            
            # Step 2: 计算 cluster_strength_ratio
            calc_result = calculator.calculate()
            
            console.print(f"\n[green]✅ cluster_strength_ratio 计算完成[/green]")
            console.print(f"[dim]   Tier: {calc_result['tier']}, Ratio: {calc_result['cluster_strength_ratio']}[/dim]")
            
            # 写回文件
            output_path = output if output else input_file
            calculator.write_back(output_path)
            console.print(f"[dim]   已更新: {output_path}[/dim]")
            
            # 如果仅计算模式，到此结束
            if calc_only:
                console.print(f"\n[cyan]📈 计算结果详情:[/cyan]")
                console.print(f"[dim]   avg_top1: {calc_result['avg_top1']:.4f}[/dim]")
                console.print(f"[dim]   avg_enp:  {calc_result['avg_enp']:.2f}[/dim]")
                console.print(f"[dim]   Short: top1={calc_result['short']['top1']:.4f}, enp={calc_result['short']['enp']:.2f}[/dim]")
                console.print(f"[dim]   Mid:   top1={calc_result['mid']['top1']:.4f}, enp={calc_result['mid']['enp']:.2f}[/dim]")
                console.print(f"[dim]   Long:  top1={calc_result['long']['top1']:.4f}, enp={calc_result['long']['enp']:.2f}[/dim]")
                return
            
            # Step 3: 继续执行下游节点（需要 cache 文件）
            if not cache:
                console.print("\n[yellow]⚠️ 未指定 --cache 参数，跳过下游节点[/yellow]")
                console.print("[dim]   若需执行完整分析，请添加 --cache 参数指定缓存文件[/dim]")
                console.print(f"[dim]   示例: analyze {symbol} -i {input_file} --cache {symbol}_20251215.json[/dim]")
                return
            
            console.print(f"\n[cyan]🔄 继续执行下游节点...[/cyan]")
            
            # 加载缓存参数
            cached = load_cache_params(symbol, cache)
            market_params = cached.get('market_params', {})
            dyn_params = cached.get('dyn_params', {})
            
            console.print(f"[dim]   从缓存加载: market_params={bool(market_params)}, dyn_params={bool(dyn_params)}[/dim]")
            
            # Step 4: 构造 Calculator 输入（与 Agent3 输出格式一致）
            raw_data = load_json_with_comments(input_file)
            agent3_like_data = {
                "targets": raw_data.get("spec", {}).get("targets", {}),
                "indices": raw_data.get("spec", {}).get("indices", {})
            }
            
            # 确保 cluster_strength_ratio 已更新
            if "gamma_metrics" not in agent3_like_data["targets"]:
                agent3_like_data["targets"]["gamma_metrics"] = {}
            agent3_like_data["targets"]["gamma_metrics"]["cluster_strength_ratio"] = calc_result['cluster_strength_ratio']
            
            console.print(f"[dim]   数据转换完成，targets.symbol={agent3_like_data['targets'].get('symbol')}[/dim]")
            
            # Step 5: 将数据写入缓存的 source_target.data（方案 C）
            from core.workflow import CacheManager
            cache_manager = CacheManager()
            
            if cache_manager.update_source_target_data(symbol, cache, agent3_like_data):
                console.print(f"[dim]   ✅ 数据已写入 cache.source_target.data[/dim]")
            else:
                console.print(f"[yellow]   ⚠️ 写入 source_target.data 失败[/yellow]")
            
            # Step 6: 调用 Calculator
            console.print(f"\n[yellow]📐 执行 Calculator...[/yellow]")
            
            # 加载模型配置（Calculator 可能需要）
            model_client = ModelClientFactory.create_from_config(model_config)
            env_vars = {
                'config': config,
                'market_params': market_params
            }
            
            agent_executor = AgentExecutor(model_client, env_vars)
            
            calc_output = agent_executor.execute_code_node(
                node_name="Calculator",
                func=calculator_main,
                aggregated_data=agent3_like_data,
                symbol=symbol,
                **env_vars
            )
            
            # 检查 Calculator 结果
            data_status = calc_output.get("data_status")
            
            if data_status == "awaiting_data":
                console.print("\n[yellow]⚠️ 数据不完整[/yellow]")
                validation = calc_output.get("validation", {})
                missing = validation.get("missing_fields", [])
                if missing:
                    console.print(f"[dim]   缺失字段: {[m.get('path') for m in missing[:5]]}...[/dim]")
                return
            
            console.print(f"[green]   ✅ Calculator 验证通过[/green]")
            
            # Step 7: 执行 Pipeline
            console.print(f"\n[yellow]🚀 执行 Pipeline...[/yellow]")
            
            pipeline = AnalysisPipeline(
                agent_executor=agent_executor,
                cache_manager=cache_manager,
                env_vars=env_vars,
                enable_pretty_print=True,
                cache_file=cache,
                error_handler=None,
                market_params=market_params,
                dyn_params=dyn_params
            )
            
            result = pipeline.run(calc_output)
            
            # Step 7: 处理结果
            status = result.get("status")
            if status == "success":
                console.print("\n[green]✅ 分析完成![/green]")
                
                # 保存报告
                if output:
                    report_path = Path(output).with_suffix('.html')
                    report_content = result.get("report", "")
                    if report_content:
                        report_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(report_path, 'w', encoding='utf-8') as f:
                            f.write(report_content)
                        console.print(f"[dim]   报告已保存: {report_path}[/dim]")
            else:
                console.print(f"\n[yellow]⚠️ 分析状态: {status}[/yellow]")
            
            return
            
        except FileNotFoundError as e:
            console.print(f"[red]❌ 文件不存在: {e}[/red]")
            sys.exit(1)
        except ValueError as e:
            console.print(f"[red]❌ 数据错误: {e}[/red]")
            sys.exit(1)
        except Exception as e:
            import traceback
            console.print(f"[red]❌ 处理失败: {e}[/red]")
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            sys.exit(1)
    
    console.print(f"\n[bold cyan]📊 Swing Quant - 分析 {symbol}[/bold cyan]")
    
    # 加载模型配置
    model_client = ModelClientFactory.create_from_config(model_config)
    env_vars = {'config': config}
    
    if not folder:
        # ========== 模式1: 生成命令清单 ==========
        if not params_input:
            console.print("[red]❌ 生成命令清单需要指定市场参数[/red]")
            console.print("[yellow]💡 示例:[/yellow]")
            console.print(f"[dim]   analyze {symbol} -p '{{\"vix\":18,\"ivr\":65,\"iv30\":42,\"hv20\":38}}'[/dim]")
            sys.exit(1)
        
        params = load_params(params_input)
        params = validate_market_params(params)
        env_vars['market_params'] = params
        
        console.print(f"[green]✅ 市场参数已加载[/green]")
        console.print(f"[dim]   VIX={params['vix']}, IVR={params['ivr']}, VRP={params['iv30']/params['hv20']:.2f}[/dim]")
        
        mode = 'full'
        
    else:
        # ========== 模式2: 完整分析 ==========
        if not cache:
            console.print("[red]❌ 完整分析需要指定缓存文件[/red]")
            console.print(f"[yellow]💡 示例: analyze {symbol} -f {folder} --cache {symbol}_20251206.json[/yellow]")
            sys.exit(1)
        
        # 从缓存加载参数
        cached = load_cache_params(symbol, cache)
        env_vars['market_params'] = cached['market_params']
        env_vars['dyn_params'] = cached['dyn_params']
        
        console.print(f"[green]✅ 从缓存加载参数[/green]")
        mode = 'full'
    
    # 执行命令
    command = AnalyzeCommand(console, model_client, env_vars)
    try:
        command.execute(
            symbol=symbol,
            folder=folder,
            output=output,
            mode=mode,
            cache=cache,
            market_params=env_vars.get('market_params'),
            dyn_params=env_vars.get('dyn_params')
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ 用户中断[/yellow]")
        sys.exit(0)


# ============================================================
# quick 命令 - 快速分析（自动从 VA API 获取参数）
# ============================================================

@cli.command(name='quick')
@click.argument('symbol')
@click.option('-v', '--vix', type=float, required=True, help='VIX 指数（必需）')
@click.option('-t', '--target-date', 'target_date', help='目标日期 (YYYY-MM-DD)')
@click.option('-f', '--folder', type=click.Path(exists=True), help='数据文件夹路径')
@click.option('-c', '--cache', help='缓存文件名')
@click.option('-o', '--output', type=click.Path(), help='输出文件路径')
@click.option('--va-url', default='http://localhost:8668', help='VA API 服务地址')
@click.option('--model-config', default=DEFAULT_MODEL_CONFIG, help='模型配置文件')
def quick(symbol: str, vix: float, target_date: str, folder: str, cache: str, output: str, va_url: str, model_config: str):
    """
    快速分析命令 - 自动从 VA API 获取市场参数
    
    \b
    示例:
      quick NVDA -v 18.5                              # 生成命令清单
      quick NVDA -v 18.5 -f ./data -c NVDA.json      # 完整分析
      quick NVDA -v 18.5 -t 2025-12-06               # 指定历史日期
    """
    
    setup_logging()
    symbol = symbol.upper()
    
    console.print(f"\n[bold cyan]🚀 Swing Quant - 快速分析 {symbol}[/bold cyan]")
    
    # 1. 从 VA API 获取参数
    client = VAClient(base_url=va_url)
    
    try:
        api_params = client.get_params(symbol, vix=vix, date=target_date)
        params = {
            'vix': vix if vix is not None else api_params.get('vix'),
            'ivr': api_params['ivr'],
            'iv30': api_params['iv30'],
            'hv20': api_params['hv20'],
            'iv_path': api_params.get('iv_path', 'N/A')
        }
        
        if api_params.get('earning_date'):
            params['earning_date'] = api_params['earning_date']
        
        console.print(f"[green]✅ 参数获取成功[/green]")
        
    except VAClientError as e:
        console.print(f"[red]❌ VA API 调用失败: {e}[/red]")
        sys.exit(1)
    
    # 2. 验证参数
    params = validate_market_params(params)
    
    # 3. 执行分析
    model_client = ModelClientFactory.create_from_config(model_config)
    env_vars = {
        'config': config,
        'market_params': params,
        'tag': 'Meso'
    }
    
    if folder and cache:
        cached = load_cache_params(symbol, cache)
        env_vars['dyn_params'] = cached['dyn_params']
    
    command = AnalyzeCommand(console, model_client, env_vars)
    try:
        command.execute(
            symbol=symbol,
            folder=folder,
            output=output,
            mode='full',
            cache=cache,
            market_params=params,
            dyn_params=env_vars.get('dyn_params'),
            tag='Meso'
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ 用户中断[/yellow]")
        sys.exit(0)


# ============================================================
# update 命令 - 增量更新
# ============================================================

@cli.command()
@click.argument('symbol')
@click.option('-f', '--folder', type=click.Path(exists=True), required=True, help='数据文件夹路径')
@click.option('-c', '--cache', required=True, help='缓存文件名（必需）')
@click.option('-o', '--output', type=click.Path(), help='输出文件路径')
@click.option('--model-config', default=DEFAULT_MODEL_CONFIG, help='模型配置文件')
def update(symbol: str, folder: str, cache: str, output: str, model_config: str):
    """
    增量更新命令 - 补齐缺失字段
    示例:
      update NVDA -f ./data/new_images -c NVDA_20251206.json
    """
    setup_logging()
    symbol = symbol.upper()
    
    console.print(f"\n[bold yellow]🔄 Swing Quant - 增量更新 {symbol}[/bold yellow]")
    
    # 1. 从缓存加载参数
    try:
        cached = load_cache_params(symbol, cache)
    except click.ClickException as e:
        console.print(f"[red]❌ {e.message}[/red]")
        console.print(f"\n[yellow]💡 提示：update 模式需要先运行完整分析[/yellow]")
        console.print(f"[dim]   python app.py analyze {symbol} -p params.json[/dim]")
        sys.exit(1)
    
    market_params = cached['market_params']
    dyn_params = cached['dyn_params']
    
    console.print(f"[green]✅ 从缓存加载参数[/green]")
    console.print(f"[dim]   场景: {dyn_params.get('scenario')}, VIX={market_params.get('vix')}[/dim]")
    
    # 2. 执行增量更新
    model_client = ModelClientFactory.create_from_config(model_config)
    env_vars = {
        'config': config,
        'market_params': market_params,
        'dyn_params': dyn_params
    }
    
    command = AnalyzeCommand(console, model_client, env_vars)
    try:
        command.execute(
            symbol=symbol,
            folder=folder,
            output=output,
            mode='update',  # 关键：指定为 update 模式
            cache=cache,
            market_params=market_params,
            dyn_params=dyn_params
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ 用户中断[/yellow]")
        sys.exit(0)


# ============================================================
# refresh 命令 - 刷新快照
# ============================================================

@cli.command()
@click.argument('symbol')
@click.option('-f', '--folder', type=click.Path(exists=True), help='数据文件夹路径')
@click.option('-i', '--input', 'input_file', type=click.Path(), help='输入JSON文件路径 (与 -f 互斥)')
@click.option('-c', '--cache', required=True, help='缓存文件名（必需）')
@click.option('--model-config', default=DEFAULT_MODEL_CONFIG, help='模型配置文件')
def refresh(symbol: str, folder: str, input_file: str, cache: str, model_config: str):
    """
    刷新快照命令 - 盘中数据更新
    
    \b
    两种模式：
    1. 图片文件夹模式（-f）：从图片提取数据
    2. 输入文件模式（-i）：从JSON文件读取数据
    
    \b
    注意: -f 和 -i 参数互斥，不能同时使用
    
    \b
    示例:
      # 图片文件夹模式
      refresh NVDA -f ./data/latest -c NVDA_20251206.json
      
      # 输入文件模式
      refresh NVDA -i ./data/input/nvda_datetime.json -c NVDA_20251206.json
    """
    setup_logging()
    symbol = symbol.upper()
    
    # 检查 -i 和 -f 参数互斥
    if input_file and folder:
        console.print("[red]❌ 参数错误: -i 和 -f 参数互斥，不能同时使用[/red]")
        console.print("[yellow]💡 提示:[/yellow]")
        console.print("[dim]   使用 -f 进行图片文件夹模式（从图片提取数据）[/dim]")
        console.print("[dim]   使用 -i 进行输入文件模式（从JSON读取数据）[/dim]")
        sys.exit(1)
    
    # 检查至少有一个数据源
    if not input_file and not folder:
        console.print("[red]❌ 参数错误: 必须指定 -f 或 -i 参数之一[/red]")
        console.print("[yellow]💡 提示:[/yellow]")
        console.print(f"[dim]   refresh {symbol} -f ./data/latest -c {cache}[/dim]")
        console.print(f"[dim]   refresh {symbol} -i ./data/input/{symbol.lower()}_datetime.json -c {cache}[/dim]")
        sys.exit(1)
    
    console.print(f"\n[bold magenta]📸 Swing Quant - 刷新快照 {symbol}[/bold magenta]")
    
    # 1. 从缓存加载参数
    try:
        cached = load_cache_params(symbol, cache)
    except click.ClickException as e:
        console.print(f"[red]❌ {e.message}[/red]")
        console.print(f"\n[yellow]💡 提示：refresh 模式需要先运行完整分析[/yellow]")
        console.print(f"[dim]   python app.py analyze {symbol} -f ./data --cache {cache}[/dim]")
        sys.exit(1)
    
    market_params = cached['market_params']
    dyn_params = cached['dyn_params']
    
    console.print(f"[green]✅ 从缓存加载参数[/green]")
    console.print(f"[dim]   场景: {dyn_params.get('scenario')}, VIX={market_params.get('vix')}[/dim]")
    
    # 2. 执行刷新
    model_client = ModelClientFactory.create_from_config(model_config)
    env_vars = {
        'config': config,
        'market_params': market_params,
        'dyn_params': dyn_params
    }
    
    command = RefreshCommand(console, model_client, env_vars)
    try:
        command.execute(
            symbol=symbol,
            folder=folder,
            input_file=input_file,  # 新增：传递输入文件参数
            cache=cache,
            market_params=market_params,
            dyn_params=dyn_params
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ 用户中断[/yellow]")
        sys.exit(0)


# ============================================================
# params 命令 - 参数模板
# ============================================================

@cli.command()
@click.option('-o', '--output', default='params.json', help='输出文件路径')
@click.option('--example', is_flag=True, help='生成带示例值的模板')
def params(output: str, example: bool):
    """
    生成参数模板文件
    
    \b
    示例:
      params                    # 生成空模板
      params -o nvda.json       # 指定输出文件
      params --example          # 生成带示例值
    """
    template = {
        "vix": 18.5 if example else None,
        "ivr": 65 if example else None,
        "iv30": 42.8 if example else None,
        "hv20": 38.2 if example else None,
        "beta": 1.7 if example else None,
        "earning_date": "2025-01-25" if example else None
    }
    
    template["_comment"] = {
        "vix": "VIX 指数（必需）",
        "ivr": "IV Rank 0-100（必需）",
        "iv30": "30日隐含波动率（必需）",
        "hv20": "20日历史波动率（必需）",
        "beta": "股票 Beta 值（可选）",
        "earning_date": "财报日期 YYYY-MM-DD（可选）"
    }
    
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
    
    console.print(f"[green]✅ 参数模板已生成: {output}[/green]")
    console.print(f"[dim]编辑后使用: analyze SYMBOL -p {output}[/dim]")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    cli()