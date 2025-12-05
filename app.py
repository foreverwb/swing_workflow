#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Swing Quant Workflow - 主程序入口（重构版）
期权分析策略系统
"""

import sys
from pathlib import Path
import click
from rich.console import Console
from loguru import logger

from core.model_client import ModelClientFactory
from commands import AnalyzeCommand, RefreshCommand
from utils.config_loader import config  # 🆕 使用已有的 ConfigLoader
# 从缓存加载市场参数
from core.workflow import CacheManager

console = Console()


def setup_logging():
    """配置日志（仅控制台输出）"""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
    logger.info("✅ 日志系统初始化完成（控制台模式）")


@click.group()
def cli():
    """Swing Quant Workflow - 期权分析策略系统"""
    pass


@cli.command()
@click.option('--symbol', '-s', required=True, help='股票代码 (如 AAPL)')
@click.option('--folder', '-f', type=click.Path(exists=True), help='数据文件夹路径（可选）')
@click.option('--model-config', '-c', default='config/model_config.yaml', help='模型配置文件路径')
@click.option('--output', '-o', type=click.Path(), help='输出文件路径')
@click.option('--mode', '-m', type=click.Choice(['full', 'update']), default='full', 
              help='运行模式：full=完整分析, update=增量补齐')
@click.option('--cache', type=str, help='指定缓存文件名（如 NVDA_20251127.json）')
# 🆕 新增市场状态参数
@click.option('--vix', type=float, default=None, help='VIX指数 (如 18.5) ')
@click.option('--ivr', type=float, default=None, help='IV Rank 0-100 ')
@click.option('--iv30', type=float, default=None, help='30日隐含波动率 ')
@click.option('--hv20', type=float, default=None, help='20日历史波动率 ')
@click.option('--beta', type=float, default=None, help='股票 Beta 值 - ')
@click.option('--earning-date', type=str, default=None, help='财报日期 YYYY-MM-DD - 可选')
def analyze(symbol: str, folder: str, model_config: str, output: str, mode: str, cache: str,
            vix: float, ivr: float, iv30: float, hv20: float, beta: float, earning_date: str):
    """
    智能分析命令
    - 无文件夹：生成数据抓取命令清单（Agent2）
    - 有文件夹：执行完整期权策略分析（Agent3 → Pipeline）
    
    示例:
        python app.py analyze -s TSLA --vix 28.5 --ivr 85 --iv30 45.2 --hv20 38.7
    """
    setup_logging()
    
    # 加载配置
    console.print("\n[yellow]📁 加载配置...[/yellow]")
    model_client = ModelClientFactory.create_from_config(model_config)
    
    # 初始化 env_vars
    env_vars = {
        'config': config,
    }
    
    # 🆕 验证市场参数
    if not folder:
        # ========== Agent2 模式：必须提供市场参数 ==========
        if not all([vix is not None, ivr is not None, iv30 is not None, hv20 is not None]):
            console.print("[red]❌ 生成命令清单时必须指定市场参数[/red]")
            console.print("[yellow]💡 示例: python app.py analyze -s TSLA --vix 28.5 --ivr 85 --iv30 45.2 --hv20 38.7[/yellow]")
            sys.exit(1)
        
        # 验证市场参数
        try:
            if not (0 <= ivr <= 100):
                raise ValueError(f"IVR 必须在 0-100 之间，当前值: {ivr}")
            if vix < 0 or iv30 < 0 or hv20 <= 0:
                raise ValueError("VIX/IV30/HV20 必须为正数")
            if beta is not None and beta <= 0:
                raise ValueError(f"Beta 必须为正数，当前值: {beta}")
            # 验证财报日期（如果提供）
            if earning_date:
                from datetime import datetime
                try:
                    datetime.strptime(earning_date, "%Y-%m-%d")
                except ValueError:
                    raise ValueError(f"财报日期格式错误，应为 YYYY-MM-DD，当前值: {earning_date}")
        except ValueError as e:
            console.print(f"[red]❌ 参数错误: {e}[/red]")
            sys.exit(1)
        
        env_vars['market_params'] = {
            'vix': vix,
            'ivr': ivr,
            'iv30': iv30,
            'hv20': hv20
        }
        if beta is not None:
            env_vars['market_params']['beta'] = beta
            console.print(f"[dim]   Beta={beta} (用户指定)[/dim]")
        if earning_date:
            env_vars['market_params']['earning_date'] = earning_date
            console.print(f"[dim]   财报日期={earning_date} (用户指定)[/dim]")
        logger.info(f"✅ 市场参数已设置 | VIX={vix}, IVR={ivr}, VRP={iv30/hv20:.2f}")
        
    else:
        # ========== Agent3 模式：从缓存读取市场参数 ==========
        if not cache:
            console.print("[red]❌ 完整分析模式必须指定 --cache 参数[/red]")
            console.print(f"[yellow]💡 示例: python app.py analyze -s {symbol.upper()} -f {folder} --cache {symbol.upper()}_20251130.json[/yellow]")
            sys.exit(1)
        
        cache_manager = CacheManager()
        cached_params = cache_manager.load_market_params_from_cache(symbol.upper(), cache)
        
        if not cached_params:
            console.print(f"[red]❌ 无法从缓存文件 {cache} 读取市场参数[/red]")
            console.print("[yellow]💡 请确保已先执行命令清单生成步骤[/yellow]")
            sys.exit(1)
        
        env_vars['market_params'] = cached_params['market_params']
        env_vars['dyn_params'] = cached_params['dyn_params']
        
        mp = cached_params['market_params']
        dp = cached_params['dyn_params']
        
        beta_info = f", Beta={mp.get('beta')}" if mp.get('beta') else ""
        earning_info = f", 财报={mp.get('earning_date')}" if mp.get('earning_date') else ""
        
        logger.info(f"✅ 从缓存加载市场参数 | VIX={mp.get('vix')}, IVR={mp.get('ivr')}, 场景={dp.get('scenario')}")
        console.print(f"[green]✅ 从缓存加载市场参数[/green]")
        console.print(f"[dim]   VIX={mp.get('vix')}, IVR={mp.get('ivr')}, 场景={dp.get('scenario')}{beta_info}{earning_info}[/dim]")
    
    
    # 创建命令处理器
    command = AnalyzeCommand(console, model_client, env_vars)
    
    
    # 🔧 修复：通过 kwargs 传递 market_params
    try:
        command.execute(
            symbol=symbol,
            folder=folder,
            output=output,
            mode=mode,
            cache=cache,
            market_params=env_vars['market_params'],
            dyn_params=env_vars.get('dyn_params') 
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ 用户中断执行[/yellow]")
        sys.exit(0)


@cli.command()
@click.option('--symbol', '-s', required=True, help='股票代码')
@click.option('--folder', '-f', required=True, type=click.Path(exists=True), help='数据文件夹')
@click.option('--cache', required=True, type=str, help='指定缓存文件名（如 NVDA_20251127.json）')
def refresh(symbol: str, folder: str, cache: str):
    """盘中刷新 Greeks 数据（快速快照）"""
    setup_logging()
    
    # 🆕 优化：直接使用 ConfigLoader
    model_client = ModelClientFactory.create_from_config()
    env_vars = {'config': config}  # 传递 config 实例而非展平字典
    
    cache_manager = CacheManager()
    cached_params = cache_manager.load_market_params_from_cache(symbol.upper(), cache)
    
    if not cached_params:
        console.print(f"[red]❌ 无法从缓存文件 {cache} 读取市场参数[/red]")
        console.print("[yellow]💡 请确保缓存文件存在且包含市场参数[/yellow]")
        sys.exit(1)
    
    env_vars['market_params'] = cached_params['market_params']
    env_vars['dyn_params'] = cached_params['dyn_params']
    
    mp = cached_params['market_params']
    dp = cached_params['dyn_params']
    console.print(f"[green]✅ 从缓存加载市场参数[/green]")
    console.print(f"[dim]   VIX={mp.get('vix')}, IVR={mp.get('ivr')}, 场景={dp.get('scenario')}[/dim]")
    # 创建命令处理器
    command = RefreshCommand(console, model_client, env_vars)
    
    # 执行命令
    try:
        command.execute(
            symbol=symbol,
            folder=folder,
            cache=cache,
            market_params=env_vars['market_params'],
            dyn_params=env_vars['dyn_params']
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ 用户中断执行[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    cli()