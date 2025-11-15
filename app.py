"""
Swing Quant Local - 美股期权量化分析系统
从 Dify Workflow 转换为本地独立运行程序
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from agents.router import RouterAgent
from agents.command_generator import CommandGeneratorAgent
from agents.data_validator import DataValidatorAgent
from agents.technical_analyzer import TechnicalAnalyzerAgent
from agents.scenario_analyzer import ScenarioAnalyzerAgent
from agents.strategy_generator import StrategyGeneratorAgent
from agents.comparison import ComparisonAgent
from agents.report_generator import ReportGeneratorAgent
from calculators.event_detector import EventDetector
from calculators.scoring_engine import ScoringEngine
from calculators.strategy_calculator import StrategyCalculator
from calculators.ranking_engine import RankingEngine
from utils.logger import setup_logger
from utils.file_handler import FileHandler
from utils.data_aggregator import DataAggregator

logger = setup_logger(__name__)


class SwingQuantWorkflow:
    """Swing Quant 工作流主类"""
    
    def __init__(self, config: Config):
        self.config = config
        self.file_handler = FileHandler()
        
        # 初始化所有 Agent
        self.router = RouterAgent(config)
        self.command_gen = CommandGeneratorAgent(config)
        self.data_validator = DataValidatorAgent(config)
        self.technical = TechnicalAnalyzerAgent(config)
        self.scenario = ScenarioAnalyzerAgent(config)
        self.strategy_gen = StrategyGeneratorAgent(config)
        self.comparison = ComparisonAgent(config)
        self.report_gen = ReportGeneratorAgent(config)
        
        # 初始化计算引擎
        self.event_detector = EventDetector(config)
        self.scoring_engine = ScoringEngine(config)
        self.strategy_calc = StrategyCalculator(config)
        self.ranking_engine = RankingEngine(config)
    
    def run(self, user_query: str, uploaded_files: list = None) -> Dict[str, Any]:
        """
        执行完整工作流
        
        Args:
            user_query: 用户输入 (如 "AAPL" 或上传数据文件)
            uploaded_files: 上传的图表文件列表或文件夹路径
        
        Returns:
            最终分析报告（单标的）或批量分析结果（多标的）
        """
        logger.info(f"开始处理查询: {user_query}")
        
        # 处理文件输入：支持文件夹
        processed_files = self._process_file_input(uploaded_files)
        context = {"user_query": user_query, "uploaded_files": processed_files}
        
        try:
            # === Step 1: 路由判断 ===
            route_result = self.router.process(user_query)
            logger.info(f"路由结果: {route_result}")
            
            if route_result == "SYMBOL":
                # 分支 A: 生成命令清单
                return self._handle_symbol_branch(user_query)
            
            elif route_result == "DATA" and processed_files:
                # 分支 B: 数据分析
                # 检查是否为批量分析
                grouped_files = self._group_files_by_symbol(processed_files)
                
                if len(grouped_files) >= 10:
                    # 批量分析模式
                    logger.info(f"检测到 {len(grouped_files)} 个标的，启动批量分析模式")
                    return self._handle_batch_analysis(grouped_files)
                else:
                    # 单标的分析
                    return self._handle_data_branch(user_query, processed_files)
            
            else:
                return {"error": "INVALID", "message": "无效输入，请提供股票代码或上传数据"}
        
        except Exception as e:
            logger.error(f"工作流执行失败: {e}", exc_info=True)
            return {"error": str(e)}
    
    def _process_file_input(self, uploaded_files: list) -> list:
        """
        处理文件输入，支持文件夹
        
        Args:
            uploaded_files: 文件列表或包含文件夹路径
        
        Returns:
            展开后的文件列表
        """
        if not uploaded_files:
            return []
        
        all_files = []
        for item in uploaded_files:
            item_path = Path(item)
            
            if item_path.is_dir():
                # 递归扫描文件夹
                logger.info(f"扫描文件夹: {item_path}")
                for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg']:
                    all_files.extend(item_path.rglob(f'*{ext}'))
                    all_files.extend(item_path.rglob(f'*{ext.upper()}'))
            elif item_path.is_file():
                all_files.append(item_path)
            else:
                logger.warning(f"无效路径: {item}")
        
        # 转换为字符串并去重
        all_files = [str(f) for f in all_files]
        all_files = list(set(all_files))
        all_files.sort()
        
        logger.info(f"共找到 {len(all_files)} 个文件")
        return all_files
    
    def _group_files_by_symbol(self, files: list) -> Dict[str, list]:
        """
        根据文件名中的股票代码分组
        
        Args:
            files: 文件列表
        
        Returns:
            {symbol: [file1, file2, ...]}
        """
        import re
        grouped = {}
        
        for file_path in files:
            file_name = Path(file_path).stem.upper()
            
            # 尝试从文件名提取股票代码
            # 支持格式: AAPL_gexr.png, NVDA-skew.png, TSLA_data_20250115.png
            match = re.search(r'\b([A-Z]{1,5})\b', file_name)
            
            if match:
                symbol = match.group(1)
                if symbol not in grouped:
                    grouped[symbol] = []
                grouped[symbol].append(file_path)
            else:
                # 无法识别代码，归入 UNKNOWN
                if 'UNKNOWN' not in grouped:
                    grouped['UNKNOWN'] = []
                grouped['UNKNOWN'].append(file_path)
        
        return grouped
    
    def _handle_batch_analysis(self, grouped_files: Dict[str, list]) -> Dict[str, Any]:
        """
        批量分析多个标的
        
        Args:
            grouped_files: {symbol: [files]}
        
        Returns:
            批量分析结果
        """
        results = {}
        success_count = 0
        failed_symbols = []
        
        total = len(grouped_files)
        logger.info(f"开始批量分析 {total} 个标的")
        
        for idx, (symbol, files) in enumerate(grouped_files.items(), 1):
            logger.info(f"[{idx}/{total}] 处理标的: {symbol}, 文件数: {len(files)}")
            
            try:
                # 执行单标的分析
                result = self._handle_data_branch(symbol, files)
                
                if "error" not in result:
                    results[symbol] = {
                        "status": "success",
                        "report": result,
                        "file_count": len(files)
                    }
                    success_count += 1
                else:
                    results[symbol] = {
                        "status": "failed",
                        "error": result.get("error"),
                        "file_count": len(files)
                    }
                    failed_symbols.append(symbol)
                
            except Exception as e:
                logger.error(f"分析 {symbol} 失败: {e}")
                results[symbol] = {
                    "status": "failed",
                    "error": str(e),
                    "file_count": len(files)
                }
                failed_symbols.append(symbol)
        
        # 生成批量汇总报告
        summary = self._generate_batch_summary(results, success_count, failed_symbols)
        
        return {
            "type": "batch_analysis",
            "total_symbols": total,
            "success_count": success_count,
            "failed_count": len(failed_symbols),
            "failed_symbols": failed_symbols,
            "summary": summary,
            "details": results
        }
    
    def _generate_batch_summary(self, results: Dict, success_count: int, failed_symbols: list) -> str:
        """生成批量分析汇总报告"""
        lines = ["# 批量期权分析汇总报告\n"]
        lines.append(f"**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append(f"**成功**: {success_count} | **失败**: {len(failed_symbols)}\n")
        
        if failed_symbols:
            lines.append(f"\n⚠️ **失败标的**: {', '.join(failed_symbols)}\n")
        
        lines.append("\n## 成功标的汇总\n")
        lines.append("| 标的 | 推荐策略 | 入场判定 | 主导剧本 | 总评分 |\n")
        lines.append("|------|---------|---------|---------|--------|\n")
        
        for symbol, data in results.items():
            if data["status"] == "success":
                report = data.get("report", {})
                strategy = report.get("final_recommendation", "N/A")
                entry = report.get("entry_check", "N/A")
                scenario = report.get("primary_scenario", "N/A")
                score = report.get("total_score", "N/A")
                lines.append(f"| {symbol} | {strategy} | {entry} | {scenario} | {score} |\n")
        
        return "".join(lines)
    
    def _handle_symbol_branch(self, symbol: str) -> Dict[str, Any]:
        """处理股票代码分支：生成命令清单"""
        logger.info(f"执行命令清单生成: {symbol}")
        
        # Agent 2: 生成命令清单
        command_list = self.command_gen.generate(symbol)
        
        return {
            "type": "command_list",
            "symbol": symbol,
            "commands": command_list,
            "message": "请执行以上命令并回传数据"
        }
    
    def _handle_data_branch(self, user_query: str, uploaded_files: list, session_state: dict = None) -> Dict[str, Any]:
        """处理数据分析分支：完整量化分析"""
        logger.info(f"执行数据分析，文件数: {len(uploaded_files)}")

        if session_state is None:
            session_state = {
                "first_parse_data": "",
                "current_symbol": "",
                "data_status": "initial",
                "missing_count": 0
            }
            
        # === Step 1: 事件检测 (CODE1) ===
        event_result = self.event_detector.detect(user_query)
        logger.info(f"事件检测完成: {event_result.get('event_count', 0)} 个事件")
        
        # === Step 2: 数据校验 (Agent 3) ===
        merged_data = self.data_validator.validate(user_query, uploaded_files)
        # ✨ 新增: Step 2.5 数据聚合
        aggregation_result = self.data_aggregator.process(
            agent3_output=merged_data,
            first_parse_data=session_state.get("first_parse_data", ""),
            current_symbol=session_state.get("current_symbol", ""),
            data_status=session_state.get("data_status", "initial"),
            missing_count=session_state.get("missing_count", 0)
        )
        # 更新会话状态
        session_state.update({
            "first_parse_data": aggregation_result["first_parse_data"],
            "current_symbol": aggregation_result["current_symbol"],
            "data_status": aggregation_result["data_status"],
            "missing_count": aggregation_result["missing_count"]
        })

        # 检查是否需要补齐
        if aggregation_result["data_status"] == "awaiting_data":
            return {
                "type": "missing_data",
                "symbol": aggregation_result["current_symbol"],
                "progress": aggregation_result["user_guide_progress"],
                "summary": aggregation_result["user_guide_summary"],
                "commands": aggregation_result["user_guide_commands"],
                "critical": aggregation_result["user_guide_priority_critical"],
                "high": aggregation_result["user_guide_priority_high"],
                "next_action": aggregation_result["user_guide_next_action"],
                "session_state": session_state  # 返回会话状态
            }
        
        # 数据完整,继续分析
        merged_data = json.loads(aggregation_result["result"])
        
        if merged_data["status"] == "missing_data":
            logger.warning("数据不完整，返回补齐指引")
            return {
                "type": "missing_data",
                "missing_fields": merged_data["missing_fields"],
                "补齐指引": merged_data["补齐指引"]
            }
        
        logger.info("数据校验通过")
        
        # === Step 3: 技术面分析 (Agent 4, 可选) ===
        technical_result = None
        if uploaded_files:
            try:
                technical_result = self.technical.analyze(uploaded_files, merged_data)
                logger.info(f"技术面评分: {technical_result.get('ta_score', 0)}")
            except Exception as e:
                logger.warning(f"技术面分析失败，跳过: {e}")
        
        # === Step 4: 评分计算 (CODE2) ===
        scoring_result = self.scoring_engine.calculate(
            merged_data, 
            technical_result
        )
        logger.info(f"总评分: {scoring_result['scoring']['total_score']}")
        
        # === Step 5: 剧本分析 (Agent 5) ===
        scenario_result = self.scenario.analyze(scoring_result)
        logger.info(f"主导剧本: {scenario_result['scenario_classification']['primary_scenario']}")
        
        # === Step 6: 策略辅助计算 (CODE3) ===
        strategy_calc_result = self.strategy_calc.calculate(
            merged_data,
            scenario_result,
            technical_result
        )
        
        # === Step 7: 策略生成 (Agent 6) ===
        strategies = self.strategy_gen.generate(
            scenario_result,
            strategy_calc_result,
            merged_data
        )
        logger.info(f"生成策略数: {len(strategies['strategies'])}")
        
        # === Step 8: 策略对比计算 (CODE4) ===
        ranking_result = self.ranking_engine.rank(
            strategies,
            scenario_result,
            merged_data
        )
        
        # === Step 9: 策略对比 (Agent 7) ===
        comparison_result = self.comparison.compare(
            ranking_result,
            scenario_result,
            strategies
        )
        logger.info(f"推荐策略: {comparison_result.get('final_recommendation', 'N/A')}")
        
        # === Step 10: 最终报告生成 (Agent 8) ===
        final_report = self.report_gen.generate(
            merged_data,
            technical_result,
            scenario_result,
            comparison_result,
            event_result
        )
        
        logger.info("工作流执行完成")
        return final_report


def main():
    """主程序入口"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Swing Quant 美股期权量化分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
        示例用法:
        # 生成命令清单
        python main.py "AAPL"
        
        # 单标的分析
        python main.py "AAPL数据" --files chart1.png chart2.png
        
        # 批量分析（文件夹）
        python main.py "批量分析" --folder data/charts/
        
        # 批量分析（多个文件）
        python main.py "批量分析" --files data/*.png
        """
    )
    
    parser.add_argument("query", help="股票代码 (如 AAPL) 或数据输入描述")
    parser.add_argument("--files", nargs="+", help="上传的图表文件路径（支持通配符）")
    parser.add_argument("--folder", help="包含图表的文件夹路径（批量分析）")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--output", default="report.md", help="输出报告路径（单标的）")
    parser.add_argument("--output-dir", default="reports", help="批量分析输出目录")
    
    args = parser.parse_args()
    
    # 加载配置
    config = Config.from_yaml(args.config)
    
    # 创建工作流实例
    workflow = SwingQuantWorkflow(config)
    
    # 处理文件输入
    file_input = []
    if args.folder:
        file_input.append(args.folder)
    if args.files:
        file_input.extend(args.files)
    
    # 执行分析
    result = workflow.run(args.query, file_input)
    
    # 输出结果
    if result.get("type") == "command_list":
        print("\n=== 命令清单 ===")
        for cmd in result["commands"]:
            print(cmd)
    
    elif result.get("type") == "missing_data":
        print("\n=== 数据不完整 ===")
        print(json.dumps(result["missing_fields"], indent=2, ensure_ascii=False))
    
    elif result.get("type") == "batch_analysis":
        # 批量分析结果
        print("\n=== 批量分析完成 ===")
        print(f"总标的数: {result['total_symbols']}")
        print(f"成功: {result['success_count']} | 失败: {result['failed_count']}")
        
        if result['failed_symbols']:
            print(f"失败标的: {', '.join(result['failed_symbols'])}")
        
        # 保存汇总报告
        summary_path = Path(args.output_dir) / "batch_summary.md"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(result['summary'])
        print(f"\n汇总报告: {summary_path}")
        
        # 保存各标的详细报告
        for symbol, data in result['details'].items():
            if data['status'] == 'success':
                report_path = Path(args.output_dir) / f"{symbol}_report.md"
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(data['report'].get('report', ''))
                print(f"  - {symbol}: {report_path}")
    
    else:
        # 单标的分析
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result.get("report", ""))
        print(f"\n分析报告已保存到: {args.output}")
        print(f"推荐策略: {result.get('final_recommendation', 'N/A')}")


if __name__ == "__main__":
    main()