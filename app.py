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
@click.option('--vix', type=float, required=True, help='VIX指数 (如 18.5)')
@click.option('--ivr', type=float, required=True, help='IV Rank 0-100 (如 65.3)')
@click.option('--iv30', type=float, required=True, help='30日隐含波动率 (如 42.8)')
@click.option('--hv20', type=float, required=True, help='20日历史波动率 (如 38.2)')
def analyze(symbol: str, folder: str, model_config: str, output: str, mode: str, cache: str,
            vix: float, ivr: float, iv30: float, hv20: float):
    """
    智能分析命令
    - 无文件夹：生成数据抓取命令清单（Agent2）
    - 有文件夹：执行完整期权策略分析（Agent3 → Pipeline）
    
    示例:
        python app.py analyze -s TSLA --vix 28.5 --ivr 85 --iv30 45.2 --hv20 38.7
    """
    setup_logging()
    
    # 🆕 验证市场参数
    try:
        if not (0 <= ivr <= 100):
            raise ValueError(f"IVR 必须在 0-100 之间，当前值: {ivr}")
        if vix < 0 or iv30 < 0 or hv20 <= 0:
            raise ValueError("VIX/IV30/HV20 必须为正数")
    except ValueError as e:
        console.print(f"[red]❌ 参数错误: {e}[/red]")
        sys.exit(1)
    
    # 🆕 优化：直接使用 ConfigLoader（无需手动展平）
    console.print("\n[yellow]📁 加载配置...[/yellow]")
    model_client = ModelClientFactory.create_from_config(model_config)
    
    # 🆕 env_vars 现在直接传递 config 实例，各模块按需获取
    # 不再需要预先展平所有配置项
    env_vars = {
        'config': config,  # 传递 ConfigLoader 单例
        'market_params': {  # 🆕 市场参数
            'vix': vix,
            'ivr': ivr,
            'iv30': iv30,
            'hv20': hv20
        }
    }
    
    logger.info(f"✅ 配置加载完成 | 市场参数: VIX={vix}, IVR={ivr}, VRP={iv30/hv20:.2f}")
    
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
            market_params=env_vars['market_params']  # ✅ 关键修复！
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
    
    # 创建命令处理器
    command = RefreshCommand(console, model_client, env_vars)
    
    # 执行命令
    try:
        command.execute(
            symbol=symbol,
            folder=folder,
            cache=cache
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ 用户中断执行[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    cli()