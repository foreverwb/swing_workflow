
import json
from typing import Dict, List, Tuple
from datetime import datetime

def calculate_ev(pw: float, max_profit: float, max_loss: float) -> float:
    """计算期望值"""
    return pw * max_profit - (1 - pw) * max_loss

def calculate_rar(ev: float, max_loss: float) -> float:
    """计算风险调整收益"""
    return ev / max_loss if max_loss > 0 else 0

def calculate_scenario_match(strategy_type: str, primary_scenario: str, 
                            scenario_probability: int) -> Tuple[str, str]:
    """计算剧本匹配度"""
    if strategy_type == "保守":
        if "区间" in primary_scenario and scenario_probability >= 60:
            return "高", f"区间剧本概率 {scenario_probability}%,信用策略完美匹配"
        elif "区间" in primary_scenario:
            return "中", f"区间剧本概率 {scenario_probability}% 略低,但仍适配"
        else:
            return "低", f"趋势剧本 {primary_scenario},区间策略不适配"
    
    elif strategy_type == "均衡":
        if "趋势" in primary_scenario and scenario_probability >= 55:
            return "高", f"趋势剧本概率 {scenario_probability}%,借记策略适配"
        elif "区间" in primary_scenario:
            return "中", "区间剧本下可获取部分方向收益"
        else:
            return "低", "剧本不明确,方向策略风险大"
    
    elif strategy_type == "进取":
        if "强趋势" in primary_scenario or scenario_probability >= 65:
            return "高", f"强确信场景({scenario_probability}%),单腿敞口可最大化收益"
        elif "趋势" in primary_scenario:
            return "中", "趋势初期,单腿风险较大"
        else:
            return "低", "非趋势场景,单腿时间价值流失快"
    
    return "低", "无法判断匹配度"

def check_liquidity(strategy: dict, spot: float, em1: float) -> Tuple[bool, str]:
    """流动性检查"""
    legs = strategy.get("legs", [])
    
    # 1. 检查腿部数量
    leg_count = len(legs)
    if leg_count > 4:
        return False, f"腿部数量 {leg_count} 过多,流动性风险高"
    
    # 2. 检查行权价距离
    for leg in legs:
        strike = leg.get("strike")
        if not isinstance(strike, (int, float)):
            continue
        
        distance_em1 = abs(strike - spot) / em1 if em1 > 0 else 0
        
        if distance_em1 > 3:
            return False, f"{leg['type']} @ {strike} 距现价 {distance_em1:.1f}×EM1$,流动性不足"
    
    return True, "流动性达标"

def rank_strategies(strategies: List[dict], primary_scenario: str, 
                    scenario_probability: int, spot: float, em1: float) -> List[dict]:
    """策略排序主函数"""
    ranked = []
    
    for strategy in strategies:
        # 提取数据
        rr = strategy.get("rr_calculation", {})
        pw_calc = strategy.get("pw_calculation", {})
        
        max_profit = rr.get("max_profit", 0)
        max_loss = rr.get("max_loss", 0)
        pw_str = pw_calc.get("pw_estimate", "50%")
        
        # 解析 Pw
        pw = 0.5
        try:
            if "约" in pw_str:
                pw = 0.4
            elif "-" in pw_str:
                parts = pw_str.replace("%", "").split("-")
                pw = (float(parts[0]) + float(parts[1])) / 200
            else:
                pw = float(pw_str.rstrip("%")) / 100
        except:
            pw = 0.5
        
        # 计算指标
        ev = calculate_ev(pw, max_profit, max_loss)
        rar = calculate_rar(ev, max_loss)
        
        scenario_match, match_reason = calculate_scenario_match(
            strategy.get("strategy_type", ""),
            primary_scenario,
            scenario_probability
        )
        
        liquidity_pass, liquidity_note = check_liquidity(strategy, spot, em1)
        
        # 综合评分
        score = 0
        
        # EV 评分 (40分)
        if ev > 0.5:
            score += 40
        elif ev > 0.2:
            score += 30
        elif ev > 0:
            score += 20
        
        # RAR 评分 (30分)
        if rar > 0.3:
            score += 30
        elif rar > 0.15:
            score += 25
        elif rar > 0.05:
            score += 15
        
        # 剧本匹配 (20分)
        if scenario_match == "高":
            score += 20
        elif scenario_match == "中":
            score += 10
        
        # 流动性 (10分)
        if liquidity_pass:
            score += 10
        
        ranked.append({
            "strategy": strategy,
            "ev": round(ev, 2),
            "rar": round(rar, 3),
            "pw": pw,
            "scenario_match": scenario_match,
            "match_reason": match_reason,
            "liquidity_pass": liquidity_pass,
            "liquidity_note": liquidity_note,
            "composite_score": score
        })
    
    # 排序
    ranked.sort(key=lambda x: x["composite_score"], reverse=True)
    
    for i, item in enumerate(ranked):
        item["rank"] = i + 1
    
    return ranked

def main(strategies_output: dict, scenario_output: dict, 
               agent3_output: dict, **env_vars) -> dict:
    try:
        strategies = strategies_output.get("strategies", [])
        spot = agent3_output.get("spot_price", 0)
        em1 = agent3_output.get("em1_dollar", 0)
        
        scenario_class = scenario_output.get("scenario_classification", {})
        primary_scenario = scenario_class.get("primary_scenario", "")
        scenario_probability = scenario_class.get("scenario_probability", 0)
        
        ranked = rank_strategies(
            strategies, 
            primary_scenario, 
            scenario_probability, 
            spot, 
            em1
        )
        
        # ✅ 关键改动：扁平化输出，提取第一名的关键指标
        top1 = ranked[0] if ranked else {}
        top2 = ranked[1] if len(ranked) > 1 else {}
        top3 = ranked[2] if len(ranked) > 2 else {}
        
        result = {
            # 基础信息
            "symbol": agent3_output.get("symbol", ""),
            "total_strategies": len(strategies),
            "positive_ev_count": sum(1 for r in ranked if r["ev"] > 0),
            "analysis_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            
            # Top1 策略（扁平化）
            "top1_rank": top1.get("rank", 0),
            "top1_strategy_type": top1.get("strategy", {}).get("strategy_type", ""),
            "top1_structure": top1.get("strategy", {}).get("structure", ""),
            "top1_ev": top1.get("ev", 0),
            "top1_rar": top1.get("rar", 0),
            "top1_pw": top1.get("pw", 0),
            "top1_scenario_match": top1.get("scenario_match", ""),
            "top1_match_reason": top1.get("match_reason", ""),
            "top1_liquidity_pass": top1.get("liquidity_pass", False),
            "top1_liquidity_note": top1.get("liquidity_note", ""),
            "top1_composite_score": top1.get("composite_score", 0),
            
            # Top2 策略（扁平化）
            "top2_rank": top2.get("rank", 0),
            "top2_strategy_type": top2.get("strategy", {}).get("strategy_type", ""),
            "top2_structure": top2.get("strategy", {}).get("structure", ""),
            "top2_ev": top2.get("ev", 0),
            "top2_rar": top2.get("rar", 0),
            "top2_composite_score": top2.get("composite_score", 0),
            
            # Top3 策略（扁平化）
            "top3_rank": top3.get("rank", 0),
            "top3_strategy_type": top3.get("strategy", {}).get("strategy_type", ""),
            "top3_structure": top3.get("strategy", {}).get("structure", ""),
            "top3_ev": top3.get("ev", 0),
            "top3_rar": top3.get("rar", 0),
            "top3_composite_score": top3.get("composite_score", 0),
            
            # 完整排序列表（序列化为 JSON 字符串）
            "ranking_json": json.dumps(ranked, ensure_ascii=False)
        }
        return { "result": json.dumps(result, ensure_ascii=False, indent=2) }
        
    except Exception as e:
        return {"result": {
            "error": True,
            "error_message": str(e)
        }}