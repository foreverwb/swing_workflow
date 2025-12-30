"""
Agent 6: 策略生成 Schema (v3.0 - Phase 3 Enhanced)

变更:
1. 新增 'source_blueprint' 字段，追踪策略来源 (Code3 vs LLM)
2. 强化 execution_plan 对微观战术的描述
"""

def get_schema() -> dict:
    """获取 Agent 6 输出 Schema"""
    return {
        "type": "object",
        "required": ["meta_info", "strategies"],
        "properties": {
            
            "meta_info": {
                "type": "object",
                "required": ["trade_style", "t_scale", "lambda_factor", "em1_dollar"],
                "properties": {
                    "trade_style": {"type": "string", "enum": ["SCALP", "SWING", "POSITION"]},
                    "t_scale": {"type": "number"},
                    "lambda_factor": {"type": "number"},
                    "em1_dollar": {"type": "number"}
                },
                "additionalProperties": False
            },
            
            "validation_flags": {
                "type": "object",
                "properties": {
                    "is_vetoed": {"type": "boolean"},
                    "veto_reason": {"type": "string"},
                    "strategy_bias": {"type": "string", "enum": ["Credit_Favored", "Debit_Favored", "Neutral"]},
                    "confidence_penalty": {"type": "number"}
                },
                "additionalProperties": False
            },
            
            "strategies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "strategy_name",
                        "strategy_type",
                        "structure",
                        "legs",
                        "execution_plan",
                        "quant_metrics",
                        "risk_management"
                    ],
                    "properties": {
                        "strategy_name": {"type": "string"},
                        
                        # [新增] 蓝图来源追踪
                        "source_blueprint": {
                            "type": "string",
                            "description": "如果基于Code3蓝图，此处填写蓝图名称 (如 Bullish_Debit_Vertical)，否则为 Manual"
                        },

                        "strategy_type": {
                            "type": "string",
                            "enum": ["directional", "volatility", "income", "hedge", "WAIT"]
                        },
                        "structure": {"type": "string"},
                        "description": {"type": "string"},
                        "suitability_score": {"type": "integer"},
                        
                        "legs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["action", "strike", "rationale"],
                                "properties": {
                                    "action": {"type": "string", "enum": ["buy", "sell"]},
                                    "option_type": {"type": "string", "enum": ["call", "put"]},
                                    "strike": {"type": "number"},
                                    "quantity": {"type": "integer"},
                                    "expiry_dte": {"type": "integer"},
                                    "rationale": {"type": "string"}
                                },
                                "additionalProperties": False
                            }
                        },
                        
                        "execution_plan": {
                            "type": "object",
                            "required": [
                                "entry_trigger", 
                                "entry_timing",
                                "holding_period", 
                                "exit_plan"
                            ],
                            "properties": {
                                "entry_trigger": {"type": "string"},
                                "entry_timing": {
                                    "type": "string",
                                    "description": "基于Rigid/Brittle墙体属性的入场时机 (Confirmation vs Aggressive)"
                                },
                                "holding_period": {"type": "string"},
                                "exit_plan": {
                                    "type": "object",
                                    "required": ["profit_target", "stop_loss"],
                                    "properties": {
                                        "profit_target": {"type": "string"},
                                        "stop_loss": {"type": "string"},
                                        "time_decay_exit": {"type": "string"},
                                        "adjustment": {"type": "string"}
                                    },
                                    "additionalProperties": False
                                }
                            },
                            "additionalProperties": False
                        },
                        
                        "quant_metrics": {
                            "type": "object",
                            "properties": {
                                "setup_cost": {"type": "string"},
                                "max_profit": {"type": "number"},
                                "max_loss": {"type": "number"},
                                "rr_ratio": {"type": "string"},
                                "pw_estimate": {"type": "string"},
                                "breakeven": {"type": "array", "items": {"type": "number"}},
                                "greeks_exposure": {
                                    "type": "object",
                                    "properties": {
                                        "delta": {"type": "string"},
                                        "gamma": {"type": "string"},
                                        "vega": {"type": "string"},
                                        "theta": {"type": "string"}
                                    },
                                    "additionalProperties": False
                                }
                            },
                            "additionalProperties": False
                        },
                        
                        "risk_management": {"type": "string"},
                        "pros": {"type": "array", "items": {"type": "string"}},
                        "cons": {"type": "array", "items": {"type": "string"}}
                    },
                    "additionalProperties": False
                }
            }
        },
        "additionalProperties": False
    }