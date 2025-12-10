"""
Code 4: 策略对比引擎 (重构版 - 修复配置访问)

变更:
1. 修复 self.cfg 未定义导致的 AttributeError
2. 内置默认评分阈值 (DEFAULT_THRESHOLDS)，解决配置缺失问题
3. 规范化配置访问方式
"""
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from utils.config_loader import config

# ============= 默认阈值配置 (兜底策略) =============
# 由于 env_config.yaml 中可能缺失这些具体的评分阈值，
# 在此定义默认值以防止 KeyError
DEFAULT_THRESHOLDS = {
    # EV (期望价值) 评分
    'EV_HIGH_THRESHOLD': 500,
    'EV_HIGH_SCORE': 25,
    'EV_MID_THRESHOLD': 200,
    'EV_MID_SCORE': 15,
    'EV_LOW_SCORE': 5,
    
    # RAR (风险调整后收益) 评分
    'RAR_HIGH_THRESHOLD': 0.5,  # 收益/最大亏损 > 0.5
    'RAR_HIGH_SCORE': 20,
    'RAR_MID_THRESHOLD': 0.2,
    'RAR_MID_SCORE': 10,
    'RAR_LOW_THRESHOLD': 0.1,
    'RAR_LOW_SCORE': 5,
    
    # 场景匹配评分
    'SCENARIO_HIGH_SCORE': 25,
    'SCENARIO_MID_SCORE': 10,
    
    # 流动性评分
    'LIQUIDITY_PASS_SCORE': 10,
    'MAX_LEGS': 4,
    'MAX_STRIKE_DISTANCE_EM1': 3.0,
    
    # 质量过滤惩罚
    'ZERO_DTE_HIGH_PENALTY': 20,
    'ZERO_DTE_MID_PENALTY': 10,
    'VETO_DIRECTIONAL_ZERO': True,
    'BIAS_MISMATCH_PENALTY': 15
}

# ============= 数据类定义 =============

@dataclass
class StrategyMetrics:
    """单个策略的评估指标"""
    rank: int = 0
    strategy_type: str = ""
    structure: str = ""
    ev: float = 0.0
    rar: float = 0.0
    pw: float = 0.5
    scenario_match: str = "低"
    match_reason: str = ""
    liquidity_pass: bool = True
    liquidity_note: str = ""
    composite_score: float = 0.0
    quality_adjustment: float = 0.0  # 质量过滤调整分
    quality_notes: List[str] = field(default_factory=list)


@dataclass
class QualityFilter:
    """质量过滤结果"""
    filters_triggered: List[str] = field(default_factory=list)
    total_penalty: float = 0.0
    overall_confidence: float = 1.0
    zero_dte_ratio: Optional[float] = None
    is_vetoed: bool = False
    strategy_bias: str = "Neutral"


# ============= 主入口函数 =============

def main(strategies_output: dict, scenario_output: dict, 
         agent3_output: dict, **env_vars) -> dict:
    """
    Code 4 主入口
    """
    try:
        # 兼容处理：如果是字符串则解析，如果是字典则直接使用
        if isinstance(strategies_output, str):
            strategies_output = json.loads(strategies_output)
        if isinstance(scenario_output, str):
            scenario_output = json.loads(scenario_output)
        if isinstance(agent3_output, str):
            agent3_output = json.loads(agent3_output)

        engine = ComparisonEngine(env_vars)
        return engine.process(strategies_output, scenario_output, agent3_output)
    except Exception as e:
        import traceback
        import json
        return {
            "error": True,
            "message": str(e),
            "traceback": traceback.format_exc()
        }


# ============= 对比引擎 =============

class ComparisonEngine:
    """策略对比引擎 (重构版)"""
    
    def __init__(self, env_vars: Dict):
        # 加载配置（保留原有逻辑，增加默认阈值）
        self.scoring_config = config.get_section('scoring')
        self.rr_config = config.get_section('rr_calculation')
        
        # 使用默认阈值，实际项目中建议将其移入 env_config.yaml
        self.thresholds = DEFAULT_THRESHOLDS
    
    # ------------- 主处理流程 -------------
    
    def process(self, strategies_output: dict, scenario_output: dict, 
                agent3_output: dict) -> dict:
        """主处理流程"""
        # 提取输入
        strategies = strategies_output.get("strategies", [])
        
        # 兼容 meta 信息位置
        meta = agent3_output.get("meta", {})
        spot = agent3_output.get("spot_price", 0) or meta.get("spot", 0)
        em1 = agent3_output.get("em1_dollar", 0) or meta.get("em1", 0)
        symbol = agent3_output.get("symbol", "UNKNOWN")
        
        # 场景信息 (兼容 agent5 和 code3 格式)
        scenario_class = scenario_output.get("scenario_classification", {})
        if not scenario_class:
            # 尝试从 meta 中获取（如果是 Code 3 透传）
            scenario_meta = scenario_output.get("meta", {})
            scenario_class = {
                "primary_scenario": scenario_meta.get("primary_scenario", ""),
                "scenario_probability": scenario_meta.get("scenario_probability", 0)
            }
            
        primary_scenario = scenario_class.get("primary_scenario", "")
        scenario_prob = scenario_class.get("scenario_probability", 0)
        
        # 提取 validation_flags (来自 code3)
        # 注意：Code 3 输出结构中 validation 可能在根节点
        validation = agent3_output.get("validation", {})
        quality_filter = self._process_quality_filter(validation)
        
        # 排序策略
        ranked = self._rank_strategies(
            strategies, primary_scenario, scenario_prob, 
            spot, em1, quality_filter, validation
        )
        
        # 提取 Top 3
        top3 = [self._extract_metrics(r, i+1) for i, r in enumerate(ranked[:3])]
        
        # 组装输出
        return {
            "symbol": symbol,
            "total_strategies": len(strategies),
            "positive_ev_count": sum(1 for r in ranked if r.get("ev", 0) > 0),
            "analysis_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "quality_filter": asdict(quality_filter),
            "top3": [asdict(m) for m in top3],
            "ranking": ranked
        }
    
    # ------------- 质量过滤 -------------
    
    def _process_quality_filter(self, validation: Dict) -> QualityFilter:
        """处理质量过滤"""
        qf = QualityFilter()
        cfg = self.thresholds
        
        zero_dte = validation.get("zero_dte_ratio")
        is_vetoed = validation.get("is_vetoed", False)
        strategy_bias = validation.get("strategy_bias", "Neutral")
        
        qf.zero_dte_ratio = zero_dte
        qf.is_vetoed = is_vetoed
        qf.strategy_bias = strategy_bias
        
        # 0DTE 噪音
        if zero_dte is not None:
            if zero_dte > 0.5:
                qf.filters_triggered.append("0DTE_HIGH")
                qf.total_penalty += cfg['ZERO_DTE_HIGH_PENALTY']
            elif zero_dte > 0.3:
                qf.filters_triggered.append("0DTE_MID")
                qf.total_penalty += cfg['ZERO_DTE_MID_PENALTY']
        
        # 量价背离
        if is_vetoed:
            qf.filters_triggered.append("VOLUME_DIVERGENCE")
        
        # 计算整体置信度
        confidence_penalty = validation.get("confidence_penalty", 0)
        qf.overall_confidence = 1.0 - confidence_penalty
        
        return qf
    
    # ------------- 策略排序 -------------
    
    def _rank_strategies(self, strategies: List[dict], primary_scenario: str,
                         scenario_prob: int, spot: float, em1: float,
                         quality_filter: QualityFilter, validation: Dict) -> List[dict]:
        """策略排序"""
        ranked = []
        
        for strategy in strategies:
            # 基础指标计算
            metrics = self._calc_base_metrics(strategy, primary_scenario, scenario_prob, spot, em1)
            
            # 应用质量过滤
            quality_adj, quality_notes = self._apply_quality_filter(
                strategy, quality_filter, validation, metrics
            )
            metrics["quality_adjustment"] = quality_adj
            metrics["quality_notes"] = quality_notes
            metrics["composite_score"] += quality_adj
            
            # 确保分数不为负
            metrics["composite_score"] = max(0, metrics["composite_score"])
            
            ranked.append(metrics)
        
        # 排序
        ranked.sort(key=lambda x: x["composite_score"], reverse=True)
        for i, item in enumerate(ranked):
            item["rank"] = i + 1
        
        return ranked
    
    def _calc_base_metrics(self, strategy: dict, primary_scenario: str,
                           scenario_prob: int, spot: float, em1: float) -> dict:
        """计算基础指标"""
        cfg = self.thresholds
        
        # 提取 RR 和 Pw
        # Agent 6 输出的结构通常在 quant_metrics 中
        quant = strategy.get("quant_metrics", {})
        
        # 尝试解析 max_profit/loss (可能是字符串或数字)
        max_profit = self._parse_currency(quant.get("max_profit", 0))
        max_loss = self._parse_currency(quant.get("max_loss", 0))
        
        # 解析胜率
        pw_str = quant.get("pw_estimate", "50%")
        pw = self._parse_pw(pw_str)
        
        # EV 和 RAR
        ev = pw * max_profit - (1 - pw) * max_loss
        rar = ev / max_loss if max_loss > 0 else 0
        
        # 剧本匹配
        strategy_type = strategy.get("strategy_type", "")
        scenario_match, match_reason = self._calc_scenario_match(
            strategy_type, primary_scenario, scenario_prob
        )
        
        # 流动性
        liquidity_pass, liquidity_note = self._check_liquidity(strategy, spot, em1)
        
        # 计算得分
        score = 0
        
        # EV 得分
        if ev > cfg['EV_HIGH_THRESHOLD']:
            score += cfg['EV_HIGH_SCORE']
        elif ev > cfg['EV_MID_THRESHOLD']:
            score += cfg['EV_MID_SCORE']
        elif ev > 0:
            score += cfg['EV_LOW_SCORE']
        
        # RAR 得分
        if rar > cfg['RAR_HIGH_THRESHOLD']:
            score += cfg['RAR_HIGH_SCORE']
        elif rar > cfg['RAR_MID_THRESHOLD']:
            score += cfg['RAR_MID_SCORE']
        elif rar > cfg['RAR_LOW_THRESHOLD']:
            score += cfg['RAR_LOW_SCORE']
        
        # 剧本匹配得分
        if scenario_match == "高":
            score += cfg['SCENARIO_HIGH_SCORE']
        elif scenario_match == "中":
            score += cfg['SCENARIO_MID_SCORE']
        
        # 流动性得分
        if liquidity_pass:
            score += cfg['LIQUIDITY_PASS_SCORE']
        
        return {
            "strategy": strategy,
            "ev": round(ev, 2),
            "rar": round(rar, 3),
            "pw": pw,
            "scenario_match": scenario_match,
            "match_reason": match_reason,
            "liquidity_pass": liquidity_pass,
            "liquidity_note": liquidity_note,
            "composite_score": score
        }
    
    def _apply_quality_filter(self, strategy: dict, qf: QualityFilter,
                               validation: Dict, metrics: dict) -> Tuple[float, List[str]]:
        """应用质量过滤，返回调整分和说明"""
        cfg = self.thresholds
        adjustment = 0.0
        notes = []
        
        strategy_type = strategy.get("strategy_type", "")
        is_directional = any(kw in strategy_type.lower() for kw in 
                            ["call", "put", "bull", "bear", "long", "short", "directional"])
        is_credit = any(kw in strategy_type.lower() for kw in 
                       ["iron", "condor", "butterfly", "credit", "income"])
        is_debit = any(kw in strategy_type.lower() for kw in 
                      ["debit", "straddle", "strangle"])
        
        # 1. 量价背离 - 方向策略归零
        if qf.is_vetoed and is_directional and cfg['VETO_DIRECTIONAL_ZERO']:
            adjustment = -metrics["composite_score"]  # 归零
            notes.append("⛔ 量价背离，方向策略禁用")
        
        # 2. 0DTE 噪音 - 短期策略扣分
        # 尝试获取 DTE
        dte = 0
        legs = strategy.get("legs", [])
        if legs:
            dte = legs[0].get("expiry_dte", 0)
            
        if "0DTE_HIGH" in qf.filters_triggered and dte > 0 and dte < 3:
            adjustment -= cfg['ZERO_DTE_HIGH_PENALTY']
            notes.append(f"⚠️ 0DTE噪音高，DTE={dte}短期策略风险大")
        elif "0DTE_MID" in qf.filters_triggered and dte > 0 and dte < 3:
            adjustment -= cfg['ZERO_DTE_MID_PENALTY']
            notes.append(f"⚠️ 0DTE中度噪音，DTE={dte}")
        
        # 3. 策略偏好不匹配
        bias = qf.strategy_bias
        if bias == "Credit_Favored" and is_debit:
            adjustment -= cfg['BIAS_MISMATCH_PENALTY']
            notes.append("策略偏好Credit，但选择了Debit策略")
        elif bias == "Debit_Favored" and is_credit:
            adjustment -= cfg['BIAS_MISMATCH_PENALTY']
            notes.append("策略偏好Debit，但选择了Credit策略")
        
        return adjustment, notes
    
    # ------------- 辅助方法 -------------
    
    def _parse_currency(self, value) -> float:
        """解析货币字符串"""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # 移除 $ , 等字符
            clean = value.replace('$', '').replace(',', '').strip()
            try:
                return float(clean)
            except:
                return 0.0
        return 0.0

    def _parse_pw(self, pw_str: str) -> float:
        """解析胜率字符串"""
        if not pw_str:
            return 0.5
        try:
            # 处理 "约50%" 格式
            if "约" in pw_str:
                return 0.4
            # 处理 "50-60%" 范围格式
            if "-" in pw_str:
                parts = pw_str.replace("%", "").split("-")
                return (float(parts[0]) + float(parts[1])) / 200
            # 处理 "50%" 或 "0.5" 格式
            cleaned = pw_str.rstrip("%").strip()
            val = float(cleaned)
            return val / 100 if val > 1 else val
        except:
            return 0.5
    
    def _calc_scenario_match(self, strategy_type: str, primary_scenario: str,
                              scenario_prob: int) -> Tuple[str, str]:
        """计算剧本匹配度"""
        st = strategy_type.lower() if strategy_type else ""
        ps = primary_scenario.lower() if primary_scenario else ""
        
        # 保守策略 (Iron Condor, Butterfly)
        if any(kw in st for kw in ["保守", "condor", "butterfly", "iron", "income"]):
            if ("区间" in ps or "range" in ps) and scenario_prob >= 60:
                return "高", f"区间剧本{scenario_prob}%，信用策略完美匹配"
            elif "区间" in ps or "range" in ps:
                return "中", f"区间剧本{scenario_prob}%略低，但仍适配"
            else:
                return "低", f"趋势剧本，区间策略风险较大"
        
        # 均衡策略 (Spread)
        if any(kw in st for kw in ["均衡", "spread", "vertical"]):
            if ("趋势" in ps or "trend" in ps) and scenario_prob >= 55:
                return "高", f"趋势剧本{scenario_prob}%，价差策略适配"
            elif "区间" in ps:
                return "中", "区间剧本下可获取部分方向收益"
            else:
                return "低", "剧本不明确，方向策略风险大"
        
        # 进取策略 (Long Call/Put, Straddle)
        if any(kw in st for kw in ["进取", "long call", "long put", "straddle"]):
            if ("强趋势" in ps or "breakout" in ps) or scenario_prob >= 65:
                return "高", f"强确信场景{scenario_prob}%，单腿可最大化收益"
            elif "趋势" in ps:
                return "中", "趋势初期，单腿风险较大"
            else:
                return "低", "非趋势场景，单腿时间价值流失快"
        
        # WAIT 策略
        if "wait" in st:
            if scenario_prob < 50:
                return "高", "市场混沌，观望最佳"
            else:
                return "中", "有一定机会但选择观望"

        return "中", "通用策略"
    
    def _check_liquidity(self, strategy: dict, spot: float, em1: float) -> Tuple[bool, str]:
        """流动性检查"""
        cfg = self.thresholds
        legs = strategy.get("legs", [])
        
        # 腿数检查
        if len(legs) > cfg['MAX_LEGS']:
            return False, f"腿部数量{len(legs)}过多，流动性风险高"
        
        # 行权价距离检查
        if em1 <= 0:
            return True, "EM1$数据缺失，跳过距离检查"
        
        for leg in legs:
            strike = leg.get("strike")
            if not isinstance(strike, (int, float)):
                continue
            
            distance = abs(strike - spot) / em1
            if distance > cfg['MAX_STRIKE_DISTANCE_EM1']:
                leg_type = leg.get("type", leg.get("option_type", ""))
                return False, f"{leg_type}@{strike} 距现价{distance:.1f}×EM1$，流动性不足"
        
        return True, "流动性达标"
    
    def _extract_metrics(self, ranked_item: dict, rank: int) -> StrategyMetrics:
        """从排序结果提取指标"""
        strategy = ranked_item.get("strategy", {})
        return StrategyMetrics(
            rank=rank,
            strategy_type=strategy.get("strategy_type", ""),
            structure=strategy.get("structure", ""),
            ev=ranked_item.get("ev", 0),
            rar=ranked_item.get("rar", 0),
            pw=ranked_item.get("pw", 0.5),
            scenario_match=ranked_item.get("scenario_match", ""),
            match_reason=ranked_item.get("match_reason", ""),
            liquidity_pass=ranked_item.get("liquidity_pass", True),
            liquidity_note=ranked_item.get("liquidity_note", ""),
            composite_score=ranked_item.get("composite_score", 0),
            quality_adjustment=ranked_item.get("quality_adjustment", 0),
            quality_notes=ranked_item.get("quality_notes", [])
        )