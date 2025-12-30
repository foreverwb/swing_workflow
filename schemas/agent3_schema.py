"""
Agent 3 JSON Schema - v4.2 (English Enums & 3D Framework)

变更:
1. [微观结构] 显性定义 micro_structure 的 Enum 值 (Rigid/Brittle)，与 code_input_calc.py 保持一致
2. [波动定价] 新增 vol_surface (Smile/Skew)
3. [情绪锚点] 新增 sentiment_anchors (Max Pain)
4. [国际化] 全面切换为英文 Enum (Rising/Falling/Flat)
"""

def get_schema() -> dict:
    """返回 Agent 3 的 JSON Schema"""
    return {
        "type": "object",
        "required": ["targets", "indices"],
        "properties": {
            "targets": {
                "type": "object",
                "required": [
                    "symbol",
                    "spot_price",
                    "walls",
                    "gamma_metrics",
                    "directional_metrics",
                    "atm_iv",
                    "validation_metrics"
                ],
                "properties": {
                    "symbol": {"type": "string"},
                    "spot_price": {"type": "number"},
                    
                    # === 1. 方向维度 (Direction) ===
                    "walls": {
                        "type": "object",
                        "required": ["call_wall", "put_wall", "major_wall"],
                        "properties": {
                            "call_wall": {"type": "number"},
                            "put_wall": {"type": "number"},
                            "major_wall": {"type": "number"}
                        }
                    },
                    
                    "gamma_metrics": {
                        "type": "object",
                        "required": ["vol_trigger", "spot_vs_trigger", "net_gex"],
                        "properties": {
                            "vol_trigger": {
                                "type": "number", 
                                "description": "即 Gamma Flip Level (体制转换分界线)"
                            },
                            "spot_vs_trigger": {
                                "type": "string", 
                                "enum": ["above", "below", "near", "N/A"]
                            },
                            "net_gex": {
                                "type": "string", 
                                "enum": ["positive_gamma", "negative_gamma"]
                            },
                            "gap_distance_dollar": {"type": "number"},
                            
                            # [A] 物理微观结构 (来自 code_input_calc.py 计算)
                            "micro_structure": {
                                "type": "object",
                                "properties": {
                                    "wall_type": {
                                        "type": "string",
                                        "enum": [
                                            "Rigid (刚性墙)", 
                                            "Brittle (脆性墙)", 
                                            "Elastic (弹性墙)",
                                            "Unknown"
                                        ],
                                        "description": "基于 ECR 集中度定义的墙体物理属性"
                                    },
                                    "breakout_difficulty": {
                                        "type": "string",
                                        "enum": ["High", "Medium", "Low", "Unknown"],
                                        "description": "基于墙体硬度的突破难度评估"
                                    },
                                    "sustain_potential": {
                                        "type": "string",
                                        "enum": ["High", "Low", "Unknown"],
                                        "description": "基于 SER 次级结构的趋势接力能力"
                                    }
                                }
                            },

                            # [B] 结构峰值 (支持手动输入或算法搜索)
                            "structural_peaks": {
                                "type": "object",
                                "description": "具体的阻力位价格与强度",
                                "properties": {
                                    "nearby_peak": {
                                        "type": "object",
                                        "required": ["price"],
                                        "properties": {
                                            "price": {"type": "number"},
                                            "intensity": {"type": "number", "description": "GEX绝对值或相对强度"}
                                        }
                                    },
                                    "secondary_peak": {
                                        "type": "object",
                                        "properties": {
                                            "price": {"type": "number"},
                                            "intensity": {"type": "number"}
                                        }
                                    }
                                }
                            }
                        }
                    },
                    
                    "directional_metrics": {
                        "type": "object",
                        "properties": {
                            "dex_bias": {
                                "type": "string",
                                "enum": ["support", "mixed", "oppose", "N/A"]
                            },
                            "dex_bias_strength": {
                                "type": "string",
                                "enum": ["strong", "mid", "weak", "N/A"]
                            },
                            "vanna_dir": {
                                "type": "string",
                                "enum": ["up", "down", "flat", "N/A"]
                            },
                            "vanna_confidence": {
                                "type": "string",
                                "enum": ["high", "medium", "low", "N/A"]
                            },
                            "iv_path": {
                                "type": "string",
                                "enum": ["Rising", "Falling", "Flat", "Insufficient_Data"],
                                "description": "基于3日ATM IV趋势"
                            },
                            "iv_path_confidence": {
                                "type": "string",
                                "enum": ["High", "Medium", "Low", "N/A"]
                            }
                        }
                    },
                    
                    # === 2. 波动维度 (Volatility) ===
                    "atm_iv": {
                        "type": "object",
                        "required": ["iv_7d", "iv_14d"],
                        "properties": {
                            "iv_7d": {"type": "number"},
                            "iv_14d": {"type": "number"},
                            "iv_source": {"type": "string", "enum": ["contango", "backwardation", "flat"]}
                        }
                    },
                    
                    # [新增] 波动率曲面特征 (用于定价)
                    "vol_surface": {
                        "type": "object",
                        "description": "波动率曲面特征，决定 Spread/Ratio 的构建方式",
                        "properties": {
                            "smile_steepness": {
                                "type": "string", 
                                "enum": [
                                    "Steep",        # OTM 极贵 -> Ratio Spread / Credit Spread
                                    "Flat",         # OTM 便宜 -> Long Strangle / Calendar
                                    "Skewed_Put",   # Put 端极贵 -> Put Ratio / Collar
                                    "Skewed_Call",  # Call 端极贵 -> Call Ratio / Cov Call
                                    "N/A"
                                ],
                                "description": "微笑曲线形态"
                            },
                            "skew_25d": {
                                "type": "number",
                                "description": "25 Delta Put-Call Skew Spread"
                            }
                        }
                    },

                    # === 3. 情绪维度 (Sentiment) ===
                    "validation_metrics": {
                        "type": "object",
                        "properties": {
                            "net_volume_signal": {
                                "type": ["string", "null"],
                                "enum": ["Bullish_Call_Buy", "Bearish_Put_Buy", "Neutral", "Divergence", None]
                            },
                            "net_vega_exposure": {
                                "type": ["string", "null"],
                                "enum": ["Long_Vega", "Short_Vega", "Unknown", None]
                            }
                        }
                    },
                    
                    # [新增] 情绪锚点 (震荡市专用)
                    "sentiment_anchors": {
                        "type": "object",
                        "description": "市场情绪锚点",
                        "properties": {
                            "max_pain": {
                                "type": "number",
                                "description": "最大痛点价格 (Grind/Range 场景的目标位)"
                            },
                            "put_call_ratio": {
                                "type": "number",
                                "description": "PCR 指标 (可选)"
                            }
                        }
                    }
                }
            },
            
            # 指数部分保持宽泛定义
            "indices": {
                "type": "object", 
                "additionalProperties": True
            }
        }
    }