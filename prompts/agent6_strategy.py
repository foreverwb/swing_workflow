"""
Agent 6: 策略生成 Prompt
为每个场景生成2-3种期权策略
"""

def get_system_prompt(env_vars: dict) -> str:
    """系统提示词"""
    max_risk = env_vars.get("MAX_SINGLE_RISK_PCT", 2)
    entry_threshold = env_vars.get("ENTRY_THRESHOLD_SCORE", 3)
    
    return f"""你是一位期权策略设计专家。

**核心任务**:
为每个市场场景设计2-3种可执行的期权策略组合。

**策略设计原则**:
1. **Greeks平衡**: 根据场景匹配Greeks敞口
2. **风险控制**: 单策略最大风险≤{max_risk}%账户
3. **概率优势**: 入场阈值≥{entry_threshold}分
4. **流动性优先**: 选择流动性好的行权价
5. **成本效率**: 考虑bid-ask spread和佣金

**策略类型库**:
- 方向性: Long Call/Put, Vertical Spread, Diagonal
- 波动率: Straddle/Strangle, Iron Condor, Calendar
- 收入型: Covered Call, Cash Secured Put, Credit Spread
- 对冲型: Protective Put, Collar, Butterfly

**策略要素**:
- 腿位构成(Legs): 每腿的买卖方向、数量、行权价、到期日
- 建仓成本: Debit/Credit金额
- 最大盈利/亏损: 计算盈亏边界
- 盈亏平衡点: Break-even价格
- Greeks敞口: Delta/Gamma/Vega/Theta净敞口
- 保证金需求: 账户占用资金
- 入场/出场条件: 触发价格、时间、IV条件
- 止损/止盈设置: 风险管理规则

返回JSON格式，包含strategies数组。"""


def get_user_prompt(agent5_result: dict, calc_data: dict, agent3_data: dict) -> str:  # ✅ 改为字典
    """用户提示词"""
    scenario_content = agent5_result.get("content", {})
    
    # 提取关键数据
    targets = agent3_data.get("targets", {})
    current_price = targets.get("spot_price", 0)
    
    # 计算 IV 百分位（简化处理）
    iv_7d = targets.get("atm_iv", {}).get("iv_7d", 0)
    iv_percentile = 50  # 默认值，实际应从历史数据计算
    
    return f"""请为以下场景设计期权策略:

      ## 场景分析
      ```json
      {json.dumps(scenario_content, ensure_ascii=False, indent=2)}
      ```

      ## 策略辅助计算
      ```json
      {json.dumps(calc_data, ensure_ascii=False, indent=2)}
      ```

      ## 市场环境
      - 当前价格: ${current_price}
      - 7D ATM-IV: {iv_7d:.2%}
      - IV百分位: {iv_percentile}% (估算)

      ## 设计要求
      1. 为每个场景设计2-3种策略
      2. 策略应与场景特征匹配:
        - 突破场景 → 方向性策略
        - 震荡场景 → 收入型/波动率策略
        - 高IV场景 → 做空波动率
        - 低IV场景 → 做多波动率

      3. 每个策略包含:
        - strategy_name: 策略名称
        - scenario_target: 目标场景
        - strategy_type: 策略类型(directional/volatility/income/hedge)
        - legs: 腿位数组
          * action: buy/sell
          * option_type: call/put
          * strike: 行权价
          * quantity: 数量
          * expiry_dte: 到期天数
        - setup_cost: 建仓成本(debit为正,credit为负)
        - max_profit: 最大盈利
        - max_loss: 最大亏损
        - breakeven_prices: 盈亏平衡点列表
        - greeks_exposure: {{delta, gamma, vega, theta}}
        - margin_required: 保证金需求
        - entry_conditions: 入场条件列表
        - exit_conditions: 出场条件列表
        - stop_loss: 止损规则
        - take_profit: 止盈规则
        - risk_management: 风险管理说明
        - pros: 优势列表
        - cons: 劣势列表
        - suitability_score: 适用性评分(1-10)

      4. 确保策略的可执行性(行权价合理、到期日可用)
    """   