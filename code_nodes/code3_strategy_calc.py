"""
Code 3: 策略计算引擎 (重构版 - 修复配置访问)

变更:
1. 移除冗余的扁平化输出，改用嵌套结构
2. 统一配置管理，修复 self.env 访问错误
3. 新增 validation_metrics 处理逻辑
"""
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict, field
from utils.config_loader import config

# ============= 数据类定义 =============

@dataclass
class ValidationFlags:
    """验证标记"""
    is_vetoed: bool = False
    veto_reason: str = ""
    confidence_penalty: float = 0.0
    noise_status: str = "结构稳定"
    zero_dte_ratio: Optional[float] = None
    strategy_bias: str = "Neutral"
    strategy_bias_reason: str = ""
    net_volume_signal: Optional[str] = None
    net_vega_exposure: Optional[str] = None
    net_theta_exposure: Optional[str] = None
    theta_pin_note: str = ""


@dataclass
class DTEResult:
    """DTE 计算结果"""
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
    """盈亏比计算结果"""
    width: float
    ivr: int
    cost: float          # credit 为负，debit 为正
    max_profit: float
    max_loss: float
    ratio: str
    formula: str


@dataclass
class WinProbResult:
    """胜率计算结果"""
    estimate: float      # 0-1 范围
    formula: str
    note: str
    noise_adjusted: Optional[float] = None


@dataclass
class StrategyOutput:
    """策略计算完整输出"""
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

# ============= 主入口函数 =============

def main(agent3_output: dict, agent5_output: dict, technical_score: float = 0, **env_vars) -> dict:
    """
    Code 3 主入口
    
    Returns:
        dict - 策略计算结果对象
    """
    try:
        agent3_data = json.loads(agent3_output) if isinstance(agent3_output, str) else agent3_output
        agent5_data = json.loads(agent5_output) if isinstance(agent5_output, str) else agent5_output
        
        market_params = env_vars.get('market_params', {})
        
        calculator = StrategyCalculator(market_params=market_params)
        return calculator.process(agent3_data, agent5_data, technical_score)
        
    except Exception as e:
        import traceback
        return {
            "error": True,
            "message": str(e),
            "traceback": traceback.format_exc()
        }


# ============= 策略计算引擎 =============

class StrategyCalculator:
    """策略计算引擎 (重构版)"""
    
    def __init__(self, market_params: Dict[str, float] = None):
        self.dte_config = config.get_section('dte')
        self.strikes_config = config.get_section('strikes')
        self.rr_config = config.get_section('rr_calculation')
        self.pw_config = config.get_section('pw_calculation')
        self.greeks_config = config.get_section('greeks')
        self.exit_config = config.get_section('exit_rules')
        self.market_params = market_params or {}
    
    def _safe_get(self, data: Dict, *keys, default=None):
        """安全多层取值"""
        for key in keys:
            if isinstance(data, dict):
                data = data.get(key, default)
            else:
                return default
        return data if data is not None else default
    
    # ------------- 主处理流程 -------------
    
    def process(self, agent3_data: Dict, agent5_data: Dict, technical_score: float = 0) -> Dict:
        """主处理流程"""
        # 提取基础数据
        spot = agent3_data.get("spot_price", 0)
        em1 = agent3_data.get("em1_dollar", 0)
        walls = agent3_data.get("walls", {})
        gamma = agent3_data.get("gamma_metrics", {})
        direction = agent3_data.get("directional_metrics", {})
        vol_metrics = agent3_data.get("volatility_metrics", {})
        validation_raw = agent3_data.get("validation_metrics", {})
        
        scenario = agent5_data.get("scenario_classification", {})
        primary_scenario = scenario.get("primary_scenario", "未知")
        
        # 校验必需字段
        if spot == 0 or em1 == 0:
            raise ValueError("缺失关键字段: spot_price 或 em1_dollar")
        
        # 1. 验证指标处理
        validation = self._process_validation(validation_raw, primary_scenario)
        
        # 若触发否决，直接返回
        if validation.is_vetoed:
            return self._build_vetoed_result(validation, spot, em1, primary_scenario)
        
        # 2. 核心计算
        strikes = self._calc_strikes(spot, em1, walls)
        dte = self._calc_dte(gamma.get("gap_distance_em1_multiple", 2.0),
                            gamma.get("monthly_cluster_override", False), vol_metrics)
        
        ivr = self._safe_get(vol_metrics, 'market_snapshot', 'ivr', default=40)
        
        rr_credit = self._calc_rr_credit(strikes["iron_condor"]["width_call"], ivr)
        rr_debit = self._calc_rr_debit(strikes["bull_call_spread"]["width"], ivr)
        
        pw_credit = self._calc_pw_credit(gamma.get("cluster_strength_ratio", 1.5),
                                          gamma.get("gap_distance_em1_multiple", 2.0), technical_score)
        pw_debit = self._calc_pw_debit(direction.get("dex_same_dir_pct", 0.5),
                                        direction.get("vanna_confidence", "medium"),
                                        gamma.get("gap_distance_em1_multiple", 2.0))
        pw_butterfly = self._calc_pw_butterfly(spot, spot, em1, direction.get("iv_path", "平"))
        
        # 应用噪音惩罚
        penalty = validation.confidence_penalty
        pw_credit.noise_adjusted = round(pw_credit.estimate * (1 - penalty), 3)
        pw_debit.noise_adjusted = round(pw_debit.estimate * (1 - penalty), 3)
        
        # 3. 组装结果
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
            "greeks_ranges": self._get_greeks_ranges(),
            "exit_params": self._get_exit_params(),
            "meta": {
                "spot": spot,
                "em1": em1,
                "ivr": ivr,
                "technical_score": technical_score,
                "primary_scenario": primary_scenario,
                "scenario_probability": scenario.get("scenario_probability", 0),
                "gamma_regime": self._safe_get(agent5_data, "gamma_regime", "spot_vs_trigger", default="unknown"),
                "noise_penalty": penalty,
                "strategy_bias": validation.strategy_bias
            }
        }
    
    def _build_vetoed_result(self, validation: ValidationFlags, spot: float, em1: float, scenario: str) -> Dict:
        """构建被否决的结果"""
        return {
            "trade_status": "VETOED",
            "veto_reason": validation.veto_reason,
            "validation": asdict(validation),
            "strategies": [],
            "meta": {"spot": spot, "em1": em1, "primary_scenario": scenario}
        }
    
    # ------------- 验证指标处理 -------------
    
    def _process_validation(self, data: Dict, primary_scenario: str) -> ValidationFlags:
        """处理验证型数据，生成布尔锁和修正系数"""
        flags = ValidationFlags()
        
        # 原始数据
        zero_dte = data.get("zero_dte_ratio")
        vol_signal = data.get("net_volume_signal")
        vega = data.get("net_vega_exposure")
        theta = data.get("net_theta_exposure")
        
        flags.zero_dte_ratio = zero_dte
        flags.net_volume_signal = vol_signal
        flags.net_vega_exposure = vega
        flags.net_theta_exposure = theta
        
        # A. 噪音修正 (直接使用配置中的阈值需谨慎，此处简化硬编码，可改为从 config 获取)
        # 示例：self.config.validation.zero_dte_noise_threshold
        if zero_dte is not None:
            if zero_dte > 0.5:
                flags.confidence_penalty = 0.3
                flags.noise_status = "严重噪音(0DTE>50%)"
            elif zero_dte > 0.3:
                flags.confidence_penalty = 0.1
                flags.noise_status = "中度噪音(0DTE>30%)"
        else:
            flags.noise_status = "0DTE数据缺失"
        
        # B. 量价背离检测 (布尔锁)
        bullish_kw = ["上行", "突破", "看涨", "bullish", "Bullish"]
        bearish_kw = ["下行", "跌破", "看跌", "bearish", "Bearish"]
        is_bullish = any(k in primary_scenario for k in bullish_kw)
        is_bearish = any(k in primary_scenario for k in bearish_kw)
        
        if vol_signal and vol_signal not in ("Neutral", "Unknown"):
            if is_bullish and vol_signal == "Bearish_Put_Buy":
                flags.is_vetoed = True
                flags.veto_reason = "GEX看涨但实时成交量看跌(量价背离)"
            elif is_bearish and vol_signal == "Bullish_Call_Buy":
                flags.is_vetoed = True
                flags.veto_reason = "GEX看跌但实时成交量看涨(量价背离)"
        
        # C. 策略偏好
        if vega == "Short_Vega":
            flags.strategy_bias = "Credit_Favored"
            flags.strategy_bias_reason = "Dealer Short Vega，压制波动，适合卖方策略"
        elif vega == "Long_Vega":
            flags.strategy_bias = "Debit_Favored"
            flags.strategy_bias_reason = "Dealer Long Vega，放大波动，适合买方策略"
        
        # D. Theta 选点
        if theta == "Long_Theta":
            flags.theta_pin_note = "Dealer Long Theta，倾向Pin在高Theta区域"
        elif theta == "Short_Theta":
            flags.theta_pin_note = "Dealer Short Theta，时间衰减对Dealer不利"
        
        return flags
    
    # ------------- 行权价计算 -------------
    
    def _calc_strikes(self, spot: float, em1: float, walls: Dict) -> Dict:
        """计算各策略行权价"""
        call_w = walls.get("call_wall") or spot * 1.05
        put_w = walls.get("put_wall") or spot * 0.95
        
        # 修复：使用 self.strikes_config
        cfg = self.strikes_config
        cons_off = cfg.conservative_long_offset
        bal_off = cfg.balanced_wing_offset
        agg_off = cfg.aggressive_long_offset
        
        def r(x): return round(x, 2)
        
        return {
            "iron_condor": {
                "short_call": r(call_w), "long_call": r(call_w + cons_off * em1),
                "short_put": r(put_w), "long_put": r(put_w - cons_off * em1),
                "width_call": r(cons_off * em1), "width_put": r(cons_off * em1)
            },
            "iron_butterfly": {
                "body": r(spot),
                "call_wing": r(spot + bal_off * em1), "put_wing": r(spot - bal_off * em1),
                "wing_width": r(bal_off * em1)
            },
            "bull_call_spread": {
                "long_call": r(spot + agg_off * em1), "short_call": r(call_w),
                "width": r(call_w - (spot + agg_off * em1))
            },
            "bear_put_spread": {
                "long_put": r(spot - agg_off * em1), "short_put": r(put_w),
                "width": r((spot - agg_off * em1) - put_w)
            },
            "bull_put_spread": {
                "long_put": r(put_w - cons_off * em1), "short_put": r(put_w),
                "width": r(cons_off * em1)
            },
            "bear_call_spread": {
                "long_call": r(call_w + cons_off * em1), "short_call": r(call_w),
                "width": r(cons_off * em1)
            },
            "long_call": {"strike": r(spot + agg_off * em1)},
            "long_put": {"strike": r(spot - agg_off * em1)}
        }
    
    # ------------- DTE 计算 -------------
    
    def _calc_dte(self, gap_em1: float, monthly_override: bool, vol_metrics: Dict) -> DTEResult:
        """基于波动率时间膨胀的 DTE 计算"""
        gap_em1 = gap_em1 or 2.0
        vol_metrics = vol_metrics or {}
        
        # T_scale
        cached = vol_metrics.get('t_scale')
        if cached is not None:
            t_scale, source = cached, "上游缓存"
        else:
            hv20 = self.market_params.get('hv20', 30)
            iv30 = self.market_params.get('iv30', 30) or 30
            t_scale = max(0.5, min(2.0, (hv20 / iv30) ** 0.8))
            source = "本地计算"
        
        # 基准 + 膨胀
        base, vol_adj = 21.0, 21.0 * t_scale
        
        # Gap 修正 (阈值可从 config 获取，此处使用默认值简化)
        # cfg = self.dte_config
        # high_thresh = cfg.gap_high_threshold
        gap_mult = 1.2 if gap_em1 > 3 else (0.8 if gap_em1 < 1 else 1.0)
        raw_dte = vol_adj * gap_mult
        
        # 月度强制
        if monthly_override and raw_dte < 25:
            raw_dte = 25.0
        
        final = int(max(5, min(45, raw_dte)))
        
        # Vol state
        vol_state = "高IV溢价" if t_scale < 0.9 else ("低IV溢价" if t_scale > 1.1 else "IV/HV均衡")
        
        # VRP
        snap = vol_metrics.get('market_snapshot', {})
        iv30 = snap.get('iv30') or self.market_params.get('iv30', 30)
        hv20 = snap.get('hv20') or self.market_params.get('hv20', 30)
        vrp = round(iv30 / hv20, 2) if hv20 > 0 else 1.0
        
        return DTEResult(
            final=final, base=int(base), t_scale=round(t_scale, 3), t_scale_source=source,
            gap_level="high" if gap_em1 > 3 else ("low" if gap_em1 < 1 else "mid"),
            monthly_override=monthly_override, vol_state=vol_state, vrp=vrp,
            rationale=f"T_scale={t_scale:.2f}({vol_state}), 基准{int(base)}×{t_scale:.2f}={int(vol_adj)}d, Gap×{gap_mult}→{final}d"
        )
    
    # ------------- RR 盈亏比 -------------
    
    def _calc_rr_credit(self, width: float, ivr: int) -> RiskRewardResult:
        """信用价差 RR"""
        # 修复：使用 self.rr_config.credit_ivr
        cfg = self.rr_config.credit_ivr
        
        if ivr <= 25:
            cr = cfg['0-25']
        elif ivr <= 50:
            cr = cfg['25-50']
        elif ivr <= 75:
            cr = cfg['50-75']
        else:
            cr = cfg['75-100']
        
        credit = width * cr
        loss = width - credit
        ratio = f"1:{loss/credit:.1f}" if credit > 0 else "N/A"
        
        return RiskRewardResult(
            width=round(width, 2), ivr=ivr, cost=-round(credit, 2),
            max_profit=round(credit, 2), max_loss=round(loss, 2), ratio=ratio,
            formula=f"W={width:.1f}×{cr}={credit:.2f}"
        )
    
    def _calc_rr_debit(self, width: float, ivr: int) -> RiskRewardResult:
        """借贷价差 RR"""
        # 修复：使用 self.rr_config.debit_ivr
        cfg = self.rr_config.debit_ivr
        
        if ivr <= 40:
            dr = cfg['0-40']
        elif ivr <= 70:
            dr = cfg['40-70']
        else:
            dr = cfg['70-100']
        
        debit = width * dr
        profit = width - debit
        ratio = f"{profit/debit:.1f}:1" if debit > 0 else "N/A"
        
        return RiskRewardResult(
            width=round(width, 2), ivr=ivr, cost=round(debit, 2),
            max_profit=round(profit, 2), max_loss=round(debit, 2), ratio=ratio,
            formula=f"W={width:.1f}×{dr}={debit:.2f}"
        )
    
    # ------------- Pw 胜率 -------------
    
    def _calc_pw_credit(self, cluster: float, gap_em1: float, tech_score: float) -> WinProbResult:
        """信用价差胜率"""
        # 修复：使用 self.pw_config.credit
        cfg = self.pw_config.credit
        
        cluster = cluster or 1.0
        gap_em1 = gap_em1 or 2.0
        
        base = cfg.base
        c_adj = cfg.cluster_coef * cluster
        d_pen = cfg.distance_penalty_coef * gap_em1
        t_boost = 0.05 * tech_score if tech_score > 0 else 0
        
        raw = base + c_adj - d_pen + t_boost
        adj = max(cfg.min, min(cfg.max, raw))
        
        return WinProbResult(
            estimate=round(adj, 3),
            formula=f"{base}+{c_adj:.2f}-{d_pen:.2f}+{t_boost:.2f}={adj:.2f}",
            note=f"簇强{cluster:.1f}, 距离{gap_em1:.1f}×EM1$, Tech{tech_score}"
        )
    
    def _calc_pw_debit(self, dex_pct: float, vanna_conf: str, gap_em1: float) -> WinProbResult:
        """借贷价差胜率"""
        # 修复：使用 self.pw_config.debit
        cfg = self.pw_config.debit
        
        dex_pct = dex_pct or 0.5
        gap_em1 = gap_em1 or 2.0
        
        vanna_w = {'high': cfg.vanna_weight_high,
                   'medium': cfg.vanna_weight_medium,
                   'low': cfg.vanna_weight_low}.get(vanna_conf, cfg.vanna_weight_low)
        
        base = cfg.base
        d_adj = cfg.dex_coef * dex_pct
        v_adj = vanna_w * cfg.vanna_coef
        g_pen = -0.05 if gap_em1 > 3 else (-0.03 if gap_em1 > 2 else 0)
        
        raw = base + d_adj + v_adj + g_pen
        adj = max(cfg.min, min(cfg.max, raw))
        
        return WinProbResult(
            estimate=round(adj, 3),
            formula=f"{base}+{d_adj:.2f}+{v_adj:.2f}+{g_pen:.2f}={adj:.2f}",
            note=f"DEX{dex_pct*100:.0f}%, Vanna-{vanna_conf}"
        )
    
    def _calc_pw_butterfly(self, spot: float, body: float, em1: float, iv_path: str) -> WinProbResult:
        """蝶式胜率"""
        if not all([spot, body, em1]) or em1 == 0:
            return WinProbResult(estimate=0.5, formula="数据异常", note="参数不足")
        
        # 修复：使用 self.pw_config.butterfly
        cfg = self.pw_config.butterfly
        
        dist = abs(spot - body) / em1
        
        if dist < 0.3:
            pw_base, desc = cfg.body_inside, "body内"
        elif dist < 1.0:
            pw_base, desc = 0.55, "轻微偏离"
        else:
            pw_base, desc = cfg.body_offset_1em, "偏离1EM"
        
        iv_adj = -0.05 if iv_path == "升" else (0.05 if iv_path == "降" else 0)
        adj = max(0.3, min(0.75, pw_base + iv_adj))
        
        return WinProbResult(
            estimate=round(adj, 3),
            formula=f"dist={dist:.2f}({desc}), base={pw_base}, IV{iv_path}→{adj:.2f}",
            note=f"距离{dist:.2f}×EM1$, IV路径{iv_path}"
        )
    
    # ------------- Greeks 范围 -------------
    
    def _get_greeks_ranges(self) -> Dict:
        """各策略类型的 Greeks 目标"""
        # 修复：使用 self.greeks_config
        cfg = self.greeks_config
        
        return {
            "conservative": {
                "delta": [cfg.conservative.delta_min, cfg.conservative.delta_max],
                "theta_min": cfg.conservative.theta_min,
                "vega_max": cfg.conservative.vega_max,
                "desc": "接近中性Delta，正Theta，负Vega"
            },
            "balanced": {
                "delta_range": cfg.balanced.delta_range,
                "theta_min": cfg.balanced.theta_min,
                "desc": "轻微方向敞口，正Theta，Vega中性"
            },
            "aggressive": {
                "delta": [cfg.aggressive.delta_min, cfg.aggressive.delta_max],
                "vega_min": cfg.aggressive.vega_min,
                "desc": "明确方向Delta，可负Theta，正Vega"
            }
        }
    
    # ------------- 止盈止损 -------------
    
    def _get_exit_params(self) -> Dict:
        """止盈止损参数"""
        # 修复：使用 self.exit_config
        cfg = self.exit_config
        
        return {
            "credit": {
                "profit_pct": int(cfg.credit.profit_target_pct),
                "stop_pct": int(cfg.credit.stop_loss_pct),
                "time_exit_days": int(cfg.credit.time_decay_exit_days)
            },
            "debit": {
                "profit_pct": int(cfg.debit.profit_target_pct),
                "stop_pct": int(cfg.debit.stop_loss_pct),
                "time_exit_days": int(cfg.debit.time_decay_exit_days)
            },
            "time_management": {
                "exit_days_before_expiry": int(cfg.credit.time_decay_exit_days)
            }
        }