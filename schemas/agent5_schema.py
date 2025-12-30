"""
Agent 5: 场景分析 Schema (v3.0 - Phase 3 Enhanced)

变更:
1. 新增 'physics_assessment' 字段，用于固化微观物理判断 (Rigid/Brittle)
2. 兼容英文输出
"""

def get_schema() -> dict:
    """返回 Agent 5 的 JSON Schema"""
    return {
        "type": "object",
        "required": [
            "gamma_regime",
            "physics_assessment", # [新增] 物理属性评估
            "scoring",
            "scenario_classification",
            "scenarios",
            "validation_summary"
        ],
        "properties": {
            "gamma_regime": {
                "type": "object",
                "required": ["vol_trigger", "spot_vs_trigger", "regime_note"],
                "properties": {
                    "vol_trigger": {"type": "number"},
                    "spot_vs_trigger": {"type": "string", "enum": ["above", "below", "near"]},
                    "base_scenario": {"type": "string"},
                    "regime_note": {"type": "string"}
                }
            },
            
            # [新增] Phase 3 核心：微观物理与共振评估
            "physics_assessment": {
                "type": "object",
                "required": ["wall_nature", "breakout_probability", "resonance_check"],
                "properties": {
                    "wall_nature": {
                        "type": "string", 
                        "enum": ["Rigid", "Brittle", "Elastic", "Unknown"],
                        "description": "墙体物理属性 (Rigid=Range, Brittle=Breakout)"
                    },
                    "breakout_probability": {
                        "type": "string",
                        "enum": ["High", "Medium", "Low"]
                    },
                    "resonance_check": {
                        "type": "string",
                        "enum": ["Resonance", "Friction", "Neutral"],
                        "description": "周度与月度结构的共振状态"
                    }
                }
            },

            "scoring": {
                "type": "object",
                "properties": {
                    "total_score": {"type": "number"},
                    "weight_breakdown": {"type": "string"}
                }
            },
            "scenario_classification": {
                "type": "object",
                "required": ["primary_scenario", "scenario_probability"],
                "properties": {
                    "primary_scenario": {"type": "string"},
                    "scenario_probability": {"type": "integer"}
                }
            },
            "scenarios": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "scenario_name", 
                        "probability", 
                        "direction",
                        "validation_warnings"
                    ],
                    "properties": {
                        "scenario_name": {"type": "string"},
                        "probability": {"type": "integer"},
                        "direction": {"type": "string"},
                        "volatility_expectation": {"type": "string"},
                        "validation_warnings": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    }
                }
            },
            "validation_summary": {
                "type": "object",
                "required": ["warnings", "overall_confidence_adjustment"],
                "properties": {
                    "has_fake_breakout_risk": {"type": "boolean"},
                    "has_vol_suppression": {"type": "boolean"},
                    "overall_confidence_adjustment": {"type": "number"},
                    "warnings": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            },
            # 兼容旧字段
            "entry_threshold_check": {"type": "string"},
            "entry_rationale": {"type": "string"},
            "key_levels": {"type": "object"},
            "risk_warning": {"type": "string"}
        }
    }