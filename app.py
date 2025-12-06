#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Swing Quant Workflow - 主程序入口（优化版）
期权分析策略系统

命令简化：
- analyze NVDA -p params.json          # 生成命令清单
- analyze NVDA -f ./data --cache XX    # 完整分析
- update NVDA -f ./data --cache XX     # 增量更新
- refresh NVDA -f ./data --cache XX    # 刷新快照
"""

import sys
import json
from pathlib import Path
from datetime import datetime
import click
from rich.console import Console
from loguru import logger

from core.model_client import ModelClientFactory
from commands import AnalyzeCommand, RefreshCommand
from utils.config_loader import config


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
    """
    加载市场参数（支持 JSON 字符串或文件路径）
    
    Args:
        params_input: JSON 字符串或 .json 文件路径
        
    Returns:
        解析后的参数字典
    """
    if not params_input:
        return {}
    
    # 尝试作为文件路径
    if params_input.endswith('.json') or Path(params_input).exists():
        path = Path(params_input)
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 移除注释字段
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
    """
    验证市场参数
    
    必需字段: vix, ivr, iv30, hv20
    可选字段: beta, earning_date
    """
    required = ['vix', 'ivr', 'iv30', 'hv20']
    missing = [k for k in required if k not in params or params[k] is None]
    
    if missing:
        raise click.ClickException(f"缺少必需参数: {', '.join(missing)}")
    
    # 类型转换和验证
    try:
        params['vix'] = float(params['vix'])
        params['ivr'] = float(params['ivr'])
        params['iv30'] = float(params['iv30'])
        params['hv20'] = float(params['hv20'])
        
        if not (0 <= params['ivr'] <= 100):
            raise ValueError(f"IVR 必须在 0-100 之间，当前值: {params['ivr']}")
        if params['vix'] < 0 or params['iv30'] < 0 or params['hv20'] <= 0:
            raise ValueError("VIX/IV30/HV20 必须为正数")
        
        # 可选参数验证
        if 'beta' in params and params['beta'] is not None:
            params['beta'] = float(params['beta'])
            if params['beta'] <= 0:
                raise ValueError(f"Beta 必须为正数，当前值: {params['beta']}")
        
        if 'earning_date' in params and params['earning_date']:
            datetime.strptime(params['earning_date'], "%Y-%m-%d")
            
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
    快速开始:
      analyze NVDA -p '{"vix":18,"ivr":65,"iv30":42,"hv20":38}'
      analyze NVDA -f ./data --cache NVDA_20251206.json
      update NVDA -f ./data --cache NVDA_20251206.json
      refresh NVDA -f ./data --cache NVDA_20251206.json
    """
    pass


# ============================================================
# analyze 命令 - 智能分析
# ============================================================

@cli.command()
@click.argument('symbol')
@click.option('-f', '--folder', type=click.Path(exists=True), help='数据文件夹路径')
@click.option('-p', '--params', 'params_input', help='市场参数 JSON 或文件路径')
@click.option('-c', '--cache', help='缓存文件名 (如 NVDA_20251206.json)')
@click.option('-o', '--output', type=click.Path(), help='输出文件路径')
@click.option('--model-config', default='config/model_config.yaml', help='模型配置文件')
def analyze(symbol: str, folder: str, params_input: str, cache: str, output: str, model_config: str):
    """
    智能分析命令
    
    \b
    两种模式：
    1. 生成命令清单（无 -f）：需要 -p 指定市场参数
    2. 完整分析（有 -f）：需要 --cache 指定缓存文件
    
    \b
    示例:
      # 生成命令清单
      analyze NVDA -p '{"vix":18,"ivr":65,"iv30":42,"hv20":38}'
      analyze NVDA -p params.json
      
      # 完整分析
      analyze NVDA -f ./data/images --cache NVDA_20251206.json
    
    \b
    参数 JSON 格式:
      {
        "vix": 18.5,      # VIX 指数（必需）
        "ivr": 65,        # IV Rank 0-100（必需）
        "iv30": 42.8,     # 30日隐含波动率（必需）
        "hv20": 38.2,     # 20日历史波动率（必需）
        "beta": 1.7,      # Beta 值（可选）
        "earning_date": "2025-01-25"  # 财报日期（可选）
      }
    """
    setup_logging()
    symbol = symbol.upper()
    
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
            console.print(f"[dim]   analyze {symbol} -p params.json[/dim]")
            sys.exit(1)
        
        # 加载并验证参数
        params = load_params(params_input)
        params = validate_market_params(params)
        
        env_vars['market_params'] = params
        
        # 显示参数
        console.print(f"[green]✅ 市场参数已加载[/green]")
        console.print(f"[dim]   VIX={params['vix']}, IVR={params['ivr']}, VRP={params['iv30']/params['hv20']:.2f}[/dim]")
        if params.get('beta'):
            console.print(f"[dim]   Beta={params['beta']}[/dim]")
        if params.get('earning_date'):
            console.print(f"[dim]   财报日期={params['earning_date']}[/dim]")
        
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
        
        mp = cached['market_params']
        dp = cached['dyn_params']
        
        console.print(f"[green]✅ 从缓存加载参数[/green]")
        info_parts = [f"VIX={mp.get('vix')}", f"IVR={mp.get('ivr')}", f"场景={dp.get('scenario')}"]
        if mp.get('beta'):
            info_parts.append(f"Beta={mp.get('beta')}")
        console.print(f"[dim]   {', '.join(info_parts)}[/dim]")
        
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
# 工作流标识: Meso → Micro
# ============================================================

@cli.command(name='quick')
@click.argument('symbol')
@click.option('-v', '--vix', type=float, required=True, help='VIX 指数（必需）')
@click.option('-f', '--folder', type=click.Path(exists=True), help='数据文件夹路径')
@click.option('-c', '--cache', help='缓存文件名')
@click.option('-o', '--output', type=click.Path(), help='输出文件路径')
@click.option('--va-url', default='http://localhost:8668', help='VA API 服务地址')
@click.option('--model-config', default='config/model_config.yaml', help='模型配置文件')
def quick(symbol: str, vix: float, folder: str, cache: str, output: str, va_url: str, model_config: str):
    """
    快速分析命令 - 自动从 VA API 获取市场参数
    
    仅需指定 symbol 和 VIX，其他参数（IVR/IV30/HV20/财报日期）自动从
    volatility_analysis 服务获取。
    
    \b
    工作流标识: Meso → Micro
    
    \b
    前置条件:
      确保 volatility_analysis 服务正在运行:
      cd volatility_analysis && python app.py
    
    \b
    示例:
      # 生成命令清单（Agent2）
      quick NVDA -v 18.5
      
      # 完整分析（Agent3 → Pipeline）
      quick NVDA -v 18.5 -f ./data/images -c NVDA_20251206.json
    """
    from utils.va_client import VAClient, VAClientError
    
    setup_logging()
    symbol = symbol.upper()
    
    # 输出工作流标识
    console.print(f"\n[bold magenta]═══════════════════════════════════════[/bold magenta]")
    console.print(f"[bold magenta]       Meso → Micro 分析工作流        [/bold magenta]")
    console.print(f"[bold magenta]═══════════════════════════════════════[/bold magenta]")
    
    console.print(f"\n[bold cyan]🚀 Swing Quant - 快速分析 {symbol}[/bold cyan]")
    console.print(f"[dim]VA API: {va_url}[/dim]")
    
    # 1. 从 VA API 获取参数
    console.print(f"\n[yellow]📡 正在从 VA API 获取 {symbol} 的市场参数...[/yellow]")
    
    client = VAClient(base_url=va_url)
    
    try:
        api_params = client.get_params(symbol, vix=vix)
        
        # 验证必要参数
        missing = [k for k in ['ivr', 'iv30', 'hv20'] if api_params.get(k) is None]
        if missing:
            console.print(f"[red]❌ VA API 返回的数据缺少必要字段: {missing}[/red]")
            sys.exit(1)
        
        # 构建完整参数
        params = {
            'vix': vix,
            'ivr': api_params['ivr'],
            'iv30': api_params['iv30'],
            'hv20': api_params['hv20'],
        }
        
        if api_params.get('earning_date'):
            params['earning_date'] = api_params['earning_date']
        
        console.print(f"[green]✅ 参数获取成功[/green]")
        console.print(f"[dim]   VIX={params['vix']}, IVR={params['ivr']}, IV30={params['iv30']}, HV20={params['hv20']}[/dim]")
        console.print(f"[dim]   VRP={params['iv30']/params['hv20']:.2f}[/dim]")
        if params.get('earning_date'):
            console.print(f"[dim]   财报日期={params['earning_date']}[/dim]")
        
    except VAClientError as e:
        console.print(f"[red]❌ VA API 调用失败: {e}[/red]")
        console.print("[yellow]💡 请确保 volatility_analysis 服务正在运行:[/yellow]")
        console.print("[dim]   cd volatility_analysis && python app.py[/dim]")
        sys.exit(1)
    
    # 2. 验证参数
    params = validate_market_params(params)
    
    # 3. 加载模型配置
    model_client = ModelClientFactory.create_from_config(model_config)
    env_vars = {
        'config': config,
        'market_params': params,
        'tag': 'Meso'  # 添加工作流标识
    }
    
    # 4. 判断模式并执行
    if not folder:
        # 模式1: 生成命令清单
        mode = 'full'
    else:
        # 模式2: 完整分析
        if not cache:
            console.print("[red]❌ 完整分析需要指定缓存文件[/red]")
            console.print(f"[yellow]💡 示例: q {symbol} -v {vix} -f {folder} -c {symbol}_20251206.json[/yellow]")
            sys.exit(1)
        
        # 从缓存加载动态参数
        cached = load_cache_params(symbol, cache)
        env_vars['dyn_params'] = cached['dyn_params']
        
        console.print(f"[green]✅ 从缓存加载动态参数[/green]")
        console.print(f"[dim]   场景={cached['dyn_params'].get('scenario')}[/dim]")
        
        mode = 'full'
    
    # 5. 执行分析
    command = AnalyzeCommand(console, model_client, env_vars)
    try:
        command.execute(
            symbol=symbol,
            folder=folder,
            output=output,
            mode=mode,
            cache=cache,
            market_params=env_vars.get('market_params'),
            dyn_params=env_vars.get('dyn_params'),
            tag=env_vars.get('tag')  # 传递 tag 参数
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ 用户中断[/yellow]")
        sys.exit(0)


# ============================================================
# update 命令 - 增量更新
# ============================================================

@cli.command()
@click.argument('symbol')
@click.option('-f', '--folder', required=True, type=click.Path(exists=True), help='数据文件夹路径')
@click.option('-c', '--cache', required=True, help='缓存文件名')
@click.option('-o', '--output', type=click.Path(), help='输出文件路径')
@click.option('--model-config', default='config/model_config.yaml', help='模型配置文件')
def update(symbol: str, folder: str, cache: str, output: str, model_config: str):
    """
    增量更新命令
    
    在现有分析基础上补齐缺失字段，保留历史数据。
    
    \b
    示例:
      update NVDA -f ./data/images --cache NVDA_20251206.json
    """
    setup_logging()
    symbol = symbol.upper()
    
    console.print(f"\n[bold cyan]🔄 Swing Quant - 增量更新 {symbol}[/bold cyan]")
    
    # 加载配置和缓存
    model_client = ModelClientFactory.create_from_config(model_config)
    env_vars = {'config': config}
    
    cached = load_cache_params(symbol, cache)
    env_vars['market_params'] = cached['market_params']
    env_vars['dyn_params'] = cached['dyn_params']
    
    mp = cached['market_params']
    dp = cached['dyn_params']
    console.print(f"[green]✅ 从缓存加载参数[/green]")
    console.print(f"[dim]   VIX={mp.get('vix')}, IVR={mp.get('ivr')}, 场景={dp.get('scenario')}[/dim]")
    
    # 执行命令
    command = AnalyzeCommand(console, model_client, env_vars)
    try:
        command.execute(
            symbol=symbol,
            folder=folder,
            output=output,
            mode='update',  # 关键：使用 update 模式
            cache=cache,
            market_params=env_vars['market_params'],
            dyn_params=env_vars['dyn_params']
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ 用户中断[/yellow]")
        sys.exit(0)


# ============================================================
# refresh 命令 - 刷新快照
# ============================================================

@cli.command()
@click.argument('symbol')
@click.option('-f', '--folder', required=True, type=click.Path(exists=True), help='数据文件夹路径')
@click.option('-c', '--cache', required=True, help='缓存文件名')
@click.option('--model-config', default='config/model_config.yaml', help='模型配置文件')
def refresh(symbol: str, folder: str, cache: str, model_config: str):
    """
    刷新快照命令
    
    盘中快速刷新 Greeks 数据，生成新快照。
    
    \b
    示例:
      refresh NVDA -f ./data/images --cache NVDA_20251206.json
    """
    setup_logging()
    symbol = symbol.upper()
    
    console.print(f"\n[bold cyan]📸 Swing Quant - 刷新快照 {symbol}[/bold cyan]")
    
    # 加载配置和缓存
    model_client = ModelClientFactory.create_from_config(model_config)
    env_vars = {'config': config}
    
    cached = load_cache_params(symbol, cache)
    env_vars['market_params'] = cached['market_params']
    env_vars['dyn_params'] = cached['dyn_params']
    
    mp = cached['market_params']
    dp = cached['dyn_params']
    console.print(f"[green]✅ 从缓存加载参数[/green]")
    console.print(f"[dim]   VIX={mp.get('vix')}, IVR={mp.get('ivr')}, 场景={dp.get('scenario')}[/dim]")
    
    # 执行命令
    command = RefreshCommand(console, model_client, env_vars)
    try:
        command.execute(
            symbol=symbol,
            folder=folder,
            cache=cache,
            market_params=env_vars['market_params'],
            dyn_params=env_vars['dyn_params']
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
      params                    # 生成空模板 params.json
      params -o nvda.json       # 指定输出文件名
      params --example          # 生成带示例值的模板
    """
    template = {
        "vix": 18.5 if example else None,
        "ivr": 65 if example else None,
        "iv30": 42.8 if example else None,
        "hv20": 38.2 if example else None,
        "beta": 1.7 if example else None,
        "earning_date": "2025-01-25" if example else None
    }
    
    # 添加注释（作为额外字段）
    template["_comment"] = {
        "vix": "VIX 指数（必需）",
        "ivr": "IV Rank 0-100（必需）",
        "iv30": "30日隐含波动率（必需）",
        "hv20": "20日历史波动率（必需）",
        "beta": "股票 Beta 值（可选，覆盖配置预设）",
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