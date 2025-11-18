#!/usr/bin/env python3
"""
Swing Quant Workflow - 主程序入口
期权分析策略系统
"""

import sys
import yaml
from pathlib import Path
from datetime import datetime
import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from loguru import logger

from core.model_client import ModelClientFactory
from core.workflow_engine import WorkflowEngine


console = Console()


def setup_logging(log_dir: Path = Path("logs")):
    """配置日志"""
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"workflow_{timestamp}.log"
    
    # 配置 loguru
    logger.remove()  # 移除默认handler
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="DEBUG"
    )
    
    return log_file


def load_env_config(config_path: Path = Path("config/env_config.yaml")) -> dict:
    """加载环境变量配置"""
    if not config_path.exists():
        logger.warning(f"环境配置文件不存在: {config_path}, 使用默认值")
        return _get_default_config()
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 展平嵌套结构以兼容旧代码
        flat_config = {}
        
        # Gamma参数
        if 'gamma' in config:
            flat_config.update({
                'EM1_SQRT_FACTOR': config['gamma'].get('em1_sqrt_factor', 0.06299),
                'BREAK_WALL_THRESHOLD_LOW': config['gamma'].get('break_wall_threshold_low', 0.4),
                'BREAK_WALL_THRESHOLD_HIGH': config['gamma'].get('break_wall_threshold_high', 0.8),
                # ... 其他参数
            })
        
        # Scoring参数
        if 'scoring' in config:
            flat_config.update({
                'SCORE_WEIGHT_GAMMA_REGIME': config['scoring'].get('weight_gamma_regime', 0.4),
                'SCORE_WEIGHT_BREAK_WALL': config['scoring'].get('weight_break_wall', 0.3),
                # ... 其他参数
            })
        
        # Alpha Vantage参数
        if 'alpha_vantage' in config:
            flat_config.update({
                'ALPHA_VANTAGE_API_KEY': config['alpha_vantage'].get('api_key', ''),
                'ALPHA_VANTAGE_API_URL': config['alpha_vantage'].get('api_url', ''),
                'ENABLE_EARNINGS_API': config['alpha_vantage'].get('enable_earnings_api', True),
                'EARNINGS_CACHE_DAYS': config['alpha_vantage'].get('earnings_cache_days', 30),
            })
        
        return flat_config
        
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        return _get_default_config()

def _get_default_config() -> dict:
    """返回默认配置（原有的硬编码值）"""
    return {
        "EM1_SQRT_FACTOR": 0.06299,
        # ... 其他默认值
    }


@click.group()
def cli():
    """Swing Quant Workflow - 期权分析策略系统"""
    pass


@cli.command()
@click.option('--symbol', '-s', required=True, help='股票代码 (如 AAPL)')
@click.option('--folder', '-f', required=True, type=click.Path(exists=True), help='数据文件夹路径')
@click.option('--config', '-c', default='config/model_config.yaml', help='模型配置文件路径')
@click.option('--output', '-o', type=click.Path(), help='输出文件路径')
def analyze(symbol: str, folder: str, config: str, output: str):
    """分析单个股票的期权策略"""
    
    # 显示欢迎信息
    console.print(Panel.fit(
        "[bold blue]Swing Quant Workflow[/bold blue]\n"
        "[dim]期权分析策略系统[/dim]",
        border_style="blue"
    ))
    
    # 设置日志
    log_file = setup_logging()
    logger.info(f"日志文件: {log_file}")
    
    # 加载配置
    console.print("\n[yellow]📁 加载配置...[/yellow]")
    model_client = ModelClientFactory.create_from_config(config)
    env_vars = load_env_config()
    
    # 创建工作流引擎
    engine = WorkflowEngine(model_client, env_vars)
    
    # 运行分析
    console.print(f"\n[green]🚀 开始分析 {symbol.upper()}[/green]\n")
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("正在分析...", total=None)
            
            result = engine.run(
                symbol=symbol.upper(),
                data_folder=Path(folder)
            )
            
            progress.update(task, completed=True)
        
        # 显示结果
        if result["status"] == "incomplete":
            console.print("\n[yellow]⚠️ 数据不完整[/yellow]\n")
            console.print(result["guide"])
        
        elif result["status"] == "success":
            console.print("\n[green]✅ 分析完成![/green]\n")
            console.print(Panel(
                result["report"],
                title="📊 分析报告",
                border_style="green"
            ))
            
            # 保存报告
            if output:
                output_path = Path(output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result["report"])
                
                console.print(f"\n[dim]报告已保存至: {output_path}[/dim]")
            
            # 显示事件风险
            if result.get("event_risk", {}).get("risk_level") != "low":
                console.print(f"\n[red]⚠️ 事件风险: {result['event_risk']['risk_level']}[/red]")
        
        else:
            console.print(f"\n[red]❌ 未知状态: {result['status']}[/red]")
    
    except Exception as e:
        logger.exception("分析过程出错")
        console.print(f"\n[red]❌ 错误: {str(e)}[/red]")
        console.print(f"[dim]详细日志: {log_file}[/dim]")
        sys.exit(1)


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
    # TODO: 实现 FastAPI 服务


if __name__ == "__main__":
    cli()