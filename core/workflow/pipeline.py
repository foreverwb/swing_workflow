"""
分析流程编排器
定义完整分析流程的步骤顺序
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


class AnalysisPipeline:
    """分析流程编排器"""
    
    def __init__(self, agent_executor, cache_manager, env_vars: Dict[str, Any]):
        """
        初始化 Pipeline
        
        Args:
            agent_executor: Agent 执行器
            cache_manager: 缓存管理器
            env_vars: 环境变量
        """
        self.agent_executor = agent_executor
        self.cache_manager = cache_manager
        self.env_vars = env_vars
    
    def run(self, initial_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        运行完整流程
        
        Args:
            initial_data: 初始数据（来自 Aggregator）
            
        Returns:
            完整分析结果
        """
        # 初始化上下文
        context = {
            "initial_data": initial_data,
            "symbol": initial_data.get("symbol", "UNKNOWN")
        }
        
        # 定义流程步骤
        steps = [
            ("字段计算", self._step_calculate_fields),
            ("事件检测", self._step_event_detection),
            ("评分计算", self._step_scoring),
            ("场景分析", self._step_scenario),
            ("策略辅助", self._step_strategy_calc),
            ("策略生成", self._step_strategy),
            ("策略对比", self._step_comparison),
            ("策略排序", self._step_ranking),
            ("生成报告", self._step_report),
            ("保存结果", self._step_save_results)
        ]
        
        # 执行流程
        for i, (step_name, step_func) in enumerate(steps, 1):
            logger.info(f"📍 Step {i}/{len(steps)}: {step_name}")
            try:
                context = step_func(context)
            except Exception as e:
                logger.error(f"❌ Step {step_name} 失败: {str(e)}")
                return {
                    "status": "error",
                    "failed_step": step_name,
                    "error": str(e)
                }
        
        return {
            "status": "success",
            "report": context.get("final_report"),
            "event_risk": context.get("event_result"),
            "scoring": context.get("scoring_data"),
            "scenario": context.get("scenario_result"),
            "strategies": context.get("strategies_result"),
            "ranking": context.get("ranking_result")
        }
    
    def _step_calculate_fields(self, context: Dict) -> Dict:
        """步骤1：字段计算"""
        from code_nodes.field_calculator import main as calculator_main
        
        result = self.agent_executor.execute_code_node(
            node_name="Calculator",
            func=calculator_main,
            aggregated_data=context["initial_data"],
            **self.env_vars
        )
        
        context["calculated_data"] = self._safe_parse_json(result["result"])
        return context
    
    def _step_event_detection(self, context: Dict) -> Dict:
        """步骤2：事件检测"""
        result = self.agent_executor.execute_code_node(
            node_name="CODE1 - 事件检测",
            func=event_detection_main,
            user_query=f"分析 {context['symbol']}",
            **self.env_vars
        )
        
        context["event_result"] = self._safe_parse_json(result.get("result"))
        return context
    
    def _step_scoring(self, context: Dict) -> Dict:
        """步骤3：评分计算"""
        calculated_data = context["calculated_data"]
        
        ta_score = calculated_data.get("technical_analysis", {}).get("ta_score", 0)
        
        result = self.agent_executor.execute_code_node(
            node_name="CODE2 - 评分计算",
            func=scoring_main,
            agent3_output=calculated_data,
            technical_score=ta_score,
            **self.env_vars
        )
        
        context["scoring_data"] = self._safe_parse_json(result.get("result"))
        return context
    
    def _step_scenario(self, context: Dict) -> Dict:
        """步骤4：场景分析"""
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
            json_schema=schemas.agent5_schema.get_schema()
        )
        
        context["scenario_result"] = response.get("content", {})
        return context
    
    def _step_strategy_calc(self, context: Dict) -> Dict:
        """步骤5：策略辅助计算"""
        calculated_data = context["calculated_data"]
        scenario_result = context["scenario_result"]
        
        ta_score = calculated_data.get("technical_analysis", {}).get("ta_score", 0)
        
        result = self.agent_executor.execute_code_node(
            node_name="CODE3 - 策略辅助",
            func=strategy_calc_main,
            agent3_output=calculated_data,
            agent5_output=scenario_result,
            technical_score=ta_score,
            **self.env_vars
        )
        
        context["strategy_calc_data"] = self._safe_parse_json(result.get("result"))
        return context
    
    def _step_strategy(self, context: Dict) -> Dict:
        """步骤6：策略生成"""
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
            json_schema=schemas.agent6_schema.get_schema()
        )
        
        context["strategies_result"] = response.get("content", {})
        return context
    
    def _step_comparison(self, context: Dict) -> Dict:
        """步骤7：策略对比"""
        strategies_result = context["strategies_result"]
        scenario_result = context["scenario_result"]
        calculated_data = context["calculated_data"]
        
        result = self.agent_executor.execute_code_node(
            node_name="CODE4 - 策略对比",
            func=comparison_main,
            strategies_output=strategies_result,
            scenario_output=scenario_result,
            agent3_output=calculated_data,
            **self.env_vars
        )
        
        context["comparison_data"] = self._safe_parse_json(result.get("result"))
        return context
    
    def _step_ranking(self, context: Dict) -> Dict:
        """步骤8：策略排序"""
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
            json_schema=schemas.agent7_schema.get_schema()
        )
        
        context["ranking_result"] = response.get("content", {})
        return context
    
    def _step_report(self, context: Dict) -> Dict:
        """步骤9：生成报告"""
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
            messages=messages
        )
        
        context["final_report"] = response.get("content", "")
        return context
    
    def _step_save_results(self, context: Dict) -> Dict:
        """步骤10：保存结果"""
        symbol = context["symbol"]
        
        self.cache_manager.save_complete_analysis(
            symbol=symbol,
            initial_data=context["calculated_data"],
            scenario=context["scenario_result"],
            strategies=context["strategies_result"],
            ranking=context["ranking_result"],
            report=context["final_report"]
        )
        
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