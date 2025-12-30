"""
Code 4: 策略对比引擎 (v3.7 - Bulletproof Edition)
修复:
1. [空值防御] 即使上游没有生成策略，也能优雅返回空结果，不阻断流程
2. [智能解包] 自动处理 'raw' 字符串或嵌套 JSON
3. [日志增强] 捕获并打印详细堆栈，杜绝 "Unknown error"
"""
import json
import traceback
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict, field
from datetime import datetime
from loguru import logger
from utils.config_loader import config

# ==========================================
# 数据结构定义
# ==========================================

@dataclass
class QualityFilter:
    filters_triggered: List[str] = field(default_factory=list)
    total_penalty: float = 0.0
    overall_confidence: float = 1.0
    weekly_friction_state: str = "Clear"
    is_vetoed: bool = False
    strategy_bias: str = "Neutral"

# ==========================================
# 核心逻辑引擎
# ==========================================

class ComparisonEngine:
    def __init__(self, env_vars: Dict):
        # 加载配置，给予默认值兜底
        scoring_conf = getattr(config, 'scoring', {})
        self.cfg = {
            'WEEKLY_RESISTANCE_PENALTY': 20, 
            'BIAS_MISMATCH_PENALTY': 15,
            'VETO_DIRECTIONAL_ZERO': True,
            'EV_HIGH_THRESHOLD': 0.5, 
            'RAR_HIGH_THRESHOLD': 0.3
        }
        if isinstance(scoring_conf, dict):
            self.cfg.update(scoring_conf)
    
    def process(self, strategies_data: Any, scenario_data: Any, agent3_data: Any) -> Dict:
        """核心处理流程"""
        
        # 1. 提取策略列表 (最易出错的步骤，独立封装)
        strategies = self._extract_strategies_list(strategies_data)
        
        # 如果没有策略，返回标准空结构，而不是报错
        if not strategies:
            logger.warning("[Code 4] 未检测到有效策略，跳过评分步骤")
            return {
                "ranking": [],
                "quality_filter": asdict(QualityFilter()),
                "message": "No strategies provided by upstream",
                "analysis_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        # 2. 提取上下文数据 (防御性获取)
        agent3_data = agent3_data or {}
        scenario_data = scenario_data or {}
        
        meta = agent3_data.get("meta", {})
        spot = meta.get("spot", 0) or agent3_data.get("targets", {}).get("spot_price", 0)
        em1 = meta.get("em1", 0)
        
        scenario_class = scenario_data.get("scenario_classification", {})
        primary_scenario = scenario_class.get("primary_scenario", "Unknown")
        scenario_prob = scenario_class.get("scenario_probability", 0)
        
        validation = agent3_data.get("validation", {})
        
        # 3. 执行评分
        quality_filter = self._process_quality_filter(validation)
        ranked = self._rank_strategies(
            strategies, primary_scenario, scenario_prob, 
            spot, em1, quality_filter
        )
        
        return {
            "symbol": agent3_data.get("symbol", "UNKNOWN"),
            "quality_filter": asdict(quality_filter),
            "ranking": ranked,
            "analysis_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_strategies": len(strategies),
            "top1_score": ranked[0]["composite_score"] if ranked else 0
        }

    def _extract_strategies_list(self, data: Any) -> List[Dict]:
        """
        智能提取策略列表，支持多种嵌套格式
        """
        if not data:
            return []
            
        # Case A: 直接是列表
        if isinstance(data, list):
            return data
            
        # Case B: 字典
        if isinstance(data, dict):
            # 1. 标准格式
            if "strategies" in data and isinstance(data["strategies"], list):
                return data["strategies"]
            
            # 2. 包裹在 raw 里的 JSON 字符串 (Agent 6 常见输出)
            if "raw" in data and isinstance(data["raw"], str):
                try:
                    raw_str = data["raw"].strip()
                    # 清理 Markdown 代码块
                    if raw_str.startswith("```"):
                        lines = raw_str.split('\n')
                        if lines[0].startswith("```"): lines = lines[1:]
                        if lines[-1].startswith("```"): lines = lines[:-1]
                        raw_str = "\n".join(lines)
                    
                    parsed = json.loads(raw_str)
                    if isinstance(parsed, dict) and "strategies" in parsed:
                        return parsed["strategies"]
                except Exception as e:
                    logger.warning(f"[Code 4] 解析 raw 字段失败: {e}")
            
            # 3. 只有 raw 且 raw 本身就是列表的字符串
            if "raw" in data and isinstance(data["raw"], list):
                return data["raw"]

        return []

    def _process_quality_filter(self, validation: Dict) -> QualityFilter:
        qf = QualityFilter()
        if not validation: return qf
        
        friction = validation.get("weekly_friction_state", "Clear")
        qf.weekly_friction_state = friction
        
        if friction == "Obstructed":
            qf.filters_triggered.append("WEEKLY_RESISTANCE")
            qf.total_penalty += self.cfg['WEEKLY_RESISTANCE_PENALTY']
            
        if validation.get("is_vetoed"):
            qf.filters_triggered.append("VOLUME_DIVERGENCE")
            qf.is_vetoed = True
            
        qf.strategy_bias = validation.get("strategy_bias", "Neutral")
        return qf

    def _rank_strategies(self, strategies: List[dict], primary_scenario: str,
                         scenario_prob: int, spot: float, em1: float,
                         quality_filter: QualityFilter) -> List[dict]:
        ranked = []
        for strat in strategies:
            try:
                # 基础计算
                metrics = self._calc_base_metrics(strat)
                
                # 质量过滤
                adj, notes = self._apply_quality_filter(strat, quality_filter, metrics)
                
                metrics["quality_adjustment"] = adj
                metrics["quality_notes"] = notes
                metrics["composite_score"] = max(0, metrics["composite_score"] + adj)
                
                # 注入原始信息供报告使用
                metrics["strategy_detail"] = strat
                
                ranked.append(metrics)
            except Exception as e:
                logger.error(f"策略评分出错 ({strat.get('strategy_name', '?')}): {e}")
                continue
        
        # 排序
        ranked.sort(key=lambda x: x["composite_score"], reverse=True)
        for i, item in enumerate(ranked):
            item["rank"] = i + 1
            
        return ranked

    def _calc_base_metrics(self, strategy: dict) -> dict:
        """计算基础得分 (R/R, WinRate, EV)"""
        metrics = {
            "strategy_name": strategy.get("strategy_name", "Unknown"),
            "strategy_type": strategy.get("strategy_type", ""),
            "ev": 0.0,
            "rar": 0.0,
            "composite_score": 50.0, # 基础分
            "quality_adjustment": 0.0,
            "quality_notes": []
        }
        
        quant = strategy.get("quant_metrics", {})
        if not quant: return metrics
        
        # 1. 盈亏比 (Reward to Risk)
        try:
            rr_val = 0.0
            rr_raw = quant.get("rr_ratio", 0)
            if isinstance(rr_raw, (int, float)):
                rr_val = float(rr_raw)
            elif isinstance(rr_raw, str) and ":" in rr_raw:
                parts = rr_raw.split(":")
                if len(parts) == 2 and float(parts[0]) != 0:
                    rr_val = float(parts[1]) / float(parts[0])
            
            metrics["rar"] = rr_val
            # 简单的 R/R 评分模型: R/R > 2.0 得高分
            if rr_val > 0:
                metrics["composite_score"] += min(rr_val * 10, 30)
        except: pass
        
        # 2. 胜率 (Win Rate)
        try:
            pw_val = 50.0
            pw_raw = quant.get("pw_estimate", "50%")
            if isinstance(pw_raw, (int, float)):
                pw_val = float(pw_raw) * 100 if float(pw_raw) < 1 else float(pw_raw)
            elif isinstance(pw_raw, str):
                clean_pw = pw_raw.replace("%", "").split("(")[0].strip()
                pw_val = float(clean_pw)
            
            # 胜率每超过 50% 加分
            if pw_val > 50:
                metrics["composite_score"] += (pw_val - 50) * 0.5
        except: pass
        
        return metrics

    def _apply_quality_filter(self, strategy: dict, qf: QualityFilter, metrics: dict):
        adj = 0.0
        notes = []
        
        # 示例逻辑：如果方向不一致扣分 (此处简化，实际逻辑可更复杂)
        # if qf.is_vetoed ...
        
        # Phase 3: 蓝图加分
        if "source_blueprint" in strategy:
            src = strategy["source_blueprint"]
            if src and "MANUAL" not in src.upper():
                adj += 10
                notes.append("⭐ 官方蓝图加成")
                
        return adj, notes

# ==========================================
# 主入口 (Main Entry)
# ==========================================

def main(**kwargs) -> Dict:
    """
    Code 4 主入口 (全兼容模式)
    不管传入什么参数名，都会尝试寻找 strategies, scenario, agent3 数据
    """
    try:
        # 1. 智能提取参数 (支持多种命名习惯)
        strategies_in = kwargs.get("strategies_output") or kwargs.get("agent6_output") or kwargs.get("strategies_result")
        scenario_in = kwargs.get("scenario_output") or kwargs.get("agent5_output") or kwargs.get("scenario_result")
        agent3_in = kwargs.get("agent3_output") or kwargs.get("calculated_data")
        
        # 2. 预处理：确保是字典或 None (防止传入了 JSON 字符串)
        def _ensure_dict(d):
            if isinstance(d, str):
                try: return json.loads(d)
                except: return {}
            return d if isinstance(d, dict) else {}

        strategies_in = _ensure_dict(strategies_in)
        scenario_in = _ensure_dict(scenario_in)
        agent3_in = _ensure_dict(agent3_in)

        # 3. 初始化引擎并执行
        # 传入 kwargs 以便引擎获取可能需要的其他环境参数
        engine = ComparisonEngine(kwargs)
        result = engine.process(strategies_in, scenario_in, agent3_in)
        
        return result

    except Exception as e:
        # 4. 终极兜底：无论发生什么错误，都返回一个合法的 JSON 结构
        # 这样 Pipeline 就不会崩溃，Agent 8 也能看到错误信息
        error_msg = f"Code 4 Critical Error: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        
        return {
            "ranking": [],
            "error": True,
            "message": error_msg,
            "traceback": traceback.format_exc()
        }