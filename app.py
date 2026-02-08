#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Swing Quant Workflow - 主程序入口
期权分析策略系统

命令列表：
- analyze NVDA -p params.json          # 生成命令清单
- analyze NVDA -f ./data --cache XX    # 完整分析
- quick NVDA                           # 快速分析（自动获取参数）
- mass -d 2026-01-04                    # 批量准备输入模板
- refresh NVDA -f ./data --cache XX    # 刷新快照
"""

import sys
import os
import json
from pathlib import Path

import click
from rich.console import Console
from loguru import logger

# 确保在任意目录运行时都能正确找到项目资源
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_CONFIG = str(PROJECT_ROOT / "config" / "model_config.yaml")

os.chdir(PROJECT_ROOT)
console = Console()


def setup_logging(level: str = "INFO"):
    """配置日志"""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level=level
    )


# ============================================================
# CLI 命令组
# ============================================================

@click.group()
@click.version_option(version='3.0.0', prog_name='Swing Quant')
def cli():
    """
    Swing Quant Workflow - 期权分析策略系统
    
    \b
    命令列表:
      analyze   完整分析或生成命令清单
      quick     快速分析（自动获取参数）
      mass      批量准备命令清单和输入模板
      refresh   刷新快照（盘中更新）
      params    生成参数模板
    
    \b
    快速开始:
      analyze NVDA -p '{"vix":18,"ivr":65,"iv30":42,"hv20":38}'
      quick NVDA -f ./data -c NVDA_20251206.json
      refresh NVDA -f ./data -c NVDA_20251206.json
    """
    pass


# ============================================================
# analyze 命令
# ============================================================

@cli.command()
@click.argument('symbol')
@click.option('-f', '--folder', type=click.Path(exists=True), help='数据文件夹路径')
@click.option('-i', '--input', 'input_file', type=click.Path(), help='输入JSON文件路径 (与 -f 互斥)')
@click.option('-p', '--params', 'params_input', help='市场参数 JSON 或文件路径')
@click.option('-c', '--cache', help='缓存文件名 (如 NVDA_20251206.json)')
@click.option('-o', '--output', type=click.Path(), help='输出文件路径')
@click.option('--calc-only', is_flag=True, help='仅计算 cluster_strength_ratio')
@click.option('--model-config', default=DEFAULT_MODEL_CONFIG, help='模型配置文件')
def analyze(symbol: str, folder: str, input_file: str, params_input: str, cache: str, output: str, calc_only: bool, model_config: str):
    """
    智能分析命令
    
    \b
    三种模式：
    1. 生成命令清单（无 -f）：需要 -p 指定市场参数
    2. 完整分析（有 -f）：需要 --cache 指定缓存文件
    3. 输入文件分析（有 -i）：从JSON读取数据
    
    \b
    示例:
      analyze NVDA -p '{"vix":18,"ivr":65,"iv30":42,"hv20":38}'
      analyze NVDA -f ./data/images --cache NVDA_20251206.json
      analyze AAPL -i ./data/input/symbol_datetime.json --cache AAPL_20251215.json
    """
    setup_logging()
    
    from commands import AnalyzeCommand
    AnalyzeCommand.cli_entry(
        symbol=symbol,
        folder=folder,
        input_file=input_file,
        params_input=params_input,
        cache=cache,
        output=output,
        calc_only=calc_only,
        model_config=model_config,
        console=console
    )


# ============================================================
# quick 命令
# ============================================================

@cli.command(name='quick')
@click.argument('symbol')
@click.option('-v', '--vix', type=float, help='VIX 指数（可选）')
@click.option('-t', '--target-date', '-d', '--date', 'target_date', help='目标日期 (YYYY-MM-DD)')
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
      quick NVDA                                  # 自动获取参数
      quick NVDA -v 18.5                         # 指定VIX
      quick NVDA -f ./data -c NVDA.json          # 完整分析
      quick NVDA -t 2025-12-06                   # 指定历史日期
    """
    setup_logging()
    
    from commands import QuickCommand
    QuickCommand.cli_entry(
        symbol=symbol,
        vix=vix,
        target_date=target_date,
        folder=folder,
        cache=cache,
        output=output,
        va_url=va_url,
        model_config=model_config,
        console=console
    )


# ============================================================
# mass 命令
# ============================================================

@cli.command(name='mass')
@click.option('-d', '--date', 'target_date', default=None, help='目标日期 (YYYY-MM-DD)，默认当天')
@click.option('-s', '--symbol', 'symbols', multiple=True, help='指定 symbol，可重复或逗号分隔')
@click.option('--va-url', default='http://localhost:8668', help='VA API 服务地址')
@click.option('--model-config', default=DEFAULT_MODEL_CONFIG, help='模型配置文件')
def mass(target_date: str, symbols: tuple[str, ...], va_url: str, model_config: str):
    """
    批量准备命令 - 为指定日期批量生成命令清单与输入模板

    \b
    示例:
      mass -d 2026-01-04
      mass -d 2026-01-04 -s NVDA -s AAPL
      mass -s NVDA,MSFT
    """
    setup_logging(level="WARNING")

    from commands import MassCommand
    MassCommand.cli_entry(
        target_date=target_date,
        symbols=list(symbols),
        va_url=va_url,
        model_config=model_config,
        console=console
    )


# ============================================================
# refresh 命令
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
    示例:
      refresh NVDA -f ./data/latest -c NVDA_20251206.json
      refresh NVDA -i ./data/input/nvda.json -c NVDA_20251206.json
    """
    setup_logging()
    
    from commands import RefreshCommand
    RefreshCommand.cli_entry(
        symbol=symbol,
        folder=folder,
        input_file=input_file,
        cache=cache,
        model_config=model_config,
        console=console
    )


# ============================================================
# params 命令
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
        "earning_date": "2025-01-25" if example else None,
        "_comment": {
            "vix": "VIX 指数（必需）",
            "ivr": "IV Rank 0-100（必需）",
            "iv30": "30日隐含波动率（必需）",
            "hv20": "20日历史波动率（必需）",
            "beta": "股票 Beta 值（可选）",
            "earning_date": "财报日期 YYYY-MM-DD（可选）"
        }
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
