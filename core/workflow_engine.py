import json
import time
import base64
import copy
from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger

# 修复 1: 正确导入 ModelClientManager
from core.model_client import ModelClientManager

import prompts
import schemas
from code_nodes import (
    event_detection_main,
    scoring_main,
    strategy_calc_main,
    comparison_main,
    aggregator_main
)

class WorkflowEngine:
    """工作流引擎（支持文件夹扫描、分批识别与增量合并）"""
    
    def __init__(self, model_client_manager: ModelClientManager, env_vars: Dict[str, Any]):
        self.model_client = model_client_manager
        self.env_vars = env_vars
        
        # 会话状态变量 (用于 code_aggregator 的增量合并)
        self.conversation_vars = {
            "missing_count": 0,
            "data_status": "initial",
            "current_symbol": "",
            "first_parse_data": ""  # 这里存储上一轮完整解析的数据字符串
        }
        
        logger.info("工作流引擎初始化完成")
        
        self.cache_file = Path("data/temp") / "workflow_state.json"
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()
    
    def _load_state(self):
        """从磁盘加载之前的分析状态"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    self.conversation_vars = json.load(f)
                logger.info("📂 已加载之前的分析状态，支持增量补齐")
            except Exception as e:
                logger.warning(f"加载状态失败: {e}")
    
    def _save_state(self):
        """保存当前状态到磁盘"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.conversation_vars, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存状态失败: {e}")
    

    def run(self, symbol: str, data_folder: Path) -> Dict[str, Any]:
        """
        运行完整工作流
        """
        logger.info(f"🚀 开始完整分析 {symbol}")
        
        # 1. 扫描图片
        image_paths = self._scan_folder_images(data_folder)
        if not image_paths:
            return {"status": "error", "message": f"文件夹 {data_folder} 中未找到图片"}
            
        logger.info(f"📊 扫描到 {len(image_paths)} 张图片，准备进行分批视觉分析")
        
        # 2. Agent 3 数据校验 (分批执行 + 内部合并)
        # 返回的是当前文件夹内所有图片解析后的聚合结果
        current_run_data = self._run_agent3_validate(symbol, image_paths)
        
        # 3. 调用 Aggregator (处理跨轮次的数据累积)
        # 将"当前文件夹解析结果"与"历史缓存数据"进行合并
        aggregated_result = self._run_code_aggregator(current_run_data, symbol)
        
        # 解析聚合后的结果
        final_data = self._safe_parse_json(aggregated_result.get("result"))
        data_status = aggregated_result.get("data_status")
        
        # 4. 根据状态决定后续流程
        if data_status == "awaiting_data":
            logger.warning(f"⚠️ 数据仍缺失 {aggregated_result.get('missing_count')} 个字段，生成补齐指引")
            return {
                "status": "incomplete",
                # 直接返回 Aggregator 生成的结构化指引
                "guide": self._format_补齐指引(aggregated_result),
                "missing_count": aggregated_result.get("missing_count"),
                "merge_history": final_data.get("_merge_history", [])
            }
            
        elif data_status == "ready":
            logger.info("✅ 数据完整，开始后续分析流程")
            # 将完整的 targets 数据传入后续 Agent
            return self._run_analysis_pipeline(final_data)
            
        else:
            return {"status": "error", "message": f"未知的数据状态: {data_status}"}

    def _scan_folder_images(self, folder: Path) -> List[Path]:
        """扫描文件夹获取所有支持的图片"""
        extensions = ['*.png', '*.PNG', '*.jpg', '*.JPG', '*.jpeg', '*.JPEG']
        image_paths = []
        for ext in extensions:
            image_paths.extend(list(folder.glob(ext)))
        return sorted(image_paths)

    def _encode_image_to_base64(self, image_path: Path) -> Optional[str]:
        """本地图片转 Base64"""
        try:
            with open(image_path, "rb") as image_file:
                base64_str = base64.b64encode(image_file.read()).decode('utf-8')
                ext = image_path.suffix.lower()
                mime_type = "image/jpeg" if ext in ['.jpg', '.jpeg'] else "image/png"
                return f"data:{mime_type};base64,{base64_str}"
        except Exception as e:
            logger.error(f"❌ 图片编码失败 {image_path.name}: {e}")
            return None

    def _run_agent3_validate(self, symbol: str, image_paths: List[Path]) -> Dict:
        """
        Agent 3 核心逻辑：分批处理 -> 解析 JSON -> 内部合并
        """
        BATCH_SIZE = 3  # 每批 3 张图，避免 Payload 过大
        SLEEP_SECONDS = 2 # 冷却时间
        
        # 这是一个空的结构，用于累积当前文件夹内所有批次的结果
        combined_batch_result = {}
        
        total_images = len(image_paths)
        total_batches = (total_images + BATCH_SIZE - 1) // BATCH_SIZE
        
        logger.info(f"📦 图片总数 {total_images}，将分为 {total_batches} 个批次处理")

        for i in range(0, total_images, BATCH_SIZE):
            batch_index = (i // BATCH_SIZE) + 1
            batch_paths = image_paths[i : i + BATCH_SIZE]
            
            logger.info(f"🔄 [Agent3] 处理第 {batch_index}/{total_batches} 批次 ({len(batch_paths)} 张图)...")
            
            # 1. 构建 Prompt
            system_content = prompts.agent3_validate.get_system_prompt(self.env_vars)
            system_content += f"\n\n[重要提示] 这是任务的分批输入（第 {batch_index}/{total_batches} 批）。请提取可见数据。若数据不在当前图片中，请保持字段为空或默认值，不要编造。"

            # 修复参数错误：get_user_prompt 只接受 symbol 和 file_list
            user_prompt = prompts.agent3_validate.get_user_prompt(
                symbol, 
                [p.name for p in batch_paths] 
            )

            inputs = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_prompt}
            ]
            
            # 2. 图片转 Base64
            valid_img_count = 0
            for path in batch_paths:
                b64_str = self._encode_image_to_base64(path)
                if b64_str:
                    inputs.append({
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": b64_str}}]
                    })
                    valid_img_count += 1
            
            if valid_img_count == 0:
                logger.warning(f"⚠️ 第 {batch_index} 批次无有效图片，跳过")
                continue

            # 3. 调用 API
            try:
                response = self.model_client.responses_create(
                    inputs=inputs,
                    agent_name="agent3",
                    json_schema=schemas.agent3_schema.get_schema()
                )
                
                # 4. 增强的 JSON 解析逻辑 (修复格式异常警告)
                raw_content = response.get("content", {})
                batch_data = {}
                
                if isinstance(raw_content, dict):
                    batch_data = raw_content
                elif isinstance(raw_content, str):
                    try:
                        # 清洗 Markdown 标记
                        clean_text = raw_content.strip()
                        if clean_text.startswith("```json"):
                            clean_text = clean_text[7:]
                        if clean_text.startswith("```"):
                            clean_text = clean_text[3:]
                        if clean_text.endswith("```"):
                            clean_text = clean_text[:-3]
                        batch_data = json.loads(clean_text.strip())
                    except json.JSONDecodeError:
                        logger.error(f"❌ 第 {batch_index} 批次 JSON 解析失败")
                        logger.debug(f"原始内容片段: {raw_content[:200]}")
                        continue # 跳过此批次合并

                # 5. 执行单次运行内的合并 (Intra-run merge)
                if batch_data:
                    self._deep_merge(combined_batch_result, batch_data)
                    logger.success(f"✅ 第 {batch_index} 批次数据合并成功")
                
                # 冷却
                if batch_index < total_batches:
                    time.sleep(SLEEP_SECONDS)
                    
            except Exception as e:
                logger.error(f"❌ 第 {batch_index} 批次调用失败: {e}")
                continue

        return combined_batch_result

    def _run_code_aggregator(self, current_run_data: Dict, symbol: str) -> Dict:
        """调用 Aggregator 节点进行跨轮次数据累积"""
        result = aggregator_main(
            agent3_output=current_run_data,
            first_parse_data=self.conversation_vars["first_parse_data"], # 传入历史缓存
            current_symbol=symbol,
            data_status=self.conversation_vars["data_status"],
            missing_count=self.conversation_vars["missing_count"],
            **self.env_vars
        )
        
        # 更新会话状态 (实现记忆功能)
        if "first_parse_data" in result:
            self.conversation_vars["first_parse_data"] = result["first_parse_data"]
        if "data_status" in result:
            self.conversation_vars["data_status"] = result["data_status"]
        if "missing_count" in result:
            self.conversation_vars["missing_count"] = result["missing_count"]
        
        self._save_state()
        return result

    def _deep_merge(self, target: Dict, source: Dict):
        """
        递归合并字典：仅当 Source 包含有效数据时覆盖 Target
        有效数据定义：非 -999, 非 "N/A", 非空, 非 "false"
        """
        invalid_values = [-999, "N/A", "false", "False", "数据不足", "", None]
        
        for key, value in source.items():
            if isinstance(value, dict):
                if key not in target:
                    target[key] = {}
                self._deep_merge(target[key], value)
            else:
                # 逻辑：
                # 1. Target 没有 -> 填入
                # 2. Target 是无效值 且 Source 是有效值 -> 覆盖
                if key not in target:
                    target[key] = value
                elif (target[key] in invalid_values) and (value not in invalid_values):
                    target[key] = value

    def _format_补齐指引(self, result: Dict) -> str:
        """格式化 Aggregator 返回的指引信息"""
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
            agent3_output=merged_data,
            technical_score=merged_data.get("technical_analysis", {}).get("ta_score", 0),
            **self.env_vars
        )
        
        scoring_data = self._safe_parse_json(scoring_result.get("result"))
        
        # Step 3: Agent 5 场景分析
        logger.info("🎯 Step 3: 场景推演")
        agent5_result = self._run_agent5_scenario(scoring_data)
        
        # Step 4: CODE3 策略辅助计算
        logger.info("🧮 Step 4: 策略辅助")
        strategy_calc_result = strategy_calc_main(
            agent3_output=merged_data,
            agent5_output=agent5_result["content"],
            technical_score=merged_data.get("technical_analysis", {}).get("ta_score", 0),
            **self.env_vars
        )
        
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
            agent3_output=merged_data,
            **self.env_vars
        )
        
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
        
        return response

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

    def _safe_parse_json(self, data: Any) -> Dict:
        """安全解析JSON"""
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