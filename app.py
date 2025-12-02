#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Swing Quant Workflow - 主程序入口（重构版）
期权分析策略系统
"""

import sys
import yaml
from pathlib import Path
import click
from rich.console import Console
from loguru import logger

from core.model_client import ModelClientFactory
from commands import AnalyzeCommand, RefreshCommand


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


def load_env_config(config_path: Path = Path("config/env_config.yaml")) -> dict:
    """加载环境变量配置"""
    if not config_path.exists():
        logger.warning(f"环境配置文件不存在: {config_path}, 使用默认值")
        return {"EM1_SQRT_FACTOR": 0.06299}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 展平嵌套结构（简化版）
        flat_config = {}
        
        # Gamma参数
        if 'gamma' in config:
            flat_config.update({
                'EM1_SQRT_FACTOR': config['gamma'].get('em1_sqrt_factor', 0.06299),
                'BREAK_WALL_THRESHOLD_LOW': config['gamma'].get('break_wall_threshold_low', 0.4),
                'BREAK_WALL_THRESHOLD_HIGH': config['gamma'].get('break_wall_threshold_high', 0.8),
                'MONTHLY_OVERRIDE_THRESHOLD': config['gamma'].get('monthly_override_threshold', 0.7),
                'MONTHLY_CLUSTER_STRENGTH_RATIO': config['gamma'].get('monthly_cluster_strength_ratio', 1.5),
                'CLUSTER_STRENGTH_THRESHOLD_T': config['gamma'].get('cluster_strength_threshold_t', 1.2),
                'CLUSTER_STRENGTH_THRESHOLD_S': config['gamma'].get('cluster_strength_threshold_s', 2.0),
                'WALL_CLUSTER_WIDTH': config['gamma'].get('wall_cluster_width', 3),
                'WALL_PEAK_MULTIPLIER': config['gamma'].get('wall_peak_multiplier', 2.0),
            })
        
        # Direction参数
        if 'direction' in config:
            flat_config.update({
                'DEX_SAME_DIR_THRESHOLD_STRONG': config['direction'].get('dex_same_dir_threshold_strong', 70),
                'DEX_SAME_DIR_THRESHOLD_MEDIUM': config['direction'].get('dex_same_dir_threshold_medium', 60),
                'DEX_SAME_DIR_THRESHOLD_WEAK': config['direction'].get('dex_same_dir_threshold_weak', 50),
                'IV_PATH_THRESHOLD_VOL': config['direction'].get('iv_path_threshold_vol', 2),
                'IV_PATH_THRESHOLD_PCT': config['direction'].get('iv_path_threshold_pct', 10),
                'IV_NOISE_THRESHOLD': config['direction'].get('iv_noise_threshold', 30),
            })
        
        # ... (其他配置项按需添加)
        
        logger.info(f"✅ 成功加载 {len(flat_config)} 个环境变量")
        return flat_config
        
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        return {"EM1_SQRT_FACTOR": 0.06299}


@click.group()
def cli():
    """Swing Quant Workflow - 期权分析策略系统"""
    pass


@cli.command()
@click.option('--symbol', '-s', required=True, help='股票代码 (如 AAPL)')
@click.option('--folder', '-f', type=click.Path(exists=True), help='数据文件夹路径（可选）')
@click.option('--config', '-c', default='config/model_config.yaml', help='模型配置文件路径')
@click.option('--output', '-o', type=click.Path(), help='输出文件路径')
@click.option('--mode', '-m', type=click.Choice(['full', 'update']), default='full', 
              help='运行模式：full=完整分析, update=增量补齐')
@click.option('--cache', type=str, help='指定缓存文件名（如 NVDA_20251127.json）')
def analyze(symbol: str, folder: str, config: str, output: str, mode: str, cache: str):
    """
    智能分析命令
    - 无文件夹：生成数据抓取命令清单（Agent2）
    - 有文件夹：执行完整期权策略分析（Agent3 → Pipeline）
    """
    setup_logging()
    
    # 加载配置
    console.print("\n[yellow]📁 加载配置...[/yellow]")
    model_client = ModelClientFactory.create_from_config(config)
    env_vars = load_env_config()
    
    # 创建命令处理器
    command = AnalyzeCommand(console, model_client, env_vars)
    
    # 执行命令
    try:
        command.execute(
            symbol=symbol,
            folder=folder,
            output=output,
            mode=mode,
            cache=cache
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
    
    # 加载配置
    model_client = ModelClientFactory.create_from_config()
    env_vars = load_env_config()
    
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


@cli.command()
@click.option('--symbol', '-s', required=True, help='股票代码')
@click.option('--format', '-f', type=click.Choice(['table', 'json']), default='table', help='输出格式')
def history(symbol: str, format: str):
    """查看历史快照"""
    # TODO: 实现 HistoryCommand
    console.print("[yellow]⚠️ 功能开发中...[/yellow]")


@cli.command()
@click.option('--symbol', '-s', required=True, help='股票代码')
@click.option('--test-date', '-d', required=True, help='回测日期 YYYY-MM-DD')
@click.option('--folder', '-f', required=True, type=click.Path(exists=True), help='实际数据文件夹')
def backtest(symbol: str, test_date: str, folder: str):
    """回测验证（检验预测准确性）"""
    # TODO: 实现 BacktestCommand
    console.print("[yellow]⚠️ 功能开发中...[/yellow]")


@cli.command()
def interactive():
    """交互式模式"""
    console.print(Panel.fit(
        "[bold blue]Swing Quant Workflow - 交互式模式[/bold blue]",
        border_style="blue"
    ))
    
    # 获取输入
    symbol = console.input("\n[yellow]请输入股票代码:[/yellow] ").strip().upper()
    folder = console.input("[yellow]请输入数据文件夹路径:[/yellow] ").strip()
    
    if not symbol or not folder:
        console.print("[red]❌ 输入无效[/red]")
        return
    
    # 调用分析命令
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(analyze, ['--symbol', symbol, '--folder', folder])
    
    if result.exit_code != 0:
        console.print(f"[red]执行失败: {result.output}[/red]")


@cli.command()
@click.option('--port', '-p', default=8000, help='API 服务端口')
def api(port: int):
    """启动 API 服务（开发中）"""
    console.print("[yellow]⚠️ API 模式正在开发中...[/yellow]")


if __name__ == "__main__":
    cli()