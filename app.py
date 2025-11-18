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
        
        # ✅ 展平嵌套结构
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
        
        # DTE参数
        if 'dte' in config:
            flat_config.update({
                'DEFAULT_DTE_WEEKLY_SHORT': config['dte'].get('default_weekly_short', 7),
                'DEFAULT_DTE_WEEKLY_MID': config['dte'].get('default_weekly_mid', 14),
                'DEFAULT_DTE_MONTHLY_SHORT': config['dte'].get('default_monthly_short', 30),
                'DEFAULT_DTE_MONTHLY_MID': config['dte'].get('default_monthly_mid', 60),
                'DTE_GAP_HIGH_THRESHOLD': config['dte'].get('gap_high_threshold', 3),
                'DTE_GAP_MID_THRESHOLD': config['dte'].get('gap_mid_threshold', 2),
                'DTE_MONTHLY_ADJUSTMENT': config['dte'].get('monthly_adjustment', 7),
            })
        
        # Scoring参数
        if 'scoring' in config:
            flat_config.update({
                'SCORE_WEIGHT_GAMMA_REGIME': config['scoring'].get('weight_gamma_regime', 0.4),
                'SCORE_WEIGHT_BREAK_WALL': config['scoring'].get('weight_break_wall', 0.3),
                'SCORE_WEIGHT_DIRECTION': config['scoring'].get('weight_direction', 0.2),
                'SCORE_WEIGHT_IV': config['scoring'].get('weight_iv', 0.1),
                'ENTRY_THRESHOLD_SCORE': config['scoring'].get('entry_threshold_score', 3),
                'ENTRY_THRESHOLD_PROBABILITY': config['scoring'].get('entry_threshold_probability', 60),
                'LIGHT_POSITION_PROBABILITY': config['scoring'].get('light_position_probability', 50),
                'TECHNICAL_SCORE_MAX': config['scoring'].get('technical_score_max', 2),
            })
        
        # Strikes参数
        if 'strikes' in config:
            flat_config.update({
                'STRIKE_CONSERVATIVE_LONG_OFFSET': config['strikes'].get('conservative_long_offset', 1.5),
                'STRIKE_BALANCED_WING_OFFSET': config['strikes'].get('balanced_wing_offset', 1.0),
                'STRIKE_AGGRESSIVE_LONG_OFFSET': config['strikes'].get('aggressive_long_offset', 0.2),
                'STRIKE_RATIO_SHORT_OFFSET': config['strikes'].get('ratio_short_offset', 0.5),
                'STRIKE_RATIO_LONG_OFFSET': config['strikes'].get('ratio_long_offset', 1.5),
            })
        
        # RR计算参数
        if 'rr_calculation' in config:
            credit = config['rr_calculation'].get('credit_ivr', {})
            debit = config['rr_calculation'].get('debit_ivr', {})
            flat_config.update({
                'CREDIT_IVR_0_25': credit.get('0-25', 0.20),
                'CREDIT_IVR_25_50': credit.get('25-50', 0.30),
                'CREDIT_IVR_50_75': credit.get('50-75', 0.40),
                'CREDIT_IVR_75_100': credit.get('75-100', 0.50),
                'DEBIT_IVR_0_40': debit.get('0-40', 0.30),
                'DEBIT_IVR_40_70': debit.get('40-70', 0.40),
                'DEBIT_IVR_70_100': debit.get('70-100', 0.50),
            })
        
        # Pw计算参数
        if 'pw_calculation' in config:
            credit = config['pw_calculation'].get('credit', {})
            debit = config['pw_calculation'].get('debit', {})
            butterfly = config['pw_calculation'].get('butterfly', {})
            flat_config.update({
                'PW_CREDIT_BASE': credit.get('base', 0.5),
                'PW_CREDIT_CLUSTER_COEF': credit.get('cluster_coef', 0.1),
                'PW_CREDIT_DISTANCE_PENALTY_COEF': credit.get('distance_penalty_coef', 0.05),
                'PW_CREDIT_MIN': credit.get('min', 0.4),
                'PW_CREDIT_MAX': credit.get('max', 0.85),
                'PW_DEBIT_BASE': debit.get('base', 0.3),
                'PW_DEBIT_DEX_COEF': debit.get('dex_coef', 0.1),
                'PW_DEBIT_VANNA_COEF': debit.get('vanna_coef', 0.2),
                'PW_DEBIT_MIN': debit.get('min', 0.25),
                'PW_DEBIT_MAX': debit.get('max', 0.75),
                'PW_DEBIT_VANNA_WEIGHT_HIGH': 1.0,
                'PW_DEBIT_VANNA_WEIGHT_MEDIUM': 0.6,
                'PW_DEBIT_VANNA_WEIGHT_LOW': 0.3,
                'PW_BUTTERFLY_BODY_INSIDE': butterfly.get('body_inside', 0.65),
                'PW_BUTTERFLY_BODY_OFFSET_1EM': butterfly.get('body_offset_1em', 0.45),
            })
        
        # Greeks参数
        if 'greeks' in config:
            conservative = config['greeks'].get('conservative', {})
            balanced = config['greeks'].get('balanced', {})
            aggressive = config['greeks'].get('aggressive', {})
            flat_config.update({
                'CONSERVATIVE_DELTA_MIN': conservative.get('delta_min', -0.1),
                'CONSERVATIVE_DELTA_MAX': conservative.get('delta_max', 0.1),
                'CONSERVATIVE_THETA_MIN': conservative.get('theta_min', 5.0),
                'CONSERVATIVE_VEGA_MAX': conservative.get('vega_max', -10.0),
                'BALANCED_DELTA_RANGE': balanced.get('delta_range', 0.2),
                'BALANCED_THETA_MIN': balanced.get('theta_min', 8.0),
                'AGGRESSIVE_DELTA_MIN': aggressive.get('delta_min', 0.3),
                'AGGRESSIVE_DELTA_MAX': aggressive.get('delta_max', 0.6),
                'AGGRESSIVE_VEGA_MIN': aggressive.get('vega_min', 10.0),
            })
        
        # Exit规则
        if 'exit_rules' in config:
            credit_exit = config['exit_rules'].get('credit', {})
            debit_exit = config['exit_rules'].get('debit', {})
            flat_config.update({
                'PROFIT_TARGET_CREDIT_PCT': credit_exit.get('profit_target_pct', 30),
                'STOP_LOSS_CREDIT_PCT': credit_exit.get('stop_loss_pct', 150),
                'PROFIT_TARGET_DEBIT_PCT': debit_exit.get('profit_target_pct', 60),
                'STOP_LOSS_DEBIT_PCT': debit_exit.get('stop_loss_pct', 50),
                'TIME_DECAY_EXIT_DAYS': credit_exit.get('time_decay_exit_days', 3),
            })
        
        # Alpha Vantage参数
        if 'alpha_vantage' in config:
            flat_config.update({
                'ALPHA_VANTAGE_API_KEY': config['alpha_vantage'].get('api_key', ''),
                'ALPHA_VANTAGE_API_URL': config['alpha_vantage'].get('api_url', 'https://www.alphavantage.co/query?'),
                'ENABLE_EARNINGS_API': config['alpha_vantage'].get('enable_earnings_api', True),
                'EARNINGS_CACHE_DAYS': config['alpha_vantage'].get('earnings_cache_days', 30),
            })
        
        # Data Fetching参数
        if 'data_fetching' in config:
            flat_config.update({
                'DEFAULT_STRIKES': config['data_fetching'].get('default_strikes', 25),
                'DEFAULT_NET_WINDOW': config['data_fetching'].get('default_net_window', 60),
                'EXTENDED_NET_WINDOW': config['data_fetching'].get('extended_net_window', 120),
                'DEFAULT_INDEX_PRIMARY': config['data_fetching'].get('default_index_primary', 'SPX'),
                'DEFAULT_INDEX_SECONDARY': config['data_fetching'].get('default_index_secondary', 'QQQ'),
            })
        
        # Risk Management参数
        if 'risk_management' in config:
            flat_config.update({
                'MAX_SINGLE_RISK_PCT': config['risk_management'].get('max_single_risk_pct', 2),
                'MAX_TOTAL_EXPOSURE_PCT': config['risk_management'].get('max_total_exposure_pct', 10),
            })
        
        logger.info(f"✅ 成功加载 {len(flat_config)} 个环境变量")
        return flat_config
        
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        return _get_default_config()


def _get_default_config() -> dict:
    """返回默认配置（作为后备）"""
    return {
        # 原有的硬编码默认值...
        "EM1_SQRT_FACTOR": 0.06299,
        # ... 其他
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