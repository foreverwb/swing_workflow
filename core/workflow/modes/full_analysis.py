"""
完整分析模式
执行完整的期权分析流程
"""

from pathlib import Path
from typing import Dict, Any, List
from loguru import logger

import prompts
import schemas
from code_nodes import aggregator_main, calculator_main
from .base import BaseMode
from ..pipeline import AnalysisPipeline


class FullAnalysisMode(BaseMode):
    """完整分析模式"""
    def execute(self, symbol: str, data_folder: Path, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行完整分析
        
        流程：Agent3 → Aggregator → Calculator → Pipeline
        
        Args:
            symbol: 股票代码
            data_folder: 数据文件夹路径
            state: 当前状态（保留兼容，实际不使用）
            
        Returns:
            分析结果
        """
        logger.info(f"🎯 [完整分析模式] 开始分析 {symbol}")
        
        # 1. 扫描图片
        images = self.scan_images(data_folder)
        
        if not images:
            return {
                "status": "error",
                "message": f"文件夹 {data_folder} 中未找到图片"
            }
        
        logger.info(f"📊 扫描到 {len(images)} 张图片")
        
        # 2. Agent3 数据校验
        agent3_result = self._run_agent3(symbol, images)
        
        # 3. 数据聚合（增量合并）
        aggregated_result = self._run_aggregator(agent3_result, symbol)
        
        # 4. 字段计算 & 验证
        calculated_result = self._run_calculator(aggregated_result, symbol)
        # 5. 解析结果
        data_status = calculated_result.get("data_status")
        
        # 6. 判断状态
        if data_status == "awaiting_data":
            logger.warning(f"⚠️ 数据缺失，生成补齐指引")
            return {
                "status": "incomplete",
                "guide": calculated_result.get("guide", ""),
                "validation": calculated_result.get("validation", {}),
                "raw_result": calculated_result
            }
        
        elif data_status == "ready":
            logger.info("✅ 数据完整，开始完整分析流程")
            return self._run_full_pipeline(calculated_result)
        
        else:
            return {
                "status": "error",
                "message": f"未知的数据状态: {data_status}"
            }
    
    def _run_agent3(self, symbol: str, images: List[Path]) -> Dict[str, Any]:
        """
        Agent3 数据校验（增强版）
        
        新增功能：
        1. 详细记录请求和响应
        2. 自动规范化数据结构
        3. 修复常见格式问题
        
        Args:
            symbol: 股票代码
            images: 图片路径列表
            
        Returns:
            规范化后的 Agent3 响应
        """
        from core.workflow.agent3_handler import Agent3Handler
        
        logger.info("🔄 [Agent3] 数据校验（增强版）")
        
        # 创建处理器
        handler = Agent3Handler()
        
        # 构建 Prompt
        system_content = prompts.agent3_validate.get_system_prompt(self.env_vars)
        user_prompt = prompts.agent3_validate.get_user_prompt(
            symbol,
            [img.name for img in images]
        )
        
        # 构建消息列表
        inputs = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt}
        ]
        
        # 编码所有图片
        valid_img_count = 0
        for path in images:
            b64_str = self.encode_image_to_base64(path)
            if b64_str:
                inputs.append({
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": b64_str}}]
                })
                valid_img_count += 1
        
        if valid_img_count == 0:
            logger.error("❌ 没有有效图片可处理")
            return {}
        
        logger.info(f"📸 已编码 {valid_img_count} 张图片")
        
        # 记录请求
        handler.log_request(symbol, inputs, valid_img_count)
        
        # 调用 API
        response = self.agent_executor.execute_vision_agent(
            agent_name="agent3",
            inputs=inputs,
            json_schema=schemas.agent3_schema.get_schema()
        )
        
        # 解析响应
        raw_content = response.get("content", {})
        
        parsed_data = {}
        
        if isinstance(raw_content, dict):
            parsed_data = raw_content
        elif isinstance(raw_content, str):
            # 清洗 Markdown 标记
            import json
            try:
                clean_text = raw_content.strip()
                if clean_text.startswith("```json"):
                    clean_text = clean_text[7:]
                if clean_text.startswith("```"):
                    clean_text = clean_text[3:]
                if clean_text.endswith("```"):
                    clean_text = clean_text[:-3]
                parsed_data = json.loads(clean_text.strip())
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON 解析失败: {str(e)}")
                return {}
        else:
            logger.error(f"❌ 未知的响应类型: {type(raw_content)}")
            return {}
        
        # 记录原始响应
        handler.log_response(symbol, response, parsed_data)
        
        # 规范化数据结构（修复常见问题）
        logger.info("🔧 开始规范化数据结构")
        normalized_data = handler.normalize_structure(parsed_data)
        
        # 打印对比
        handler.print_detailed_comparison(parsed_data, normalized_data)
        
        logger.success("✅ Agent3 数据处理完成")
        
        return normalized_data
    
    def _run_aggregator(self, agent3_result: Dict, symbol: str) -> Dict[str, Any]:
        """
        运行数据聚合器
        
        Args:
            agent3_result: Agent3 结果
            state: 当前状态
            
        Returns:
            聚合结果
        """
        logger.info("📦 [Aggregator] 数据聚合")
        
        result = self.agent_executor.execute_code_node(
            node_name="Aggregator",
            func=aggregator_main,
            agent3_output=agent3_result,
            symbol=symbol,
            **self.env_vars
        )
        return result
    
    def _run_calculator(self, agent3_result: Dict, symbol: str) -> Dict[str, Any]:
        """
        运行字段计算器
        
        Args:
            data: 聚合后的数据
            
        Returns:
            计算后的数据
        """
        
        result = self.agent_executor.execute_code_node(
            node_name="Calculator",
            func=calculator_main,
            aggregated_data=agent3_result,
            symbol=symbol,
            **self.env_vars
        )
        return result
    
    def _handle_incomplete_data(self, aggregated_result: Dict) -> Dict[str, Any]:
        """
        处理数据不完整的情况
        
        Args:
            aggregated_result: 聚合结果
            
        Returns:
            包含补齐指引的结果
        """
        return {
            "status": "incomplete",
            "guide": self._format_补齐指引(aggregated_result),
            "missing_count": aggregated_result.get("missing_count"),
            "raw_result": aggregated_result
        }
    
    def _format_补齐指引(self, result: Dict) -> str:
        """格式化补齐指引"""
        return f"""
==================================================
📋 数据补齐指引 ({result.get('user_guide_progress', '0%')})
==================================================

{result.get('user_guide_summary', '')}

🔴 必须补齐 (Critical):
{result.get('user_guide_priority_critical', '无')}

🟠 建议补齐 (High):
{result.get('user_guide_priority_high', '无')}

🟡 可选补齐 (Medium):
{result.get('user_guide_priority_medium', '无')}

📝 历史合并记录:
{result.get('user_guide_merge_log', '')}

👉 下一步: {result.get('user_guide_next_action', '')}
"""
    
    def _run_full_pipeline(self, aggregated_result: Dict) -> Dict[str, Any]:
        """
        运行完整分析流程
        
        Args:
            aggregated_result: 聚合结果
            
        Returns:
            完整分析结果
        """
        logger.info("🚀 开始完整分析流程")
        # 创建并运行 Pipeline
        pipeline = AnalysisPipeline(
            agent_executor=self.agent_executor,
            cache_manager=self.cache_manager,
            env_vars=self.env_vars,
            enable_pretty_print=True,
            cache_file=self.engine.cache_file  # ⭐ 传递 cache_file
        )
        
        result = pipeline.run(aggregated_result)
        
        logger.success("✅ 完整分析流程完成")
        
        return result