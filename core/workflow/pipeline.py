"""
分析流程编排器 (v3.3 - Fix Circular Import)
修复:
1. 将 code_nodes 的导入延迟到方法内部，解决与 core/__init__.py 的循环引用问题
"""

import json
import re
from typing import Dict, Any, Optional
from loguru import logger

import prompts
import schemas
from utils.console_printer import (
    print_header,
    print_step,
    print_success,
    print_error,
    print_info,
    print_report_link
)
from core.error_handler import ErrorHandler, WorkflowError, ErrorCategory, ErrorSeverity

class AnalysisPipeline:
    """分析流程编排器（增强版）"""
    
    def __init__(
        self, agent_executor, 
        cache_manager, 
        env_vars: Dict[str, Any],
        enable_pretty_print: bool = True,
        cache_file: str = None,
        error_handler: ErrorHandler = None,
        market_params: Dict = None,
        dyn_params: Dict = None      
    ):
        self.agent_executor = agent_executor
        self.cache_manager = cache_manager
        self.enable_pretty_print = enable_pretty_print
        self.cache_file = cache_file  
        self.error_handler = error_handler  
        self.market_params = market_params or {}  
        self.dyn_params = dyn_params or {}       
        self.env_vars = env_vars
        
    def run(self, initial_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        运行完整流程
        """
        if self.enable_pretty_print:
            symbol = initial_data.get("symbol", "UNKNOWN")
            print_header(
                f"期权策略分析流程 (Phase 3)",
                f"标的: {symbol} | 完整分析模式"
            )
        
        context = {
            "initial_data": initial_data,
            "symbol": initial_data.get("symbol", "UNKNOWN"),
            "calculated_data": initial_data
        }
        
        # 定义流程步骤
        steps = [
            ("事件检测", self._step_event_detection, "检测财报、FOMC 等重大事件"),
            ("评分计算", self._step_scoring, "计算四维评分（Gamma/Wall/Direction/IV）"),
            ("场景分析", self._step_scenario, "推演市场场景及微观物理属性"),
            ("策略辅助", self._step_strategy_calc, "计算行权价、DTE、RR、Pw"),
            ("策略生成", self._step_strategy, "基于蓝图生成高盈亏比策略"),
            ("策略对比", self._step_comparison, "Code 4 量化评分与排序"),
            ("生成报告", self._step_report, "生成结构化分析报告"),
            ("生成HTML", self._step_html_report, "生成可视化仪表盘"),
            ("保存结果", self._step_save_results, "保存分析结果到缓存")
        ]
        
        for i, (step_name, step_func, step_desc) in enumerate(steps, 1):
            if self.enable_pretty_print:
                print_step(i, len(steps), f"{step_name} - {step_desc}")
            
            logger.info(f"📍 Step {i}/{len(steps)}: {step_name}")
            
            try:
                if self.error_handler:
                    self.error_handler.add_completed_step(f"Step {i}: {step_name} 开始")
                
                context = step_func(context)
                
                if self.error_handler:
                    self.error_handler.add_completed_step(f"Step {i}: {step_name} 完成")
                
                if self.enable_pretty_print:
                    print_success(f"{step_name} 完成")
            
            except WorkflowError as we:
                if self.enable_pretty_print:
                    print_error(f"{step_name} 失败", we.message)
                logger.error(f"❌ Step {step_name} 失败: {we.message}")
                if self.error_handler:
                    return self.error_handler.handle_error(we)
                return {"status": "error", "failed_step": step_name, "error": we.to_dict()}
            
            except Exception as e:
                import traceback
                if self.enable_pretty_print:
                    print_error(f"{step_name} 失败", str(e))
                logger.error(f"❌ Step {step_name} 失败: {str(e)}\n{traceback.format_exc()}")
                workflow_error = WorkflowError(
                    message=f"未预期的错误: {str(e)}",
                    severity=ErrorSeverity.CRITICAL,
                    category=ErrorCategory.CODE_BUG,
                    node_name=step_name,
                    original_error=e
                )
                if self.error_handler:
                    return self.error_handler.handle_error(workflow_error)
                return {"status": "error", "failed_step": step_name, "error": str(e)}
        
        if self.enable_pretty_print:
            print_success("🎉 完整分析流程完成！")
        
        return {
            "status": "success",
            "report": context.get("final_report"),
            "event_risk": context.get("event_result"),
            "scoring": context.get("scoring_data"),
            "scenario": context.get("scenario_result"),
            "strategies": context.get("strategies_result"),
            "comparison": context.get("comparison_data")
        }
    
    def _step_event_detection(self, context: Dict) -> Dict:
        """步骤1：事件检测"""
        # [延迟导入]
        from code_nodes import event_detection_main
        
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
        # [延迟导入]
        from code_nodes import scoring_main
        
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
        if "targets" not in scoring_data:
            scoring_data["targets"] = context["calculated_data"].get("targets", {})

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
            description="推演市场场景及微观物理属性"
        )
        context["scenario_result"] = self._safe_parse_json(response.get("content", {}))
        return context
    
    def _step_strategy_calc(self, context: Dict) -> Dict:
        """步骤4：策略辅助计算"""
        # [延迟导入]
        from code_nodes import strategy_calc_main
        
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
            description="基于蓝图生成高盈亏比策略"
        )
        context["strategies_result"] = self._safe_parse_json(response.get("content", {}))
        return context
    
    def _step_comparison(self, context: Dict) -> Dict:
        """步骤6：策略对比"""
        # [延迟导入]
        from code_nodes import comparison_main
        
        strategies_result = context["strategies_result"]
        scenario_result = context["scenario_result"]
        strategy_calc_data = context["strategy_calc_data"]
        
        result = self.agent_executor.execute_code_node(
            node_name="策略对比",
            func=comparison_main,
            description="Code 4 量化评分与排序",
            strategies_output=strategies_result, # [修正] 适配 Code 4 main 签名
            scenario_output=scenario_result,
            agent3_output=strategy_calc_data,
            **self.env_vars
        )
        context["comparison_data"] = self._safe_parse_json(result)
        return context
    
    def _step_report(self, context: Dict) -> Dict:
        """步骤8：生成报告"""
        calculated_data = context["calculated_data"]
        scenario_result = context["scenario_result"]
        strategies_result = context["strategies_result"]
        comparison_data = context["comparison_data"]
        event_result = context["event_result"]
        
        messages = [
            {
                "role": "system",
                "content": prompts.agent8_report.get_system_prompt()
            },
            {
                "role": "user",
                "content": prompts.agent8_report.get_user_prompt(
                    agent3=calculated_data,
                    agent5=scenario_result,
                    agent6=strategies_result,
                    code4=comparison_data,
                    event={"result": json.dumps(event_result, ensure_ascii=False)}
                )
            }
        ]
        
        response = self.agent_executor.execute_agent(
            agent_name="agent8",
            messages=messages,
            description="生成结构化分析报告"
        )
        context["final_report"] = response.get("content", "")
        return context
    
    def _step_html_report(self, context: Dict) -> Dict:
        """步骤9：生成 HTML 报告"""
        # [延迟导入]
        from code_nodes import html_report_main
        
        symbol = context["symbol"]
        final_report = context.get("final_report", "")
        calculated_data = context.get("calculated_data", {}) # [新增] 获取计算数据
        
        start_date = None
        if self.cache_file:
            match = re.match(r'(\w+)_(\d{8})\.json', self.cache_file)
            if match:
                start_date = match.group(2)
        
        result = self.agent_executor.execute_code_node(
            node_name="HTML报告生成",
            func=html_report_main,
            description="将 Markdown 报告转为 HTML 格式",
            report_markdown=final_report,
            symbol=symbol,
            start_date=start_date,
            current_data=calculated_data, # [关键修复] 传递当前数据以生成监控卡片
            output_dir="data/output",
            **self.env_vars
        )
        
        context["html_report_result"] = result
        if result.get("status") == "success":
            html_path = result.get("html_path", "")
            if self.enable_pretty_print and html_path:
                print_report_link(html_path, symbol)
        
        return context
    
    def _step_save_results(self, context: Dict) -> Dict:
        """步骤9：保存结果"""
        symbol = context["symbol"]
        
        if self.market_params and self.dyn_params:
            self.cache_manager.save_market_params(
                symbol=symbol,
                market_params=self.market_params,
                dyn_params=self.dyn_params,
                cache_file=self.cache_file
            )
        
        self.cache_manager.save_complete_analysis(
            symbol=symbol,
            initial_data=context["calculated_data"],
            scenario=context["scenario_result"],
            strategies=context["strategies_result"],
            ranking=context["comparison_data"],
            report=context["final_report"],
            cache_file=getattr(self, 'cache_file', None),
            market_params=self.market_params, 
            dyn_params=self.dyn_params          
        )
        
        if self.enable_pretty_print:
            print_info(f"分析结果已保存至缓存: {symbol}")
        
        logger.success(f"✅ 分析结果已保存至缓存: {symbol}")
        return context
    
    @staticmethod
    def _safe_parse_json(data: Any) -> Dict:
        """安全解析数据为 dict"""
        if isinstance(data, dict):
            if "result" in data and len(data) == 1:
                inner = data["result"]
                if isinstance(inner, dict): return inner
                elif isinstance(inner, str):
                    try: return json.loads(inner)
                    except: return {"raw": inner}
            return data
        
        if isinstance(data, str):
            clean_text = data.strip()
            if clean_text.startswith("```json"): clean_text = clean_text[7:]
            elif clean_text.startswith("```"): clean_text = clean_text[3:]
            if clean_text.endswith("```"): clean_text = clean_text[:-3]
            clean_text = clean_text.strip()
            try:
                parsed = json.loads(clean_text)
                if isinstance(parsed, dict): return parsed
            except: pass
            return {"raw": data}
        
        return {}