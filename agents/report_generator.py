"""
报告生成 Agent - Agent 8
汇总所有分析结果,生成完整 Markdown 报告
"""

from typing import Dict
from datetime import datetime
from models.llm_client import LLMClient
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ReportGeneratorAgent:
    """
    Agent 8: 最终报告生成
    汇总所有分析,生成易读的 Markdown 报告 (含事件风险)
    """
    
    def __init__(self, config):
        self.config = config
        self.llm_client = LLMClient(config)
        self.model = config.MODEL_REPORT
        
        # ✅ System Prompt (从 yml node 7001 提取)
        self.system_prompt = """
            你是最终报告生成 Agent,负责汇总所有分析结果,生成易读的 Markdown 报告。

            【任务】 汇总所有分析,生成单标的完整报告(含事件风险)。

            【输入数据源】
            - 数据校验: Agent 3
            - 剧本分析: Agent 5
            - 策略推荐: Agent 7
            - 事件检测: CODE1

            【技术面处理规则】
            技术面数据已整合到 Agent 3 中:
            - 若存在: 从 technical_analysis 提取
            - 若缺失: 报告中标注 "技术面数据缺失,仅影响评分"

            【输出模板】
            生成简洁的 Markdown 报告,遵循以下结构:

            # 美股期权分析报告

            **标的**: {symbol} | **现价**: {spot} | **EM1$**: {em1}
            **分析时间**: {timestamp} | **风险等级**: {event_risk_level} {🟢/🟡/🔴}

            ## 0. 事件风险评估 ⚠️

            **检测日期**: {detection_date}
            **风险等级**: {risk_level}

            {若无事件}
            ✅ 未检测到近期重大事件,可正常执行策略

            {若有事件,输出表格}
            | 事件类型 | 日期 | 距离 | 影响 | 说明 |
            |---------|------|------|------|------|
            | {type} | {date} | {days_away}日 | {impact} | {note} |

            ### 策略调整建议
            - **禁止跨期**: {no_cross_earnings ? "🚫 是" : "✅ 否"}
            {若是: 财报或重大事件临近,建议DTE≤{max_dte}日或等待事件后}
            - **缩短DTE**: {adjust_dte ? "⚠️ 是" : "✅ 否"}
            {若是: OPEX临近,建议DTE≤{max_dte}日}
            - **减仓操作**: {reduce_position ? "⚠️ 是" : "✅ 否"}
            {若是: FOMC临近,建议半仓或观望}

            ---

            ## 1. 综合结论

            **总评分**: {total_score}/10
            **入场判定**: {entry_check} → {入场理由简述,100字}

            **评分构成**:
            - Gamma状态: {gamma_score}/10 ({regime_note简化})
            - 破墙可能: {break_wall_score}/10 ({break_note简化})
            - 方向一致: {direction_score}/10 ({direction_note简化})
            - IV动态: {iv_score}/10 ({iv_note简化})

            **主导剧本**: {primary_scenario} (概率{probability}%)
            {adjustment_note}

            ---

            ## 2. 策略推荐

            ### 排序总览
            | 排名 | 策略 | 期望值 | 风险调整收益 | 剧本匹配 | 流动性 | 推荐等级 |
            |------|------|--------|--------------|----------|--------|----------|
            | 1 | {type} | {ev} | {rar} | {match} | {pass} | {level} |
            | 2 | {type} | {ev} | {rar} | {match} | {pass} | {level} |
            | 3 | {type} | {ev} | {rar} | {match} | {pass} | {level} |

            **最终推荐**: {final_recommendation}

            ### 首选策略详述

            **策略**: {primary_strategy_type} - {structure}
            **配置**: {allocation}
            **理由**: {rationale简化,150字}

            **量化指标**:
            - 盈亏比: {rr_ratio} | 胜率: {pw}%
            - 期望值: {ev} | 风险调整收益: {rar}
            - 最大盈利: {max_profit} | 最大亏损: {max_loss}

            **执行要点**:
            - 入场: {entry_trigger简化}
            - 止盈: {profit_target}
            - 止损: {stop_loss}
            - 时间: {time_exit}

            ---

            ## 3. 监控要点

            **关键位**:
            - 支撑: {put_wall} | 阻力: {call_wall}
            - 触发线: {vol_trigger} | 现价: {spot}

            **实时关注**:
            {根据首选策略类型调整}
            - {若保守(信用价差/铁鹰)}: 墙位稳定性、零γ漂移≤0.3×EM1、Theta收益累积、IV压缩
            - {若均衡(借记竖式/日历)}: 方向确认、DEX同向累积>60%分位、Vanna支持、gap缩小
            - {若进取(单腿/窄跨debit)}: 有效破墙且离墙≥0.5×EM1、空缺支持、Vanna+IV路径共振、指数一致

            **止损触发** (立即平仓条件):
            - Spot穿越VOL_TRIGGER (Gamma regime反转)
            - 达到策略止损点
            - gap_distance<0.5×EM1 (接近墙位)
            - vanna_dir反转
            - dex_same_dir<40%

            ---

            ## 4. 核心数据 (详细)

            ```
            标的: {symbol}
            Spot: {spot} | EM1$: {em1}

            Gamma状态:
            - VOL_TRIGGER: {vol_trigger}
            - 现价位置: {spot_vs_trigger}
            - NET-GEX: {net_gex} ({sign})

            墙位:
            - Call Wall: {call_wall}
            - Put Wall: {put_wall}
            - Major Wall: {major_wall} ({type})

            空缺与方向:
            - gap距离: {gap_distance}$ ({gap_em1}×EM1$)
            - 簇强度: {cluster_strength}
            - 月度占优: {monthly_override}
            - DEX同向: {dex_same_dir}%
            - Vanna方向: {vanna_dir} ({confidence})
            - IV路径: {iv_path} ({iv_confidence})

            波动率:
            - ATM IV 7D: {iv_7d}
            - ATM IV 14D: {iv_14d}
            - IV数据源: {iv_source}

            指数背景:
            - SPX NET-GEX: {spx_net_gex}
            - SPX EM1$: {spx_em1}
            ```

            **数据质量**: 完整度{completion_rate}% | 缺失{missing_count}项

            ---

            **报告生成**: {当前时间}
            **下次更新**: 盘前或关键数据变化时
            """
    
    def generate(self, 
                 data_validation: Dict,
                 scenario_analysis: Dict,
                 comparison: Dict,
                 event_detection: Dict) -> str:
        """
        生成完整报告
        
        Args:
            data_validation: Agent 3 数据校验结果
            scenario_analysis: Agent 5 剧本分析结果
            comparison: Agent 7 策略对比结果
            event_detection: CODE1 事件检测结果
        
        Returns:
            Markdown 格式报告文本
        """
        logger.info("开始生成最终报告")
        
        # 构造输入数据汇总
        input_data = {
            "data_validation": data_validation,
            "scenario_analysis": scenario_analysis,
            "comparison": comparison,
            "event_detection": event_detection
        }
        
        # 格式化为 JSON 字符串供 LLM 处理
        import json
        input_json = json.dumps(input_data, ensure_ascii=False, indent=2)
        
        # 构造消息
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user", 
                "content": f"请汇总所有分析,生成最终报告。\n\n{input_json}\n\n请严格按照系统提示中的模板输出 Markdown 格式报告。\n仅输出报告内容,不要添加任何前置说明或后置总结。"
            }
        ]
        
        # 调用 LLM (不使用 Structured Output,直接生成 Markdown)
        try:
            response = self.llm_client.chat_completion(
                model=self.model,
                messages=messages,
                temperature=0.5,
                max_tokens=self.config.MODEL_MAX_TOKENS
            )
            
            # 提取文本内容
            if isinstance(response, dict) and "choices" in response:
                report_text = response["choices"][0]["message"]["content"]
            elif isinstance(response, str):
                report_text = response
            else:
                report_text = str(response)
            
            logger.info("报告生成完成")
            return report_text
            
        except Exception as e:
            logger.error(f"报告生成失败: {e}", exc_info=True)
            # 返回错误报告
            return self._generate_error_report(str(e), input_data)
    
    def _generate_error_report(self, error_msg: str, input_data: Dict) -> str:
        """生成错误报告"""
        symbol = "UNKNOWN"
        try:
            # 尝试提取 symbol
            if "data_validation" in input_data:
                targets = input_data["data_validation"].get("targets", {})
                if isinstance(targets, dict):
                    symbol = targets.get("symbol", "UNKNOWN")
                elif isinstance(targets, list) and targets:
                    symbol = targets[0].get("symbol", "UNKNOWN")
        except:
            pass
        
        return f"""# 美股期权分析报告
                **标的**: {symbol}
                **分析时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                **状态**: ⚠️ 报告生成失败
                ## 错误信息
                ```
                {error_msg}
                ```
                ## 原始数据
                ```json
                {json.dumps(input_data, ensure_ascii=False, indent=2)[:1000]}...
                ```
                请检查数据完整性后重试。
            """