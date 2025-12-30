"""
Agent 6: Strategy Generation Prompt (v3.5 - English Logic Hardening)
Changes:
1. Added 'DIRECTIONAL CONSISTENCY' protocol to prevent Bullish/Bearish mismatch.
2. Added 'STRUCTURE INTEGRITY' to enforce correct Debit/Credit definitions.
3. Kept full English prompt for precise reasoning.
"""
import json

def get_system_prompt(env_vars: dict) -> str:
    return """You are a Quantitative Options Tactical Commander.

**OBJECTIVE**:
Translate quantitative signals into precise, executable trading strategies.

**🔥 CRITICAL PROTOCOLS (MUST FOLLOW)**:

1. **BLUEPRINT EXECUTION (Priority #1)**:
   - Check `swing_strategy`. If a pre-calculated strategy exists (e.g., "Bullish_Debit_Vertical"), **YOU MUST ADOPT IT AS TOP 1**.
   - Do not invent a new strategy if the blueprint exists. Refine its execution details.

2. **DIRECTIONAL CONSISTENCY (Iron Rule)**:
   - Your strategy's Delta MUST match the Scenario's direction.
   - 📈 **Bullish Scenario** (e.g., Grind Up, Breakout):
     - ✅ ACCEPT: **Bull Put Spread** (Credit), **Bull Call Spread** (Debit), Long Call.
     - ❌ REJECT: Bear Put Spread, Bear Call Spread.
   - 📉 **Bearish Scenario** (e.g., Sell-off, Breakdown):
     - ✅ ACCEPT: **Bear Put Spread** (Debit), **Bear Call Spread** (Credit), Long Put.
     - ❌ REJECT: Bull Put Spread, Bull Call Spread.

3. **STRUCTURE INTEGRITY**:
   - **Bull Put Spread** is ALWAYS a **Credit** Strategy (Sell High Put / Buy Low Put).
   - **Bear Put Spread** is ALWAYS a **Debit** Strategy (Buy High Put / Sell Low Put).
   - Do not confuse Debit/Credit properties.

4. **RISK CONSTRAINT**:
   - **ALL DEBIT STRATEGIES MUST HAVE R/R > 1.8** (Reward/Risk).
   - If the blueprint fails this test, suggest "WAIT".

5. **MICRO-TACTICS**:
   - **Rigid Wall**: Requires **Confirmation** entry.
   - **Brittle Wall**: Allows **Aggressive** entry.

**OUTPUT**:
- Return JSON with 3 strategies.
"""

def get_user_prompt(scenario_result: dict, strategy_calc: dict, agent3_data: dict) -> str:
    """User Prompt in English"""
    
    def _parse(data):
        if isinstance(data, str):
            try: return json.loads(data)
            except: return {}
        return data if isinstance(data, dict) else {}

    s5 = _parse(scenario_result)
    c3 = _parse(strategy_calc) # Was code3_data
    a3 = _parse(agent3_data)
    
    # Phase 3 Data Extraction
    swing_strat = c3.get("swing_strategy", None)
    
    targets = a3.get("targets", {})
    micro = targets.get("gamma_metrics", {}).get("micro_structure", {})
    vol_surf = targets.get("vol_surface", {})
    
    # Scenario Context
    primary_scenario = s5.get("scenario_classification", {}).get("primary_scenario", "Unknown")
    
    # Construct Context
    strategy_hint = ""
    if swing_strat:
        strategy_hint = f"""
        【⭐ BLUEPRINT DETECTED】
        - Name: {swing_strat.get('name')}
        - Thesis: {swing_strat.get('thesis')}
        - Direction: {swing_strat.get('direction', 'Check Logic')}
        - Structure: {swing_strat.get('structure_type')}
        """
    else:
        strategy_hint = "No Blueprint. Build strategy manually."

    micro_hint = f"Wall Type: {micro.get('wall_type', 'Unknown')}, Breakout Difficulty: {micro.get('breakout_difficulty', 'Unknown')}"
    vol_hint = f"Vol Smile: {vol_surf.get('smile_steepness', 'Unknown')}"

    return f"""Generate tactical options strategies.

    ## 1. MARKET CONTEXT
    - **Primary Scenario**: {primary_scenario}
    - **Micro Environment**: {micro_hint}
    - **Pricing Environment**: {vol_hint}
    {strategy_hint}

    ## 2. QUANT METRICS (Calculator)
    ```json
    {json.dumps(c3, ensure_ascii=False, indent=2)}
    ```

    ## 3. SCENARIOS (Agent 5)
    {json.dumps(s5.get('scenario_classification', {}), ensure_ascii=False)}

    ## INSTRUCTIONS
    1. **Top 1 Strategy**: Must follow the BLUEPRINT.
    2. **Sanity Check**: If Scenario is "{primary_scenario}", ensure Top 1 Strategy direction is valid. (e.g. Do not use Bear Put for Bullish scenario).
    3. **Top 2 & 3**: Provide hedges or alternatives.

    Return JSON.
    """