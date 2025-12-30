"""
Agent 5: Scenario Analysis Prompt (v3.1 - English/Phase 3)
Changes:
1. Full English prompt for better logic adherence.
2. deeply integrated 'Rigid/Brittle' wall physics.
3. Max Pain gravity logic for Range scenarios.
"""
import json

def get_system_prompt() -> str:
    return """You are an expert Options Strategist specializing in Market Structure and Volatility Surfaces.

**OBJECTIVE**:
Deduce 3-5 high-probability market scenarios based on multi-dimensional quantitative data.

**PHASE 3 REASONING FRAMEWORK**:

1. **MICRO-PHYSICS CHECK (Crucial)**:
   - Analyze `micro_structure` metrics:
     - **Rigid Wall**: High ECR (Concentration). Price is likely to be **Rejected** or **Pinned**. *Thesis: Range/Rejection.*
     - **Brittle Wall**: Low ECR (Dispersion). Price is likely to **Break Through** on momentum. *Thesis: Breakout/Trend.*
   - Analyze `sustain_potential`:
     - If Low: High risk of **False Breakout**.

2. **STRUCTURE RESONANCE**:
   - Compare Weekly Wall vs. Monthly Wall.
   - If Aligned + Gap exists -> **Resonance** (Strong Trend).
   - If Blocked -> **Friction** (Wait for confirmation).

3. **VOLATILITY CORRECTION**:
   - **Steep Smile**: OTM options are expensive. Short Vega strategies (like Naked Condors) are risky; Ratio Spreads are preferred.
   - **Max Pain**: In 'Range'/'Grind' scenarios, price tends to gravitate towards Max Pain.

**OUTPUT REQUIREMENTS**:
- Use specific terms: "Rigid Wall", "Gamma Pinning", "Vol Dampening".
- For Breakout scenarios, specify if it is a "Clean Break" (Brittle) or "Grind Break" (Rigid).

Return strictly JSON format with `scenarios` array and `validation_summary`.
"""


def get_user_prompt(scoring_data: dict) -> str:
    """User Prompt in English"""
    
    def _clean_and_parse(data):
        if isinstance(data, str):
            clean_text = data.strip()
            if clean_text.startswith("```json"): clean_text = clean_text[7:]
            elif clean_text.startswith("```"): clean_text = clean_text[3:]
            if clean_text.endswith("```"): clean_text = clean_text[:-3]
            try: return json.loads(clean_text.strip())
            except: return {}
        return data if isinstance(data, dict) else {}
    
    data = _clean_and_parse(scoring_data)
    
    # Extract Key Phase 3 Intel
    targets = data.get("targets", {})
    micro = targets.get("gamma_metrics", {}).get("micro_structure", {})
    anchors = targets.get("sentiment_anchors", {})
    
    micro_hint = f"Wall Physics: {micro.get('wall_type', 'Unknown')}, Breakout Difficulty: {micro.get('breakout_difficulty', 'Unknown')}"
    anchor_hint = f"Sentiment Anchor (Max Pain): {anchors.get('max_pain', 'N/A')}"
    
    return f"""Analyze the market scenarios.

    ## PHASE 3 INTELLIGENCE
    - **{micro_hint}**
    - **{anchor_hint}**

    ## SCORING DATA
    ```json
    {json.dumps(data, ensure_ascii=False, indent=2)}
    ```
    
    ## INSTRUCTIONS
    1. Generate 3-5 scenarios.
    2. **IF Wall is 'Rigid'**: Increase probability of 'Pinning/Rejection'. Reduce 'Direct Breakout'.
    3. **IF Wall is 'Brittle'**: Increase probability of 'Momentum Breakout'.
    4. **IF Scenario is 'Range'**: Treat Max Pain as a magnetic target.

    Return JSON.
    """