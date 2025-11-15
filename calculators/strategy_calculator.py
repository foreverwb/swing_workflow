"""
CODE3 - 策略辅助计算引擎
负责：
1. 行权价计算
2. DTE 选择
3. RR 盈亏比计算
4. Pw 胜率计算
5. Greeks 目标范围
6. 止盈止损参数
"""

import json
from typing import Dict, Any, Tuple
from utils.logger import setup_logger

logger = setup_logger(__name__)


class StrategyCalculator:
    """策略计算引擎"""
    
    def __init__(self, config):
        self.config = config
        self.env = self._load_env_vars()
    
    def _load_env_vars(self) -> Dict[str, float]:
        """加载环境变量阈值"""
        return {
            # Greeks 目标范围
            'CONSERVATIVE_DELTA_MIN': float(self.config.CONSERVATIVE_DELTA_MIN),
            'CONSERVATIVE_DELTA_MAX': float(self.config.CONSERVATIVE_DELTA_MAX),
            'CONSERVATIVE_THETA_MIN': float(self.config.CONSERVATIVE_THETA_MIN),
            'CONSERVATIVE_VEGA_MAX': float(self.config.CONSERVATIVE_VEGA_MAX),
            'BALANCED_DELTA_RANGE': float(self.config.BALANCED_DELTA_RANGE),
            'BALANCED_THETA_MIN': float(self.config.BALANCED_THETA_MIN),
            'AGGRESSIVE_DELTA_MIN': float(self.config.AGGRESSIVE_DELTA_MIN),
            'AGGRESSIVE_DELTA_MAX': float(self.config.AGGRESSIVE_DELTA_MAX),
            'AGGRESSIVE_VEGA_MIN': float(self.config.AGGRESSIVE_VEGA_MIN),
            
            # DTE 选择
            'DTE_GAP_HIGH_THRESHOLD': float(self.config.DTE_GAP_HIGH_THRESHOLD),
            'DTE_GAP_MID_THRESHOLD': float(self.config.DTE_GAP_MID_THRESHOLD),
            'DTE_MONTHLY_ADJUSTMENT': float(self.config.DTE_MONTHLY_ADJUSTMENT),
            
            # 行权价偏移
            'STRIKE_CONSERVATIVE_LONG_OFFSET': float(self.config.STRIKE_CONSERVATIVE_LONG_OFFSET),
            'STRIKE_BALANCED_WING_OFFSET': float(self.config.STRIKE_BALANCED_WING_OFFSET),
            'STRIKE_RATIO_SHORT_OFFSET': float(self.config.STRIKE_RATIO_SHORT_OFFSET),
            'STRIKE_RATIO_LONG_OFFSET': float(self.config.STRIKE_RATIO_LONG_OFFSET),
            'STRIKE_AGGRESSIVE_LONG_OFFSET': float(self.config.STRIKE_AGGRESSIVE_LONG_OFFSET),
            
            # 价差宽度
            'WIDTH_CREDIT_MIN': float(self.config.WIDTH_CREDIT_MIN),
            'WIDTH_CREDIT_MAX': float(self.config.WIDTH_CREDIT_MAX),
            'WIDTH_DEBIT_MIN': float(self.config.WIDTH_DEBIT_MIN),
            'WIDTH_DEBIT_MAX': float(self.config.WIDTH_DEBIT_MAX),
            
            # RR 计算 - 信用 IVR 映射
            'CREDIT_IVR_0_25': float(self.config.CREDIT_IVR_0_25),
            'CREDIT_IVR_25_50': float(self.config.CREDIT_IVR_25_50),
            'CREDIT_IVR_50_75': float(self.config.CREDIT_IVR_50_75),
            'CREDIT_IVR_75_100': float(self.config.CREDIT_IVR_75_100),
            
            # RR 计算 - 借贷 IVR 映射
            'DEBIT_IVR_0_40': float(self.config.DEBIT_IVR_0_40),
            'DEBIT_IVR_40_70': float(self.config.DEBIT_IVR_40_70),
            'DEBIT_IVR_70_100': float(self.config.DEBIT_IVR_70_100),
            
            # Pw 计算 - 信用
            'PW_CREDIT_BASE': float(self.config.PW_CREDIT_BASE),
            'PW_CREDIT_CLUSTER_COEF': float(self.config.PW_CREDIT_CLUSTER_COEF),
            'PW_CREDIT_DISTANCE_PENALTY_COEF': float(self.config.PW_CREDIT_DISTANCE_PENALTY_COEF),
            'PW_CREDIT_MIN': float(self.config.PW_CREDIT_MIN),
            'PW_CREDIT_MAX': float(self.config.PW_CREDIT_MAX),
            
            # Pw 计算 - 借贷
            'PW_DEBIT_BASE': float(self.config.PW_DEBIT_BASE),
            'PW_DEBIT_DEX_COEF': float(self.config.PW_DEBIT_DEX_COEF),
            'PW_DEBIT_VANNA_COEF': float(self.config.PW_DEBIT_VANNA_COEF),
            'PW_DEBIT_MIN': float(self.config.PW_DEBIT_MIN),
            'PW_DEBIT_MAX': float(self.config.PW_DEBIT_MAX),
            
            # Pw 计算 - 蝶式
            'PW_BUTTERFLY_BODY_INSIDE': float(self.config.PW_BUTTERFLY_BODY_INSIDE),
            'PW_BUTTERFLY_BODY_OFFSET_1EM': float(self.config.PW_BUTTERFLY_BODY_OFFSET_1EM),
            
            # 止盈止损
            'PROFIT_TARGET_CREDIT_PCT': float(self.config.PROFIT_TARGET_CREDIT_PCT),
            'PROFIT_TARGET_DEBIT_PCT': float(self.config.PROFIT_TARGET_DEBIT_PCT),
            'STOP_LOSS_DEBIT_PCT': float(self.config.STOP_LOSS_DEBIT_PCT),
            'STOP_LOSS_CREDIT_PCT': float(self.config.STOP_LOSS_CREDIT_PCT),
            'TIME_DECAY_EXIT_DAYS': float(self.config.TIME_DECAY_EXIT_DAYS),
        }
    
    def process(self, agent3_data: Dict, agent5_data: Dict, technical_score: float = 0) -> Dict:
        """
        主处理流程
        
        Args:
            agent3_data: Agent 3 数据校验结果
            agent5_data: Agent 5 剧本分析结果
            technical_score: 技术面评分(0-2)
        
        Returns:
            完整计算结果
        """
        try:
            logger.info("🔧 开始策略辅助计算...")
            
            # 提取数据
            targets = agent3_data.get("targets", {})
            spot = targets.get("spot_price", 0)
            em1 = targets.get("em1_dollar", 0)
            walls = targets.get("walls", {})
            gamma_metrics = targets.get("gamma_metrics", {})
            directional_metrics = targets.get("directional_metrics", {})
            
            scenario = agent5_data.get("scenario_classification", {})
            
            # 执行计算
            strikes = self.calculate_strikes(spot, em1, walls)
            dte_info = self.calculate_dte(
                gamma_metrics.get("gap_distance_em1_multiple", 2.0),
                gamma_metrics.get("monthly_cluster_override", False)
            )
            
            # 估算 IVR（简化处理，实际应从市场数据获取）
            ivr_estimate = 40  # 默认中等 IVR
            
            # RR 计算
            rr_credit_ic = self.calculate_rr_credit(
                strikes["iron_condor"]["width_call"],
                ivr_estimate
            )
            
            rr_debit_bull = self.calculate_rr_debit(
                strikes["bull_call_spread"]["width"],
                ivr_estimate
            )
            
            # Pw 计算
            pw_credit = self.calculate_pw_credit(
                gamma_metrics.get("cluster_strength_ratio", 1.5),
                gamma_metrics.get("gap_distance_em1_multiple", 2.0),
                technical_score
            )
            
            pw_debit = self.calculate_pw_debit(
                directional_metrics.get("dex_same_dir_pct", 50),
                directional_metrics.get("vanna_confidence", "medium"),
                gamma_metrics.get("gap_distance_em1_multiple", 2.0)
            )
            
            pw_butterfly = self.calculate_pw_butterfly(
                spot,
                spot,  # body 在现价
                em1,
                directional_metrics.get("iv_path", "平")
            )
            
            # Greeks 范围
            greeks_ranges = self.get_greeks_ranges()
            
            # 止盈止损参数
            exit_params = self.get_exit_parameters()
            
            result = {
                "strikes": strikes,
                "dte_final": dte_info["final_dte"],
                "dte_rationale": dte_info["rationale"],
                "rr_ic_credit": rr_credit_ic["credit"],
                "rr_ic_max_profit": rr_credit_ic["max_profit"],
                "rr_ic_max_loss": rr_credit_ic["max_loss"],
                "rr_ic_ratio": rr_credit_ic["rr_ratio"],
                "rr_ic_formula": rr_credit_ic["formula"],
                "rr_bull_debit": rr_debit_bull["debit"],
                "rr_bull_max_profit": rr_debit_bull["max_profit"],
                "rr_bull_max_loss": rr_debit_bull["max_loss"],
                "rr_bull_ratio": rr_debit_bull["rr_ratio"],
                "rr_bull_formula": rr_debit_bull["formula"],
                "pw_credit_estimate": pw_credit["pw_estimate"],
                "pw_credit_formula": pw_credit["formula"],
                "pw_debit_estimate": pw_debit["pw_estimate"],
                "pw_debit_formula": pw_debit["formula"],
                "pw_butterfly_estimate": pw_butterfly["pw_estimate"],
                "greeks_conservative_desc": greeks_ranges["conservative"]["description"],
                "greeks_balanced_desc": greeks_ranges["balanced"]["description"],
                "greeks_aggressive_desc": greeks_ranges["aggressive"]["description"],
                "exit_credit_profit_pct": exit_params["credit_strategies"]["profit_target_pct"],
                "exit_credit_stop_pct": exit_params["credit_strategies"]["stop_loss_pct"],
                "exit_debit_profit_pct": exit_params["debit_strategies"]["profit_target_pct"],
                "exit_debit_stop_pct": exit_params["debit_strategies"]["stop_loss_pct"],
                "exit_time_days": exit_params["time_management"]["exit_days_before_expiry"],
                "meta_spot": spot,
                "meta_em1": em1,
                "meta_ivr": ivr_estimate,
                "meta_technical_score": technical_score,
                "meta_primary_scenario": scenario.get("primary_scenario", "未知"),
                "meta_scenario_probability": scenario.get("scenario_probability", 0),
                "meta_gamma_regime": agent5_data.get("gamma_regime", {}).get("spot_vs_trigger", "unknown")
            }
            
            logger.info("✅ 策略辅助计算完成")
            return result
            
        except Exception as e:
            logger.error(f"❌ 策略辅助计算失败: {e}", exc_info=True)
            raise
    
    # 以下省略各个计算方法的实现（与 Dify workflow 中的 CODE3 逻辑一致）
    # calculate_strikes(), calculate_dte(), calculate_rr_credit(), etc.
    # 完整代码见文档第一部分提供的 CODE3 Python 代码