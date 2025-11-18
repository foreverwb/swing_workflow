
import json
from typing import Dict, Any


def main(agent3_output: str, technical_score: float = 0, **env_vars) -> dict:
    """
    Dify Code Node 入口函数
    
    Args:
        agent3_output: Agent 3 的数据校验结果 JSON 字符串
        agent4_output: Agent 4 的技术面分析 JSON 字符串 (可选)
        **env_vars: 环境变量字典
        
    Returns:
        {"result": 评分结果 JSON 字符串}
    """
    try:
        # 解析输入
        agent3_data = json.loads(agent3_output)
        
        # 初始化评分引擎
        scoring = OptionsScoring(env_vars)
        
        # 执行评分计算
        result = scoring.process(agent3_data)
        
        # 返回 JSON 字符串
        return {
            "result": json.dumps(result, ensure_ascii=False, indent=2)
        }
        
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
        
    def _parse_env_vars(self, env_vars: Dict[str, Any]) -> Dict[str, float]:
        """解析并验证环境变量"""
        parsed = {}
        
        # 必需的环境变量及其默认值
        defaults = {
            'SCORE_WEIGHT_GAMMA_REGIME': env_vars.SCORE_WEIGHT_GAMMA_REGIME,
            'SCORE_WEIGHT_BREAK_WALL': env_vars.SCORE_WEIGHT_BREAK_WALL,
            'SCORE_WEIGHT_DIRECTION': env_vars.SCORE_WEIGHT_DIRECTION,
            'SCORE_WEIGHT_IV': env_vars.SCORE_WEIGHT_IV,
            'BREAK_WALL_THRESHOLD_LOW': env_vars.BREAK_WALL_THRESHOLD_LOW,
            'BREAK_WALL_THRESHOLD_HIGH': env_vars.BREAK_WALL_THRESHOLD_HIGH,
            'MONTHLY_OVERRIDE_THRESHOLD': env_vars.MONTHLY_OVERRIDE_THRESHOLD,
            'MONTHLY_CLUSTER_STRENGTH_RATIO': env_vars.MONTHLY_CLUSTER_STRENGTH_RATIO,
            'CLUSTER_STRENGTH_THRESHOLD_STRONG': env_vars.CLUSTER_STRENGTH_THRESHOLD_STRONG,
            'CLUSTER_STRENGTH_THRESHOLD_TREND': env_vars.CLUSTER_STRENGTH_THRESHOLD_TREND,
            'DEX_SAME_DIR_THRESHOLD_STRONG': env_vars.DEX_SAME_DIR_THRESHOLD_STRONG,
            'DEX_SAME_DIR_THRESHOLD_MEDIUM': env_vars.DEX_SAME_DIR_THRESHOLD_MEDIUM,
            'DEX_SAME_DIR_THRESHOLD_WEAK': env_vars.DEX_SAME_DIR_THRESHOLD_WEAK,
            'PW_DEBIT_VANNA_WEIGHT_HIGH': env_vars.PW_DEBIT_VANNA_WEIGHT_HIGH,
            'PW_DEBIT_VANNA_WEIGHT_MEDIUM': env_vars.PW_DEBIT_VANNA_WEIGHT_MEDIUM,
            'PW_DEBIT_VANNA_WEIGHT_LOW': env_vars.PW_DEBIT_VANNA_WEIGHT_LOW,
            'ENTRY_THRESHOLD_SCORE': env_vars.ENTRY_THRESHOLD_SCORE,
            'ENTRY_THRESHOLD_PROBABILITY': env_vars.ENTRY_THRESHOLD_PROBABILITY,
            'LIGHT_POSITION_PROBABILITY': env_vars.LIGHT_POSITION_PROBABILITY
        }
        
        for key, default_value in defaults.items():
            value = env_vars.get(key, default_value)
            # 转换为 float
            try:
                parsed[key] = float(value)
            except (ValueError, TypeError):
                parsed[key] = default_value
                
        return parsed
    
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
        if cluster_strength >= self.env['CLUSTER_STRENGTH_THRESHOLD_STRONG']:
            adjustment = -1
            cluster_note = f"簇强度{cluster_strength:.2f}≥{self.env['CLUSTER_STRENGTH_THRESHOLD_STRONG']}，主墙极强"
            cluster_desc = "极强阻力"
        elif cluster_strength >= self.env['CLUSTER_STRENGTH_THRESHOLD_TREND']:
            adjustment = 0
            cluster_note = f"簇强度{cluster_strength:.2f}在{self.env['CLUSTER_STRENGTH_THRESHOLD_TREND']}-{self.env['CLUSTER_STRENGTH_THRESHOLD_STRONG']}，中等强度"
            cluster_desc = "中等阻力"
        else:
            adjustment = 1
            cluster_note = f"簇强度{cluster_strength:.2f}<{self.env['CLUSTER_STRENGTH_THRESHOLD_TREND']}，较易突破"
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
        综合评分计算
        
        四维加权求和
        
        Args:
            scores: 各维度评分字典
            
        Returns:
            总分和权重分解
        """
        gamma_score = scores['gamma']['score']
        break_score = scores['break_wall']['score']
        direction_score = scores['direction']['score']
        iv_score = scores['iv']['score']
        
        w = self.env
        
        # 加权计算
        total = (
            gamma_score * w['SCORE_WEIGHT_GAMMA_REGIME'] +
            break_score * w['SCORE_WEIGHT_BREAK_WALL'] +
            direction_score * w['SCORE_WEIGHT_DIRECTION'] +
            iv_score * w['SCORE_WEIGHT_IV']
        )
        
        # 详细分解
        breakdown = (
            f"{gamma_score}×{w['SCORE_WEIGHT_GAMMA_REGIME']:.1f}+"
            f"{break_score}×{w['SCORE_WEIGHT_BREAK_WALL']:.1f}+"
            f"{direction_score}×{w['SCORE_WEIGHT_DIRECTION']:.1f}+"
            f"{iv_score}×{w['SCORE_WEIGHT_IV']:.1f}="
            f"{gamma_score * w['SCORE_WEIGHT_GAMMA_REGIME']:.1f}+"
            f"{break_score * w['SCORE_WEIGHT_BREAK_WALL']:.1f}+"
            f"{direction_score * w['SCORE_WEIGHT_DIRECTION']:.1f}+"
            f"{iv_score * w['SCORE_WEIGHT_IV']:.1f}="
            f"{total:.1f}"
        )
        
        return {
            "total_score": round(total, 1),
            "weight_breakdown": breakdown
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
        if cluster_strength >= self.env['CLUSTER_STRENGTH_THRESHOLD_STRONG']:
            warnings.append(
                f"簇强度{cluster_strength:.2f}≥{self.env['CLUSTER_STRENGTH_THRESHOLD_STRONG']:.1f}，"
                f"主墙极强，破墙难度高"
            )
        
        # 警示5: 簇强度接近极强阈值
        elif cluster_strength >= self.env['CLUSTER_STRENGTH_THRESHOLD_STRONG'] - 0.2:
            warnings.append(
                f"簇强度{cluster_strength:.2f}接近{self.env['CLUSTER_STRENGTH_THRESHOLD_STRONG']:.1f}，"
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
        # 提取目标数据（假设单标的）
        targets = agent3_data.get('targets', [])
        if not targets:
            raise ValueError("Agent 3 数据中未找到 targets 字段")
        
        target = targets[0]
        
        # 四维评分
        gamma_result = self.calculate_gamma_regime_score(
            target.get('gamma_metrics', {})
        )
        
        break_wall_result = self.calculate_break_wall_score(
            target.get('gamma_metrics', {})
        )
        
        direction_result = self.calculate_direction_score(
            target.get('directional_metrics', {})
        )
        
        iv_result = self.calculate_iv_score(
            target.get('directional_metrics', {})
        )
        
        # 汇总评分
        scores = {
            'gamma': gamma_result,
            'break_wall': break_wall_result,
            'direction': direction_result,
            'iv': iv_result
        }
        
        # 总分计算
        total_result = self.calculate_total_score(scores)
        
        # 入场检查
        entry_result = self.check_entry_conditions(target, total_result['total_score'])
        
        # 风险警示
        risk_warning = self.generate_risk_warnings(target, scores)
        
        # 提取关键位
        walls = target.get('walls', {})
        gamma_metrics = target.get('gamma_metrics', {})
        
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
                "weight_breakdown": total_result['weight_breakdown']
            },
            "entry_threshold_check": entry_result['entry_threshold_check'],
            "entry_rationale": entry_result['entry_rationale'],
            "key_levels": {
                "support": walls.get('put_wall'),
                "resistance": walls.get('call_wall'),
                "trigger_line": gamma_metrics.get('vol_trigger'),
                "current_spot": target.get('spot_price')
            },
            "risk_warning": risk_warning
        }
        
        return result