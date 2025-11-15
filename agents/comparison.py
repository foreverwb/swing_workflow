"""
Agent 7 - 策略对比
基于 CODE4 的排序结果，给出最终推荐和执行优先级
"""

import json
from typing import Dict
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ComparisonAgent:
    """策略对比器"""
    
    def __init__(self, llm_client, config):
        self.llm_client = llm_client
        self.config = config
        self.model = config.MODEL_COMPARISON
    
    def compare(self, ranking_result: Dict, scenario_result: Dict, validated_data: Dict) -> Dict:
        """
        策略对比与推荐
        
        Args:
            ranking_result: CODE4 排序结果
            scenario_result: Agent 5 剧本分析
            validated_data: Agent 3 数据校验
        
        Returns:
            对比结果
        """
        try:
            logger.info(f"🤖 Agent 7: 策略对比...")
            
            # 解析 ranking_json 获取完整排序
            ranking_list = json.loads(ranking_result.get("ranking_json", "[]"))
            
            # 构造 System Prompt
            system_prompt = self._build_system_prompt()
            
            # 构造 User Prompt
            user_prompt = f"""【完整排序数据】
{json.dumps(ranking_list, ensure_ascii=False, indent=2)}

【Top1 策略摘要】
- 排名: {ranking_result.get('top1_rank')}
- 类型: {ranking_result.get('top1_strategy_type')}
- 结构: {ranking_result.get('top1_structure')}
- 期望值: {ranking_result.get('top1_ev')}
- 风险调整收益: {ranking_result.get('top1_rar')}
- 胜率: {ranking_result.get('top1_pw')}
- 剧本匹配度: {ranking_result.get('top1_scenario_match')}
- 匹配理由: {ranking_result.get('top1_match_reason')}
- 流动性通过: {ranking_result.get('top1_liquidity_pass')}
- 流动性说明: {ranking_result.get('top1_liquidity_note')}
- 综合评分: {ranking_result.get('top1_composite_score')}

【Top2 策略摘要】
- 类型: {ranking_result.get('top2_strategy_type')}
- 期望值: {ranking_result.get('top2_ev')}
- 综合评分: {ranking_result.get('top2_composite_score')}

请严格按照 JSON Schema 输出策略推荐排序。"""
            
            # 调用 LLM
            response = self.llm_client.chat_completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5,
                max_tokens=3000,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "comparison_result",
                        "schema": self._get_schema()
                    }
                }
            )
            
            logger.info(f"✅ 策略对比完成: {response.get('final_recommendation', '')}")
            
            return response
            
        except Exception as e:
            logger.error(f"❌ 策略对比失败: {e}", exc_info=True)
            raise
    
    def _build_system_prompt(self) -> str:
        """构造 System Prompt"""
        return """你是策略对比 Agent。

            【任务】基于期望值、风险调整收益、剧本匹配度、流动性等维度，给出策略推荐排序。

            ## 核心职责

            ### 1. 综合推荐判断

            基于 CODE4 的排序结果,生成推荐:

            ```
            if top1_ev <= 0:
                → "不推荐: 期望值为负"

            elif top1_liquidity_pass == false:
                → "谨慎: 存在流动性问题"

            elif top1_scenario_match == "低":
                → "观望: 剧本匹配度低"

            elif top1_composite_score >= 80:
                → "强烈推荐: 综合评分优秀"
            ```

            ### 2. 推荐理由生成

            将量化数据转化为人类语言:

            ```
            示例:
            "推荐执行【Iron Condor - 铁鹰】,
            期望值 +0.52 美元为正向,
            风险调整收益 0.18 优秀,
            区间剧本概率65%完美匹配,
            综合评分 85 分,
            强烈推荐执行。"
            ```

            ### 3. 次选策略建议

            **数据来源**: 必须从 ranking_json 解析完整数组

            ```python
            # 解析 ranking_json 字符串得到完整排序数组
            ranking = JSON.parse(ranking_json)

            # 获取第2名策略（rank=2）
            second_strategy = ranking.find(s => s.rank === 2)

            # 判断条件
            if second_strategy.metrics.ev > 0 AND second_strategy.assessment.composite_score >= 60:
                → 提供次选方案 (execution_priority.secondary):
                - strategy_type: second_strategy.strategy_type + " - " + second_strategy.structure
                - allocation: "20-30%配置"
                - rationale: 简述期望值、评分及适用场景
            else:
                → 不输出 secondary 字段（或设为 null）
            ```

            **注意**: 
            - 不能使用 top2_ev 等扁平字段，这些仅为显示用
            - 必须解析 ranking_json 获取第2名的完整 metrics 和 assessment 对象
            - 条件判断基于 ranking[1] (即rank=2的策略，因为数组索引从0开始)

            ### 4. 执行优先级

            输出清晰的行动指南,包含:
            - **primary**: 首选策略 + 配置比例 + 理由
            - **secondary**: 次选策略 + 配置比例 + 理由（可选）
            - **avoid**: 避免策略 + 原因（如有）

            ---

            ## 关键原则

            1. **数据驱动**: 所有推荐都基于 CODE4 的计算结果
            2. **简洁明了**: 将技术性描述改写为通顺、专业的中文
            3. **行动导向**: 给出明确的执行建议
            4. **禁止重新计算**: 不要尝试验证或修改 CODE4 的数值

            现在请基于输入数据进行策略对比和推荐。"""
    
    def _get_schema(self) -> Dict:
        """获取 JSON Schema"""
        return {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "comparison_summary": {
                    "type": "object",
                    "properties": {
                        "total_strategies": {"type": "integer"},
                        "recommended_count": {"type": "integer"},
                        "positive_ev_count": {"type": "integer"},
                        "analysis_timestamp": {"type": "string"}
                    }
                },
                "ranking": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rank": {"type": "integer"},
                            "strategy_type": {"type": "string"},
                            "structure": {"type": "string"},
                            "metrics": {
                                "type": "object",
                                "properties": {
                                    "ev": {"type": "number"},
                                    "rar": {"type": "number"},
                                    "pw": {"type": "number"},
                                    "rr_ratio": {"type": "string"},
                                    "max_profit": {"type": "number"},
                                    "max_loss": {"type": "number"}
                                }
                            },
                            "assessment": {
                                "type": "object",
                                "properties": {
                                    "scenario_match": {"type": "string"},
                                    "match_reason": {"type": "string"},
                                    "liquidity_pass": {"type": "boolean"},
                                    "liquidity_note": {"type": "string"},
                                    "composite_score": {"type": "integer"}
                                }
                            },
                            "recommendation": {"type": "string"},
                            "note": {"type": "string"}
                        }
                    }
                },
                "final_recommendation": {"type": "string"},
                "execution_priority": {
                    "type": "object",
                    "properties": {
                        "primary": {
                            "type": "object",
                            "properties": {
                                "strategy_type": {"type": "string"},
                                "allocation": {"type": "string"},
                                "rationale": {"type": "string"}
                            }
                        },
                        "secondary": {
                            "type": "object",
                            "properties": {
                                "strategy_type": {"type": "string"},
                                "allocation": {"type": "string"},
                                "rationale": {"type": "string"}
                            }
                        },
                        "avoid": {
                            "type": "object",
                            "properties": {
                                "strategy_type": {"type": "string"},
                                "reason": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "required": ["symbol", "comparison_summary", "ranking", "final_recommendation", "execution_priority"]
        }