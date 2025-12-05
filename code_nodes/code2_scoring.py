import json
from typing import Dict, Any, Tuple


def main(agent3_output: dict, technical_score: float = 0, **env_vars) -> dict:
    """
    Dify Code Node 入口函数
    
    Args:
        agent3_output: Agent 3 的数据校验结果 JSON 字符串
        **env_vars: 环境变量字典
        
    Returns:
        {"result": 评分结果 JSON 字符串}
    """
    try:
    
        # 初始化评分引擎
        scoring = OptionsScoring(env_vars)    
        # 执行评分计算
        result = scoring.process(agent3_output)
        return result
        
    except Exception as e:
        # 错误处理
        error_result = {
            "error": True,
            "error_message": str(e),
            "error_type": type(e).__name__
        }
        return {
            "result": json.dumps(error_result, ensure_ascii=False, indent=2)
        }


class OptionsScoring:
    """期权量化评分计算引擎"""
    
    def __init__(self, env_vars: Dict[str, Any]):
        """
        初始化环境变量阈值
        
        Args:
            env_vars: 环境变量字典，包含所有阈值参数
        """
        self.env = self._parse_env_vars(env_vars)
        self.market_params = env_vars.get('market_params', {})
        
        # 获取动态权重配置
        config = env_vars.get('config')
        if config:
            self.dynamic_weights_config = config.get('scoring.dynamic_weights', {})
        else:
            self.dynamic_weights_config = {}
        
    def _parse_env_vars(self, env_vars: Dict[str, Any]) -> Dict[str, float]:
        """解析并验证环境变量"""
        parsed = {}
        
        # 必需的环境变量及其默认值
        defaults = {
            'SCORE_WEIGHT_GAMMA_REGIME': env_vars["SCORE_WEIGHT_GAMMA_REGIME"],
            'SCORE_WEIGHT_BREAK_WALL': env_vars["SCORE_WEIGHT_BREAK_WALL"],
            'SCORE_WEIGHT_DIRECTION': env_vars["SCORE_WEIGHT_DIRECTION"],
            'SCORE_WEIGHT_IV': env_vars["SCORE_WEIGHT_IV"],
            'BREAK_WALL_THRESHOLD_LOW': env_vars["BREAK_WALL_THRESHOLD_LOW"],
            'BREAK_WALL_THRESHOLD_HIGH': env_vars["BREAK_WALL_THRESHOLD_HIGH"],
            'MONTHLY_OVERRIDE_THRESHOLD': env_vars["MONTHLY_OVERRIDE_THRESHOLD"],
            'MONTHLY_CLUSTER_STRENGTH_RATIO': env_vars["MONTHLY_CLUSTER_STRENGTH_RATIO"],
            'CLUSTER_STRENGTH_THRESHOLD_S': env_vars["CLUSTER_STRENGTH_THRESHOLD_S"],
            'CLUSTER_STRENGTH_THRESHOLD_T': env_vars["CLUSTER_STRENGTH_THRESHOLD_T"],
            'DEX_SAME_DIR_THRESHOLD_STRONG': env_vars["DEX_SAME_DIR_THRESHOLD_STRONG"],
            'DEX_SAME_DIR_THRESHOLD_MEDIUM': env_vars["DEX_SAME_DIR_THRESHOLD_MEDIUM"],
            'DEX_SAME_DIR_THRESHOLD_WEAK': env_vars["DEX_SAME_DIR_THRESHOLD_WEAK"],
            'PW_DEBIT_VANNA_WEIGHT_HIGH': env_vars["PW_DEBIT_VANNA_WEIGHT_HIGH"],
            'PW_DEBIT_VANNA_WEIGHT_MEDIUM': env_vars["PW_DEBIT_VANNA_WEIGHT_MEDIUM"],
            'PW_DEBIT_VANNA_WEIGHT_LOW': env_vars["PW_DEBIT_VANNA_WEIGHT_LOW"],
            'ENTRY_THRESHOLD_SCORE': env_vars["ENTRY_THRESHOLD_SCORE"],
            'ENTRY_THRESHOLD_PROBABILITY': env_vars["ENTRY_THRESHOLD_PROBABILITY"],
            'LIGHT_POSITION_PROBABILITY': env_vars["LIGHT_POSITION_PROBABILITY"],
            'INDEX_GAP_THRESHOLD_RATIO': env_vars.get("INDEX_GAP_THRESHOLD_RATIO", 0.5),
            'INDEX_CONFLICT_PENALTY': env_vars.get("INDEX_CONFLICT_PENALTY", -1),
            'INDEX_CONSISTENCY_BONUS': env_vars.get("INDEX_CONSISTENCY_BONUS", 1),
        }
        for key, default_value in defaults.items():
            value = env_vars.get(key, default_value)
            # 转换为 float
            try:
                parsed[key] = float(value)
            except (ValueError, TypeError):
                parsed[key] = default_value
                
        return parsed
    
    def get_dynamic_weights(self, ivr: float = None) -> Tuple[Dict[str, float], str, str]:
        """
        根据 IVR 动态调整评分权重
        
        市场状态划分：
        - 恐慌期 (IVR > 80): 结构(Gamma)不再可靠，波动率(IV)均值回归是主导
        - 平静期 (IVR < 20): 波动率已死，结构(Gamma)是唯一波动源
        - 正常期 (20 <= IVR <= 80): 维持默认配置
        
        Args:
            ivr: IV Rank 值 (0-100)，如果未提供则从 market_params 获取
            
        Returns:
            (权重字典, 市场状态, 状态说明) 元组
        """
        # 获取 IVR
        if ivr is None:
            ivr = self.market_params.get('ivr', 50.0)
        
        # 获取动态权重配置
        dw = self.dynamic_weights_config
        
        # 获取阈值
        panic_threshold = dw.get('panic', {}).get('ivr_threshold', 80)
        calm_threshold = dw.get('calm', {}).get('ivr_threshold', 20)
        
        if ivr > panic_threshold:
            # 恐慌期：波动率均值回归是主导
            panic_config = dw.get('panic', {})
            weights = {
                'GAMMA': panic_config.get('gamma', 0.2),
                'BREAK': panic_config.get('break', 0.2),
                'DIR': panic_config.get('direction', 0.2),
                'IV': panic_config.get('iv', 0.4)
            }
            regime = 'panic'
            description = panic_config.get('description', '恐慌期：IV均值回归主导，结构信号弱化')
            
        elif ivr < calm_threshold:
            # 平静期：结构是唯一波动源
            calm_config = dw.get('calm', {})
            weights = {
                'GAMMA': calm_config.get('gamma', 0.5),
                'BREAK': calm_config.get('break', 0.3),
                'DIR': calm_config.get('direction', 0.1),
                'IV': calm_config.get('iv', 0.1)
            }
            regime = 'calm'
            description = calm_config.get('description', '平静期：结构主导，IV信号无效')
            
        else:
            # 正常期：使用默认权重
            normal_config = dw.get('normal', {})
            weights = {
                'GAMMA': normal_config.get('gamma', self.env.get('SCORE_WEIGHT_GAMMA_REGIME', 0.4)),
                'BREAK': normal_config.get('break', self.env.get('SCORE_WEIGHT_BREAK_WALL', 0.3)),
                'DIR': normal_config.get('direction', self.env.get('SCORE_WEIGHT_DIRECTION', 0.2)),
                'IV': normal_config.get('iv', self.env.get('SCORE_WEIGHT_IV', 0.1))
            }
            regime = 'normal'
            description = normal_config.get('description', '正常期：平衡权重')
        
        return weights, regime, description
    
    def calculate_gamma_regime_score(self, gamma_metrics: Dict) -> Dict:
        """
        1. Gamma Regime 判定（权重 40%）
        
        这是最关键的市场状态判断：
        - above: 正γ倾向，做市商压制波动
        - below: 负γ倾向，做市商放大波动
        - near: 临界状态，可能反转
        
        Args:
            gamma_metrics: Gamma 指标数据
            
        Returns:
            评分结果字典
        """
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
            
        else:  # near 或其他
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
        """
        2. 破墙可能性评估（权重 30%）
        
        评估突破主要墙位的难度：
        - 考虑距离、簇强度、月度叠加
        
        Args:
            gamma_metrics: Gamma 指标数据
            
        Returns:
            评分结果字典
        """
        gap_distance = gamma_metrics.get('gap_distance_em1_multiple', 999)
        cluster_strength = gamma_metrics.get('cluster_strength_ratio', 0)
        monthly_override = gamma_metrics.get('monthly_cluster_override', False)
        spot_vs_trigger = gamma_metrics.get('spot_vs_trigger', 'unknown')
        
        # 步骤1: 判断阈值
        if monthly_override:
            threshold = self.env['MONTHLY_OVERRIDE_THRESHOLD']
            threshold_note = f"月度簇强度≥周度{self.env['MONTHLY_CLUSTER_STRENGTH_RATIO']}倍"
        else:
            threshold = self.env['BREAK_WALL_THRESHOLD_HIGH']
            threshold_note = f"标准阈值{threshold}×EM1$"
        
        # 步骤2: 评估破墙概率
        if gap_distance < self.env['BREAK_WALL_THRESHOLD_LOW']:
            break_probability = "高"
            base_score = 9
            prob_desc = "距离近"
        elif gap_distance < self.env['BREAK_WALL_THRESHOLD_HIGH']:
            break_probability = "中"
            base_score = 6
            prob_desc = "距离适中"
        else:
            break_probability = "低"
            base_score = 3
            prob_desc = "距离远"
        
        # 步骤3: 簇强度调整
        if cluster_strength >= self.env['CLUSTER_STRENGTH_THRESHOLD_S']:
            adjustment = -1
            cluster_note = f"簇强度{cluster_strength:.2f}≥{self.env['CLUSTER_STRENGTH_THRESHOLD_S']}，主墙极强"
            cluster_desc = "极强阻力"
        elif cluster_strength >= self.env['CLUSTER_STRENGTH_THRESHOLD_T']:
            adjustment = 0
            cluster_note = f"簇强度{cluster_strength:.2f}在{self.env['CLUSTER_STRENGTH_THRESHOLD_T']}-{self.env['CLUSTER_STRENGTH_THRESHOLD_S']}，中等强度"
            cluster_desc = "中等阻力"
        else:
            adjustment = 1
            cluster_note = f"簇强度{cluster_strength:.2f}<{self.env['CLUSTER_STRENGTH_THRESHOLD_T']}，较易突破"
            cluster_desc = "较弱阻力"
        
        final_score = max(1, min(10, base_score + adjustment))  # 限制在 1-10
        
        # 确定墙位方向
        wall_direction = "Call Wall" if spot_vs_trigger == 'above' else "Put Wall"
        
        # 综合说明
        break_note = (
            f"需{gap_distance:.2f}倍EM1$距离到达{wall_direction}，"
            f"{cluster_note}，破墙难度"
            f"{'高' if final_score < 5 else '中' if final_score < 7 else '低'}"
        )
        
        rationale = (
            f"gap_distance {gap_distance:.2f}({prob_desc})给{base_score}分，"
            f"cluster {cluster_strength:.2f}({cluster_desc})调整{adjustment:+d}分"
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
        3. 方向一致性评估（权重 20%）
        
        综合 DEX 同向性和 Vanna 方向信号
        
        Args:
            directional_metrics: 方向指标数据
            
        Returns:
            评分结果字典
        """
        dex_same_dir = directional_metrics.get('dex_same_dir_pct', 0)
        vanna_dir = directional_metrics.get('vanna_dir', 'neutral')
        vanna_confidence = directional_metrics.get('vanna_confidence', 'low')
        
        # 计算 vanna 权重
        vanna_weight_map = {
            'high': self.env['PW_DEBIT_VANNA_WEIGHT_HIGH'],
            'medium': self.env['PW_DEBIT_VANNA_WEIGHT_MEDIUM'],
            'low': self.env['PW_DEBIT_VANNA_WEIGHT_LOW']
        }
        vanna_weight = vanna_weight_map.get(vanna_confidence, 0.3)
        
        # 判断方向强度
        has_strong_dex = dex_same_dir >= self.env['DEX_SAME_DIR_THRESHOLD_STRONG']
        has_clear_vanna = vanna_dir in ['up', 'down']
        has_medium_vanna = vanna_weight >= self.env['PW_DEBIT_VANNA_WEIGHT_MEDIUM']
        
        if has_strong_dex and has_clear_vanna and has_medium_vanna:
            direction_strength = "强方向信号"
            score = 9
            strength_desc = "DEX强+Vanna高置信"
            
        elif dex_same_dir >= self.env['DEX_SAME_DIR_THRESHOLD_MEDIUM'] or vanna_weight == self.env['PW_DEBIT_VANNA_WEIGHT_MEDIUM']:
            direction_strength = "中等方向信号"
            score = 6
            strength_desc = "DEX中等或Vanna中等置信"
            
        elif dex_same_dir < self.env['DEX_SAME_DIR_THRESHOLD_WEAK'] or vanna_confidence == 'low':
            direction_strength = "弱方向信号"
            score = 3
            strength_desc = "DEX弱或Vanna低置信"
        else:
            direction_strength = "中等偏弱信号"
            score = 5
            strength_desc = "信号模糊"
        
        # DEX 评价
        if dex_same_dir >= self.env['DEX_SAME_DIR_THRESHOLD_STRONG']:
            dex_eval = "强"
        elif dex_same_dir >= self.env['DEX_SAME_DIR_THRESHOLD_MEDIUM']:
            dex_eval = "中等"
        else:
            dex_eval = "弱"
        
        direction_note = (
            f"DEX同向{dex_same_dir:.1f}%({dex_eval})，"
            f"Vanna方向{vanna_dir}且置信度{vanna_confidence}权重{vanna_weight:.1f}，"
            f"综合{direction_strength}"
        )
        
        rationale = f"dex {dex_same_dir:.1f}%+vanna {vanna_confidence}({strength_desc})综合给{score}分"
        
        return {
            "score": score,
            "direction_strength": direction_strength,
            "vanna_weight": vanna_weight,
            "direction_note": direction_note,
            "rationale": rationale,
            "dex_same_dir": dex_same_dir,
            "vanna_dir": vanna_dir,
            "vanna_confidence": vanna_confidence
        }
    
    def calculate_iv_score(self, directional_metrics: Dict) -> Dict:
        """
        4. IV 动态评估（权重 10%）
        
        评估隐含波动率的路径和置信度
        
        Args:
            directional_metrics: 方向指标数据
            
        Returns:
            评分结果字典
        """
        iv_path = directional_metrics.get('iv_path', '平')
        iv_confidence = directional_metrics.get('iv_path_confidence', 'low')
        
        if iv_path == "升" and iv_confidence in ['high', 'medium']:
            iv_signal = "波动率扩张"
            note = "利多波动率策略"
            score = 8 if iv_confidence == 'high' else 6
            conf_desc = "高置信" if iv_confidence == 'high' else "中等置信"
            
        elif iv_path == "降":
            iv_signal = "波动率压缩"
            note = "利空波动率"
            if iv_confidence == 'high':
                score = 3
                conf_desc = "高置信下降"
            elif iv_confidence == 'medium':
                score = 4
                conf_desc = "中等置信下降"
            else:
                score = 5
                conf_desc = "低置信下降"
                
        else:  # "平" 或 "数据不足"
            iv_signal = "中性"
            note = "波动率稳定或数据不足"
            score = 5
            conf_desc = "平稳或不确定"
        
        iv_note = f"IV路径显示{iv_path}趋势，置信度{iv_confidence}，{note}"
        rationale = f"iv_path {iv_path}且confidence {iv_confidence}({conf_desc})给{score}分"
        
        return {
            "score": score,
            "iv_signal": iv_signal,
            "iv_note": iv_note,
            "rationale": rationale,
            "iv_path": iv_path,
            "iv_path_confidence": iv_confidence
        }
    
    def calculate_total_score(self, scores: Dict) -> Dict:
        """
        综合评分计算（动态权重版）
    
        根据 IVR 动态调整权重：
        - 恐慌期 (IVR > 80): GAMMA=0.2, BREAK=0.2, DIR=0.2, IV=0.4
        - 平静期 (IVR < 20): GAMMA=0.5, BREAK=0.3, DIR=0.1, IV=0.1
        - 正常期 (20-80): GAMMA=0.4, BREAK=0.3, DIR=0.2, IV=0.1
        
        Args:
            scores: 各维度评分字典
            
        Returns:
            总分、权重分解和市场状态
        """
        gamma_score = scores['gamma']['score']
        break_score = scores['break_wall']['score']
        direction_score = scores['direction']['score']
        iv_score = scores['iv']['score']
        index_score = scores['index_consistency']['score']
        
        # 获取动态权重
        ivr = self.market_params.get('ivr', 50.0)
        dynamic_weights, weight_regime, regime_description = self.get_dynamic_weights(ivr)
        
        # 指数权重保持不变
        index_weight = self.env.get('SCORE_WEIGHT_INDEX_CONSISTENCY', 0.1)
        
        # 调整四维权重使其与指数权重总和为 1.0
        # 四维权重需要按比例缩放到 (1 - index_weight)
        scale_factor = 1.0 - index_weight
        w = {
            'GAMMA': dynamic_weights['GAMMA'] * scale_factor,
            'BREAK': dynamic_weights['BREAK'] * scale_factor,
            'DIR': dynamic_weights['DIR'] * scale_factor,
            'IV': dynamic_weights['IV'] * scale_factor,
            'INDEX': index_weight
        }
        
        # 加权计算
        total = (
            gamma_score * w['GAMMA'] +
            break_score * w['BREAK'] +
            direction_score * w['DIR'] +
            iv_score * w['IV'] +
            index_score * w['INDEX']
        )
        
        # 详细分解
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
        """
        入场门槛检查
        
        检查 4 个关键条件：
        1. spot_vs_trigger 明确
        2. gap_distance 适中
        3. DEX 同向性
        4. Vanna 置信度
        
        Args:
            target_data: 标的完整数据
            total_score: 总评分
            
        Returns:
            入场判定结果
        """
        gamma = target_data.get('gamma_metrics', {})
        directional = target_data.get('directional_metrics', {})
        
        conditions_met = []
        conditions_failed = []
        
        # 条件1: spot_vs_trigger 明确
        spot_vs_trigger = gamma.get('spot_vs_trigger', 'unknown')
        if spot_vs_trigger in ['above', 'below']:
            conditions_met.append(f"条件1: spot_vs_trigger={spot_vs_trigger}明确")
        else:
            conditions_failed.append(f"条件1: spot_vs_trigger={spot_vs_trigger}临界状态")
        
        # 条件2: gap_distance 适中
        gap = gamma.get('gap_distance_em1_multiple', 999)
        if gap < 2:
            conditions_met.append(f"条件2: gap_distance_em1={gap:.2f}<2")
        else:
            conditions_failed.append(f"条件2: gap_distance_em1={gap:.2f}≥2偏大")
        
        # 条件3: DEX 同向性
        dex = directional.get('dex_same_dir_pct', 0)
        if dex >= self.env['DEX_SAME_DIR_THRESHOLD_MEDIUM']:
            conditions_met.append(f"条件3: dex_same_dir={dex:.1f}≥{self.env['DEX_SAME_DIR_THRESHOLD_MEDIUM']:.0f}%")
        else:
            conditions_failed.append(f"条件3: dex_same_dir={dex:.1f}<{self.env['DEX_SAME_DIR_THRESHOLD_MEDIUM']:.0f}%")
        
        # 条件4: Vanna 置信度
        vanna_conf = directional.get('vanna_confidence', 'low')
        if vanna_conf in ['high', 'medium']:
            conditions_met.append(f"条件4: vanna_confidence={vanna_conf}")
        else:
            conditions_failed.append(f"条件4: vanna_confidence={vanna_conf}低置信")
        
        # 判定逻辑
        met_count = len(conditions_met)
        total_conditions = 4
        
        # 入场判定
        if total_score >= self.env['ENTRY_THRESHOLD_SCORE'] and met_count >= 3:
            entry_check = "入场"
            rationale_parts = [
                f"总分{total_score:.1f}≥{self.env['ENTRY_THRESHOLD_SCORE']:.1f}满足",
                f"关键信号：{met_count}/{total_conditions}个条件满足"
            ]
            
        elif total_score >= self.env['ENTRY_THRESHOLD_SCORE'] and met_count >= 2:
            entry_check = "轻仓试探"
            rationale_parts = [
                f"总分{total_score:.1f}≥{self.env['ENTRY_THRESHOLD_SCORE']:.1f}满足",
                f"但关键信号仅{met_count}/{total_conditions}个条件满足",
                "建议轻仓试探"
            ]
            
        else:
            entry_check = "观望"
            rationale_parts = [
                f"总分{total_score:.1f}或条件不足（{met_count}/{total_conditions}）",
                "建议观望"
            ]
        
        # 组装 rationale
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
        """
        生成风险警示
        
        Args:
            target_data: 标的完整数据
            scores: 各维度评分
            
        Returns:
            风险警示字符串
        """
        warnings = []
        
        gamma = target_data.get('gamma_metrics', {})
        directional = target_data.get('directional_metrics', {})
        
        gap_distance = gamma.get('gap_distance_em1_multiple', 0)
        spot_vs_trigger = gamma.get('spot_vs_trigger', 'unknown')
        cluster_strength = gamma.get('cluster_strength_ratio', 0)
        vanna_dir = directional.get('vanna_dir', 'neutral')
        iv_path = directional.get('iv_path', '平')
        
        # 警示1: gap_distance 偏大
        if gap_distance > 2:
            wall_type = "Call Wall" if spot_vs_trigger == 'above' else "Put Wall"
            warnings.append(
                f"gap_distance偏大需{gap_distance:.2f}倍EM1$才能到{wall_type}，"
                f"若短期内未突破需调整为区间策略"
            )
        
        # 警示2: 临界状态
        if spot_vs_trigger == "near":
            warnings.append(
                "现价接近Gamma翻转线，regime可能反转，高波动风险"
            )
        
        # 警示3: Vanna 与 IV 冲突
        vanna_up = vanna_dir == 'up'
        vanna_down = vanna_dir == 'down'
        iv_up = iv_path == '升'
        iv_down = iv_path == '降'
        
        if (vanna_up and iv_down) or (vanna_down and iv_up):
            warnings.append(
                f"Vanna方向{vanna_dir}与IV路径{iv_path}冲突，信号不一致，增加不确定性"
            )
        
        # 警示4: 簇强度极强
        if cluster_strength >= self.env['CLUSTER_STRENGTH_THRESHOLD_S']:
            warnings.append(
                f"簇强度{cluster_strength:.2f}≥{self.env['CLUSTER_STRENGTH_THRESHOLD_S']:.1f}，"
                f"主墙极强，破墙难度高"
            )
        
        # 警示5: 簇强度接近极强阈值
        elif cluster_strength >= self.env['CLUSTER_STRENGTH_THRESHOLD_S'] - 0.2:
            warnings.append(
                f"簇强度{cluster_strength:.2f}接近{self.env['CLUSTER_STRENGTH_THRESHOLD_S']:.1f}，"
                f"注意主墙阻力"
            )
        
        return "; ".join(warnings) if warnings else "风险可控"
    
    def process(self, agent3_data: Dict) -> Dict:
        """
        主处理流程
        
        Args:
            agent3_data: Agent 3 的数据校验结果
            
        Returns:
            完整的评分结果 JSON
        """
        targets = agent3_data.get('targets', {})
        indices = agent3_data.get('indices', {})
        if not targets:
            raise ValueError("Agent 3 数据中未找到 targets 字段")
        
        # 四维评分
        gamma_result = self.calculate_gamma_regime_score(
            targets.get('gamma_metrics', {})
        )
        break_wall_result = self.calculate_break_wall_score(
            targets.get('gamma_metrics', {})
        )      
        direction_result = self.calculate_direction_score(
            targets.get('directional_metrics', {})
        )  
        iv_result = self.calculate_iv_score(
            targets.get('directional_metrics', {})
        )  
        index_result = self.calculate_index_consistency_score(
            targets.get('gamma_metrics', {}),
            targets.get('directional_metrics', {}),
            indices
        )
            # 汇总评分
        scores = {
            'gamma': gamma_result,
            'break_wall': break_wall_result,
            'direction': direction_result,
            'iv': iv_result,
            'index_consistency': index_result
        }  
        # 总分计算
        total_result = self.calculate_total_score(scores)  
        # 入场检查
        entry_result = self.check_entry_conditions(targets, total_result['total_score'])  
        # 风险警示
        risk_warning = self.generate_risk_warnings(targets, scores)  
        # 提取关键位
        walls = targets.get('walls', {})
        gamma_metrics = targets.get('gamma_metrics', {}) 
        # 组装最终输出
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
                "dex_same_dir": direction_result['dex_same_dir'],
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
    
    def calculate_index_consistency_score(
    self, 
    gamma_metrics: Dict, 
    directional_metrics: Dict,
    indices: Dict
) -> Dict:
        """
        5. 指数背景一致性评估（权重 10%）
        
        评分规则：
        1. Range 场景一致性（+1分）：
        - 指数 NET-GEX = positive_gamma
        - 个股 spot_vs_trigger = above（在墙上）
        - IV 路径 = 平/降
        
        2. Trend 场景一致性（+1分）：
        - 指数 NET-GEX = negative_gamma
        - 个股破墙距离 ≥ 0.5 × EM1_index
        - IV 路径与方向配合（below+升 或 above+降）
        
        3. 方向冲突惩罚（-1分）：
        - 指数负γ趋势 但 个股DEX同向<50%
        - 指数正γ区间 但 个股深度负γ区域
        
        Args:
            gamma_metrics: 个股 Gamma 指标字典
            directional_metrics: 个股方向指标字典
            indices: 指数背景数据字典
            
        Returns:
            {
                "score": 最终评分 (1-10),
                "consistency_level": "强一致" | "中性" | "冲突",
                "consistency_note": 详细说明,
                "rationale": 评分逻辑,
                "primary_index": 主要参考指数,
                "index_net_gex": 指数净Gamma方向,
                "adjustment": 调整分数
            }
        """
    
        base_score = 5
        adjustment = 0
        consistency_note = []
        
        # 从环境变量读取阈值参数
        threshold_ratio = self.env.get('INDEX_GAP_THRESHOLD_RATIO', 0.5)
        conflict_penalty = self.env.get('INDEX_CONFLICT_PENALTY', -1)
        consistency_bonus = self.env.get('INDEX_CONSISTENCY_BONUS', 1)
        
        # ========================================
        # 数据完整性检查
        # ========================================
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
        
        # ========================================
        # 选择主要参考指数（优先级：SPX > QQQ > 首个）
        # ========================================
        primary_index = None
        primary_symbol = None
        
        for idx_symbol in ['SPX', 'QQQ']:
            if idx_symbol in indices:
                primary_index = indices[idx_symbol]
                primary_symbol = idx_symbol
                break
        
        if not primary_index:
            # 使用第一个可用指数
            primary_symbol = list(indices.keys())[0]
            primary_index = indices[primary_symbol]
        
        # ========================================
        # 提取关键数据
        # ========================================
        # 指数数据
        idx_net_gex = primary_index.get('net_gex_idx', '')
        idx_em1 = primary_index.get('em1_dollar_idx', 0)
        
        # 个股数据
        stock_spot_vs_trigger = gamma_metrics.get('spot_vs_trigger', '')
        stock_gap_distance = gamma_metrics.get('gap_distance_dollar', 0)
        stock_iv_path = directional_metrics.get('iv_path', '平')
        stock_dex_same_dir = directional_metrics.get('dex_same_dir_pct', 0.5)
        
        # ========================================
        # 规则1：Range 场景一致性（+1分）
        # ========================================
        if idx_net_gex == 'positive_gamma' and stock_spot_vs_trigger == 'above':
            # 指数正γ + 个股在墙上 → 区间剧本倾向
            if stock_iv_path in ['平', '降']:
                adjustment += consistency_bonus
                consistency_note.append(
                    f"{primary_symbol}正γ且个股在墙上，IV{stock_iv_path}符合区间预期"
                )
            else:
                # IV路径不配合，但不扣分
                consistency_note.append(
                    f"{primary_symbol}正γ但IV{stock_iv_path}，区间信号减弱"
                )
        
        # ========================================
        # 规则2：Trend 场景一致性（+1分）
        # ========================================
        if idx_net_gex == 'negative_gamma':
            # 指数负γ → 趋势倾向
            if idx_em1 > 0:
                threshold = threshold_ratio * idx_em1
                
                if stock_gap_distance >= threshold:
                    # 个股破墙距离充足
                    # 检查 IV 路径配合
                    iv_cooperates = (
                        (stock_spot_vs_trigger == 'below' and stock_iv_path == '升') or
                        (stock_spot_vs_trigger == 'above' and stock_iv_path == '降')
                    )
                    
                    if iv_cooperates:
                        adjustment += consistency_bonus
                        consistency_note.append(
                            f"{primary_symbol}负γ，个股破墙{stock_gap_distance:.1f}≥{threshold:.1f}"
                            f"({threshold_ratio}×EM1_idx)，IV{stock_iv_path}配合"
                        )
                    else:
                        consistency_note.append(
                            f"{primary_symbol}负γ，个股破墙充足但IV路径{stock_iv_path}不完全配合"
                        )
                else:
                    consistency_note.append(
                        f"{primary_symbol}负γ，但个股破墙距离{stock_gap_distance:.1f}<{threshold:.1f}"
                        f"({threshold_ratio}×EM1_idx)不足"
                    )
            else:
                consistency_note.append(
                    f"{primary_symbol}负γ但EM1_idx数据缺失，无法判断破墙充分性"
                )
        
        # ========================================
        # 规则3：方向冲突惩罚（-1分）
        # ========================================
        # 冲突情况1：指数负γ趋势 但 个股方向混乱
        if idx_net_gex == 'negative_gamma' and stock_dex_same_dir < 0.5:
            adjustment += conflict_penalty
            consistency_note.append(
                f"⚠️ {primary_symbol}负γ趋势信号强，但个股DEX同向仅{stock_dex_same_dir*100:.1f}%，方向冲突"
            )
        
        # 冲突情况2：指数正γ区间 但 个股深陷负γ区
        if idx_net_gex == 'positive_gamma' and stock_spot_vs_trigger == 'below':
            if idx_em1 > 0 and stock_gap_distance > idx_em1:
                adjustment += conflict_penalty
                consistency_note.append(
                    f"⚠️ {primary_symbol}正γ区间倾向，但个股在负γ区深度{stock_gap_distance:.1f}"
                    f">{idx_em1:.1f}EM1_idx，背离明显"
                )
        
        # ========================================
        # 最终评分计算
        # ========================================
        final_score = max(1, min(10, base_score + adjustment))
        
        # 一致性等级判定
        if adjustment > 0:
            consistency_level = "强一致"
        elif adjustment == 0:
            consistency_level = "中性"
        else:
            consistency_level = "冲突"
        
        # 组装说明文本
        full_note = f"参考{primary_symbol}背景（NET-GEX={idx_net_gex}）：" + "；".join(consistency_note)
        
        # 评分逻辑说明
        rationale = f"基础5分，指数一致性调整{adjustment:+d}分（bonus={consistency_bonus}, penalty={conflict_penalty}）→ {final_score}分"
        
        return {
            "score": final_score,
            "consistency_level": consistency_level,
            "consistency_note": full_note,
            "rationale": rationale,
            "primary_index": primary_symbol,
            "index_net_gex": idx_net_gex,
            "adjustment": adjustment
        }