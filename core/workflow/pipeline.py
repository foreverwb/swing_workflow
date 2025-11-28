"""
分析流程编排器（增强版）
集成美化控制台输出
"""

import json
from typing import Dict, Any
from loguru import logger

import prompts
import schemas
from code_nodes import (
    event_detection_main,
    scoring_main,
    strategy_calc_main,
    comparison_main
)
from utils.console_printer import (
    print_header,
    print_step,
    print_success,
    print_error,
    print_info,
    print_warning
)


class AnalysisPipeline:
    """分析流程编排器（增强版）"""
    
    def __init__(
        self, agent_executor, 
        cache_manager, 
        env_vars: Dict[str, Any],
        enable_pretty_print: bool = True,
        cache_file: str = None
    ):
        """
        初始化 Pipeline
        
        Args:
            agent_executor: Agent 执行器
            cache_manager: 缓存管理器
            env_vars: 环境变量
            enable_pretty_print: 是否启用美化打印
        """
        self.agent_executor = agent_executor
        self.cache_manager = cache_manager
        self.env_vars = env_vars
        self.enable_pretty_print = enable_pretty_print
        self.cache_file = cache_file  # ⭐ 新增：支持指定缓存文件
    
    def run(self, initial_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        运行完整流程（增强版）
        
        Args:
            initial_data: 初始数据（包含 23 个字段）
            
        Returns:
            完整分析结果
        """
        # 打印流程标题
        if self.enable_pretty_print:
            symbol = initial_data.get("symbol", "UNKNOWN")
            print_header(
                f"期权策略分析流程",
                f"标的: {symbol} | 完整分析模式"
            )
        
        # 初始化上下文
        context = {
            "initial_data": initial_data,
            "symbol": initial_data.get("symbol", "UNKNOWN"),
            "calculated_data": initial_data
        }
        
        # 定义流程步骤
        steps = [
            ("事件检测", self._step_event_detection, "检测财报、FOMC 等重大事件"),
            ("评分计算", self._step_scoring, "计算四维评分（Gamma/Wall/Direction/IV）"),
            ("场景分析", self._step_scenario, "推演市场场景及概率"),
            ("策略辅助", self._step_strategy_calc, "计算行权价、DTE、RR、Pw"),
            ("策略生成", self._step_strategy, "为每个场景设计期权策略"),
            ("策略对比", self._step_comparison, "计算策略 EV、RAR、流动性"),
            ("策略排序", self._step_ranking, "综合评分并排序推荐"),
            ("生成报告", self._step_report, "生成人类可读的分析报告"),
            ("保存结果", self._step_save_results, "保存分析结果到缓存")
        ]
        
        # 执行流程
        for i, (step_name, step_func, step_desc) in enumerate(steps, 1):
            if self.enable_pretty_print:
                print_step(i, len(steps), f"{step_name} - {step_desc}")
            
            logger.info(f"📍 Step {i}/{len(steps)}: {step_name}")
            
            try:
                context = step_func(context)
                
                if self.enable_pretty_print:
                    print_success(f"{step_name} 完成")
            
            except Exception as e:
                if self.enable_pretty_print:
                    print_error(f"{step_name} 失败", str(e))
                
                logger.error(f"❌ Step {step_name} 失败: {str(e)}")
                
                return {
                    "status": "error",
                    "failed_step": step_name,
                    "error": str(e)
                }
        
        # 流程完成
        if self.enable_pretty_print:
            print_success("🎉 完整分析流程完成！")
        
        return {
            "status": "success",
            "report": context.get("final_report"),
            "event_risk": context.get("event_result"),
            "scoring": context.get("scoring_data"),
            "scenario": context.get("scenario_result"),
            "strategies": context.get("strategies_result"),
            "ranking": context.get("ranking_result")
        }
    
    def _step_event_detection(self, context: Dict) -> Dict:
        """步骤1：事件检测"""
        result = self.agent_executor.execute_code_node(
            node_name="事件检测",
            func=event_detection_main,
            description="检测财报、FOMC、OPEX 等事件",
            user_query=f"分析 {context['symbol']}",
            **self.env_vars
        )
        
        context["event_result"] = self._safe_parse_json(result)
        return context
    
    def _step_scoring(self, context: Dict) -> Dict:
        """步骤2：评分计算"""
        calculated_data = context["calculated_data"]
        
        ta_score = calculated_data.get("technical_analysis", {}).get("ta_score", 0)
        
        result = self.agent_executor.execute_code_node(
            node_name="评分计算",
            func=scoring_main,
            description="计算 Gamma Regime、破墙、方向、IV 四维评分",
            agent3_output=calculated_data,
            technical_score=ta_score,
            **self.env_vars
        )
        
        context["scoring_data"] = self._safe_parse_json(result)
        return context
    
    def _step_scenario(self, context: Dict) -> Dict:
        """步骤3：场景分析"""
        scoring_data = context["scoring_data"]
        
        messages = [
            {
                "role": "system",
                "content": prompts.agent5_scenario.get_system_prompt()
            },
            {
                "role": "user",
                "content": prompts.agent5_scenario.get_user_prompt(scoring_data)
            }
        ]
        
        response = self.agent_executor.execute_agent(
            agent_name="agent5",
            messages=messages,
            json_schema=schemas.agent5_schema.get_schema(),
            description="基于评分推演 3-5 种市场场景"
        )
        
        context["scenario_result"] = response.get("content", {})
        return context
    
    def _step_strategy_calc(self, context: Dict) -> Dict:
        """步骤4：策略辅助计算"""
        calculated_data = context["calculated_data"]
        scenario_result = context["scenario_result"]
        
        ta_score = calculated_data.get("technical_analysis", {}).get("ta_score", 0)
        targets = calculated_data.get("targets", {})
        result = self.agent_executor.execute_code_node(
            node_name="策略辅助",
            func=strategy_calc_main,
            description="计算行权价、DTE、RR、Pw 等策略参数",
            agent3_output=targets,
            agent5_output=scenario_result,
            technical_score=ta_score,
            **self.env_vars
        )
        
        context["strategy_calc_data"] = self._safe_parse_json(result)
        return context
    
    def _step_strategy(self, context: Dict) -> Dict:
        """步骤5：策略生成"""
        scenario_result = context["scenario_result"]
        strategy_calc_data = context["strategy_calc_data"]
        calculated_data = context["calculated_data"]
        
        messages = [
            {
                "role": "system",
                "content": prompts.agent6_strategy.get_system_prompt(self.env_vars)
            },
            {
                "role": "user",
                "content": prompts.agent6_strategy.get_user_prompt(
                    {"content": scenario_result},
                    strategy_calc_data,
                    calculated_data
                )
            }
        ]
        
        response = self.agent_executor.execute_agent(
            agent_name="agent6",
            messages=messages,
            json_schema=schemas.agent6_schema.get_schema(),
            description="为每个场景设计 2-3 种期权策略"
        )
        print("策略生成 response", response)
        context["strategies_result"] = response.get("content", {})
        return context
    
    def _step_comparison(self, context: Dict) -> Dict:
        """步骤6：策略对比"""
        strategies_result = context["strategies_result"]
        scenario_result = context["scenario_result"]
        calculated_data = context["calculated_data"]
        
        result = self.agent_executor.execute_code_node(
            node_name="策略对比",
            func=comparison_main,
            description="计算策略 EV、RAR、流动性、场景匹配度",
            strategies_output=strategies_result,
            scenario_output=scenario_result,
            agent3_output=calculated_data,
            **self.env_vars
        )
        
        context["comparison_data"] = self._safe_parse_json(result)
        return context
    
    def _step_ranking(self, context: Dict) -> Dict:
        """步骤7：策略排序"""
        comparison_data = context["comparison_data"]
        scenario_result = context["scenario_result"]
        strategies_result = context["strategies_result"]
        
        messages = [
            {
                "role": "system",
                "content": prompts.agent7_comparison.get_system_prompt()
            },
            {
                "role": "user",
                "content": prompts.agent7_comparison.get_user_prompt(
                    comparison_data,
                    scenario_result,
                    strategies_result
                )
            }
        ]
        
        response = self.agent_executor.execute_agent(
            agent_name="agent7",
            messages=messages,
            json_schema=schemas.agent7_schema.get_schema(),
            description="综合评分并排序，推荐 Top 3 策略"
        )
        
        context["ranking_result"] = response.get("content", {})
        return context
    
    def _step_report(self, context: Dict) -> Dict:
        """步骤8：生成报告"""
        calculated_data = context["calculated_data"]
        scenario_result = context["scenario_result"]
        ranking_result = context["ranking_result"]
        event_result = context["event_result"]
        
        messages = [
            {
                "role": "system",
                "content": prompts.agent8_report.get_system_prompt()
            },
            {
                "role": "user",
                "content": prompts.agent8_report.get_user_prompt(
                    calculated_data,
                    scenario_result,
                    ranking_result,
                    {"result": json.dumps(event_result, ensure_ascii=False)}
                )
            }
        ]
        
        response = self.agent_executor.execute_agent(
            agent_name="agent8",
            messages=messages,
            description="生成人类可读的 Markdown 报告"
        )
        
        context["final_report"] = response.get("content", "")
        return context
    
    def _step_save_results(self, context: Dict) -> Dict:
        """步骤9：保存结果"""
        symbol = context["symbol"]
        
        self.cache_manager.save_complete_analysis(
            symbol=symbol,
            initial_data=context["calculated_data"],
            scenario=context["scenario_result"],
            strategies=context["strategies_result"],
            ranking=context["ranking_result"],
            report=context["final_report"],
            cache_file=getattr(self, 'cache_file', None)  # ⭐ 传递 cache_file
        )
        
        if self.enable_pretty_print:
            print_info(f"分析结果已保存至缓存: {symbol}")
        
        logger.success(f"✅ 分析结果已保存至缓存: {symbol}")
        
        return context
    
    @staticmethod
    def _safe_parse_json(data: Any) -> Dict:
        """安全解析 JSON"""
        if isinstance(data, dict):
            return data
        elif isinstance(data, str):
            try:
                return json.loads(data)
            except:
                return {}
        return {}