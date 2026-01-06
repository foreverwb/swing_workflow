"""
Code 2: 评分引擎
适配单例配置
"""
import json
from typing import Dict, Any, Tuple
from utils.config_loader import config 
from utils.formatters import F
import traceback
from loguru import logger

def main(agent3_output: dict, technical_score: float = 0, **env_vars) -> dict:
    """
    Dify Code Node 入口函数
    """
    try:
        if isinstance(agent3_output, str):
            agent3_output = json.loads(agent3_output)
            
        scoring = OptionsScoring(env_vars)    
        result = scoring.process(agent3_output)
        return result
        
    except Exception as e:
        
        logger.error(f"❌ Scoring calculation failed")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        
        error_result = {
            "error": True,
            "error_message": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()  
        }
        return {
            "result": json.dumps(error_result, ensure_ascii=False, indent=2)
        }


class OptionsScoring:
    """期权量化评分计算引擎"""
    
    def __init__(self, env_vars: Dict[str, Any]):
        """
        初始化环境变量阈值
        """
        self.conf = config.scoring
        self.env_gamma = config.gamma
        self.env_dir = config.direction
        self.pw_config = config.get_section('pw_calculation')
        self.market_params = env_vars.get('market_params', {})
        self.dynamic_weights_config = self.conf.dynamic_weights
    
    def get_dynamic_weights(self, ivr: float = None) -> Tuple[Dict[str, float], str, str]:
        if ivr is None:
            ivr = self.market_params.get('ivr') or 50.0
        
        dw = self.dynamic_weights_config
        
        if ivr > dw.panic.ivr_threshold:
            weights = {
                'GAMMA': dw.panic.gamma,
                'BREAK': dw.panic.get('break', 0.2),
                'DIR': dw.panic.direction,
                'IV': dw.panic.iv
            }
            regime = 'panic'
            description = dw.panic.description
            
        elif ivr < dw.calm.ivr_threshold:
            weights = {
                'GAMMA': dw.calm.gamma,
                'BREAK': dw.calm.get('break'),
                'DIR': dw.calm.direction,
                'IV': dw.calm.iv
            }
            regime = 'calm'
            description = dw.calm.description
            
        else:
            weights = {
                'GAMMA': dw.normal.gamma,
                'BREAK': dw.normal.get('break'),
                'DIR': dw.normal.direction,
                'IV': dw.normal.iv
            }
            regime = 'normal'
            description = dw.normal.description
        
        return weights, regime, description
    
    def calculate_gamma_regime_score(self, gamma_metrics: Dict) -> Dict:
        spot = gamma_metrics.get('spot_price', 0)
        vol_trigger = gamma_metrics.get('vol_trigger', 0)
        spot_vs_trigger = gamma_metrics.get('spot_vs_trigger', 'unknown')
        
        if spot_vs_trigger == "above":
            base_scenario = "区间"
            regime_note = f"现价{spot}在VOL_TRIGGER {vol_trigger}上方，正γ倾向，做市商压制波动维持区间"
            score = 7
            rationale = "明确above状态给7分"
        elif spot_vs_trigger == "below":
            base_scenario = "趋势"
            regime_note = f"现价{spot}在VOL_TRIGGER {vol_trigger}下方，负γ倾向，做市商放大波动趋势加速"
            score = 7
            rationale = "明确below状态给7分"
        else:
            base_scenario = "过渡"
            regime_note = f"现价{spot}接近VOL_TRIGGER {vol_trigger}，临界状态，可能Gamma翻转高波动"
            score = 4
            rationale = "临界near状态给4分，警示风险"
            
        return {
            "score": score,
            "base_scenario": base_scenario,
            "regime_note": regime_note,
            "rationale": rationale
        }
    
    def calculate_break_wall_score(self, gamma_metrics: Dict) -> Dict:
        gap_distance = gamma_metrics.get('gap_distance_em1_multiple', 999)
        cluster_strength = gamma_metrics.get('cluster_strength_ratio', 0)
        monthly_override = gamma_metrics.get('monthly_cluster_override', False)
        spot_vs_trigger = gamma_metrics.get('spot_vs_trigger', 'unknown')
        
        if monthly_override:
            threshold = self.env_gamma.monthly_override_threshold
            threshold_note = f"月度簇强度≥周度{self.env_gamma.monthly_cluster_strength_ratio}倍"
        else:
            threshold = self.env_gamma.break_wall_threshold_high
            threshold_note = f"标准阈值{threshold}×EM1$"
        
        if gap_distance < self.env_gamma.break_wall_threshold_low:
            break_probability = "高"
            base_score = 9
            prob_desc = "距离近"
        elif gap_distance < self.env_gamma.break_wall_threshold_high:
            break_probability = "中"
            base_score = 6
            prob_desc = "距离适中"
        else:
            break_probability = "低"
            base_score = 3
            prob_desc = "距离远"
        
        if cluster_strength >= self.env_gamma.cluster_strength_threshold_s:
            adjustment = -1
            cluster_note = f"簇强度{cluster_strength:.2f}≥{self.env_gamma.cluster_strength_threshold_s}，主墙极强"
            cluster_desc = "极强阻力"
        elif cluster_strength >= self.env_gamma.cluster_strength_threshold_t:
            adjustment = 0
            cluster_note = f"簇强度{cluster_strength:.2f}在{self.env_gamma.cluster_strength_threshold_t}-{self.env_gamma.cluster_strength_threshold_s}，中等强度"
            cluster_desc = "中等阻力"
        else:
            adjustment = 1
            cluster_note = f"簇强度{cluster_strength:.2f}<{self.env_gamma.cluster_strength_threshold_t}，较易突破"
            cluster_desc = "较弱阻力"
        
        final_score = max(1, min(10, base_score + adjustment))
        wall_direction = "Call Wall" if spot_vs_trigger == 'above' else "Put Wall"
        
        break_note = (
            f"需{gap_distance:.2f}倍EM1$距离到达{wall_direction}，"
            f"{cluster_note}，破墙难度"
            f"{'高' if final_score < 5 else '中' if final_score < 7 else '低'}"
        )
        
        rationale = (
            f"gap_distance {gap_distance:.2f}({prob_desc})给{base_score}分，"
            f"cluster {cluster_strength:.2f}({cluster_desc})调整{F.int(adjustment, signed=True)}分"
        )
        
        return {
            "score": final_score,
            "break_probability": break_probability,
            "threshold": threshold,
            "threshold_note": threshold_note,
            "break_note": break_note,
            "rationale": rationale,
            "gap_distance_em1": gap_distance,
            "cluster_strength": cluster_strength,
            "monthly_override": monthly_override
        }
    
    def calculate_direction_score(self, directional_metrics: Dict) -> Dict:
        """
        计算方向评分
        
        DEX评分规则：
        - dex_bias=support + dex_bias_strength=strong → 强方向 (9分)
        - dex_bias=support + dex_bias_strength=mid → 中等方向 (6分)
        - dex_bias=mixed → 模糊 (5分)
        - dex_bias=oppose → 弱方向 (3分)
        """
        dex_bias = directional_metrics.get('dex_bias', 'mixed')
        dex_strength = directional_metrics.get('dex_bias_strength', 'weak')
        vanna_dir = directional_metrics.get('vanna_dir', 'neutral')
        vanna_confidence = directional_metrics.get('vanna_confidence', 'low')
        pw_debit = self.pw_config.get('debit')
        
        vanna_weight_map = {
            'high': pw_debit.vanna_weight_high,
            'medium': pw_debit.vanna_weight_medium,
            'low': pw_debit.vanna_weight_low
        }
        vanna_weight = vanna_weight_map.get(vanna_confidence, 0.3)
        
        # DEX方向评估
        has_strong_dex = (dex_bias == 'support' and dex_strength == 'strong')
        has_medium_dex = (dex_bias == 'support' and dex_strength == 'medium')
        has_mixed_dex = (dex_bias == 'mixed')
        has_oppose_dex = (dex_bias == 'oppose')
        
        has_clear_vanna = vanna_dir in ['up', 'down']
        has_medium_vanna = vanna_weight >= pw_debit.vanna_weight_medium
        
        # 评分逻辑
        if has_strong_dex and has_clear_vanna and has_medium_vanna:
            direction_strength = "强方向信号"
            score = 9
            strength_desc = "DEX强支持+Vanna高置信"
        elif has_medium_dex or vanna_weight == pw_debit.vanna_weight_medium:
            direction_strength = "中等方向信号"
            score = 6
            strength_desc = "DEX中等支持或Vanna中等置信"
        elif has_mixed_dex:
            direction_strength = "模糊信号"
            score = 5
            strength_desc = "DEX混合信号"
        elif has_oppose_dex or vanna_confidence == 'low':
            direction_strength = "弱方向信号"
            score = 3
            strength_desc = "DEX反向或Vanna低置信"
        else:
            direction_strength = "中等偏弱信号"
            score = 5
            strength_desc = "信号模糊"
        
        # DEX评估文本
        if has_strong_dex:
            dex_eval = "强支持"
        elif has_medium_dex:
            dex_eval = "中等支持"
        elif has_mixed_dex:
            dex_eval = "混合"
        else:
            dex_eval = "反向"
        
        direction_note = (
            f"DEX偏向{dex_bias}/{dex_strength}({dex_eval})，"
            f"Vanna方向{vanna_dir}且置信度{vanna_confidence}权重{vanna_weight:.1f}，"
            f"综合{direction_strength}"
        )
        rationale = f"dex {dex_bias}/{dex_strength}+vanna {vanna_confidence}({strength_desc})综合给{score}分"
        
        return {
            "score": score,
            "direction_strength": direction_strength,
            "vanna_weight": vanna_weight,
            "direction_note": direction_note,
            "rationale": rationale,
            "dex_bias": dex_bias,
            "dex_bias_strength": dex_strength,
            "vanna_dir": vanna_dir,
            "vanna_confidence": vanna_confidence
        }
    
    def calculate_iv_score(self, directional_metrics: Dict) -> Dict:
        iv_path = directional_metrics.get('iv_path', 'Flat')  # '平' → 'Flat'
        iv_confidence = directional_metrics.get('iv_path_confidence', 'low')
        
        if iv_path == "Rising" and iv_confidence in ['high', 'medium']:  # "升" → "Rising"
            iv_signal = "波动率扩张"
            note = "利多波动率策略"
            score = 8 if iv_confidence == 'high' else 6
            conf_desc = "高置信" if iv_confidence == 'high' else "中等置信"
        elif iv_path == "Falling":  # "降" → "Falling"
            iv_signal = "波动率压缩"
            note = "利空波动率"
            if iv_confidence == 'high': score = 3; conf_desc = "高置信下降"
            elif iv_confidence == 'medium': score = 4; conf_desc = "中等置信下降"
            else: score = 5; conf_desc = "低置信下降"
        else:  # "Flat" 或 "Insufficient_Data"
            iv_signal = "中性"
            note = "波动率稳定或数据不足"
            score = 5
            conf_desc = "平稳或不确定"
        
        iv_note = f"IV路径显示{iv_path}趋势，置信度{iv_confidence}, {note}"
        rationale = f"iv_path {iv_path}且confidence {iv_confidence}({conf_desc})给{score}分"
        
        return {
            "score": score,
            "iv_signal": iv_signal,
            "iv_note": iv_note,
            "rationale": rationale,
            "iv_path": iv_path,
            "iv_path_confidence": iv_confidence
        }
    
    def calculate_index_consistency_score(self, gamma_metrics: Dict, directional_metrics: Dict, indices: Dict) -> Dict:
        base_score = 5
        adjustment = 0
        consistency_note = []
        
        threshold_ratio = self.conf.index_gap_threshold_ratio
        conflict_penalty = self.conf.index_conflict_penalty
        consistency_bonus = self.conf.index_consistency_bonus
        
        if not indices or not isinstance(indices, dict):
            return {
                "score": base_score,
                "consistency_level": "无数据",
                "consistency_note": "未提供指数背景数据，给予中性评分",
                "rationale": "缺失指数数据，默认5分",
                "primary_index": "N/A",
                "index_net_gex": "N/A",
                "adjustment": 0
            }
        
        primary_index = None
        primary_symbol = None
        for idx_symbol in ['SPX', 'QQQ']:
            if idx_symbol in indices:
                primary_index = indices[idx_symbol]
                primary_symbol = idx_symbol
                break
        if not primary_index:
            primary_symbol = list(indices.keys())[0]
            primary_index = indices[primary_symbol]
        
        idx_net_gex = primary_index.get('net_gex_idx', '')
        idx_em1 = primary_index.get('em1_dollar_idx', 0)
        stock_spot_vs_trigger = gamma_metrics.get('spot_vs_trigger', '')
        stock_gap_distance = gamma_metrics.get('gap_distance_dollar', 0)
        stock_iv_path = directional_metrics.get('iv_path', 'Flat')
        stock_dex_bias = directional_metrics.get('dex_bias', 'mixed')
        
        if idx_net_gex == 'positive_gamma' and stock_spot_vs_trigger == 'above':
            if stock_iv_path in ['Flat', 'Falling']:
                adjustment += consistency_bonus
                consistency_note.append(f"{primary_symbol}正γ且个股在墙上，IV{stock_iv_path}符合区间预期")
            else:
                consistency_note.append(f"{primary_symbol}正γ但IV{stock_iv_path}，区间信号减弱")
        
        if idx_net_gex == 'negative_gamma':
            if idx_em1 > 0:
                threshold = threshold_ratio * idx_em1
                if stock_gap_distance >= threshold:
                    iv_cooperates = (
                        (stock_spot_vs_trigger == 'below' and stock_iv_path == 'Rising') or
                        (stock_spot_vs_trigger == 'above' and stock_iv_path == 'Falling')
                    )
                    if iv_cooperates:
                        adjustment += consistency_bonus
                        consistency_note.append(f"{primary_symbol}负γ，个股破墙{stock_gap_distance:.1f}≥{threshold:.1f}，IV配合")
                    else:
                        consistency_note.append(f"{primary_symbol}负γ，个股破墙充足但IV路径{stock_iv_path}不完全配合")
                else:
                    consistency_note.append(f"{primary_symbol}负γ，但个股破墙距离{stock_gap_distance:.1f}不足")
            else:
                consistency_note.append(f"{primary_symbol}负γ但EM1_idx缺失")
        
        if idx_net_gex == 'negative_gamma' and stock_dex_bias == 'oppose':
            adjustment += conflict_penalty
            consistency_note.append(f"⚠️ {primary_symbol}负γ趋势强，但个股DEX反向信号冲突")
        
        if idx_net_gex == 'positive_gamma' and stock_spot_vs_trigger == 'below':
            if idx_em1 > 0 and stock_gap_distance > idx_em1:
                adjustment += conflict_penalty
                consistency_note.append(f"⚠️ {primary_symbol}正γ区间，但个股深陷负γ区{stock_gap_distance:.1f}>{idx_em1:.1f}EM1")
        
        final_score = max(1, min(10, base_score + adjustment))
        
        if adjustment > 0: consistency_level = "强一致"
        elif adjustment == 0: consistency_level = "中性"
        else: consistency_level = "冲突"
        
        full_note = f"参考{primary_symbol}背景（NET-GEX={idx_net_gex}）：" + "；".join(consistency_note)
        rationale = f"基础5分，指数一致性调整{F.int(adjustment, signed=True)}分 → {final_score}分"
        
        return {
            "score": final_score,
            "consistency_level": consistency_level,
            "consistency_note": full_note,
            "rationale": rationale,
            "primary_index": primary_symbol,
            "index_net_gex": idx_net_gex,
            "adjustment": adjustment
        }

    def calculate_total_score(self, scores: Dict) -> Dict:
        gamma_score = scores['gamma']['score']
        break_score = scores['break_wall']['score']
        direction_score = scores['direction']['score']
        iv_score = scores['iv']['score']
        index_score = scores['index_consistency']['score']
        
        ivr = self.market_params.get('ivr') or 50.0
        dynamic_weights, weight_regime, regime_description = self.get_dynamic_weights(ivr)
        
        index_weight = self.conf.weight_index_consistency
        
        scale_factor = 1.0 - index_weight
        w = {
            'GAMMA': dynamic_weights['GAMMA'] * scale_factor,
            'BREAK': dynamic_weights['BREAK'] * scale_factor,
            'DIR': dynamic_weights['DIR'] * scale_factor,
            'IV': dynamic_weights['IV'] * scale_factor,
            'INDEX': index_weight
        }
        
        total = (
            gamma_score * w['GAMMA'] +
            break_score * w['BREAK'] +
            direction_score * w['DIR'] +
            iv_score * w['IV'] +
            index_score * w['INDEX']
        )
        
        breakdown = (
            f"[{weight_regime}] "
            f"Gamma:{gamma_score}×{w['GAMMA']:.2f}+"
            f"Break:{break_score}×{w['BREAK']:.2f}+"
            f"Dir:{direction_score}×{w['DIR']:.2f}+"
            f"IV:{iv_score}×{w['IV']:.2f}+"
            f"Index:{index_score}×{w['INDEX']:.2f}="
            f"{total:.1f}"
        )
        
        return {
            "total_score": round(total, 1),
            "weight_breakdown": breakdown,
            "weight_regime": weight_regime,
            "regime_description": regime_description,
            "ivr_used": ivr,
            "applied_weights": {
                "gamma": round(w['GAMMA'], 3),
                "break": round(w['BREAK'], 3),
                "direction": round(w['DIR'], 3),
                "iv": round(w['IV'], 3),
                "index": round(w['INDEX'], 3)
            }
        }
    
    def check_entry_conditions(self, target_data: Dict, total_score: float) -> Dict:
        gamma = target_data.get('gamma_metrics', {})
        directional = target_data.get('directional_metrics', {})
        
        conditions_met = []
        conditions_failed = []
        
        spot_vs_trigger = gamma.get('spot_vs_trigger', 'unknown')
        if spot_vs_trigger in ['above', 'below']:
            conditions_met.append(f"条件1: spot_vs_trigger={spot_vs_trigger}明确")
        else:
            conditions_failed.append(f"条件1: spot_vs_trigger={spot_vs_trigger}临界状态")
        
        gap = gamma.get('gap_distance_em1_multiple', 999)
        if gap < 2:
            conditions_met.append(f"条件2: gap_distance_em1={gap:.2f}<2")
        else:
            conditions_failed.append(f"条件2: gap_distance_em1={gap:.2f}≥2偏大")
        
        dex_bias = directional.get('dex_bias', 'mixed')
        dex_strength = directional.get('dex_bias_strength', 'weak')
        # DEX支持条件：bias=support 且 strength 不为 weak
        if dex_bias == 'support' and dex_strength in ['strong', 'medium']:
            conditions_met.append(f"条件3: dex_bias={dex_bias}/{dex_strength}支持")
        else:
            conditions_failed.append(f"条件3: dex_bias={dex_bias}/{dex_strength}不支持")
        
        vanna_conf = directional.get('vanna_confidence', 'low')
        if vanna_conf in ['high', 'medium']:
            conditions_met.append(f"条件4: vanna_confidence={vanna_conf}")
        else:
            conditions_failed.append(f"条件4: vanna_confidence={vanna_conf}低置信")
        
        met_count = len(conditions_met)
        total_conditions = 4
        entry_threshold = self.conf.entry_threshold_score
        
        if total_score >= entry_threshold and met_count >= 3:
            entry_check = "入场"
            rationale_parts = [
                f"总分{total_score:.1f}≥{entry_threshold:.1f}满足",
                f"关键信号：{met_count}/{total_conditions}个条件满足"
            ]
        elif total_score >= entry_threshold and met_count >= 2:
            entry_check = "轻仓试探"
            rationale_parts = [
                f"总分{total_score:.1f}≥{entry_threshold:.1f}满足",
                f"但关键信号仅{met_count}/{total_conditions}个条件满足",
                "建议轻仓试探"
            ]
        else:
            entry_check = "观望"
            rationale_parts = [
                f"总分{total_score:.1f}或条件不足（{met_count}/{total_conditions}）",
                "建议观望"
            ]
        
        rationale = "。".join(rationale_parts) + "。"
        rationale += f"\n满足：{', '.join(conditions_met) if conditions_met else '无'}"
        rationale += f"\n不满足：{', '.join(conditions_failed) if conditions_failed else '无'}"
        
        return {
            "entry_threshold_check": entry_check,
            "entry_rationale": rationale,
            "conditions_met_count": met_count,
            "conditions_total": total_conditions,
            "conditions_met": conditions_met,
            "conditions_failed": conditions_failed
        }
    
    def generate_risk_warnings(self, target_data: Dict, scores: Dict) -> str:
        warnings = []
        gamma = target_data.get('gamma_metrics', {})
        directional = target_data.get('directional_metrics', {})
        
        gap_distance = gamma.get('gap_distance_em1_multiple', 0)
        spot_vs_trigger = gamma.get('spot_vs_trigger', 'unknown')
        cluster_strength = gamma.get('cluster_strength_ratio', 0)
        vanna_dir = directional.get('vanna_dir', 'neutral')
        iv_path = directional.get('iv_path', 'Flat')  # '平' → 'Flat'
        
        if gap_distance > 2:
            wall_type = "Call Wall" if spot_vs_trigger == 'above' else "Put Wall"
            warnings.append(f"gap_distance偏大需{gap_distance:.2f}倍EM1$才能到{wall_type}")
        
        if spot_vs_trigger == "near":
            warnings.append("现价接近Gamma翻转线，regime可能反转，高波动风险")
        
        vanna_up = vanna_dir == 'up'
        vanna_down = vanna_dir == 'down'
        iv_up = iv_path == 'Rising'    
        iv_down = iv_path == 'Falling' 
        
        if (vanna_up and iv_down) or (vanna_down and iv_up):
            warnings.append(f"Vanna方向{vanna_dir}与IV路径{iv_path}冲突，信号不一致")
        
        cluster_threshold_s = self.env_gamma.cluster_strength_threshold_s
        if cluster_strength >= cluster_threshold_s:
            warnings.append(f"簇强度{cluster_strength:.2f}≥{cluster_threshold_s:.1f}，主墙极强")
        elif cluster_strength >= cluster_threshold_s - 0.2:
            warnings.append(f"簇强度{cluster_strength:.2f}接近{cluster_threshold_s:.1f}，注意主墙阻力")
        
        return "; ".join(warnings) if warnings else "风险可控"
    
    def process(self, agent3_data: Dict) -> Dict:
        targets = agent3_data.get('targets', {})
        indices = agent3_data.get('indices', {})
        if not targets:
            raise ValueError("Agent 3 数据中未找到 targets 字段")
        
        gamma_result = self.calculate_gamma_regime_score(targets.get('gamma_metrics', {}))
        break_wall_result = self.calculate_break_wall_score(targets.get('gamma_metrics', {}))      
        direction_result = self.calculate_direction_score(targets.get('directional_metrics', {}))  
        iv_result = self.calculate_iv_score(targets.get('directional_metrics', {}))  
        index_result = self.calculate_index_consistency_score(targets.get('gamma_metrics', {}), targets.get('directional_metrics', {}), indices)
        
        scores = {
            'gamma': gamma_result,
            'break_wall': break_wall_result,
            'direction': direction_result,
            'iv': iv_result,
            'index_consistency': index_result
        }  
        
        total_result = self.calculate_total_score(scores)  
        entry_result = self.check_entry_conditions(targets, total_result['total_score'])  
        risk_warning = self.generate_risk_warnings(targets, scores)  
        
        walls = targets.get('walls', {})
        gamma_metrics = targets.get('gamma_metrics', {}) 
        
        result = {
            "gamma_regime": {
                "vol_trigger": gamma_metrics.get('vol_trigger'),
                "spot_vs_trigger": gamma_metrics.get('spot_vs_trigger'),
                "base_scenario": gamma_result['base_scenario'],
                "regime_note": gamma_result['regime_note']
            },
            "break_wall_assessment": {
                "gap_distance_em1": break_wall_result['gap_distance_em1'],
                "cluster_strength": break_wall_result['cluster_strength'],
                "monthly_override": break_wall_result['monthly_override'],
                "threshold": break_wall_result['threshold'],
                "threshold_note": break_wall_result['threshold_note'],
                "break_probability": break_wall_result['break_probability'],
                "break_note": break_wall_result['break_note']
            },
            "directional_signals": {
                "dex_bias": direction_result['dex_bias'],
                "dex_bias_strength": direction_result['dex_bias_strength'],
                "vanna_dir": direction_result['vanna_dir'],
                "vanna_confidence": direction_result['vanna_confidence'],
                "vanna_weight": direction_result['vanna_weight'],
                "direction_strength": direction_result['direction_strength'],
                "direction_note": direction_result['direction_note']
            },
            "iv_dynamics": {
                "iv_path": iv_result['iv_path'],
                "iv_path_confidence": iv_result['iv_path_confidence'],
                "iv_signal": iv_result['iv_signal'],
                "iv_note": iv_result['iv_note']
            },
            "scoring": {
                "gamma_regime_score": gamma_result['score'],
                "gamma_regime_rationale": gamma_result['rationale'],
                "break_wall_score": break_wall_result['score'],
                "break_wall_rationale": break_wall_result['rationale'],
                "direction_score": direction_result['score'],
                "direction_rationale": direction_result['rationale'],
                "iv_score": iv_result['score'],
                "iv_score_rationale": iv_result['rationale'],
                "total_score": total_result['total_score'],
                "weight_breakdown": total_result['weight_breakdown'],
                "weight_regime": total_result.get('weight_regime', 'normal'),
                "regime_description": total_result.get('regime_description', ''),
                "applied_weights": total_result.get('applied_weights', {})
            },
            "entry_threshold_check": entry_result['entry_threshold_check'],
            "entry_rationale": entry_result['entry_rationale'],
            "key_levels": {
                "support": walls.get('put_wall'),
                "resistance": walls.get('call_wall'),
                "trigger_line": gamma_metrics.get('vol_trigger'),
                "current_spot": targets.get('spot_price')
            },
            "risk_warning": risk_warning
        } 
        return result