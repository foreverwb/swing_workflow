"""
分析流程编排器 (v3.6 - Data Flow Fix)
修复:
1. [Critical] 确保 Agent 6 的策略数据被正确传递到 final_data，防止 analyze 结果为空
2. [Typo] 修复之前版本可能存在的 contextport_link 拼写错误
"""

import json
import re
from typing import Dict, Any, Optional
from loguru import logger

import prompts
import schemas
from utils.console_printer import (
    print_header, print_step, print_success, print_error, print_info, print_report_link
)
from core.error_handler import ErrorHandler, WorkflowError, ErrorCategory, ErrorSeverity
from code_nodes import strategy_calc_main, comparison_main

class AnalysisPipeline:
    
    def __init__(
        self, agent_executor, cache_manager, env_vars: Dict[str, Any],
        enable_pretty_print: bool = True, cache_file: str = None,
        error_handler: ErrorHandler = None, market_params: Dict = None, dyn_params: Dict = None      
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
        if self.enable_pretty_print:
            symbol = initial_data.get("symbol", "UNKNOWN")
            print_header(f"期权策略分析流程 (Phase 3)", f"标的: {symbol} | 完整分析模式")
        
        context = {
            "initial_data": initial_data,
            "symbol": initial_data.get("symbol", "UNKNOWN"),
            "calculated_data": initial_data
        }
        
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
            if self.enable_pretty_print: print_step(i, len(steps), f"{step_name} - {step_desc}")
            logger.info(f"📍 Step {i}/{len(steps)}: {step_name}")
            try:
                context = step_func(context)
                if self.enable_pretty_print: print_success(f"{step_name} 完成")
            except Exception as e:
                import traceback
                logger.error(f"❌ Step {step_name} 失败: {str(e)}\n{traceback.format_exc()}")
                return {"status": "error", "failed_step": step_name, "error": str(e)}
        
        if self.enable_pretty_print: print_success("🎉 完整分析流程完成！")
        return {"status": "success", "report": context.get("final_report")}
    
    def _step_event_detection(self, context: Dict) -> Dict:
        from code_nodes import event_detection_main
        res = self.agent_executor.execute_code_node("事件检测", event_detection_main, "检测事件", user_query=f"分析 {context['symbol']}", **self.env_vars)
        context["event_result"] = self._safe_parse_json(res)
        return context

    def _step_scoring(self, context: Dict) -> Dict:
        from code_nodes import scoring_main
        calc = context["calculated_data"]
        res = self.agent_executor.execute_code_node("评分计算", scoring_main, "计算评分", agent3_output=calc, technical_score=calc.get("technical_analysis", {}).get("ta_score", 0), **self.env_vars)
        context["scoring_data"] = self._safe_parse_json(res)
        return context

    def _step_scenario(self, context: Dict) -> Dict:
        scoring = context["scoring_data"]
        if "targets" not in scoring: scoring["targets"] = context["calculated_data"].get("targets", {})
        msgs = [{"role": "system", "content": prompts.agent5_scenario.get_system_prompt()}, {"role": "user", "content": prompts.agent5_scenario.get_user_prompt(scoring)}]
        res = self.agent_executor.execute_agent("agent5", msgs, schemas.agent5_schema.get_schema(), "推演场景")
        print(">>>>>>>>> agent_5 <<<<<<<<", '\n', res)
        context["scenario_result"] = self._safe_parse_json(res.get("content", {}))
        return context

    def _step_strategy_calc(self, context: Dict) -> Dict:
        res = self.agent_executor.execute_code_node("策略辅助", strategy_calc_main, "计算策略参数", agent3_output=context["calculated_data"].get("targets", {}), agent5_output=context["scenario_result"], technical_score=0, **self.env_vars)
        print(">>>>>>>>> strategy_calc <<<<<<<<", '\n', res)
        context["strategy_calc_data"] = self._safe_parse_json(res)
        return context

    def _step_strategy(self, context: Dict) -> Dict:
        msgs = [{"role": "system", "content": prompts.agent6_strategy.get_system_prompt(self.env_vars)}, {"role": "user", "content": prompts.agent6_strategy.get_user_prompt({"content": context["scenario_result"]}, context["strategy_calc_data"], context["calculated_data"])}]
        res = self.agent_executor.execute_agent("agent6", msgs, schemas.agent6_schema.get_schema(), "生成策略")
        print(">>>>>>>>> agent_6 <<<<<<<<<<<", '\n', res)
        
        # [Fix] 增强解析逻辑
        raw_content = res.get("content", {})
        # [Bug Fix] 使用 ensure_strategies_key=True 确保返回标准格式
        parsed = self._safe_parse_json(raw_content, ensure_strategies_key=True)
        
        # [Fix] 确保 strategies 字段存在且是列表
        if "strategies" not in parsed or not isinstance(parsed.get("strategies"), list):
            # 尝试从其他可能的键获取策略
            strategies_found = []
            for key in ["strategy", "recommendations", "suggested_strategies"]:
                if key in parsed:
                    val = parsed[key]
                    strategies_found = val if isinstance(val, list) else [val]
                    break
            parsed["strategies"] = strategies_found
        
        context["strategies_result"] = parsed
        
        # [Log] 确认策略生成情况
        strat_count = len(context["strategies_result"].get("strategies", []))
        logger.info(f"Generated {strat_count} strategies")
        if strat_count == 0:
            logger.warning(f"[Warning] Agent6 返回的策略为空，原始内容: {str(raw_content)[:200]}...")
        return context

    def _step_comparison(self, context: Dict) -> Dict:
        res = self.agent_executor.execute_code_node("策略对比", comparison_main, "策略评分", strategies_output=context["strategies_result"], scenario_output=context["scenario_result"], agent3_output=context["strategy_calc_data"], **self.env_vars)
        context["comparison_data"] = self._safe_parse_json(res)
        return context

    def _step_report(self, context: Dict) -> Dict:
        msgs = [{"role": "system", "content": prompts.agent8_report.get_system_prompt()}, {"role": "user", "content": prompts.agent8_report.get_user_prompt(agent3=context["calculated_data"], agent5=context["scenario_result"], agent6=context["strategies_result"], code4=context["comparison_data"], event={"result": json.dumps(context["event_result"], ensure_ascii=False)}, strategy_calc=context["strategy_calc_data"])}]
        res = self.agent_executor.execute_agent("agent8", msgs, description="生成报告")
        context["final_report"] = res.get("content", "")
        return context

    def _step_html_report(self, context: Dict) -> Dict:
        from code_nodes import html_report_main
        symbol = context["symbol"]
        targets = context.get("calculated_data", {}).get("targets", {})
        
        # [Critical] 显式构造 final_data，确保 strategies 被包含
        strategies_result = context.get("strategies_result", {})
        
        final_data_payload = {
            "targets": targets,
            "report": context.get("final_report", ""),
            "agent6_result": strategies_result,   # 核心策略
            "strategies": strategies_result,      # [Fix] 添加 strategies 字段供 HTML 生成器多路径读取
            "market_params": self.market_params,
            "snapshot": {
                "targets": targets,
                "data": {
                    "strategy_calc": context.get("strategy_calc_data", {}),
                    "agent6_result": strategies_result
                },
                "meta": context.get("strategy_calc_data", {}).get("meta", {})
            }
        }
        
        start_date = None
        if self.cache_file:
            match = re.match(r'(\w+)_o_(\d{8})\.json', self.cache_file)
            if match: start_date = match.group(2)
        if not start_date:
            start_date = self.env_vars.get("start_date")
        
        html_kwargs = dict(self.env_vars)
        html_kwargs.update({
            "symbol": symbol,
            "final_data": final_data_payload,
            "mode": "full",
            "output_dir": "data/output",
            "start_date": start_date,
        })
        result = self.agent_executor.execute_code_node(
            node_name="HTML报告生成", func=html_report_main, description="生成HTML",
            **html_kwargs
        )
        
        context["html_report_result"] = result
        if result.get("status") == "success":
            print_report_link(result['html_path'], symbol)
        return context
    
    def _step_save_results(self, context: Dict) -> Dict:
        symbol = context["symbol"]
        start_date_hint = self.env_vars.get("start_date")
        # 保存参数
        if self.market_params:
            if self.cache_file:
                self.cache_manager.save_market_params(symbol, self.market_params, self.dyn_params, self.cache_file)
            else:
                self.cache_manager.save_market_params(
                    symbol,
                    self.market_params,
                    self.dyn_params,
                    start_date=start_date_hint
                )
        
        # [Critical] 确保传递 strategies 给 save_complete_analysis
        self.cache_manager.save_complete_analysis(
            symbol=symbol,
            initial_data=context["calculated_data"],
            scenario=context["scenario_result"],
            strategies=context["strategies_result"], # 确保此字段非空
            ranking=context["comparison_data"],
            report=context["final_report"],
            start_date=start_date_hint,
            cache_file=self.cache_file,
            market_params=self.market_params,
            dyn_params=self.dyn_params
        )
        if self.enable_pretty_print: print_info(f"分析结果已保存至缓存: {symbol}")
        return context
    
    @staticmethod
    def _safe_parse_json(data: Any, ensure_strategies_key: bool = False) -> Dict:
        """
        安全解析 JSON 数据，处理各种边界情况
        
        支持的输入格式:
        1. 已经是 dict 的数据
        2. 包含 "result" 键的单一键字典
        3. JSON 字符串
        4. 带有 Markdown 代码块的 JSON 字符串
        
        Args:
            data: 输入数据
            ensure_strategies_key: 如果为True，确保返回结果包含strategies键
        """
        result = {}
        
        if isinstance(data, dict):
            # 处理 {"result": ...} 包装
            if "result" in data and len(data) == 1:
                inner = data["result"]
                if isinstance(inner, (dict, list)): 
                    result = inner if isinstance(inner, dict) else {"strategies": inner}
                elif isinstance(inner, str): 
                    try: 
                        result = json.loads(inner) 
                    except: 
                        result = {"raw": inner}
                else:
                    result = {}
            else:
                # [Fix] 如果字典为空，返回空字典而不是 None
                result = data if data else {}
        elif isinstance(data, str):
            try: 
                cleaned = data.strip().replace('```json','').replace('```','').strip()
                parsed = json.loads(cleaned)
                # [Fix] 确保返回的是字典
                if isinstance(parsed, list):
                    result = {"strategies": parsed}
                else:
                    result = parsed if isinstance(parsed, dict) else {"raw": parsed}
            except: 
                result = {"raw": data}
        elif isinstance(data, list):
            # [Fix] 如果是列表，包装成字典
            result = {"strategies": data}
        
        # [Bug Fix] 确保策略数据包含 strategies 键
        if ensure_strategies_key and "strategies" not in result:
            result["strategies"] = []
            
        return result
