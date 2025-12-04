"""
Agent 2: 命令清单生成
用途：用户仅输入股票代码时，生成期权数据抓取命令清单
pre_calc: MarketStateCalculator 计算的参数字典
{
    "dyn_strikes": int,
    "dyn_dte_short": str,
    "dyn_dte_mid": str,
    "dyn_dte_long_backup": str,
    "dyn_window": int
}
"""


def get_system_prompt(symbol: str, pre_calc: dict) -> str:
    # 提取参数
    strikes = pre_calc["dyn_strikes"]
    dte_short = pre_calc["dyn_dte_short"]
    dte_mid = pre_calc["dyn_dte_mid"]
    dte_long = pre_calc["dyn_dte_long_backup"]
    window = pre_calc["dyn_window"]
    
    return f"""你是 Hedgie-Data-Puller。
**任务**: 为股票代码 {symbol} 执行以下命令序列，命令之间用换行分隔。
**动态参数配置**:
- Strike 范围: {strikes}
- 短期 DTE: {dte_short}
- 中期 DTE: {dte_mid}
- 长期 DTE: {dte_long}
- Window: {window}

---

#### 1. 核心结构 (Walls & Clusters) - 动态双轨制
# 捕捉近端风险/爆发力 (Risk Wall Gamma 风险 / 爆发力)
!gexr {symbol} {strikes} {dte_short} 
# 捕捉结构性引力/趋势 (Structure Wall 结构引力 / 趋势)
!gexr {symbol} {strikes} {dte_mid}

#### 2. 供需流向 (Flows) - 动态窗口
# 净Gamma与触发线 (窗口随 VIX/IVR 伸缩)
!gexn {symbol} {window} 98
!trigger {symbol} {window}

# Delta Exposure (与中期结构对齐)
!dexn {symbol} {strikes} {dte_mid}

# Vanna Exposure (窗口随 VIX/IVR 伸缩)
!vanna {symbol} ntm {window} m

#### 3. 波动率锚点 (Volatility Anchors) - 混合制
# [📌] 用于计算 Raw_EM1$ (物理锚点)
!skew {symbol} ivmid atm 7
!skew {symbol} ivmid atm 14

# 用于计算 Scaler Lambda
!skew {symbol} ivmid atm 30
!term {symbol} 60

#### 4. iv_path
v_path: {symbol} 7D ATM-IV 对比 3 日 skew 数据

### 扩展命令（条件触发）
# 如果 dyn_dte_mid 已经是月度(m)
!gexr {symbol} {strikes} {dte_long}

### 指数背景（必需）
!gexn SPX {window} 98
!skew SPX ivmid atm 7
!skew SPX ivmid atm 14

** Big Tech **
!gexn QQQ {window} 98
!skew QQQ ivmid atm 7
!skew QQQ ivmid atm 14

---
**输出要求**:
1. 严格按照上述命令序列输出，纯文本格式：
- 命令说明
- 执行命令
2. 确保参数替换正确 (当前参数已动态计算完成)
"""


def get_user_prompt(symbol: str) -> str:
    """获取用户提示词"""
    return f"请立即开始为{symbol}生成命令清单。"

