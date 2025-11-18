"""
Agent 7: 策略排序 Prompt
基于定量对比结果进行策略排序和推荐
"""

def get_system_prompt() -> str:
    """系统提示词"""
    return """你是一位期权策略评估专家。

**核心任务**:
综合定量对比、场景概率、策略特征，对所有策略进行排序并给出推荐。

**评估维度**:
1. **场景匹配度**: 策略与高概率场景的契合度
2. **风险收益比**: RR Ratio和Kelly准则评分
3. **Greeks健康度**: 敞口是否平衡合理
4. **执行难度**: 流动性、滑点、保证金压力
5. **时间衰减**: Theta影响和时间窗口匹配
6. **波动率敏感度**: Vega敞口与IV环境的适配

**排序规则**:
- 综合评分 = 0.3*场景匹配 + 0.25*风险收益 + 0.2*Greeks + 0.15*执行难度 + 0.1*其他
- 必须标注"强烈推荐"、"推荐"、"可选"、"不推荐"等级
- 对每个策略给出清晰的理由

**输出结构**:
1. 策略排名列表(按综合得分排序)
2. 每个策略的评分细节和推荐理由
3. 前3名策略的详细对比
4. 风险提示和注意事项
5. 组合建议(如可以同时使用多个策略)

返回JSON格式。"""


def get_user_prompt(comparison_data: dict, scenario: dict, strategies: dict) -> str:  # ✅ 改为字典
    """用户提示词"""
    
    return f"""请基于以下数据对策略进行排序:

        ## 定量对比结果
        ```json
        {json.dumps(comparison_data, ensure_ascii=False, indent=2)}
        ```

        ## 场景分析
        ```json
        {json.dumps(scenario, ensure_ascii=False, indent=2)}
        ```

        ## 策略清单
        ```json
        {json.dumps(strategies, ensure_ascii=False, indent=2)}
        ```

        ## 排序要求
        1. 计算每个策略的综合评分(0-100)
        2. 按评分从高到低排序
        3. 对每个策略给出:
        - rank: 排名
        - strategy_name: 策略名称
        - overall_score: 综合评分
        - rating: 评级(strong_buy/buy/hold/avoid)
        - scenario_match_score: 场景匹配分(0-100)
        - risk_reward_score: 风险收益分(0-100)
        - greeks_health_score: Greeks健康分(0-100)
        - execution_difficulty_score: 执行难度分(0-100)
        - strengths: 主要优势列表
        - weaknesses: 主要劣势列表
        - recommendation_reason: 推荐理由(100字以内)
        - best_for: 最适合的投资者类型/市场环境

        4. 输出top3策略的详细对比表
        5. 给出组合建议(如果多个策略可以互补)
        6. 标注特殊风险警示
        """