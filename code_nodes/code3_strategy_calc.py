"""
Code 3: 策略计算引擎 (Swing 增强版 v3.0 - Phase 3 Final)
变更：
1. [新增] Delta 维度支持 (delta_profile, delta_rationale)
2. [增强] 基于 DEX Bias 和 Gamma Regime 的方向判定逻辑
3. [夯实] 强制 R > 1.8 逻辑：Debit 策略优先
"""
import json
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from utils.config_loader import config 
import traceback
from loguru import logger

@dataclass
class ValidationFlags:
    is_vetoed: bool = False
    veto_reason: str = ""
    weekly_friction_state: str = "Clear"
    execution_guidance: str = ""
    strategy_bias: str = "Neutral"
    strategy_bias_reason: str = ""
    net_volume_signal: Optional[str] = None
    net_vega_exposure: Optional[str] = None
    confidence_penalty: float = 0.0

@dataclass
class DTEResult:
    final: int
    base: int = 21
    t_scale: float = 1.0
    t_scale_source: str = "本地计算"
    gap_level: str = "mid"
    monthly_override: bool = False
    vol_state: str = "IV/HV均衡"
    vrp: float = 1.0
    rationale: str = ""

@dataclass
class RiskRewardResult:
    width: float
    ivr: int
    cost: float
    max_profit: float
    max_loss: float
    ratio: float
    ratio_str: str 
    meets_edge: bool
    formula: str

@dataclass
class WinProbResult:
    estimate: float
    formula: str
    note: str
    noise_adjusted: Optional[float] = None
    theoretical_base: float = 0.5

@dataclass
class SwingStrategyObject:
    """[新增] 波段策略实体对象"""
    name: str
    thesis: str
    action: str
    structure_type: str
    legs: Dict
    max_profit: float
    max_loss: float
    rr_ratio: float
    entry_trigger: str
    invalidation_level: str
    target_level: str
    # [Phase 3 新增字段]
    delta_profile: str = "Neutral"
    delta_rationale: str = ""

@dataclass
class StrategyOutput:
    trade_status: str
    validation: ValidationFlags
    strikes: Dict
    dte: DTEResult
    volatility: Dict
    rr: Dict[str, RiskRewardResult]
    pw: Dict[str, WinProbResult]
    greeks_ranges: Dict
    exit_params: Dict
    meta: Dict
    swing_strategy: Optional[SwingStrategyObject] = None

class StrategyCalculator:
    
    def __init__(self, env_vars: Dict[str, Any]):
        self.conf = config
        self.market_params = env_vars.get('market_params', {})
        
    def _calc_theoretical_win_rate(self, strategy_type: str, iv: float, dte: int) -> float:
        if dte <= 0 or iv <= 0: return 0.5
        if strategy_type == 'credit': return 0.65 
        elif strategy_type == 'debit': return 0.45 
        return 0.5

    def _calc_weekly_friction(self, spot: float, gamma_metrics: Dict) -> Tuple[str, str]:
        # [适配] 支持 micro_structure 中的 nearby_peak
        # 优先读取 structural_peaks 下的嵌套结构 (Phase 3 Schema)
        peaks = gamma_metrics.get('structural_peaks', {})
        nearby_data = peaks.get('nearby_peak')
        
        if nearby_data:
             weekly_peak = nearby_data.get('price')
        else:
             # 回退兼容旧路径
             weekly_peak = gamma_metrics.get('nearby_peak', {}).get('price')

        if not weekly_peak or spot == 0:
            return "Clear", "无周度结构阻挡"
            
        distance_pct = abs(spot - weekly_peak) / spot
        if distance_pct < 0.01:
            return "Obstructed", f"受周度结构 {weekly_peak} 压制 (距离 {distance_pct:.1%})"
        else:
            return "Clear", "周度路径通畅"

    def _process_validation(self, data: Dict, gamma_metrics: Dict, spot: float, primary_scenario: str) -> ValidationFlags:
        flags = ValidationFlags()
        friction_state, friction_note = self._calc_weekly_friction(spot, gamma_metrics)
        flags.weekly_friction_state = friction_state
        if friction_state == "Obstructed":
            flags.execution_guidance = f"⚠️ {friction_note}。建议：等待突破或回踩确认。"
        else:
            flags.execution_guidance = "结构通畅，可按计划执行。"
            
        vol_signal = data.get("net_volume_signal")
        flags.net_volume_signal = vol_signal
        
        # 兼容中英文场景描述
        bullish_kw = ["上行", "突破", "看涨", "bullish", "Bullish", "Trend"]
        bearish_kw = ["下行", "跌破", "看跌", "bearish", "Bearish"]
        is_bullish = any(k in primary_scenario for k in bullish_kw)
        is_bearish = any(k in primary_scenario for k in bearish_kw)
        
        if vol_signal and vol_signal not in ("Neutral", "Unknown", None):
            if is_bullish and vol_signal == "Bearish_Put_Buy":
                flags.is_vetoed = True
                flags.veto_reason = "GEX看涨但实时成交量看跌(量价背离)"
            elif is_bearish and vol_signal == "Bullish_Call_Buy":
                flags.is_vetoed = True
                flags.veto_reason = "GEX看跌但实时成交量看涨(量价背离)"
        
        vega = data.get("net_vega_exposure")
        flags.net_vega_exposure = vega
        if vega == "Short_Vega":
            flags.strategy_bias = "Credit_Favored"
            flags.strategy_bias_reason = "Dealer Short Vega，压制波动"
        elif vega == "Long_Vega":
            flags.strategy_bias = "Debit_Favored"
            flags.strategy_bias_reason = "Dealer Long Vega，放大波动"
            
        return flags

    def _determine_delta_bias(self, directional: Dict, gamma_regime: str) -> Tuple[str, str]:
        """[Phase 3 新增] 计算 Delta 偏好: Long / Short / Neutral"""
        dex_bias = directional.get("dex_bias", "mixed")
        dex_strength = directional.get("dex_bias_strength", "weak")
        
        # 1. 强 DEX 信号主导 (Dealer 库存倾向)
        if dex_bias == "support" and dex_strength in ["strong", "medium"]:
            return "Long Delta", "DEX强支撑 (Dealer做多库存)"
        elif dex_bias == "oppose" and dex_strength in ["strong", "medium"]: 
            return "Short Delta", "DEX强阻力 (Dealer做空库存)"
            
        # 2. Gamma Regime 辅助
        if gamma_regime == "below": # 负 Gamma 通常伴随动量
            return "Short Delta", "负Gamma区域 (顺势做空)"
        elif gamma_regime == "above":
            # 正 Gamma 震荡偏多 (但可能是区间)
            return "Neutral/Long Delta", "正Gamma震荡"
            
        return "Neutral Delta", "混合信号或无明显方向"

    def _enforce_edge(self, strategy_type: str, legs: Dict, width: float, cost: float, max_profit: float) -> Optional[Dict]:
        if cost <= 0 or width <= 0: return None
        risk = cost
        reward = max_profit
        rr = reward / risk if risk > 0 else 0
        if rr < 1.8:
            logger.warning(f"策略 {strategy_type} R/R={rr:.2f} < 1.8，被风控过滤")
            return None
        return {
            "rr_ratio": round(rr, 2),
            "risk": round(risk, 2),
            "reward": round(reward, 2),
            "legs": legs
        }

    def _calc_rr_debit(self, width: float, ivr: int) -> RiskRewardResult:
        cost_ratio_est = 0.35 + (ivr / 100.0) * 0.15
        debit = width * cost_ratio_est
        profit = width - debit
        r_value = profit / debit if debit > 0 else 0
        meets_edge = r_value >= 1.8
        return RiskRewardResult(
            width=round(width, 2), cost=round(debit, 2), ivr=ivr,
            max_profit=round(profit, 2), max_loss=round(debit, 2),
            ratio=round(r_value, 2), ratio_str=f"{r_value:.1f}:1",
            meets_edge=meets_edge, formula="Est Cost"
        )

    def _calc_rr_credit(self, width: float, ivr: int) -> RiskRewardResult:
        credit_ratio_est = 0.20 + (ivr / 100.0) * 0.20
        credit = width * credit_ratio_est
        risk = width - credit
        r_value = credit / risk if risk > 0 else 0
        return RiskRewardResult(
            width=round(width, 2), cost=-round(credit, 2), ivr=ivr,
            max_profit=round(credit, 2), max_loss=round(risk, 2),
            ratio=round(r_value, 2), ratio_str=f"1:{1/r_value:.1f}" if r_value > 0 else "N/A",
            meets_edge=False, formula="Est Credit"
        )

    def _calc_strikes(self, spot: float, em1: float, walls: Dict) -> Dict:
        call_w = walls.get("call_wall") or spot * 1.05
        put_w = walls.get("put_wall") or spot * 0.95
        e = self.conf.strikes
        cons_off = e.conservative_long_offset
        agg_off = e.aggressive_long_offset
        def r(x): return round(x, 2)
        return {
            "iron_condor": {
                "short_call": r(call_w), "long_call": r(call_w + cons_off * em1),
                "short_put": r(put_w), "long_put": r(put_w - cons_off * em1),
                "width_call": r(cons_off * em1), "width_put": r(cons_off * em1)
            },
            "bull_call_spread": {
                "long_call": r(spot + agg_off * em1), "short_call": r(call_w),
                "width": r(call_w - (spot + agg_off * em1))
            },
            "bear_put_spread": {
                "long_put": r(spot - agg_off * em1), "short_put": r(put_w),
                "width": r((spot - agg_off * em1) - put_w)
            },
            "long_call": {"strike": r(spot + agg_off * em1)},
            "long_put": {"strike": r(spot - agg_off * em1)}
        }

    def _calc_dte(self, gap_em1: float, monthly_override: bool, vol_metrics: Dict) -> DTEResult:
        gap_em1 = gap_em1 or 2.0
        cached = vol_metrics.get('t_scale')
        if cached is not None: t_scale, source = cached, "上游缓存"
        else: t_scale, source = 1.0, "Default"
        
        base, vol_adj = 21.0, 21.0 * t_scale
        gap_mult = 1.2 if gap_em1 > 3 else (0.8 if gap_em1 < 1 else 1.0)
        raw_dte = vol_adj * gap_mult
        if monthly_override and raw_dte < 25: raw_dte = 25.0
        final = int(max(5, min(45, raw_dte)))
        return DTEResult(final, int(base), round(t_scale, 3), source, "mid", monthly_override, "Normal", 1.0, "")

    def _calc_pw_credit(self, cluster: float, gap_em1: float, tech_score: float, iv: float, dte: int) -> WinProbResult:
        c = self.conf.pw_calculation.credit
        theoretical = self._calc_theoretical_win_rate('credit', iv, dte)
        final = (c.base * 0.7) + (theoretical * 0.3)
        adj = max(c.min, min(c.max, final))
        return WinProbResult(round(adj, 3), "Hybrid", "Credit", None, theoretical)

    def _calc_pw_debit(self, iv: float, dte: int) -> WinProbResult:
        e = self.conf.pw_calculation.debit
        theoretical = self._calc_theoretical_win_rate('debit', iv, dte)
        final = (e.base * 0.7) + (theoretical * 0.3)
        adj = max(e.min, min(e.max, final))
        return WinProbResult(round(adj, 3), "Hybrid", "Debit", None, theoretical)

    def _calc_pw_butterfly(self, spot: float, body: float, em1: float, iv_path: str) -> WinProbResult:
        return WinProbResult(0.55, "Fixed", "Butterfly")

    def _get_greeks_ranges(self) -> Dict: return self.conf.greeks
    def _get_exit_params(self) -> Dict: return self.conf.exit_rules
    def _safe_get(self, data: Dict, *keys, default=None):
        for key in keys:
            if isinstance(data, dict): data = data.get(key, default)
            else: return default
        return data if data is not None else default

    def _build_vetoed_result(self, validation: ValidationFlags, spot: float, em1: float, scenario: str) -> Dict:
        return {
            "trade_status": "VETOED",
            "veto_reason": validation.veto_reason,
            "validation": asdict(validation),
            "strategies": [],
            "meta": {"spot": spot, "em1": em1, "primary_scenario": scenario}
        }

    def _synthesize_swing_strategy(self, spot: float, scenario: str, vol_metrics: Dict, strikes: Dict, micro: Dict, delta_bias: str, delta_note: str) -> Optional[SwingStrategyObject]:
        ivr = vol_metrics.get("market_snapshot", {}).get("ivr") or 50
        is_high_vol = ivr > 50
        is_trend = "Trend" in scenario or "Breakout" in scenario
        is_range = "Range" in scenario or "Grind" in scenario
        is_bullish = "Bullish" in scenario or "Up" in scenario
        is_delta_long = "Long Delta" in delta_bias  # [Phase 3] Delta 辅助判断
        
        strategy_obj = None
        
        # 场景 1: Trend(Up) OR Long Delta + Low Vol -> Debit Call Spread
        if (is_trend or is_delta_long) and not is_high_vol:
            if is_bullish or is_delta_long:
                width = strikes["bull_call_spread"]["width"]
                cost_est = width * 0.30 
                profit_est = width - cost_est
                valid = self._enforce_edge("Debit_Call_Spread", strikes["bull_call_spread"], width, cost_est, profit_est)
                if valid:
                    strategy_obj = SwingStrategyObject(
                        name="Bullish_Debit_Vertical",
                        thesis="Trend(Up) + Vol(Low) -> Cheap Gamma",
                        action=f"Buy Call {strikes['bull_call_spread']['long_call']}",
                        structure_type="Debit",
                        legs=strikes["bull_call_spread"],
                        max_profit=valid["reward"],
                        max_loss=valid["risk"],
                        rr_ratio=valid["rr_ratio"],
                        entry_trigger="Breakout",
                        invalidation_level=f"Spot < {spot * 0.98:.2f}",
                        target_level=f"Target: {strikes['bull_call_spread']['short_call']}",
                        # [Phase 3] 注入 Delta 信息
                        delta_profile="Long Delta",
                        delta_rationale=f"{delta_note} + 低波动率优势"
                    )
        
        # Fallback 策略
        if not strategy_obj and is_trend and is_bullish:
             width = strikes["bull_call_spread"]["width"]
             cost_est = width * 0.35 
             profit_est = width - cost_est
             valid = self._enforce_edge("Fallback", strikes["bull_call_spread"], width, cost_est, profit_est)
             if valid:
                 strategy_obj = SwingStrategyObject(
                     name="Trend_Debit_Fallback",
                     thesis="Trend Follow (Fallback)",
                     action="Debit Spread",
                     structure_type="Debit",
                     legs=strikes["bull_call_spread"],
                     max_profit=valid["reward"],
                     max_loss=valid["risk"],
                     rr_ratio=valid["rr_ratio"],
                     entry_trigger="Breakout",
                     invalidation_level="Support Loss",
                     target_level="Resistance",
                     delta_profile="Long Delta",
                     delta_rationale="趋势跟踪 (Fallback)"
                 )
        return strategy_obj

    def process(self, agent3_data: Dict, agent5_data: Dict, technical_score: float = 0) -> Dict:
        spot = agent3_data.get("spot_price", 0)
        em1 = agent3_data.get("em1_dollar", 0)
        walls = agent3_data.get("walls", {})
        gamma = agent3_data.get("targets", {}).get("gamma_metrics", {})
        direction = agent3_data.get("directional_metrics", {})
        vol_metrics = agent3_data.get("volatility_metrics", {})
        validation_raw = agent3_data.get("targets", {}).get("validation_metrics", {})
        micro_structure = gamma.get("micro_structure", {})
        
        scenario = agent5_data.get("scenario_classification", {})
        primary_scenario = scenario.get("primary_scenario", "未知")
        
        if spot == 0 or em1 == 0:
            raise ValueError("缺失关键字段: spot_price 或 em1_dollar")
        
        validation = self._process_validation(validation_raw, gamma, spot, primary_scenario)
        if validation.is_vetoed:
            return self._build_vetoed_result(validation, spot, em1, primary_scenario)
        
        # [Phase 3] 计算 Delta Bias
        delta_bias, delta_note = self._determine_delta_bias(direction, gamma.get("spot_vs_trigger", "unknown"))
        
        strikes = self._calc_strikes(spot, em1, walls)
        dte = self._calc_dte(gamma.get("gap_distance_em1_multiple", 2.0),
                            gamma.get("monthly_cluster_override", False), vol_metrics)
        
        ivr = self._safe_get(vol_metrics, 'market_snapshot', 'ivr', default=40)
        iv_atm = self._safe_get(vol_metrics, 'market_snapshot', 'iv30', default=30)
        
        rr_credit = self._calc_rr_credit(strikes["iron_condor"]["width_call"], ivr)
        rr_debit = self._calc_rr_debit(strikes["bull_call_spread"]["width"], ivr)
        
        if rr_debit.meets_edge and not rr_credit.meets_edge:
            if validation.strategy_bias == "Neutral":
                validation.strategy_bias = "Debit_Favored"
                validation.strategy_bias_reason = "Debit策略盈亏比 > 1.8"
        
        pw_credit = self._calc_pw_credit(gamma.get("cluster_strength_ratio", 1.5),
                                          gamma.get("gap_distance_em1_multiple", 2.0), technical_score, iv_atm, dte.final)
        pw_debit = self._calc_pw_debit(iv_atm, dte.final)
        # [变更] iv_path 默认值修正为 "Flat"
        pw_butterfly = self._calc_pw_butterfly(spot, spot, em1, direction.get("iv_path", "Flat"))
        
        # [Phase 3] 传递 delta_bias 和 delta_note 到策略合成
        swing_strategy = self._synthesize_swing_strategy(spot, primary_scenario, vol_metrics, strikes, micro_structure, delta_bias, delta_note)
        
        return {
            "trade_status": "ACTIVE",
            "validation": asdict(validation),
            "strikes": strikes,
            "dte": asdict(dte),
            "volatility": {
                "lambda_factor": vol_metrics.get("lambda_factor", 1.0),
                "t_scale": dte.t_scale,
                "vrp": dte.vrp,
                "vol_state": dte.vol_state,
                "ivr": ivr
            },
            "rr": {
                "iron_condor": asdict(rr_credit),
                "bull_call_spread": asdict(rr_debit)
            },
            "pw": {
                "credit": asdict(pw_credit),
                "debit": asdict(pw_debit),
                "butterfly": asdict(pw_butterfly)
            },
            "swing_strategy": asdict(swing_strategy) if swing_strategy else None,
            "greeks_ranges": self._get_greeks_ranges(),
            "exit_params": self._get_exit_params(),
            "meta": {
                "spot": spot,
                "em1": em1,
                "primary_scenario": primary_scenario,
                "gamma_regime": self._safe_get(agent5_data, "gamma_regime", "spot_vs_trigger", default="unknown"),
                "strategy_bias": validation.strategy_bias,
                # [Phase 3] 输出 Delta 偏好
                "delta_bias": delta_bias 
            }
        }

def main(agent3_output: dict, agent5_output: dict, technical_score: float = 0, **env_vars) -> dict:
    try:
        if isinstance(agent3_output, str): agent3_output = json.loads(agent3_output)
        if isinstance(agent5_output, str): agent5_output = json.loads(agent5_output)
        calculator = StrategyCalculator(env_vars)
        return calculator.process(agent3_output, agent5_output, technical_score)
    except Exception as e:
        logger.error(f"❌ Strategy_calc error: {e}")
        return {"error": True, "error_message": str(e), "traceback": traceback.format_exc()}