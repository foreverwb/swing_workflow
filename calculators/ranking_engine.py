"""
CODE4 - 策略排序引擎
负责：
1. 计算期望值 (EV)
2. 计算风险调整收益 (RAR)
3. 评估剧本匹配度
4. 流动性检查
5. 综合评分排序
"""

import json
from typing import Dict, List, Tuple, Any
from utils.logger import setup_logger

logger = setup_logger(__name__)


class RankingEngine:
    """策略排序引擎"""
    
    def __init__(self, config):
        self.config = config
    
    def rank_strategies(
        self, 
        strategies: Dict, 
        scenario_result: Dict, 
        validated_data: Dict
    ) -> Dict:
        """
        策略排序主函数
        
        Args:
            strategies: Agent 6 生成的策略列表
            scenario_result: Agent 5 的剧本分析结果
            validated_data: Agent 3 的数据校验结果
        
        Returns:
            排序结果字典
        """
        try:
            logger.info("🏆 开始策略排序...")
            
            # 提取数据
            strategy_list = strategies.get("strategies", [])
            spot = validated_data.get("targets", {}).get("spot_price", 0)
            em1 = validated_data.get("targets", {}).get("em1_dollar", 0)
            
            scenario_class = scenario_result.get("scenario_classification", {})
            primary_scenario = scenario_class.get("primary_scenario", "")
            scenario_probability = scenario_class.get("scenario_probability", 0)
            
            # 执行排序
            ranked_list = self._rank_strategies_internal(
                strategy_list, 
                primary_scenario, 
                scenario_probability, 
                spot, 
                em1
            )
            
            # 扁平化输出（提取 Top1/2/3）
            top1 = ranked_list[0] if ranked_list else {}
            top2 = ranked_list[1] if len(ranked_list) > 1 else {}
            top3 = ranked_list[2] if len(ranked_list) > 2 else {}
            
            result = {
                # 基础信息
                "symbol": validated_data.get("targets", {}).get("symbol", ""),
                "total_strategies": len(strategy_list),
                "positive_ev_count": sum(1 for r in ranked_list if r["ev"] > 0),
                "analysis_timestamp": self._get_timestamp(),
                
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
                
                # 完整排序列表（JSON 字符串，供 Agent 7 解析）
                "ranking_json": json.dumps(ranked_list, ensure_ascii=False)
            }
            
            logger.info(f"✅ 策略排序完成: Top1 = {result['top1_strategy_type']} (EV: {result['top1_ev']:.2f})")
            return result
            
        except Exception as e:
            logger.error(f"❌ 策略排序失败: {e}", exc_info=True)
            raise
    
    def _rank_strategies_internal(
        self, 
        strategies: List[Dict], 
        primary_scenario: str, 
        scenario_probability: int, 
        spot: float, 
        em1: float
    ) -> List[Dict]:
        """
        内部排序逻辑
        
        Args:
            strategies: 策略列表
            primary_scenario: 主导剧本
            scenario_probability: 剧本概率
            spot: 现价
            em1: EM1$
        
        Returns:
            排序后的策略列表（包含指标）
        """
        ranked = []
        
        for strategy in strategies:
            # 提取数据
            rr = strategy.get("rr_calculation", {})
            pw_calc = strategy.get("pw_calculation", {})
            
            max_profit = rr.get("max_profit", 0)
            max_loss = rr.get("max_loss", 0)
            pw_str = pw_calc.get("pw_estimate", "50%")
            
            # 解析 Pw
            pw = self._parse_pw(pw_str)
            
            # 计算指标
            ev = self._calculate_ev(pw, max_profit, max_loss)
            rar = self._calculate_rar(ev, max_loss)
            
            # 剧本匹配度
            scenario_match, match_reason = self._calculate_scenario_match(
                strategy.get("strategy_type", ""),
                primary_scenario,
                scenario_probability
            )
            
            # 流动性检查
            liquidity_pass, liquidity_note = self._check_liquidity(strategy, spot, em1)
            
            # 综合评分
            composite_score = self._calculate_composite_score(
                ev, rar, scenario_match, liquidity_pass
            )
            
            ranked.append({
                "strategy": strategy,
                "ev": round(ev, 2),
                "rar": round(rar, 3),
                "pw": pw,
                "scenario_match": scenario_match,
                "match_reason": match_reason,
                "liquidity_pass": liquidity_pass,
                "liquidity_note": liquidity_note,
                "composite_score": composite_score
            })
        
        # 按综合评分降序排序
        ranked.sort(key=lambda x: x["composite_score"], reverse=True)
        
        # 添加排名
        for i, item in enumerate(ranked):
            item["rank"] = i + 1
        
        return ranked
    
    # ============= 核心计算函数 =============
    
    def _calculate_ev(self, pw: float, max_profit: float, max_loss: float) -> float:
        """
        计算期望值 (Expected Value)
        
        公式: EV = Pw × MaxProfit - (1 - Pw) × MaxLoss
        """
        return pw * max_profit - (1 - pw) * max_loss
    
    def _calculate_rar(self, ev: float, max_loss: float) -> float:
        """
        计算风险调整收益 (Risk-Adjusted Return)
        
        公式: RAR = EV / MaxLoss
        """
        return ev / max_loss if max_loss > 0 else 0
    
    def _calculate_scenario_match(
        self, 
        strategy_type: str, 
        primary_scenario: str, 
        scenario_probability: int
    ) -> Tuple[str, str]:
        """
        计算剧本匹配度
        
        Returns:
            (match_level, reason)
            match_level: "高" | "中" | "低"
        """
        # 保守策略（信用价差/铁鹰）
        if strategy_type == "保守":
            if "区间" in primary_scenario and scenario_probability >= 60:
                return "高", f"区间剧本概率 {scenario_probability}%,信用策略完美匹配"
            elif "区间" in primary_scenario:
                return "中", f"区间剧本概率 {scenario_probability}% 略低,但仍适配"
            else:
                return "低", f"趋势剧本 {primary_scenario},区间策略不适配"
        
        # 均衡策略（借记价差）
        elif strategy_type == "均衡":
            if "趋势" in primary_scenario and scenario_probability >= 55:
                return "高", f"趋势剧本概率 {scenario_probability}%,借记策略适配"
            elif "区间" in primary_scenario:
                return "中", "区间剧本下可获取部分方向收益"
            else:
                return "低", "剧本不明确,方向策略风险大"
        
        # 进取策略（单腿）
        elif strategy_type == "进取":
            if "强趋势" in primary_scenario or scenario_probability >= 65:
                return "高", f"强确信场景({scenario_probability}%),单腿敞口可最大化收益"
            elif "趋势" in primary_scenario:
                return "中", "趋势初期,单腿风险较大"
            else:
                return "低", "非趋势场景,单腿时间价值流失快"
        
        return "低", "无法判断匹配度"
    
    def _check_liquidity(self, strategy: dict, spot: float, em1: float) -> Tuple[bool, str]:
        """
        流动性检查
        
        Returns:
            (pass, note)
        """
        legs = strategy.get("legs", [])
        
        # 检查 1: 腿部数量
        leg_count = len(legs)
        if leg_count > 4:
            return False, f"腿部数量 {leg_count} 过多,流动性风险高"
        
        # 检查 2: 行权价距离
        for leg in legs:
            strike = leg.get("strike")
            if not isinstance(strike, (int, float)):
                continue
            
            distance_em1 = abs(strike - spot) / em1 if em1 > 0 else 0
            
            if distance_em1 > 3:
                return False, f"{leg['type']} @ {strike} 距现价 {distance_em1:.1f}×EM1$,流动性不足"
        
        return True, "流动性达标"
    
    def _calculate_composite_score(
        self, 
        ev: float, 
        rar: float, 
        scenario_match: str, 
        liquidity_pass: bool
    ) -> int:
        """
        综合评分计算
        
        评分规则:
        - EV 评分 (40分)
        - RAR 评分 (30分)
        - 剧本匹配 (20分)
        - 流动性 (10分)
        
        Returns:
            综合评分 (0-100)
        """
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
        
        return score
    
    # ============= 辅助函数 =============
    
    def _parse_pw(self, pw_str: str) -> float:
        """
        解析 Pw 字符串
        
        支持格式:
        - "65%" -> 0.65
        - "约 50%" -> 0.5
        - "50-60%" -> 0.55 (取中间值)
        """
        try:
            # 去掉 "约" 和空格
            pw_str = pw_str.replace("约", "").strip()
            
            # 处理范围（如 "50-60%"）
            if "-" in pw_str:
                parts = pw_str.replace("%", "").split("-")
                return (float(parts[0]) + float(parts[1])) / 200
            
            # 处理百分比（如 "65%"）
            return float(pw_str.rstrip("%")) / 100
            
        except Exception as e:
            logger.warning(f"⚠️ Pw 解析失败: {pw_str}, 使用默认值 0.5")
            return 0.5
    
    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")