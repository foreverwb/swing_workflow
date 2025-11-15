"""
Agent 6 - 策略生成器
基于剧本分析和计算辅助结果，生成三种风险等级的期权策略
"""

import json
from typing import Dict
from utils.logger import setup_logger

logger = setup_logger(__name__)


class StrategyGenerator:
    """策略生成器"""
    
    def __init__(self, llm_client, config):
        self.llm_client = llm_client
        self.config = config
        self.model = config.MODEL_STRATEGY
    
    def generate(self, validated_data: Dict, scenario_result: Dict, calc_result: Dict) -> Dict:
        """
        生成期权策略
        
        Args:
            validated_data: Agent 3 数据校验结果
            scenario_result: Agent 5 剧本分析结果
            calc_result: CODE3 策略辅助计算结果
        
        Returns:
            策略列表
        """
        try:
            logger.info(f"🤖 Agent 6: 策略生成...")
            
            # 构造 System Prompt
            system_prompt = self._build_system_prompt(calc_result)
            
            # 构造 User Prompt
            user_prompt = f"""请根据剧本分析和计算辅助结果，生成三种风险等级的期权策略。

【当前市场状态】
- 主导剧本: {scenario_result['scenario_classification']['primary_scenario']}
- 剧本概率: {scenario_result['scenario_classification']['scenario_probability']}%
- Gamma状态: {scenario_result['gamma_regime']['spot_vs_trigger']}
- 技术面评分: {validated_data.get('technical_analysis', {}).get('ta_score', 0)}/2

【关键信号】
- DEX同向: {scenario_result['directional_signals']['dex_same_dir']}%
- Vanna方向: {scenario_result['directional_signals']['vanna_dir']}({scenario_result['directional_signals']['vanna_confidence']})
- IV路径: {scenario_result['iv_dynamics']['iv_path']}({scenario_result['iv_dynamics']['iv_path_confidence']})

请严格按照系统提示中的 JSON Schema 输出三个策略方案。"""
            
            # 调用 LLM
            response = self.llm_client.chat_completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5,
                max_tokens=6000,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "strategies",
                        "schema": self._get_schema()
                    }
                }
            )
            
            strategies = response.get("strategies", [])
            logger.info(f"✅ 策略生成完成: {len(strategies)} 个方案")
            
            return response
            
        except Exception as e:
            logger.error(f"❌ 策略生成失败: {e}", exc_info=True)
            raise
    
    def _build_system_prompt(self, calc_result: Dict) -> str:
        """构造 System Prompt（包含计算结果）"""
        return f"""你是期权策略研究员与期权交易教练，负责期权策略生成 Agent。

            【任务】基于剧本分析和计算辅助结果，设计三种风险等级的期权策略。

            【输入数据】
            **计算辅助**(CODE3):
            {json.dumps(calc_result, ensure_ascii=False, indent=2)}

            ## 核心职责

            ### 1. 策略类型选择（基于推理）

            根据 Gamma 状态和主导场景选择策略：

            ```
            if Gamma状态 = "above" and 主导场景 = "区间":
                首选: Iron Condor (保守)
                备选: Iron Butterfly (保守), Bull Put Spread (均衡)

            elif Gamma状态 = "below" and 主导场景 = "趋势上行":
                首选: Bull Call Spread (均衡)
                备选: Call Ratio Spread (均衡), Long Call (进取)

            elif Gamma状态 = "below" and 主导场景 = "趋势下行":
                首选: Bear Put Spread (均衡)
                备选: Put Ratio Spread (均衡), Long Put (进取)

            elif Gamma状态 = "near":
                首选: 观望
                备选: Collar (对冲)
            ```

            ### 2. 腿部结构设计（使用计算结果）

            **可用的行权价数据**（从 CODE3 提取）：
            - 标的: {calc_result.get('meta_spot')}
            - EM1$: {calc_result.get('meta_em1')}
            - 行权价: 直接引用 calc_result['strikes'] 中的数值

            **行权价选择原则**：
            - 保守策略：Short 腿贴近墙位，Long 腿距离 Short 腿 1.0-1.5×EM1$
            - 均衡策略：Long 腿距离现价 0.2-0.5×EM1$，Short 腿靠近墙位
            - 进取策略：Long 腿距离现价 0.2×EM1$ 以内

            **每条腿必须包含 rationale**，解释：
            1. 为何选择该行权价（参考墙位/EM1$）
            2. 该腿在策略中的作用（收权利金/限制风险/方向敞口）
            3. 与 Gamma 状态/剧本的适配性

            ### 3. DTE 与 Greeks（直接引用）

            **DTE**:
            - 最终 DTE: {calc_result.get('dte_final')} 日
            - 选择理由: {calc_result.get('dte_rationale')}

            **Greeks 目标**(根据策略类型选择):
            - 保守策略: {calc_result.get('greeks_conservative_desc')}
            - 均衡策略: {calc_result.get('greeks_balanced_desc')}
            - 进取策略: {calc_result.get('greeks_aggressive_desc')}

            ### 4. RR/Pw（直接引用计算结果）

            **关键：不要重新计算，直接引用 CODE3 的数值和公式**

            例如 Iron Condor:
            ```json
            {{
            "rr_calculation": {{
                "credit": {calc_result.get('rr_ic_credit')},
                "max_profit": {calc_result.get('rr_ic_max_profit')},
                "max_loss": {calc_result.get('rr_ic_max_loss')},
                "rr_ratio": "{calc_result.get('rr_ic_ratio')}",
                "formula": "{calc_result.get('rr_ic_formula')}",
                "rr_note": "盈亏比 {calc_result.get('rr_ic_ratio')} 适合高胜率策略"
            }},
            "pw_calculation": {{
                "pw_estimate": "{calc_result.get('pw_credit_estimate')}",
                "formula": "{calc_result.get('pw_credit_formula')}",
                "pw_note": "主导场景概率支持，综合胜率可信度高"
            }}
            }}
            ```

            ### 5. 执行方案（需要你的语言能力）

            **入场触发**：
            从 Agent 5 提取关键信号：
            - Spot vs Trigger：{calc_result.get('meta_gamma_regime')}
            - 方向强度：参考 scenario_result
            - DEX同向：参考 scenario_result
            - Vanna方向：参考 scenario_result
            - IV路径：参考 scenario_result

            **描述具体入场条件**（根据策略类型调整）：
            - 保守策略：如 "Spot在[Put_Wall, Call_Wall]区间徘徊，IV未显著上升（7D ATM-IV平稳），DEX同向维持>60%"
            - 均衡策略：如 "Spot向Call_Wall方向移动但未突破，Vanna_dir=up且iv_path=升，DEX同向>65%"
            - 进取策略：如 "Spot有效突破墙位≥0.5×EM1$，成交量确认，Vanna与IV路径一致"

            **出场计划**（引用环境参数）：

            信用策略：
            - 止盈：权利金衰减至 {calc_result.get('exit_credit_profit_pct')}% 时回补
            - 止损：浮亏达最大亏损 {calc_result.get('exit_credit_stop_pct')}% 时平仓
            - 时间：到期前 {calc_result.get('exit_time_days')} 日强制平仓
            - 调整：Spot接近Short腿<0.5×EM1$时考虑roll out

            借记策略：
            - 止盈：浮盈达 {calc_result.get('exit_debit_profit_pct')}% 时先落袋50%
            - 止损：亏损达 {calc_result.get('exit_debit_stop_pct')}% 时平仓
            - 时间：到期前 {calc_result.get('exit_time_days')} 日评估展期或平仓

            **风险评估**
            综合评估策略风险：
            - "最大风险 {{RR中的max_loss}} 需严格止损"
            - "单笔风险应控制在账户总资金 2% 以内"
            - "若事件临近（如财报前5日）或IV突然扩张>20%，提前平仓"

            ---

            【输出 JSON 格式】生成三个策略对象（保守/均衡/进取），每个包含：
            - strategy_type, structure, description
            - legs (包含 rationale)
            - dte, greeks_target
            - rr_calculation, pw_calculation（直接引用计算结果）
            - entry_trigger, exit_plan, risk_note

            ## 关键注意事项

            1. **数据驱动**: 所有数值从 CODE3 引用，不要重新计算
            2. **Rationale 必须具体**: 每条腿都要解释"为何选择该行权价""在策略中的作用""与剧本的适配"
            3. **执行方案要可操作**: 入场触发条件要具体到可验证（如"DEX>60%"而非"方向明确"）
            4. **风险描述要量化**: 明确最大亏损数值、止损百分比、仓位限制
            5. **三种策略要有差异**: 保守/均衡/进取的结构、Greeks、RR/Pw都应明显不同

            ---

            现在请基于输入数据生成三种策略方案。"""
    
    def _get_schema(self) -> Dict:
        """获取 JSON Schema"""
        return {
            "type": "object",
            "properties": {
                "strategies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "strategy_type": {"type": "string"},
                            "structure": {"type": "string"},
                            "description": {"type": "string"},
                            "legs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "action": {"type": "string"},
                                        "type": {"type": "string"},
                                        "strike": {"type": "number"},
                                        "quantity": {"type": "number"},
                                        "rationale": {"type": "string"}
                                    }
                                }
                            },
                            "dte": {"type": "string"},
                            "dte_rationale": {"type": "string"},
                            "greeks_target": {
                                "type": "object",
                                "properties": {
                                    "delta": {"type": "string"},
                                    "delta_range": {"type": "string"},
                                    "theta_min": {"type": "string"},
                                    "vega_max": {"type": "string"},
                                    "vega_min": {"type": "string"}
                                }
                            },
                            "rr_calculation": {
                                "type": "object",
                                "properties": {
                                    "credit": {"type": "number"},
                                    "debit": {"type": "number"},
                                    "max_profit": {"type": "number"},
                                    "max_loss": {"type": "number"},
                                    "rr_ratio": {"type": "string"},
                                    "formula": {"type": "string"},
                                    "rr_note": {"type": "string"}
                                }
                            },
                            "pw_calculation": {
                                "type": "object",
                                "properties": {
                                    "pw_estimate": {"type": "string"},
                                    "formula": {"type": "string"},
                                    "pw_note": {"type": "string"},
                                    "pw_综合判断": {"type": "string"}
                                }
                            },
                            "entry_trigger": {"type": "string"},
                            "entry_timing": {"type": "string"},
                            "exit_plan": {
                                "type": "object",
                                "properties": {
                                    "profit_target": {"type": "string"},
                                    "stop_loss": {"type": "string"},
                                    "time_decay_exit": {"type": "string"},
                                    "adjustment": {"type": "string"}
                                }
                            },
                            "risk_note": {"type": "string"}
                        },
                        "required": ["strategy_type", "structure", "description", "legs", "dte", "greeks_target", "rr_calculation", "pw_calculation", "entry_trigger", "exit_plan", "risk_note"]
                    }
                }
            },
            "required": ["strategies"]
        }