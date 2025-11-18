"""
Swing Quant Workflow Engine
期权分析工作流引擎核心（支持多模型编排）
"""

import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from loguru import logger
from core.model_client import ModelClientManager
from code_nodes import (
    event_detection_main,
    scoring_main,
    strategy_calc_main,
    comparison_main,
    aggregator_main
)
import prompts
import schemas


class WorkflowEngine:
    """工作流引擎（支持多模型编排）"""
    
    def __init__(self, model_client_manager: ModelClientManager, env_vars: Dict[str, Any]):
        """
        初始化工作流引擎
        
        Args:
            model_client_manager: 模型客户端管理器（支持多模型）
            env_vars: 环境变量
        """
        self.model_client = model_client_manager
        self.env_vars = env_vars
        
        # 会话变量(用于数据累积) - 对应 conversation_variables
        self.conversation_vars = {
            "missing_count": 0,           # 缺失字段数量
            "data_status": "initial",     # 数据处理状态: initial | awaiting_data | ready | error
            "current_symbol": "",         # 当前分析的股票代码
            "first_parse_data": ""        # 首次解析的完整数据，用于补齐时合并
        }
        
        logger.info("工作流引擎初始化完成")
        logger.info(f"已配置 {len(self.model_client.list_all_agents())} 个Agent模型")

    def run(self, symbol: str, data_folder: Path) -> Dict[str, Any]:
        """
        运行完整工作流
        
        Args:
            symbol: 股票代码
            data_folder: 数据文件夹路径
            
        Returns:
            最终分析报告
        """
        logger.info(f"🚀 开始分析 {symbol}")
        
        # 获取文件列表
        files = self._get_files(data_folder)
        
        # Step 1: 判断分支(是否有文件)
        has_files = len(files) > 0
        
        if not has_files:
            # 分支1: 生成命令清单
            logger.warning(f"文件夹 {data_folder} 中没有找到图表文件")
            return self._run_agent2_cmdlist(symbol)
        
        logger.info(f"📁 找到 {len(files)} 个文件")
        
        # 分支2: 数据校验流程
        
        # Step 2: Agent 3 数据校验
        agent3_result = self._run_agent3_validate(symbol, files)
        
        # Step 3: 数据聚合(CODE_AGGREGATOR)
        aggregated_result = self._run_code_aggregator(agent3_result)
        
        # 检查数据状态
        data_status = aggregated_result.get("data_status")
        
        if data_status == "awaiting_data":
            # 数据不完整,返回补齐指引
            logger.warning("⚠️ 数据不完整,生成补齐指引")
            return {
                "status": "incomplete",
                "guide": self._format_补齐指引(aggregated_result)
            }
        
        elif data_status == "ready":
            # 数据完整,进入分析流程
            logger.info("✅ 数据完整,开始分析")
            return self._run_analysis_pipeline(aggregated_result)
        
        else:
            # 错误状态
            raise ValueError(f"未知的数据状态: {data_status}")

    def _run_analysis_pipeline(self, aggregated_result: Dict) -> Dict:
        """运行完整分析流程"""
        
        # 解析聚合数据
        merged_data = self._safe_parse_json(aggregated_result.get("result"))
        
        # Step 1: CODE1 事件检测
        logger.info("🔍 Step 1: 事件检测")
        event_result = event_detection_main(
            user_query=f"分析 {merged_data.get('symbol', 'UNKNOWN')}",
            **self.env_vars
        )
        
        # Step 2: CODE2 评分计算
        logger.info("📊 Step 2: 四维评分")
        scoring_result = scoring_main(
            agent3_output=merged_data,  # 直接传字典
            technical_score=merged_data.get("technical_analysis", {}).get("ta_score", 0),
            **self.env_vars
        )
        
        # 解析评分结果
        scoring_data = self._safe_parse_json(scoring_result.get("result"))
        
        # Step 3: Agent 5 场景分析
        logger.info("🎯 Step 3: 场景推演")
        agent5_result = self._run_agent5_scenario(scoring_data)
        
        # Step 4: CODE3 策略辅助计算
        logger.info("🧮 Step 4: 策略辅助")
        strategy_calc_result = strategy_calc_main(
            agent3_output=merged_data,  # 直接传字典
            agent5_output=agent5_result["content"],
            technical_score=merged_data.get("technical_analysis", {}).get("ta_score", 0),
            **self.env_vars
        )
        
        # 解析策略辅助结果
        strategy_calc_data = self._safe_parse_json(strategy_calc_result.get("result"))
        
        # Step 5: Agent 6 策略生成
        logger.info("💡 Step 5: 策略生成")
        agent6_result = self._run_agent6_strategy(
            agent5_result, 
            strategy_calc_data,
            merged_data
        )
        
        # Step 6: CODE4 策略对比
        logger.info("⚖️ Step 6: 策略对比")
        comparison_result = comparison_main(
            strategies_output=agent6_result["content"],
            scenario_output=agent5_result["content"],
            agent3_output=merged_data,  # 直接传字典
            **self.env_vars
        )
        
        # 解析对比结果
        comparison_data = self._safe_parse_json(comparison_result.get("result"))
        
        # Step 7: Agent 7 策略排序
        logger.info("🏆 Step 7: 策略排序")
        agent7_result = self._run_agent7_comparison(
            comparison_data,
            agent5_result["content"],
            agent6_result["content"]
        )
        
        # Step 8: Agent 8 最终报告
        logger.info("📋 Step 8: 生成报告")
        final_report = self._run_agent8_report(
            merged_data,
            agent5_result["content"],
            agent7_result["content"],
            event_result
        )
        
        logger.success("✅ 分析完成!")
        
        return {
            "status": "success",
            "report": final_report["content"],
            "event_risk": self._safe_parse_json(event_result.get("result")),
            "scoring": scoring_data,
            "scenario": agent5_result["content"],
            "strategies": agent6_result["content"],
            "ranking": agent7_result["content"]
        }

    def _run_agent2_cmdlist(self, symbol: str) -> Dict:
        """Agent 2: 命令清单生成"""
        messages = [
            {
                "role": "system",
                "content": prompts.agent2_cmdlist.get_system_prompt(self.env_vars)
            },
            {
                "role": "user",
                "content": prompts.agent2_cmdlist.get_user_prompt(symbol)
            }
        ]
        
        response = self.model_client.chat_completion(
            messages=messages,
            agent_name="agent2"
        )
        
        return {
            "status": "command_list",
            "content": response["content"]
        }

    def _run_agent3_validate(self, symbol: str, files: List[Path]) -> Dict:
        """Agent 3: 数据校验"""
        
        # 创建包含图片的消息
        message = self.model_client.create_image_message(
            text=prompts.agent3_validate.get_user_prompt(symbol, files),
            image_paths=files,
            agent_name="agent3"
        )
        
        messages = [
            {
                "role": "system",
                "content": prompts.agent3_validate.get_system_prompt(self.env_vars)
            },
            message
        ]
        
        response = self.model_client.chat_completion(
            messages=messages,
            agent_name="agent3",
            json_schema=schemas.agent3_schema.get_schema()
        )
        
        return response["content"]

    def _run_code_aggregator(self, agent3_output: Dict) -> Dict:
        """CODE_AGGREGATOR: 数据聚合"""
        result = aggregator_main(
            agent3_output=agent3_output,
            first_parse_data=self.conversation_vars["first_parse_data"],
            current_symbol=self.conversation_vars["current_symbol"],
            data_status=self.conversation_vars["data_status"],
            missing_count=self.conversation_vars["missing_count"],
            **self.env_vars
        )
        
        # 更新会话变量
        if "data_status" in result:
            self.conversation_vars["data_status"] = result["data_status"]
        if "missing_count" in result:
            self.conversation_vars["missing_count"] = result["missing_count"]
        if "current_symbol" in result:
            self.conversation_vars["current_symbol"] = result["current_symbol"]
        if "first_parse_data" in result and result["first_parse_data"]:
            self.conversation_vars["first_parse_data"] = result["first_parse_data"]
        
        return result

    def _run_agent5_scenario(self, scoring_data: Dict) -> Dict:
        """Agent 5: 场景分析"""
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
        
        response = self.model_client.chat_completion(
            messages=messages,
            agent_name="agent5",
            json_schema=schemas.agent5_schema.get_schema()
        )
        
        return response

    def _run_agent6_strategy(self, agent5_result: Dict, calc_data: Dict, agent3_data: Dict) -> Dict:
        """Agent 6: 策略生成"""
        messages = [
            {
                "role": "system",
                "content": prompts.agent6_strategy.get_system_prompt(self.env_vars)
            },
            {
                "role": "user",
                "content": prompts.agent6_strategy.get_user_prompt(
                    agent5_result, 
                    calc_data,
                    agent3_data
                )
            }
        ]
        
        response = self.model_client.chat_completion(
            messages=messages,
            agent_name="agent6",
            json_schema=schemas.agent6_schema.get_schema()
        )
        
        return response

    def _run_agent7_comparison(self, comparison_data: Dict, scenario: Dict, strategies: Dict) -> Dict:
        """Agent 7: 策略对比"""
        messages = [
            {
                "role": "system",
                "content": prompts.agent7_comparison.get_system_prompt()
            },
            {
                "role": "user",
                "content": prompts.agent7_comparison.get_user_prompt(
                    comparison_data, scenario, strategies
                )
            }
        ]
        
        response = self.model_client.chat_completion(
            messages=messages,
            agent_name="agent7",
            json_schema=schemas.agent7_schema.get_schema()
        )
        
        return response

    def _run_agent8_report(self, agent3: Dict, agent5: Dict, agent7: Dict, event: Dict) -> Dict:
        """Agent 8: 最终报告"""
        messages = [
            {
                "role": "system",
                "content": prompts.agent8_report.get_system_prompt()
            },
            {
                "role": "user",
                "content": prompts.agent8_report.get_user_prompt(
                    agent3, agent5, agent7, event
                )
            }
        ]
        
        response = self.model_client.chat_completion(
            messages=messages,
            agent_name="agent8"
        )
        
        return response

    def _get_files(self, folder: Path) -> List[Path]:
        """获取文件夹中的图片文件"""
        extensions = ['.png', '.jpg', '.jpeg', '.gif', '.webp']
        files = []
        
        for ext in extensions:
            files.extend(folder.glob(f'*{ext}'))
            files.extend(folder.glob(f'*{ext.upper()}'))
        
        return sorted(files)

    def _safe_parse_json(self, data: Any) -> Dict:
        """
        安全解析JSON（统一处理）
        
        Args:
            data: 可能是字典、JSON字符串或其他类型
            
        Returns:
            解析后的字典，失败返回空字典
        """
        if isinstance(data, dict):
            return data
        elif isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败: {str(e)[:100]}")
                logger.debug(f"原始数据: {data[:200]}")
                return {}
        else:
            logger.warning(f"未知数据类型: {type(data)}")
            return {}

    def _format_补齐指引(self, result: Dict) -> str:
        """格式化补齐指引"""
        return f"""
            {result.get('user_guide_summary', '')}
            📋 需要执行的命令
            {result.get('user_guide_commands', '')}
            📊 当前进度
            {result.get('user_guide_progress', '')}
            ⚠️ 缺失字段明细
            Critical(必须补齐):
            {result.get('user_guide_priority_critical', '无')}
            High(强烈建议):
            {result.get('user_guide_priority_high', '无')}
            Medium(可选):
            {result.get('user_guide_priority_medium', '无')}
            💡 下一步操作
            {result.get('user_guide_next_action', '')}
            📝 合并日志
            {result.get('user_guide_merge_log', '')}

            当前状态: 等待补齐数据(已缓存首次解析结果)
            股票代码: {result.get('current_symbol', '')}
            缺失数量: {result.get('missing_count', 0)}个字段
        """