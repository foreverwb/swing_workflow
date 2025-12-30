"""
Agent 8: 最终报告 Prompt (v3.5 - Verdict & Monitor)
变更:
1. [新增] 交易决策面板 (Verdict) - 位于报告最顶端
2. [新增] 动态监控看板 (Live Monitoring)
3. [增强] 策略描述逻辑，确保正确转述 Agent 6 的意图
"""

def get_system_prompt() -> str:
    """系统提示词"""
    return """你是一位精通微观结构物理学与实战风控的期权交易总监。

**核心任务**:
生成一份**"实战导向"**的交易指令书。报告必须逻辑严密，数据详实。

**报告结构规范**:

# ${SYMBOL} 结构化交易分析报告

## 🚦 交易决策面板 (Tactical Verdict)
> *这是交易的最终闸门 (Gatekeeper)，必须置于报告最顶端。*
- **决策指令**: [强力入场 (Aggressive) / 轻仓试探 (Probe) / 等待确认 (Wait for Setup) / 观望 (Abstain)]
- **决策逻辑**:
  1. **数据熔断**: 检查 Price 是否为 0 或关键数据 N/A。若有，指令必须为 **"观望 (Abstain) - 数据异常"**。
  2. **物理属性**: **Rigid Wall** -> 倾向 "轻仓/等待"; **Brittle Wall** -> 倾向 "强力入场"。
  3. **量化评分**: 若 Top 1 得分 < 40 -> "观望"。
- **仓位建议**: (例如: "建议 1/2 仓位起步...")

## 📡 动态监控看板 (Live Monitoring)
> *指导持仓期间的导航。*
- **结构漂移**: 警惕 Wall ($XXX) 下移? Zero Gamma ($XXX) 上行?
- **微观失效**: 若墙体由 Brittle 转 Rigid (ECR升高)，提示止盈。
- **波动率**: 监控 IV [Rising/Falling] 是否符合预期。

## 🎯 执行摘要
...

## 🔬 微观结构与定价
> *利用 ECR/SER 进行物理推演*
- **墙体物理**: [Rigid/Brittle] (ECR: X.XX) -> 推演 "能不能穿?"
- **接力能力**: [High/Low] (SER: X.XX) -> 推演 "穿了能不能跑?"
- **结构映射**: 映射到 Nearby Peak ($XXX) 和 Secondary Peak ($XXX)。

## 🔮 场景推演
...

## 💡 策略推荐 (Strategy Deck)
> *基于 Agent 6 生成的详细战术*
> **注意**: 在描述策略时，请简要解释为什么该策略（如 Bull Put）匹配当前场景（如 Grind Up）。

### ⭐ Top 1: [策略名]
- **蓝图来源**: [source_blueprint]
...

## ⚖️ 策略量化对比
...

## ⚠️ 风险雷达
...
"""


def get_user_prompt(agent3: dict, agent5: dict, agent6: dict, code4: dict, event: dict) -> str:
    """用户提示词"""
    import json
    
    def _clean_and_parse(data):
        if isinstance(data, str):
            try: return json.loads(data)
            except: return {}
        if not isinstance(data, dict): return {}
        # 自动解包 raw 字段
        if "raw" in data and len(data.keys()) <= 2:
            raw_content = data["raw"]
            if isinstance(raw_content, str):
                try:
                    clean = raw_content.strip()
                    if clean.startswith("```json"): clean = clean[7:]
                    elif clean.startswith("```"): clean = clean[3:]
                    if clean.endswith("```"): clean = clean[:-3]
                    return json.loads(clean.strip())
                except: pass
        return data
    
    a3 = _clean_and_parse(agent3)
    a5 = _clean_and_parse(agent5)
    a6 = _clean_and_parse(agent6)
    c4 = _clean_and_parse(code4)
    evt = _clean_and_parse(event)
    
    symbol = a3.get("symbol", "UNKNOWN")
    
    # 优先从 targets 获取价格
    current_price = a3.get("targets", {}).get("spot_price")
    if not current_price:
        current_price = a3.get("market_data", {}).get("current_price", 0)
    
    # 提取核心情报
    targets = a3.get("targets", {})
    gamma_metrics = targets.get("gamma_metrics", {})
    micro = gamma_metrics.get("micro_structure", {})
    peaks = gamma_metrics.get("structural_peaks", {})
    walls = targets.get("walls", {})
    anchors = targets.get("sentiment_anchors", {})
    vol_surf = targets.get("vol_surface", {})
    
    # 构造微观上下文
    micro_context = {
        "physics": micro,
        "locations": {
            "nearby_peak": peaks.get("nearby_peak"),
            "secondary_peak": peaks.get("secondary_peak"),
            "call_wall": walls.get("call_wall"),
            "put_wall": walls.get("put_wall")
        }
    }
    
    return f"""请生成实战交易指令书。

## 标的信息
- Symbol: {symbol}
- Price: ${current_price}

## 核心情报 (Phase 3 Physics)
- **微观全景**: {json.dumps(micro_context, ensure_ascii=False)}
- **情绪锚点**: {json.dumps(anchors, ensure_ascii=False)}
- **波动率曲面**: {json.dumps(vol_surf, ensure_ascii=False)}

## 场景推演 (Agent 5)
```json
{json.dumps(a5, ensure_ascii=False, indent=2)}

## 策略详情 (Agent 6)
{json.dumps(a6, ensure_ascii=False, indent=2)}

## 策略评分对比 (Code 4)
{json.dumps(c4, ensure_ascii=False, indent=2)}

## 事件风险
{json.dumps(evt, ensure_ascii=False)}

请严格遵守以下 4 条指令 (Checklist):

[位置]: 必须将 交易决策面板 置于报告最顶端。

[风控]: 若 Price 为 0，必须在面板触发 "Abstain"。

[逻辑]: 检查 Agent 6 的策略方向是否正确，并在报告中清晰阐述。

[推演]: 在“微观结构”章节，必须清晰阐述 ECR（钉住风险）和 SER（接力能力）是如何影响当前具体的 Nearby Peak 和 Secondary Peak 的，禁止只列数字。
"""