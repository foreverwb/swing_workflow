"""
完整分析模式
执行完整的期权分析流程
"""
import json
from pathlib import Path
from typing import Dict, Any, List
from loguru import logger

import prompts
import schemas
from code_nodes import calculator_main
from code_nodes.runtime_label_builder import RuntimeLabelBuilder
from .base import BaseMode
from ..pipeline import AnalysisPipeline
from core.error_handler import ErrorHandler, WorkflowError, ErrorCategory, ErrorSeverity
from core.workflow.agent3_handler import Agent3Handler

class FullAnalysisMode(BaseMode):
    """完整分析模式"""
    def execute(
        self, 
        symbol: str, 
        data_folder: Path, 
        state: Dict[str, Any],
        market_params: Dict = None,
        dyn_params: Dict = None       
    ) -> Dict[str, Any]:
        """执行完整分析 - 增强容错"""
        logger.info(f"🎯 [完整分析模式] 开始分析 {symbol}")
        
        # 创建错误处理器
        error_handler = ErrorHandler(symbol)
        # 保存市场参数到实例（供后续使用）
        self.market_params = market_params or {}
        self.dyn_params = dyn_params or {}
        
        try:
            # 1. 扫描图片
            error_handler.add_completed_step("扫描图片")
            images = self.scan_images(data_folder)
            
            if not images:
                return {
                    "status": "error",
                    "message": f"文件夹 {data_folder} 中未找到图片"
                }
            
            logger.info(f"📊 扫描到 {len(images)} 张图片")
            
            # 2. Agent3 数据校验
            error_handler.add_completed_step("开始 Agent3")
            agent3_result = self._run_agent3(symbol, images)
            error_handler.add_completed_step("完成 Agent3")
            
            # Agent3 特殊判断：区分"数据不完整"和"运行错误"
            content = agent3_result.get("content", {})
            
            # 检查是否为空列表（常见错误）
            if isinstance(content.get("targets"), list) and not content["targets"]:
                raise WorkflowError(
                    message="Agent3 返回空列表，这是代码 Bug 或 Schema 问题",
                    severity=ErrorSeverity.CRITICAL,
                    category=ErrorCategory.CODE_BUG,
                    node_name="Agent3",
                    context={"response": agent3_result}
                )
            
            # 3. 字段计算 & 验证（直接使用 Agent3 输出）
            error_handler.add_completed_step("开始 Calculator")
            calculated_result = self._run_calculator(agent3_result, symbol)
            error_handler.add_completed_step("完成 Calculator")
            
            # 4. 解析结果
            data_status = calculated_result.get("data_status")
            
            # 5. 判断状态
            if data_status == "awaiting_data":
                logger.warning(f"⚠️ 数据缺失，生成补齐指引（非错误）")
                return {
                    "status": "incomplete",
                    "guide": calculated_result.get("guide", ""),
                    "validation": calculated_result.get("validation", {}),
                    "raw_result": calculated_result
                }
            
            elif data_status == "ready":
                logger.info("✅ 数据完整，开始完整分析流程")
                error_handler.add_completed_step("数据验证通过，进入 Pipeline")
                return self._run_full_pipeline(
                    calculated_result, 
                    error_handler,
                    market_params=self.market_params,
                    dyn_params=self.dyn_params
                )
            
            else:
                raise WorkflowError(
                    message=f"未知的数据状态: {data_status}",
                    severity=ErrorSeverity.CRITICAL,
                    category=ErrorCategory.CODE_BUG,
                    node_name="Calculator",
                    context={"data_status": data_status}
                )
    
        except WorkflowError as we:
            # 捕获分类后的错误
            logger.error(f"❌ 流程终止: {we.message}")
            return error_handler.handle_error(we)
        
        except Exception as e:
            # 未分类的错误（兜底）
            logger.exception("❌ 未知错误")
            workflow_error = WorkflowError(
                message=f"未预期的错误: {str(e)}",
                severity=ErrorSeverity.CRITICAL,
                category=ErrorCategory.CODE_BUG,
                node_name="Unknown",
                original_error=e
            )
        return error_handler.handle_error(workflow_error)
    
    def _run_agent3(self, symbol: str, images: List[Path]) -> Dict[str, Any]:
        """
        Agent3 数据校验（增强版 + RuntimeLabel）
        
        新增功能：
        1. 详细记录请求和响应
        2. 自动规范化数据结构
        3. 修复常见格式问题
        4. 为每张图片附加 RuntimeLabel（语义约束）
        
        Args:
            symbol: 股票代码
            images: 图片路径列表
            
        Returns:
            规范化后的 Agent3 响应
        """
        
        logger.info("🔄 [Agent3] 数据校验（增强版 + RuntimeLabel）")
        
        # 创建处理器
        handler = Agent3Handler()
        label_builder = RuntimeLabelBuilder()
        
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
        
        # 编码所有图片 + 附加 RuntimeLabel
        valid_img_count = 0
        label_count = 0
        
        for path in images:
            b64_str = self.encode_image_to_base64(path)
            if not b64_str:
                logger.warning(f"⚠️ 无法编码图片: {path.name}")
                continue
            
            # 构建 RuntimeLabel
            label = label_builder.build_label(path.name, symbol)
            
            # 构建消息内容（Label + Image 合并为一条消息）
            content_parts = []
            
            if label:
                # 添加 RuntimeLabel（JSON 格式）
                label_json = label.to_json()
                content_parts.append({
                    "type": "text",
                    "text": f"### RuntimeLabel\n```json\n{label_json}\n```"
                })
                label_count += 1
                logger.debug(f"📎 附加 Label: {path.name} → CMD={label.CMD}, ROLE={label.TIMEFRAME_ROLE}")
            else:
                # 无法解析时提供基础说明
                content_parts.append({
                    "type": "text",
                    "text": f"### 图片: {path.name}\n（未能解析 RuntimeLabel，请根据图表内容自行判断）"
                })
                logger.warning(f"⚠️ 无法生成 Label: {path.name}")
            
            # 添加图片
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": b64_str}
            })
            
            # 添加到消息列表（一条消息包含 Label + Image）
            inputs.append({
                "role": "user",
                "content": content_parts
            })
            valid_img_count += 1
        
        if valid_img_count == 0:
            logger.error("❌ 没有有效图片可处理")
            return {}
        
        logger.info(f"📸 已编码 {valid_img_count} 张图片，附加 {label_count} 个 RuntimeLabel")
        
        # 记录请求
        handler.log_request(symbol, inputs, valid_img_count)
        # 调用 API
        response = self.agent_executor.execute_vision_agent(
            agent_name="agent3",
            inputs=inputs,
            json_schema=schemas.agent3_schema.get_schema()
        )
        logger.debug(f"Agent3 原始响应: {json.dumps(response, ensure_ascii=False)[:500]}...")
        
        # 解析响应
        raw_content = response.get("content", {})
        
        parsed_data = {}
        
        if isinstance(raw_content, dict):
            parsed_data = raw_content
        elif isinstance(raw_content, str):
            # 清洗 Markdown 标记
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
    
    def _run_calculator(self, agent3_result: Dict, symbol: str) -> Dict[str, Any]:
        """
        运行字段计算器
        
        Args:
            agent3_result: Agent3 规范化后的结果
            symbol: 股票代码
            
        Returns:
            计算后的数据
        """
        
        calc_kwargs = dict(self.env_vars)
        calc_kwargs.update({
            "aggregated_data": agent3_result,  # Calculator 期望的参数名
            "symbol": symbol,
        })
        result = self.agent_executor.execute_code_node(
            node_name="Calculator",
            func=calculator_main,
            **calc_kwargs
        )
        return result

    
    def _run_full_pipeline(
        self, 
        calculated_result: Dict, 
        error_handler: ErrorHandler,
        market_params: Dict = None, 
        dyn_params: Dict = None
    ) -> Dict[str, Any]:
        """
        运行完整分析流程
        
        Args:
            calculated_result: Calculator 计算后的结果
            error_handler: 错误处理器
            market_params: 市场参数
            dyn_params: 动态参数
            
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
            cache_file=self.engine.cache_file,  
            error_handler=error_handler,
            market_params=market_params,
            dyn_params=dyn_params
        )
        
        result = pipeline.run(calculated_result)
        
        logger.success("✅ 完整分析流程完成")
        
        return result
