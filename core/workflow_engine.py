"""
WorkflowEngine - 工作流引擎
支持完整分析流程和盘中刷新
"""

import json
import time
import base64
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from loguru import logger

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
    """工作流引擎"""
    
    def __init__(self, model_client_manager: ModelClientManager, env_vars: Dict[str, Any]):
        """
        初始化工作流引擎
        
        Args:
            model_client_manager: 模型客户端管理器
            env_vars: 环境变量字典
        """
        self.model_client = model_client_manager
        self.env_vars = env_vars
        
        # 会话状态变量（用于增量补齐）
        self.conversation_vars = {
            "missing_count": 0,
            "data_status": "initial",
            "current_symbol": "",
            "first_parse_data": ""
        }
        
        logger.info("工作流引擎初始化完成")
        
        # 缓存文件
        self.cache_file = Path("data/temp") / "workflow_state.json"
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()
    
    def _load_state(self):
        """从磁盘加载之前的分析状态"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.conversation_vars = json.load(f)
                logger.info("📂 已加载之前的分析状态，支持增量补齐")
            except Exception as e:
                logger.warning(f"加载状态失败: {e}")
    
    def _save_state(self):
        """保存当前状态到磁盘"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.conversation_vars, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存状态失败: {e}")
    
    def run(self, symbol: str, data_folder: Path, mode: str = "full") -> Dict[str, Any]:
        """
        运行完整工作流
        
        Args:
            symbol: 股票代码
            data_folder: 数据文件夹
            mode: 运行模式
                - "full": 完整分析（默认）
                - "update": 增量补齐数据
                - "refresh": 仅刷新 Greeks（用于盘中观测）
        
        Returns:
            分析结果字典
        """
        mode_desc = {
            "full": "完整分析",
            "update": "增量补齐",
            "refresh": "刷新快照"
        }.get(mode, "完整分析")
        
        logger.info(f"🚀 开始{mode_desc} {symbol}")
        
        # 1. 加载历史缓存（如果存在）
        cache_file = Path(f"data/cache/{symbol}_analysis.json")
        previous_data = None
        
        if mode in ["update", "refresh"] and cache_file.exists():
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)
                # 从最后一个快照获取历史数据
                snapshots = cached.get("greeks_snapshots", [])
                if snapshots:
                    previous_data = snapshots[-1].get("data", {}).get("targets", {})
                    logger.info(f"📂 加载历史快照数据")
        
        # 2. 扫描图片
        image_paths = self._scan_folder_images(data_folder)
        if not image_paths:
            return {
                "status": "error",
                "message": f"文件夹 {data_folder} 中未找到图片"
            }
        
        logger.info(f"📊 扫描到 {len(image_paths)} 张图片，准备分析")
        
        # 3. Agent 3 数据校验（一次性上传所有图片）
        current_run_data = self._run_agent3_validate(
            symbol,
            image_paths,
            previous_data=previous_data
        )
        
        # 4. 如果是 refresh 模式，保存快照并返回
        if mode == "refresh":
            # 执行聚合和计算
            aggregated_result = self._run_code_aggregator(current_run_data, symbol)
            aggregated_data = self._safe_parse_json(aggregated_result.get("result"))
            
            # 执行字段计算
            from code_nodes.field_calculator import main as calculator_main
            calculated_result = calculator_main(
                aggregated_data=aggregated_data,
                **self.env_vars
            )
            calculated_data = self._safe_parse_json(calculated_result.get("result"))
            
            # 保存快照
            return self._save_greeks_snapshot(symbol, calculated_data)
        
        # 5. 正常流程：调用 Aggregator
        aggregated_result = self._run_code_aggregator(current_run_data, symbol)
        
        # 解析聚合后的结果
        final_data = self._safe_parse_json(aggregated_result.get("result"))
        data_status = aggregated_result.get("data_status")
        
        # 6. 根据状态决定后续流程
        if data_status == "awaiting_data":
            logger.warning(f"⚠️ 数据仍缺失 {aggregated_result.get('missing_count')} 个字段，生成补齐指引")
            return {
                "status": "incomplete",
                "guide": self._format_补齐指引(aggregated_result),
                "missing_count": aggregated_result.get("missing_count"),
                "merge_history": final_data.get("_merge_history", [])
            }
        
        elif data_status == "ready":
            logger.info("✅ 数据完整，开始后续分析流程")
            return self._run_analysis_pipeline(final_data, cache_file)
        
        else:
            return {
                "status": "error",
                "message": f"未知的数据状态: {data_status}"
            }
    
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
    
    def _run_agent3_validate(
        self,
        symbol: str,
        image_paths: List[Path],
        previous_data: Optional[Dict] = None
    ) -> Dict:
        """
        Agent 3 数据校验（一次性处理所有图片）
        
        Args:
            symbol: 股票代码
            image_paths: 图片路径列表
            previous_data: 历史数据（用于 update 模式）
        
        Returns:
            解析后的数据字典
        """
        logger.info(f"🔄 [Agent3] 处理 {len(image_paths)} 张图片...")
        
        # 1. 构建 Prompt
        system_content = prompts.agent3_validate.get_system_prompt(self.env_vars)
        
        # 如果有历史数据，添加上下文
        if previous_data:
            system_content += f"""

【重要：这是增量补齐任务】
以下是首次分析已获取的数据，请在此基础上补充缺失字段：
```json
{json.dumps(previous_data, ensure_ascii=False, indent=2)}
```

**补齐要求**：
1. 保留上述已有的有效数据（不要覆盖）
2. 从当前上传的图片中提取缺失的字段
3. 对于需要关联计算的字段，提取原始数据即可（系统会自动计算）
4. 确保所有 22 个必需字段都有有效值
"""
        
        user_prompt = prompts.agent3_validate.get_user_prompt(
            symbol,
            [p.name for p in image_paths]
        )
        
        # 2. 构建消息列表
        inputs = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt}
        ]
        
        # 3. 添加所有图片
        valid_img_count = 0
        for path in image_paths:
            b64_str = self._encode_image_to_base64(path)
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
        
        # 4. 调用 API
        try:
            response = self.model_client.responses_create(
                inputs=inputs,
                agent_name="agent3",
                json_schema=schemas.agent3_schema.get_schema()
            )
            
            # ⭐ 新增：打印 Agent3 返回数据
            self._print_agent_response("Agent3 - 数据校验", response)
            
            # 5. 解析响应
            raw_content = response.get("content", {})
            
            # 调试日志
            logger.info(f"📊 响应类型: {type(raw_content)}")
            logger.info(f"📊 响应长度: {len(str(raw_content))} 字符")
            
            # 解析 JSON
            if isinstance(raw_content, dict):
                batch_data = raw_content
            elif isinstance(raw_content, str):
                # 尝试清洗 Markdown 标记
                try:
                    clean_text = raw_content.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    if clean_text.startswith("```"):
                        clean_text = clean_text[3:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]
                    batch_data = json.loads(clean_text.strip())
                except json.JSONDecodeError as e:
                    logger.error(f"❌ JSON 解析失败: {str(e)}")
                    logger.debug(f"原始内容片段: {raw_content[:200]}")
                    return {}
            else:
                logger.error(f"❌ 未知的响应类型: {type(raw_content)}")
                return {}
            
            logger.success(f"✅ 数据解析成功")
            
            # ⭐ 新增：打印解析后的数据摘要
            self._print_data_summary("Agent3 解析结果", batch_data)
            
            return batch_data
        
        except Exception as e:
            logger.error(f"❌ Agent3 调用失败: {e}")
            return {}
    
    def _run_code_aggregator(self, current_run_data: Dict, symbol: str) -> Dict:
        """调用 Aggregator 节点进行跨轮次数据累积"""
        logger.info("📦 [Aggregator] 执行数据聚合")
        
        result = aggregator_main(
            agent3_output=current_run_data,
            first_parse_data=self.conversation_vars["first_parse_data"],
            current_symbol=symbol,
            data_status=self.conversation_vars["data_status"],
            missing_count=self.conversation_vars["missing_count"],
            **self.env_vars
        )
        
        # ⭐ 新增：打印 Aggregator 结果
        self._print_code_node_result("Aggregator", result)
        
        # 更新会话状态（实现记忆功能）
        if "first_parse_data" in result:
            self.conversation_vars["first_parse_data"] = result["first_parse_data"]
        if "data_status" in result:
            self.conversation_vars["data_status"] = result["data_status"]
        if "missing_count" in result:
            self.conversation_vars["missing_count"] = result["missing_count"]
        
        self._save_state()
        return result
    
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
    
    def _run_analysis_pipeline(self, aggregated_result: Dict, cache_file: Path) -> Dict:
        """
        运行完整分析流程
        
        Args:
            aggregated_result: 聚合后的数据
            cache_file: 缓存文件路径
        """
        # 解析聚合数据
        merged_data = self._safe_parse_json(aggregated_result.get("result"))
        
        # ⭐ 新增：关联字段计算
        logger.info("🧮 [Calculator] 执行关联字段计算")
        from code_nodes.field_calculator import main as calculator_main
        
        calculated_result = calculator_main(
            aggregated_data=merged_data,
            **self.env_vars
        )
        
        # ⭐ 新增：打印计算结果
        self._print_code_node_result("Calculator", calculated_result)
        
        calculated_data = self._safe_parse_json(calculated_result.get("result"))
        
        # 验证计算结果
        calc_log = calculated_data.get("targets", {}).get("_calculation_log", {})
        if calc_log.get("checks"):
            logger.info(f"📊 计算验证: {len(calc_log['checks'])} 项检查")
            for check in calc_log["checks"]:
                if not check.get("is_valid"):
                    logger.warning(f"⚠️ {check['field']}: {check['note']}")
        
        # Step 1: CODE1 事件检测
        logger.info("🔍 Step 1: 事件检测")
        event_result = event_detection_main(
            user_query=f"分析 {calculated_data.get('symbol', 'UNKNOWN')}",
            **self.env_vars
        )
        
        # ⭐ 新增：打印事件检测结果
        self._print_code_node_result("CODE1 - 事件检测", event_result)
        
        # Step 2: CODE2 评分计算
        logger.info("📊 Step 2: 四维评分")
        scoring_result = scoring_main(
            agent3_output=calculated_data,
            technical_score=calculated_data.get("technical_analysis", {}).get("ta_score", 0),
            **self.env_vars
        )
        
        # ⭐ 新增：打印评分结果
        self._print_code_node_result("CODE2 - 评分计算", scoring_result)
        
        scoring_data = self._safe_parse_json(scoring_result.get("result"))
        
        # Step 3: Agent 5 场景分析
        logger.info("🎯 Step 3: 场景推演")
        agent5_result = self._run_agent5_scenario(scoring_data)
        
        # ⭐ 新增：打印场景分析结果
        self._print_agent_response("Agent5 - 场景分析", agent5_result)
        
        # Step 4: CODE3 策略辅助计算
        logger.info("🧮 Step 4: 策略辅助")
        strategy_calc_result = strategy_calc_main(
            agent3_output=calculated_data,
            agent5_output=agent5_result["content"],
            technical_score=calculated_data.get("technical_analysis", {}).get("ta_score", 0),
            **self.env_vars
        )
        
        # ⭐ 新增：打印策略辅助计算结果
        self._print_code_node_result("CODE3 - 策略辅助", strategy_calc_result)
        
        strategy_calc_data = self._safe_parse_json(strategy_calc_result.get("result"))
        
        # Step 5: Agent 6 策略生成
        logger.info("💡 Step 5: 策略生成")
        agent6_result = self._run_agent6_strategy(
            agent5_result,
            strategy_calc_data,
            calculated_data
        )
        
        # ⭐ 新增：打印策略生成结果
        self._print_agent_response("Agent6 - 策略生成", agent6_result)
        
        # Step 6: CODE4 策略对比
        logger.info("⚖️ Step 6: 策略对比")
        comparison_result = comparison_main(
            strategies_output=agent6_result["content"],
            scenario_output=agent5_result["content"],
            agent3_output=calculated_data,
            **self.env_vars
        )
        
        # ⭐ 新增：打印策略对比结果
        self._print_code_node_result("CODE4 - 策略对比", comparison_result)
        
        comparison_data = self._safe_parse_json(comparison_result.get("result"))
        
        # Step 7: Agent 7 策略排序
        logger.info("🏆 Step 7: 策略排序")
        agent7_result = self._run_agent7_comparison(
            comparison_data,
            agent5_result["content"],
            agent6_result["content"]
        )
        
        # ⭐ 新增：打印策略排序结果
        self._print_agent_response("Agent7 - 策略排序", agent7_result)
        
        # Step 8: Agent 8 最终报告
        logger.info("📋 Step 8: 生成报告")
        final_report = self._run_agent8_report(
            calculated_data,
            agent5_result["content"],
            agent7_result["content"],
            event_result
        )
        
        # ⭐ 新增：打印最终报告（仅前500字符）
        self._print_agent_response("Agent8 - 最终报告", final_report, truncate=500)
        
        # 保存完整分析结果到缓存
        self._save_complete_analysis(
            cache_file=cache_file,
            symbol=calculated_data.get("symbol", "UNKNOWN"),
            initial_data=calculated_data,
            scenario=agent5_result["content"],
            strategies=agent6_result["content"],
            ranking=agent7_result["content"],
            report=final_report["content"]
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
    
    # ⭐⭐⭐ 新增：打印辅助函数 ⭐⭐⭐
    
    def _print_agent_response(self, agent_name: str, response: Dict, truncate: int = None):
        """
        打印 Agent 响应数据
        
        Args:
            agent_name: Agent 名称
            response: 响应字典
            truncate: 截断长度（可选，用于长文本）
        """
        print("\n" + "="*80)
        print(f"📤 {agent_name} 返回数据")
        print("="*80)
        
        # 打印元数据
        if "model" in response:
            print(f"🤖 模型: {response['model']}")
        if "usage" in response:
            usage = response["usage"]
            print(f"📊 Token使用: 输入={usage.get('input_tokens', 0)}, 输出={usage.get('output_tokens', 0)}")
        
        # 打印内容
        content = response.get("content", {})
        
        if isinstance(content, dict):
            print(f"\n📋 内容类型: dict")
            print(f"📋 字段数量: {len(content)}")
            
            # 打印主要字段
            if truncate:
                content_str = json.dumps(content, ensure_ascii=False, indent=2)
                if len(content_str) > truncate:
                    print(f"\n{content_str[:truncate]}...")
                    print(f"\n[内容过长，已截断至 {truncate} 字符]")
                else:
                    print(f"\n{content_str}")
            else:
                # 打印关键字段摘要
                key_fields = ["symbol", "status", "total_score", "scenario_classification", "strategies"]
                print(f"\n🔑 关键字段:")
                for key in key_fields:
                    if key in content:
                        value = content[key]
                        if isinstance(value, (dict, list)):
                            print(f"  • {key}: {type(value).__name__} (长度: {len(value)})")
                        else:
                            print(f"  • {key}: {value}")
        
        elif isinstance(content, str):
            print(f"\n📋 内容类型: str")
            print(f"📋 内容长度: {len(content)} 字符")
            if truncate and len(content) > truncate:
                print(f"\n{content[:truncate]}...")
                print(f"\n[内容过长，已截断至 {truncate} 字符]")
            else:
                print(f"\n{content}")
        
        else:
            print(f"\n📋 内容类型: {type(content)}")
            print(f"\n{content}")
        
        print("="*80 + "\n")
    
    def _print_code_node_result(self, node_name: str, result: Dict):
        """
        打印 Code Node 结果
        
        Args:
            node_name: 节点名称
            result: 结果字典
        """
        print("\n" + "="*80)
        print(f"🔧 {node_name} 执行结果")
        print("="*80)
        
        # 检查是否有错误
        if "error" in result or (isinstance(result.get("result"), str) and "error" in result["result"]):
            print(f"❌ 执行失败")
            print(f"\n{json.dumps(result, ensure_ascii=False, indent=2)}")
            print("="*80 + "\n")
            return
        
        # 打印结果
        result_data = result.get("result", {})
        
        if isinstance(result_data, str):
            # 尝试解析 JSON
            try:
                parsed = json.loads(result_data)
                print(f"📋 结果类型: JSON (已解析)")
                
                # 打印关键信息
                if isinstance(parsed, dict):
                    print(f"📋 字段数量: {len(parsed)}")
                    
                    # 提取关键字段
                    key_indicators = [
                        "symbol", "status", "data_status", "missing_count",
                        "validation_summary", "total_score", "em1_dollar",
                        "calculation_log", "event_count", "risk_level"
                    ]
                    
                    print(f"\n🔑 关键指标:")
                    for key in key_indicators:
                        if key in parsed:
                            value = parsed[key]
                            if isinstance(value, dict):
                                print(f"  • {key}: {json.dumps(value, ensure_ascii=False)}")
                            else:
                                print(f"  • {key}: {value}")
                
                # 打印前500字符的完整JSON
                full_json = json.dumps(parsed, ensure_ascii=False, indent=2)
                if len(full_json) > 500:
                    print(f"\n📄 完整数据（前500字符）:")
                    print(full_json[:500] + "...")
                else:
                    print(f"\n📄 完整数据:")
                    print(full_json)
                    
            except json.JSONDecodeError:
                print(f"📋 结果类型: str (非JSON)")
                print(f"📋 内容长度: {len(result_data)} 字符")
                if len(result_data) > 500:
                    print(f"\n{result_data[:500]}...")
                else:
                    print(f"\n{result_data}")
        
        elif isinstance(result_data, dict):
            print(f"📋 结果类型: dict")
            print(f"📋 字段数量: {len(result_data)}")
            print(f"\n{json.dumps(result_data, ensure_ascii=False, indent=2)[:500]}...")
        else:
            print(f"📋 结果类型: {type(result_data)}")
            print(f"\n{result_data}")
        
        print("="*80 + "\n")
    
    def _print_data_summary(self, title: str, data: Dict):
        """
        打印数据摘要
        
        Args:
            title: 标题
            data: 数据字典
        """
        print("\n" + "="*80)
        print(f"📊 {title}")
        print("="*80)
        
        if not isinstance(data, dict):
            print(f"⚠️ 数据类型错误: {type(data)}")
            print("="*80 + "\n")
            return
        
        # 提取关键信息
        if "targets" in data:
            targets = data["targets"]
            if isinstance(targets, dict):
                print(f"✅ targets 类型: dict")
                print(f"✅ Symbol: {targets.get('symbol', 'N/A')}")
                print(f"✅ Status: {targets.get('status', 'N/A')}")
                print(f"✅ Spot Price: {targets.get('spot_price', 'N/A')}")
                print(f"✅ EM1 Dollar: {targets.get('em1_dollar', 'N/A')}")
                
                # 检查嵌套字段
                if "gamma_metrics" in targets:
                    gm = targets["gamma_metrics"]
                    print(f"\n📈 Gamma Metrics:")
                    print(f"  • vol_trigger: {gm.get('vol_trigger', 'N/A')}")
                    print(f"  • spot_vs_trigger: {gm.get('spot_vs_trigger', 'N/A')}")
                    print(f"  • net_gex: {gm.get('net_gex', 'N/A')}")
                
                if "walls" in targets:
                    walls = targets["walls"]
                    print(f"\n🧱 Walls:")
                    print(f"  • call_wall: {walls.get('call_wall', 'N/A')}")
                    print(f"  • put_wall: {walls.get('put_wall', 'N/A')}")
                    print(f"  • major_wall: {walls.get('major_wall', 'N/A')}")
            else:
                print(f"⚠️ targets 类型: {type(targets)}")
        
        if "validation_summary" in data:
            vs = data["validation_summary"]
            print(f"\n✔️ 验证摘要:")
            print(f"  • 完成率: {vs.get('completion_rate', 0)}%")
            print(f"  • 提供字段: {vs.get('provided', 0)}/{vs.get('total_required', 22)}")
            print(f"  • 缺失字段: {vs.get('missing_count', 0)}")
        
        print("="*80 + "\n")
    
    # ⭐⭐⭐ 打印辅助函数结束 ⭐⭐⭐
    
    def _save_complete_analysis(
        self,
        cache_file: Path,
        symbol: str,
        initial_data: Dict,
        scenario: Dict,
        strategies: Dict,
        ranking: Dict,
        report: str
    ):
        """
        保存完整分析结果到缓存
        
        Args:
            cache_file: 缓存文件路径
            symbol: 股票代码
            initial_data: 初始数据
            scenario: 场景分析
            strategies: 策略列表
            ranking: 策略排序
            report: 最终报告
        """
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 加载现有缓存（如果存在）
        if cache_file.exists():
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)
        else:
            cached = {
                "symbol": symbol,
                "created_at": datetime.now().isoformat(),
                "last_updated": None,
                "analysis": {},
                "greeks_snapshots": [],
                "backtest_records": []
            }
        
        # 更新分析结果
        cached["analysis"] = {
            "status": "completed",
            "initial_date": datetime.now().strftime("%Y-%m-%d"),
            "initial_spot": initial_data.get("targets", {}).get("spot_price"),
            "scenario": scenario,
            "strategies": strategies,
            "ranking": ranking,
            "report": report
        }
        
        cached["last_updated"] = datetime.now().isoformat()
        
        # 保存首次快照
        if not cached["greeks_snapshots"]:
            snapshot = {
                "snapshot_id": 0,
                "type": "initial_analysis",
                "timestamp": datetime.now().isoformat(),
                "note": "完整分析",
                "spot_price": initial_data.get("targets", {}).get("spot_price"),
                "em1_dollar": initial_data.get("targets", {}).get("em1_dollar"),
                "vol_trigger": self._get_nested_value(initial_data.get("targets", {}), "gamma_metrics.vol_trigger"),
                "spot_vs_trigger": self._get_nested_value(initial_data.get("targets", {}), "gamma_metrics.spot_vs_trigger"),
                "net_gex": self._get_nested_value(initial_data.get("targets", {}), "gamma_metrics.net_gex"),
                "call_wall": self._get_nested_value(initial_data.get("targets", {}), "walls.call_wall"),
                "put_wall": self._get_nested_value(initial_data.get("targets", {}), "walls.put_wall"),
                "iv_7d": self._get_nested_value(initial_data.get("targets", {}), "atm_iv.iv_7d"),
                "iv_14d": self._get_nested_value(initial_data.get("targets", {}), "atm_iv.iv_14d"),
                "data": initial_data,
                "changes": None
            }
            cached["greeks_snapshots"].append(snapshot)
        
        # 保存缓存
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cached, f, ensure_ascii=False, indent=2)
        
        logger.success(f"✅ 完整分析结果已保存: {cache_file}")
    
    def _save_greeks_snapshot(self, symbol: str, data: Dict, note: str = "") -> Dict:
        """
        保存 Greeks 快照（用于 refresh 模式）
        
        Args:
            symbol: 股票代码
            data: 完整数据（含计算结果）
            note: 快照备注
        
        Returns:
            快照保存结果
        """
        cache_file = Path(f"data/cache/{symbol}_analysis.json")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 加载现有缓存
        if cache_file.exists():
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)
        else:
            cached = {
                "symbol": symbol,
                "created_at": datetime.now().isoformat(),
                "last_updated": None,
                "analysis": {},
                "greeks_snapshots": [],
                "backtest_records": []
            }
        
        # 提取关键数据
        targets = data.get("targets", {})
        
        # 获取上一次快照
        previous_snapshot = cached["greeks_snapshots"][-1] if cached["greeks_snapshots"] else None
        
        # 创建新快照
        snapshot_id = len(cached["greeks_snapshots"])
        new_snapshot = {
            "snapshot_id": snapshot_id,
            "type": "initial_analysis" if snapshot_id == 0 else "intraday_refresh",
            "timestamp": datetime.now().isoformat(),
            "note": note,
            "spot_price": targets.get("spot_price"),
            "em1_dollar": targets.get("em1_dollar"),
            "vol_trigger": self._get_nested_value(targets, "gamma_metrics.vol_trigger"),
            "spot_vs_trigger": self._get_nested_value(targets, "gamma_metrics.spot_vs_trigger"),
            "net_gex": self._get_nested_value(targets, "gamma_metrics.net_gex"),
            "call_wall": self._get_nested_value(targets, "walls.call_wall"),
            "put_wall": self._get_nested_value(targets, "walls.put_wall"),
            "iv_7d": self._get_nested_value(targets, "atm_iv.iv_7d"),
            "iv_14d": self._get_nested_value(targets, "atm_iv.iv_14d"),
            "data": data,
            "changes": None
        }
        
        # 计算变化
        if previous_snapshot:
            new_snapshot["changes"] = self._calculate_snapshot_changes(
                previous_snapshot,
                new_snapshot
            )
        
        # 添加快照
        cached["greeks_snapshots"].append(new_snapshot)
        cached["last_updated"] = datetime.now().isoformat()
        
        # 保存缓存
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cached, f, ensure_ascii=False, indent=2)
        
        logger.success(f"✅ 快照已保存: {cache_file}")
        
        # 生成摘要
        summary = self._generate_snapshot_summary(new_snapshot)
        
        return {
            "status": "success",
            "snapshot": new_snapshot,
            "snapshot_summary": summary,
            "cache_file": str(cache_file)
        }
    
    def _calculate_snapshot_changes(self, old_snapshot: Dict, new_snapshot: Dict) -> Dict:
        """计算两次快照的变化"""
        changes = {}
        
        key_fields = [
            "spot_price", "em1_dollar", "vol_trigger",
            "call_wall", "put_wall", "net_gex",
            "iv_7d", "iv_14d"
        ]
        
        for field in key_fields:
            old_value = old_snapshot.get(field)
            new_value = new_snapshot.get(field)
            
            if old_value is None or new_value is None:
                continue
            
            if old_value == -999 or new_value == -999:
                continue
            
            if old_value != new_value:
                change_info = {
                    "old": old_value,
                    "new": new_value
                }
                
                # 计算百分比变化
                if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
                    if old_value != 0:
                        pct_change = ((new_value - old_value) / old_value) * 100
                        change_info["change_pct"] = round(pct_change, 2)
                
                changes[field] = change_info
        
        return changes if changes else None
    
    def _generate_snapshot_summary(self, snapshot: Dict) -> str:
        """生成快照摘要"""
        lines = [
            f"快照 #{snapshot['snapshot_id']}",
            f"时间: {snapshot['timestamp'][:19]}",
            f"类型: {snapshot['type']}",
            ""
        ]
        
        if snapshot.get('note'):
            lines.append(f"备注: {snapshot['note']}")
            lines.append("")
        
        lines.extend([
            f"现价: ${snapshot.get('spot_price', 'N/A')}",
            f"EM1$: ${snapshot.get('em1_dollar', 'N/A')}",
            f"Vol Trigger: ${snapshot.get('vol_trigger', 'N/A')}",
            f"状态: {snapshot.get('spot_vs_trigger', 'N/A')}",
            f"NET-GEX: {snapshot.get('net_gex', 'N/A')}",
            ""
        ])
        
        if snapshot.get('changes'):
            lines.append("变化:")
            for field, change in snapshot['changes'].items():
                pct_str = f" ({change['change_pct']:+.2f}%)" if 'change_pct' in change else ""
                lines.append(f"  • {field}: {change['old']} → {change['new']}{pct_str}")
        
        return "\n".join(lines)
    
    def _get_nested_value(self, data: Dict, path: str):
        """获取嵌套字段值（支持点号路径）"""
        keys = path.split('.')
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value if value != -999 else None
    
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