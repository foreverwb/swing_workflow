#!/usr/bin/env python3
"""
Swing Quant Workflow - 主程序入口
期权分析策略系统
"""

import sys
import yaml
import json
from pathlib import Path
from datetime import datetime
import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from loguru import logger

from core.model_client import ModelClientFactory
from core.workflow import WorkflowEngine


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
        "EM1_SQRT_FACTOR": 0.06299,
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
@click.option('--mode', '-m', type=click.Choice(['full', 'update']), default='full', 
              help='运行模式：full=完整分析, update=增量补齐')
def analyze(symbol: str, folder: str, config: str, output: str, mode: str):
    """分析单个股票的期权策略"""
    
    # 显示欢迎信息
    mode_desc = "完整分析" if mode == "full" else "增量补齐"
    console.print(Panel.fit(
        f"[bold blue]Swing Quant Workflow[/bold blue]\n"
        f"[dim]期权分析策略系统 - {mode_desc}[/dim]",
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
    console.print(f"\n[green]🚀 开始{mode_desc} {symbol.upper()}[/green]\n")
    
    # 简单的文件夹检查
    folder_path = Path(folder)
    if not folder_path.exists():
        console.print(f"[red]❌ 错误: 文件夹不存在 {folder_path}[/red]")
        sys.exit(1)
        
    image_count = len(list(folder_path.glob('*.[pP][nN][gG]'))) + len(list(folder_path.glob('*.[jJ][pP][gG]')))
    if image_count == 0:
        console.print(f"[red]❌ 错误: 文件夹 {folder_path} 中没有找到图片 (png/jpg)[/red]")
        sys.exit(1)

    console.print(f"[dim]📂 扫描到 {image_count} 张图片，准备开始分析...[/dim]")
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("正在分析...", total=None)
            
            result = engine.run(
                symbol=symbol.upper(),
                data_folder=Path(folder),
                mode=mode  # ⭐ 传入模式参数
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
@click.option('--symbol', '-s', required=True, help='股票代码')
@click.option('--folder', '-f', required=True, type=click.Path(exists=True), help='数据文件夹')
@click.option('--note', '-n', default='', help='快照备注（可选）')
def refresh(symbol: str, folder: str, note: str):
    """盘中刷新 Greeks 数据（快速快照）"""
    
    console.print(Panel.fit(
        f"[bold cyan]📸 盘中快照: {symbol.upper()}[/bold cyan]\n"
        f"[dim]仅运行 Agent3 + 计算引擎[/dim]",
        border_style="cyan"
    ))
    
    # 设置日志
    log_file = setup_logging()
    logger.info(f"盘中刷新: {symbol}")
    
    # 加载配置
    console.print("\n[yellow]📁 加载配置...[/yellow]")
    model_client = ModelClientFactory.create_from_config()
    env_vars = load_env_config()
    
    # 创建工作流引擎
    engine = WorkflowEngine(model_client, env_vars)
    
    # 扫描图片
    folder_path = Path(folder)
    image_count = len(list(folder_path.glob('*.[pP][nN][gG]'))) + len(list(folder_path.glob('*.[jJ][pP][gG]')))
    
    if image_count == 0:
        console.print(f"[red]❌ 错误: 文件夹中没有找到图片[/red]")
        sys.exit(1)
    
    console.print(f"[dim]📊 扫描到 {image_count} 张图片[/dim]")
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("正在刷新数据...", total=None)
            
            # 运行 refresh 模式
            result = engine.run(
                symbol=symbol.upper(),
                data_folder=folder_path,
                mode="refresh"  # ⭐ refresh 模式
            )
            
            progress.update(task, completed=True)
        
        # 显示结果
        if result["status"] == "success":
            console.print("\n[green]✅ 快照已保存![/green]\n")
            
            snapshot = result["snapshot"]
            console.print(Panel(
                f"[bold]快照 #{snapshot['snapshot_id']}[/bold]\n"
                f"时间: {snapshot['timestamp'][:19]}\n"
                f"现价: ${snapshot.get('spot_price', 'N/A')}\n"
                f"EM1$: ${snapshot.get('em1_dollar', 'N/A')}\n"
                f"Vol Trigger: ${snapshot.get('vol_trigger', 'N/A')}\n"
                f"状态: {snapshot.get('spot_vs_trigger', 'N/A')}",
                title="📊 快照摘要",
                border_style="green"
            ))
            
            # 显示变化
            if snapshot.get("changes"):
                console.print("\n[yellow]📈 数据变化:[/yellow]")
                for field, change in snapshot["changes"].items():
                    emoji = "🔺" if change.get("change_pct", 0) > 0 else "🔻" if change.get("change_pct", 0) < 0 else "➡️"
                    pct_str = f" ({change['change_pct']:+.2f}%)" if "change_pct" in change else ""
                    console.print(f"  {emoji} {field}: {change['old']} → {change['new']}{pct_str}")
            else:
                console.print("\n[dim]ℹ️ 首次快照，无历史对比[/dim]")
            
            # 提示查看历史
            console.print(f"\n[dim]💡 查看历史快照: python app.py history -s {symbol.upper()}[/dim]")
        else:
            console.print(f"\n[red]❌ 刷新失败: {result.get('message', '未知错误')}[/red]")
    
    except Exception as e:
        logger.exception("刷新失败")
        console.print(f"\n[red]❌ 错误: {str(e)}[/red]")
        console.print(f"[dim]详细日志: {log_file}[/dim]")
        sys.exit(1)


@cli.command()
@click.option('--symbol', '-s', required=True, help='股票代码')
@click.option('--format', '-f', type=click.Choice(['table', 'json']), default='table', help='输出格式')
def history(symbol: str, format: str):
    """查看历史快照"""
    
    cache_file = Path(f"data/cache/{symbol.upper()}_analysis.json")
    
    if not cache_file.exists():
        console.print(f"[red]❌ 未找到 {symbol.upper()} 的历史数据[/red]")
        console.print(f"[dim]请先运行: python app.py analyze -s {symbol.upper()} -f <folder>[/dim]")
        sys.exit(1)
    
    with open(cache_file, 'r', encoding='utf-8') as f:
        cached = json.load(f)
    
    snapshots = cached.get("greeks_snapshots", [])
    
    if not snapshots:
        console.print(f"[yellow]⚠️ {symbol.upper()} 尚无快照记录[/yellow]")
        return
    
    if format == 'json':
        console.print_json(data=snapshots)
        return
    
    # 表格模式
    table = Table(title=f"📊 {symbol.upper()} 快照历史 ({len(snapshots)} 条记录)")
    
    table.add_column("ID", justify="center", style="cyan")
    table.add_column("时间", style="dim")
    table.add_column("现价", justify="right", style="green")
    table.add_column("EM1$", justify="right")
    table.add_column("Vol Trigger", justify="right")
    table.add_column("状态", justify="center")
    table.add_column("备注")
    
    for snap in snapshots:
        table.add_row(
            str(snap["snapshot_id"]),
            snap["timestamp"][:16],
            f"${snap.get('spot_price', 0):.2f}" if snap.get('spot_price') else "N/A",
            f"${snap.get('em1_dollar', 0):.2f}" if snap.get('em1_dollar') else "N/A",
            f"${snap.get('vol_trigger', 0):.2f}" if snap.get('vol_trigger') else "N/A",
            snap.get("spot_vs_trigger", "N/A"),
            snap.get("note", "")
        )
    
    console.print(table)
    
    # 显示统计
    console.print(f"\n[dim]创建时间: {cached.get('created_at', 'N/A')}")
    console.print(f"最后更新: {cached.get('last_updated', 'N/A')}[/dim]")


@cli.command()
@click.option('--symbol', '-s', required=True, help='股票代码')
@click.option('--test-date', '-d', required=True, help='回测日期 YYYY-MM-DD')
@click.option('--folder', '-f', required=True, type=click.Path(exists=True), help='实际数据文件夹')
def backtest(symbol: str, test_date: str, folder: str):
    """回测验证（检验预测准确性）"""
    
    console.print(Panel.fit(
        f"[bold magenta]🔬 回测验证: {symbol.upper()}[/bold magenta]\n"
        f"[dim]测试日期: {test_date}[/dim]",
        border_style="magenta"
    ))
    
    cache_file = Path(f"data/cache/{symbol.upper()}_analysis.json")
    
    if not cache_file.exists():
        console.print(f"[red]❌ 未找到 {symbol.upper()} 的分析记录[/red]")
        console.print(f"[dim]请先运行: python app.py analyze -s {symbol.upper()} -f <folder>[/dim]")
        sys.exit(1)
    
    with open(cache_file, 'r', encoding='utf-8') as f:
        cached = json.load(f)
    
    analysis = cached.get("analysis", {})
    
    if not analysis:
        console.print(f"[red]❌ 未找到完整分析记录（需先执行 analyze 命令）[/red]")
        sys.exit(1)
    
    # 提取初始预测
    scenario = analysis.get("scenario", {})
    strategies = analysis.get("strategies", {})
    
    if not scenario:
        console.print(f"[red]❌ 未找到场景预测数据[/red]")
        sys.exit(1)
    
    # 设置日志
    log_file = setup_logging()
    
    # 加载配置
    console.print("\n[yellow]📁 加载配置...[/yellow]")
    model_client = ModelClientFactory.create_from_config()
    env_vars = load_env_config()
    
    # 创建工作流引擎
    engine = WorkflowEngine(model_client, env_vars)
    
    # 运行 refresh 模式获取实际数据
    console.print(f"\n[yellow]📊 获取 {test_date} 实际数据...[/yellow]")
    
    folder_path = Path(folder)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("正在获取数据...", total=None)
            
            result = engine.run(
                symbol=symbol.upper(),
                data_folder=folder_path,
                mode="refresh"
            )
            
            progress.update(task, completed=True)
        
        if result["status"] != "success":
            console.print(f"\n[red]❌ 获取实际数据失败[/red]")
            sys.exit(1)
        
        actual_snapshot = result["snapshot"]
        actual_data = actual_snapshot["data"]
        
        # 执行回测分析
        backtest_result = _analyze_backtest(
            initial_analysis=analysis,
            actual_data=actual_data,
            test_date=test_date
        )
        
        # 保存回测记录
        cached["backtest_records"].append(backtest_result)
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cached, f, ensure_ascii=False, indent=2)
        
        # 显示回测结果
        _display_backtest_results(backtest_result)
        
    except Exception as e:
        logger.exception("回测失败")
        console.print(f"\n[red]❌ 错误: {str(e)}[/red]")
        console.print(f"[dim]详细日志: {log_file}[/dim]")
        sys.exit(1)


def _analyze_backtest(initial_analysis: dict, actual_data: dict, test_date: str) -> dict:
    """
    执行回测分析
    
    优先级排序：
    1. 命中率（剧本预测正确率）
    2. 策略期望收益
    3. 执行可用性
    4. 回撤控制
    """
    targets = actual_data.get("targets", {})
    actual_spot = targets.get("spot_price")
    actual_spot_vs_trigger = targets.get("gamma_metrics", {}).get("spot_vs_trigger")
    
    # 初始预测
    initial_spot = initial_analysis.get("initial_spot", 0)
    scenario_data = initial_analysis.get("scenario", {})
    scenarios = scenario_data.get("scenarios", []) if isinstance(scenario_data.get("scenarios"), list) else []
    strategies_data = initial_analysis.get("strategies", {})
    strategies = strategies_data.get("strategies", []) if isinstance(strategies_data.get("strategies"), list) else []
    
    # ===== 1. 命中率分析（优先级1）=====
    scenario_hit = False
    matched_scenario = None
    
    # 提取主导场景
    primary_scenario = scenario_data.get("scenario_classification", {}).get("primary_scenario", "")
    
    # 判断实际走势
    actual_direction = "neutral"
    if actual_spot and initial_spot:
        change_pct = ((actual_spot - initial_spot) / initial_spot) * 100
        if change_pct > 2:
            actual_direction = "bullish"
        elif change_pct < -2:
            actual_direction = "bearish"
    
    # 简化判断：检查主导场景是否匹配
    if "突破" in primary_scenario or "趋势" in primary_scenario:
        if actual_direction in ["bullish", "bearish"]:
            scenario_hit = True
            matched_scenario = primary_scenario
    elif "区间" in primary_scenario or "震荡" in primary_scenario:
        if actual_direction == "neutral":
            scenario_hit = True
            matched_scenario = primary_scenario
    
    hit_rate = 100.0 if scenario_hit else 0.0
    
    # ===== 2. 策略期望收益（优先级2）=====
    strategy_pnl = {}
    
    for strategy in strategies[:3]:  # 仅评估 Top 3
        strategy_name = strategy.get("strategy_name", "") or strategy.get("structure", "Unknown")
        
        # 简化 PnL 计算（实际需要根据策略类型和Greeks计算）
        # 这里仅作演示，实际应根据期权定价公式计算
        pnl = 0.0
        
        # 基于方向和策略类型简单估算
        strategy_type = strategy.get("strategy_type", "")
        if "Credit" in strategy_type or "credit" in strategy_type:
            # 信用策略：区间内盈利
            if actual_direction == "neutral":
                pnl = 50.0  # 假设盈利
            else:
                pnl = -100.0  # 假设亏损
        elif "Debit" in strategy_type or "debit" in strategy_type:
            # 借贷策略：方向对盈利
            if actual_direction != "neutral":
                pnl = 100.0
            else:
                pnl = -50.0
        
        strategy_pnl[strategy_name] = pnl
    
    # ===== 3. 执行可用性（优先级3）=====
    execution_score = _evaluate_execution_quality(initial_analysis)
    
    # ===== 4. 回撤控制（优先级4）=====
    max_drawdown = 0.0  # 简化处理，实际需要记录价格路径
    
    return {
        "test_date": test_date,
        "initial_spot": initial_spot,
        "actual_spot": actual_spot,
        "spot_change_pct": ((actual_spot - initial_spot) / initial_spot * 100) if initial_spot else 0,
        
        # 优先级1：命中率
        "scenario_hit_rate": hit_rate,
        "matched_scenario": matched_scenario,
        "scenario_hit": scenario_hit,
        "predicted_scenario": primary_scenario,
        "actual_direction": actual_direction,
        
        # 优先级2：策略收益
        "strategy_pnl": strategy_pnl,
        "total_pnl": sum(strategy_pnl.values()),
        
        # 优先级3：执行可用性
        "execution_score": execution_score,
        
        # 优先级4：回撤控制
        "max_drawdown": max_drawdown,
        
        # 综合评分
        "overall_score": _calculate_overall_backtest_score(
            hit_rate, strategy_pnl, execution_score, max_drawdown
        )
    }


def _evaluate_execution_quality(analysis: dict) -> float:
    """评估执行可用性（1-10分）"""
    strategies_data = analysis.get("strategies", {})
    strategies = strategies_data.get("strategies", []) if isinstance(strategies_data.get("strategies"), list) else []
    
    if not strategies:
        return 0.0
    
    score = 10.0
    
    # 检查要素完整性
    for strategy in strategies[:3]:
        required_fields = ["legs", "entry_trigger", "exit_plan"]
        missing = sum(1 for f in required_fields if f not in strategy or not strategy[f])
        score -= missing * 0.5
    
    return max(0, score)


def _calculate_overall_backtest_score(
    hit_rate: float,
    strategy_pnl: dict,
    execution_score: float,
    max_drawdown: float
) -> float:
    """
    计算综合回测评分
    
    权重：
    - 命中率：40%
    - 策略收益：30%
    - 执行可用性：20%
    - 回撤控制：10%
    """
    # 归一化各指标
    hit_rate_normalized = hit_rate / 100
    
    # PnL 归一化（假设 +100 为满分）
    total_pnl = sum(strategy_pnl.values())
    pnl_normalized = min(1.0, max(0, (total_pnl + 100) / 200))
    
    execution_normalized = execution_score / 10
    
    # 回撤归一化（20%回撤为0分）
    drawdown_normalized = max(0, 1 - abs(max_drawdown) / 20)
    
    overall = (
        hit_rate_normalized * 0.4 +
        pnl_normalized * 0.3 +
        execution_normalized * 0.2 +
        drawdown_normalized * 0.1
    ) * 100
    
    return round(overall, 2)


def _display_backtest_results(result: dict):
    """显示回测结果"""
    # 总览面板
    console.print(Panel(
        f"[bold]测试日期:[/bold] {result['test_date']}\n"
        f"[bold]价格变化:[/bold] ${result['initial_spot']:.2f} → ${result['actual_spot']:.2f} "
        f"({result['spot_change_pct']:+.2f}%)\n"
        f"[bold]综合评分:[/bold] {result['overall_score']:.2f}/100",
        title="📊 回测总览",
        border_style="magenta"
    ))
    
    # 优先级1：命中率
    hit_emoji = "✅" if result['scenario_hit'] else "❌"
    console.print(f"\n{hit_emoji} [bold]场景命中率:[/bold] {result['scenario_hit_rate']:.1f}%")
    console.print(f"   预测场景: {result['predicted_scenario']}")
    console.print(f"   实际走势: {result['actual_direction']}")
    if result['matched_scenario']:
        console.print(f"   [green]✓ 匹配成功[/green]")
    else:
        console.print(f"   [red]✗ 预测失败[/red]")
    
    # 优先级2：策略收益
    if result['strategy_pnl']:
        console.print(f"\n💰 [bold]策略收益:[/bold]")
        for strategy, pnl in result['strategy_pnl'].items():
            pnl_emoji = "📈" if pnl > 0 else "📉" if pnl < 0 else "➡️"
            console.print(f"   {pnl_emoji} {strategy}: ${pnl:+.2f}")
        
        total_pnl = result['total_pnl']
        total_emoji = "🎉" if total_pnl > 0 else "⚠️"
        total_style = "green" if total_pnl > 0 else "red"
        console.print(f"   {total_emoji} [bold {total_style}]总计: ${total_pnl:+.2f}[/bold {total_style}]")
    
    # 优先级3：执行可用性
    exec_emoji = "✅" if result['execution_score'] >= 8 else "⚠️" if result['execution_score'] >= 5 else "❌"
    console.print(f"\n{exec_emoji} [bold]执行可用性:[/bold] {result['execution_score']:.1f}/10")
    
    # 优先级4：回撤控制
    console.print(f"\n📉 [bold]最大回撤:[/bold] {result['max_drawdown']:.2f}%")
    
    # 综合评价
    console.print(f"\n[bold]综合评价:[/bold]")
    if result['overall_score'] >= 80:
        console.print("   [green]🏆 优秀 - 预测准确，策略有效[/green]")
    elif result['overall_score'] >= 60:
        console.print("   [yellow]👍 良好 - 预测基本准确[/yellow]")
    elif result['overall_score'] >= 40:
        console.print("   [yellow]⚠️ 一般 - 需要改进[/yellow]")
    else:
        console.print("   [red]❌ 较差 - 预测失败[/red]")


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