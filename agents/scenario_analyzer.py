"""
Agent 5 - 剧本分析
基于四维评分推演市场剧本，评估场景概率
"""

import json
from typing import Dict
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ScenarioAnalyzer:
    """剧本分析器"""
    
    def __init__(self, llm_client, config):
        self.llm_client = llm_client
        self.config = config
        self.model = config.MODEL_SCENARIO
    
    def analyze(self, scoring_result: Dict) -> Dict:
        """
        分析市场剧本
        
        Args:
            scoring_result: CODE2 四维评分结果
        
        Returns:
            剧本分析结果
        """
        try:
            logger.info(f"🤖 Agent 5: 市场剧本分析...")
            
            # 构造 System Prompt
            system_prompt = self._build_system_prompt()
            
            # 构造 User Prompt
            user_prompt = f"""请整合数据,进行剧本推演与评分。

【评分结果】
{json.dumps(scoring_result, ensure_ascii=False, indent=2)}

请严格按照 JSON Schema 输出剧本分析结果。"""
            
            # 调用 LLM
            response = self.llm_client.chat_completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5,
                max_tokens=4000,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "scenario_analysis",
                        "schema": self._get_schema()
                    }
                }
            )
            
            scenario = response.get("scenario_classification", {})
            logger.info(f"✅ 剧本分析完成: {scenario.get('primary_scenario', '')} ({scenario.get('scenario_probability', 0)}%)")
            
            return response
            
        except Exception as e:
            logger.error(f"❌ 剧本分析失败: {e}", exc_info=True)
            raise
    
    def _build_system_prompt(self) -> str:
        """构造 System Prompt"""
        return """你是期权量化分析师与期权交易教练，负责期权策略生成 Agent。

            【任务】 基于剧本分析和计算辅助结果，设计三种风险等级的期权策略。

            【输入数据】
            **评分结果**(来自 CODE2 四维评分):
            - gamma_regime: Gamma状态判定
            - break_wall_assessment: 破墙可能性
            - directional_signals: 方向一致性
            - iv_dynamics: IV动态
            - scoring: 四维评分
            - entry_threshold_check: 入场判定
            - key_levels: 关键位
            - risk_warning: 风险警告

            ## 核心职责

            ### 1. 综合推荐判断

            基于 CODE2 的排序结果,生成推荐:

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

            ### 3. 剧本分类与概率评估

            **剧本决策树**:
            ```
            if gamma_regime.spot_vs_trigger == "above":
                base_scenario = "区间震荡"
                if break_wall.gap_distance_em1 < 1.5 and cluster_strength > 2.0:
                    → "强区间震荡" (70-80%)
                elif direction_score >= 7:
                    → "区间震荡偏向上" (60-70%)
                else:
                    → "区间震荡" (55-65%)

            elif gamma_regime.spot_vs_trigger == "below":
                base_scenario = "趋势行情"
                if direction_score >= 8 and dex_same_dir > 70:
                    → "强趋势上行/下行" (65-75%)
                elif direction_score >= 6:
                    → "趋势上行/下行" (55-65%)
                else:
                    → "弱趋势" (50-60%)

            elif gamma_regime.spot_vs_trigger == "near":
                base_scenario = "临界状态"
                → "Gamma翻转临近" (45-55%)
            ```

            **次级剧本**: 基于 scoring 的其他维度给出 1-2 个次要可能性

            **adjustment_note**: 解释剧本调整的原因（如技术面加分、IV路径影响等）

            ### 4. 入场理由

            结合 CODE2 的 entry_threshold_check 和条件满足情况:

            ```
            if entry_check == "入场":
                rationale = f"总分{total_score}≥{threshold}满足,关键信号:{met_count}/{total_conditions}个条件满足"
                + 满足条件详情
                + 不满足条件详情

            elif entry_check == "轻仓试探":
                rationale = "总分满足但信号不足,建议轻仓"

            else:
                rationale = "总分或条件不足,建议观望"
            ```

            ## 关键原则

            1. **数据驱动**: 所有推荐都基于 CODE2 的计算结果
            2. **简洁明了**: 将技术性描述改写为通顺、专业的中文
            3. **行动导向**: 给出明确的执行建议
            4. **风险透明**: 清晰说明每个策略的风险点
            5. **禁止重新计算**: 不要尝试验证或修改 CODE2 的数值

            现在请基于输入数据进行剧本推演与评分。"""
    
    def _get_schema(self) -> Dict:
        """获取 JSON Schema"""
        return {
            "type": "object",
            "properties": {
                "gamma_regime": {
                    "type": "object",
                    "properties": {
                        "vol_trigger": {"type": "number"},
                        "spot_vs_trigger": {
                            "type": "string",
                            "enum": ["above", "below", "near"]
                        },
                        "regime_note": {"type": "string"}
                    },
                    "required": ["vol_trigger", "spot_vs_trigger", "regime_note"]
                },
                "break_wall_assessment": {
                    "type": "object",
                    "properties": {
                        "gap_distance_em1": {"type": "number"},
                        "cluster_strength": {"type": "number"},
                        "break_probability": {"type": "string"},
                        "break_note": {"type": "string"}
                    }
                },
                "directional_signals": {
                    "type": "object",
                    "properties": {
                        "dex_same_dir": {"type": "number"},
                        "vanna_dir": {"type": "string"},
                        "vanna_confidence": {"type": "string"},
                        "direction_strength": {"type": "string"},
                        "direction_note": {"type": "string"}
                    }
                },
                "iv_dynamics": {
                    "type": "object",
                    "properties": {
                        "iv_path": {"type": "string"},
                        "iv_path_confidence": {"type": "string"},
                        "iv_signal": {"type": "string"},
                        "iv_note": {"type": "string"}
                    }
                },
                "scoring": {
                    "type": "object",
                    "properties": {
                        "gamma_regime_score": {"type": "number"},
                        "break_wall_score": {"type": "number"},
                        "direction_score": {"type": "number"},
                        "iv_score": {"type": "number"},
                        "total_score": {"type": "number"},
                        "weight_breakdown": {"type": "string"}
                    }
                },
                "scenario_classification": {
                    "type": "object",
                    "properties": {
                        "primary_scenario": {"type": "string"},
                        "scenario_probability": {"type": "integer"},
                        "secondary_scenarios": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "probability": {"type": "integer"}
                                }
                            }
                        },
                        "adjustment_note": {"type": "string"}
                    }
                },
                "key_levels": {
                    "type": "object",
                    "properties": {
                        "support": {"type": "number"},
                        "resistance": {"type": "number"},
                        "trigger_line": {"type": "number"},
                        "current_spot": {"type": "number"}
                    }
                },
                "entry_threshold_check": {
                    "type": "string",
                    "enum": ["入场", "轻仓试探", "观望"]
                },
                "entry_rationale": {"type": "string"},
                "risk_warning": {"type": "string"}
            },
            "required": ["gamma_regime", "scoring", "scenario_classification", "entry_threshold_check"]
        }