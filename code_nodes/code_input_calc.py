"""
输入文件计算器 - 处理 -i 参数的 symbol_datetime.json 文件
计算 cluster_strength_ratio 并写回文件

合并优化版本 (v2.1):
- 支持多种数据结构格式
- 使用 top1/ENP 方法计算集中度
- 双权重口径对比 (gex_total_m vs share_pct)
- [新增] 激活 ECR/SER/TSR 微观结构计算
- [新增] 增加物理含义转译层 (Rigid/Brittle Wall)
"""
from __future__ import annotations
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger


def remove_json_comments(json_str: str) -> str:
    """
    移除 JSON 字符串中的 JavaScript 风格注释
    支持 // 单行注释
    """
    result = []
    in_string = False
    i = 0
    while i < len(json_str):
        char = json_str[i]
        
        # 处理字符串
        if char == '"' and (i == 0 or json_str[i-1] != '\\'):
            in_string = not in_string
            result.append(char)
            i += 1
        # 处理注释
        elif not in_string and char == '/' and i + 1 < len(json_str) and json_str[i+1] == '/':
            # 跳过到行尾
            while i < len(json_str) and json_str[i] != '\n':
                i += 1
        else:
            result.append(char)
            i += 1
    
    return ''.join(result)


def load_json_with_comments(file_path: str) -> Dict[str, Any]:
    """
    加载可能包含注释的 JSON 文件
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 移除注释
    clean_content = remove_json_comments(content)
    
    return json.loads(clean_content)


def _get_panel(run: Dict[str, Any], name: str) -> Dict[str, Any]:
    """
    兼容多种结构（按优先级）：
    1) run["metadata"]["panels"][name] - 字典格式（新格式）
    2) run["metadata"]["panels"] - 列表格式，按 panel_name 匹配
    3) run["panels"][name] - 字典格式
    4) run["panels"] - 列表格式，按 panel_name 匹配
    5) run[name] - 直接在根节点
    """
    # 优先级1: metadata.panels 字典
    metadata = run.get("metadata", {})
    if isinstance(metadata.get("panels"), dict) and name in metadata["panels"]:
        return metadata["panels"][name] or {}
    
    # 优先级2: metadata.panels 列表
    if isinstance(metadata.get("panels"), list):
        for panel in metadata["panels"]:
            if panel.get("panel_name") == name:
                return panel
    
    # 优先级3: panels 字典
    if isinstance(run.get("panels"), dict) and name in run["panels"]:
        return run["panels"][name] or {}
    
    # 优先级4: panels 列表
    if isinstance(run.get("panels"), list):
        for panel in run["panels"]:
            if panel.get("panel_name") == name:
                return panel
    
    # 优先级5: 根节点直接匹配
    return run.get(name, {}) or {}


# ============================================================
# 基础工具函数
# ============================================================

def _safe_is_number(x) -> bool:
    """检查是否为有效数字（int 或 float，且非 NaN）"""
    return isinstance(x, (int, float)) and not math.isnan(x)


def _safe_float(x: Any) -> Optional[float]:
    """安全转换为浮点数"""
    try:
        if x is None:
            return None
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def _normalize(weights: List[float]) -> Optional[List[float]]:
    """归一化非负权重，使其和为1。无效或零和时返回None"""
    if not weights:
        return None
    clean = []
    for w in weights:
        if w is None:
            return None
        if w < 0:
            return None
        clean.append(float(w))
    s = sum(clean)
    if s <= 0:
        return None
    return [w / s for w in clean]


def _entropy(p: List[float]) -> float:
    """自然对数熵，p必须和为1"""
    ent = 0.0
    for x in p:
        if x > 0:
            ent -= x * math.log(x)
    return ent


def _entropy_log2(p: List[float]) -> float:
    """以2为底的熵，p必须和为1"""
    ent = 0.0
    for x in p:
        if x > 0:
            ent -= x * math.log(x, 2.0)
    return ent


def _hhi(p: List[float]) -> float:
    """HHI指数"""
    return sum(x * x for x in p)


def _topk_sum_sorted(p: List[float], k: int) -> float:
    """前k大元素之和"""
    if not p:
        return 0.0
    ps = sorted(p, reverse=True)
    return sum(ps[:k])


def _tv_distance(p: List[float], q: List[float]) -> float:
    """Total variation distance，范围[0,1]"""
    return 0.5 * sum(abs(a - b) for a, b in zip(p, q))


def _cosine_similarity(p: List[float], q: List[float]) -> float:
    """余弦相似度"""
    dot = sum(a * b for a, b in zip(p, q))
    np = math.sqrt(sum(a * a for a in p))
    nq = math.sqrt(sum(b * b for b in q))
    if np == 0 or nq == 0:
        return 0.0
    return dot / (np * nq)


def _metrics_from_norm_weights(p: List[float]) -> Dict[str, float]:
    """基于归一化权重p计算核心指标"""
    n = len(p)
    hhi = _hhi(p)
    enp = (1.0 / hhi) if hhi > 0 else float("inf")
    ent = _entropy(p)
    ent_norm = ent / math.log(n) if n > 1 else 0.0

    return {
        "top1": _topk_sum_sorted(p, 1),
        "top2": _topk_sum_sorted(p, 2),
        "hhi": hhi,
        "enp": enp,
        "entropy": ent,
        "entropy_norm": ent_norm,
    }


# ============================================================
# Dataclass 定义 (新增)
# ============================================================

@dataclass
class PanelMetrics:
    """单个 panel 的集中度指标"""
    panel_name: str
    horizon_arg: str
    n: int
    weight_source: str  # "gex_total_m_abs" / "share_pct" / "none"
    top1: float
    top2: float
    hhi: float
    enp: float
    entropy: float
    entropy_norm: float


@dataclass
class ClusterAssessment:
    """集群集中度评估结果"""
    panels: List[PanelMetrics]
    avg_top1: float
    avg_enp: float
    tier: str
    score: float


# ============================================================
# 权重选择逻辑 (新增)
# ============================================================

def choose_weights_for_panel(rows: List[Dict]) -> Tuple[Optional[List[float]], str]:
    """
    对一个 panel 选择权重：
    1) 优先 abs(gex_total_m)，若有正总和则用它；
    2) 否则退回 share_pct；
    3) 再否则返回 (None, "none")。
    返回的 weights 已经归一化，长度等于 rows 长度。
    """
    if not rows:
        return None, "none"

    # 1) 尝试使用 abs(gex_total_m)
    gex_abs: List[float] = []
    for r in rows:
        v = r.get("gex_total_m")
        if _safe_is_number(v):
            gex_abs.append(abs(float(v)))
        else:
            gex_abs.append(0.0)

    gex_sum = sum(gex_abs)
    if gex_sum > 0:
        weights = [v / gex_sum for v in gex_abs]
        return weights, "gex_total_m_abs"

    # 2) 退回使用 share_pct
    share_vals: List[float] = []
    for r in rows:
        v = r.get("share_pct")
        if _safe_is_number(v):
            val = float(v)
            if val < 0:
                val = 0.0
            share_vals.append(val)
        else:
            share_vals.append(0.0)

    share_sum = sum(share_vals)
    if share_sum > 0:
        weights = [v / share_sum for v in share_vals]
        return weights, "share_pct"

    # 3) 都不可用
    return None, "none"


# ============================================================
# 单个 panel 指标计算 (新增基于 dataclass 的版本)
# ============================================================

def compute_panel_metrics(panel: Dict) -> PanelMetrics:
    """
    计算单个 panel 的指标，返回 PanelMetrics dataclass
    使用 choose_weights_for_panel 进行权重选择
    """
    panel_name = str(panel.get("panel_name", ""))
    horizon_arg = str(panel.get("horizon_arg", ""))
    rows: List[Dict] = panel.get("rows") or []

    n = len(rows)
    weights, source = choose_weights_for_panel(rows)

    if not rows or weights is None:
        # 无有效权重的兜底结果
        return PanelMetrics(
            panel_name=panel_name,
            horizon_arg=horizon_arg,
            n=n,
            weight_source=source,
            top1=0.0,
            top2=0.0,
            hhi=0.0,
            enp=math.inf,
            entropy=0.0,
            entropy_norm=0.0,
        )

    # 计算 top1 / top2
    sorted_w = sorted(weights, reverse=True)
    top1 = sorted_w[0]
    top2 = sorted_w[1] if len(sorted_w) > 1 else 0.0

    # HHI / ENP
    hhi = sum(w * w for w in weights)
    enp = 1.0 / hhi if hhi > 0 else math.inf

    # entropy / normalized entropy (以2为底)
    entropy = 0.0
    for w in weights:
        if w > 0:
            entropy -= w * math.log(w, 2.0)
    if n > 1:
        entropy_norm = entropy / math.log(n, 2.0)
    else:
        # n=1 时，entropy 不参与后续判定，这里给 0 即可
        entropy_norm = 0.0

    return PanelMetrics(
        panel_name=panel_name,
        horizon_arg=horizon_arg,
        n=n,
        weight_source=source,
        top1=top1,
        top2=top2,
        hhi=hhi,
        enp=enp,
        entropy=entropy,
        entropy_norm=entropy_norm,
    )


# ============================================================
# 聚合 & 分档逻辑 (新增)
# ============================================================

def assess_cluster_strength(panels: List[Dict]) -> ClusterAssessment:
    """
    评估集群集中度强度
    
    分档规则：
      - strong (1.35): avg_enp <= 1.7
      - medium (1.20): avg_enp <= 2.3
      - weak (1.05): else
    
    Args:
        panels: panel 列表，每个 panel 是包含 panel_name 和 rows 的字典
        
    Returns:
        ClusterAssessment dataclass
    """
    panel_metrics_list: List[PanelMetrics] = [compute_panel_metrics(p) for p in panels]

    # 只对有有效权重的 panel 做平均
    valid_for_top1 = [pm for pm in panel_metrics_list if pm.weight_source != "none" and pm.n > 0]
    valid_for_enp = [pm for pm in panel_metrics_list if pm.weight_source != "none" and math.isfinite(pm.enp)]

    if valid_for_top1:
        avg_top1 = sum(pm.top1 for pm in valid_for_top1) / len(valid_for_top1)
    else:
        avg_top1 = 0.0

    if valid_for_enp:
        avg_enp = sum(pm.enp for pm in valid_for_enp) / len(valid_for_enp)
    else:
        avg_enp = math.inf

    # 分档规则（基于 avg_enp）
    if avg_enp <= 1.7:
        tier = "strong"
        score = 1.35
    elif avg_enp <= 2.3:
        tier = "medium"
        score = 1.20
    else:
        tier = "weak"
        score = 1.05

    return ClusterAssessment(
        panels=panel_metrics_list,
        avg_top1=avg_top1,
        avg_enp=avg_enp,
        tier=tier,
        score=score,
    )


# ============================================================
# 原有 panel_metrics 函数 (保留兼容性，返回字典格式)
# ============================================================

def panel_metrics(
    panel: Dict[str, Any],
    main_weight_key: str = "gex_total_m",
    alt_weight_key: Optional[str] = "share_pct",
) -> Dict[str, Any]:
    """
    计算单个panel的指标（字典格式输出，保持向后兼容）
    - main: 基于 main_weight_key 归一化（对 gex_total_m 取绝对值）
    - alt: 基于 alt_weight_key 归一化 + 与main的偏差
    """
    panel_name = panel.get("panel_name")
    rows = panel.get("rows") or []
    if not isinstance(rows, list):
        rows = []

    # 按行顺序提取原始权重
    main_raw: List[float] = []
    alt_raw: List[float] = []

    for r in rows:
        mw = _safe_float(r.get(main_weight_key))
        if mw is None:
            mw = 0.0
        # 对 gex_total_m 取绝对值（与 choose_weights_for_panel 保持一致）
        if main_weight_key == "gex_total_m":
            mw = abs(mw)
        main_raw.append(mw)

        if alt_weight_key:
            aw = _safe_float(r.get(alt_weight_key))
            if aw is None:
                aw = 0.0
            # share_pct 负值处理为 0
            if alt_weight_key == "share_pct" and aw < 0:
                aw = 0.0
            alt_raw.append(aw)

    main_norm = _normalize(main_raw)
    main_out: Dict[str, Any]
    if main_norm is None:
        main_out = {
            "n": len(rows),
            "total": float(sum(main_raw)) if main_raw else 0.0,
            "top1": 0.0,
            "top2": 0.0,
            "hhi": 0.0,
            "enp": float("inf"),
            "entropy": 0.0,
            "entropy_norm": 0.0,
        }
    else:
        main_out = {
            "n": len(rows),
            "total": float(sum(main_raw)),
            **_metrics_from_norm_weights(main_norm),
        }

    alt_out = None
    if alt_weight_key:
        alt_norm = _normalize(alt_raw)
        if alt_norm is not None:
            alt_metrics = {
                "n": len(rows),
                "total": float(sum(alt_raw)),
                **_metrics_from_norm_weights(alt_norm),
            }
            mismatch = None
            if main_norm is not None and len(main_norm) == len(alt_norm):
                mismatch = {
                    "tv": _tv_distance(main_norm, alt_norm),
                    "cosine": _cosine_similarity(main_norm, alt_norm),
                }
            alt_out = {
                "weight_key": alt_weight_key,
                "metrics": alt_metrics,
                "mismatch": mismatch,
            }

    return {
        "panel_name": panel_name,
        "horizon_arg": panel.get("horizon_arg"),
        "weight_key_used": main_weight_key,
        "main": main_out,
        "alt": alt_out,
    }


def _pick_alt_top(panel_dict: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """提取备选权重的top1/top2"""
    alt = panel_dict.get("alt")
    if not alt or not alt.get("metrics"):
        return None, None
    m = alt["metrics"]
    return m.get("top1"), m.get("top2")


def compute_cluster_strength_assessment(
    run: Dict[str, Any],
    main_weight_key: str = "gex_total_m",
    alt_weight_key: str = "share_pct",
) -> Dict[str, Any]:
    """
    生成最终评估结果（字典格式，保持向后兼容）
    
    分层规则 (Heuristic tiering):
      - strong (1.35): avg_top1 >= 0.65 OR avg_enp <= 1.8
      - medium (1.20): avg_top1 >= 0.50 OR avg_enp <= 2.3
      - weak (1.05): else
    """
    # 获取panels数据
    metadata = run.get("metadata", {})
    panels = metadata.get("panels") or run.get("panels") or []
    
    by_name = {p.get("panel_name"): p for p in panels if isinstance(p, dict)}

    short = panel_metrics(by_name.get("short", {"panel_name": "short", "rows": []}),
                          main_weight_key=main_weight_key, alt_weight_key=alt_weight_key)
    mid = panel_metrics(by_name.get("mid", {"panel_name": "mid", "rows": []}),
                        main_weight_key=main_weight_key, alt_weight_key=alt_weight_key)
    long = panel_metrics(by_name.get("long", {"panel_name": "long", "rows": []}),
                         main_weight_key=main_weight_key, alt_weight_key=alt_weight_key)

    panel_list = [short, mid, long]

    # 聚合计算
    main_top1s = [p["main"]["top1"] for p in panel_list if math.isfinite(p["main"]["top1"])]
    main_enps = [p["main"]["enp"] for p in panel_list if math.isfinite(p["main"]["enp"])]

    avg_top1 = sum(main_top1s) / len(main_top1s) if main_top1s else 0.0
    avg_enp = sum(main_enps) / len(main_enps) if main_enps else float("inf")

    # 分层判定
    if (avg_top1 >= 0.65) or (avg_enp <= 1.8):
        tier, score = "strong", 1.35
    elif (avg_top1 >= 0.50) or (avg_enp <= 2.3):
        tier, score = "medium", 1.20
    else:
        tier, score = "weak", 1.05

    # 日志输出
    logger.info(f"📊 集中度指标 (top1/ENP 方法):")
    logger.info(f"   Short: top1={short['main']['top1']:.4f}, enp={short['main']['enp']:.2f}, n={short['main']['n']}")
    logger.info(f"   Mid:   top1={mid['main']['top1']:.4f}, enp={mid['main']['enp']:.2f}, n={mid['main']['n']}")
    logger.info(f"   Long:  top1={long['main']['top1']:.4f}, enp={long['main']['enp']:.2f}, n={long['main']['n']}")
    logger.info(f"   平均: avg_top1={avg_top1:.4f}, avg_enp={avg_enp:.2f}")
    logger.info(f"✅ 判定为 {tier} 档集中度 ({score})")

    return {
        "tier": tier,
        "score": score,
        "cluster_strength_ratio": score,

        "panels": {"short": short, "mid": mid, "long": long},

        "summary": {
            "avg_top1_main": avg_top1,
            "avg_enp_main": avg_enp,
        },

        "top_summary": {
            "short": {
                "main_key": short["weight_key_used"],
                "top1": short["main"]["top1"],
                "top2": short["main"]["top2"],
                "enp": short["main"]["enp"],
                "n": short["main"]["n"],
                "alt_top1": _pick_alt_top(short)[0],
                "alt_top2": _pick_alt_top(short)[1],
            },
            "mid": {
                "main_key": mid["weight_key_used"],
                "top1": mid["main"]["top1"],
                "top2": mid["main"]["top2"],
                "enp": mid["main"]["enp"],
                "n": mid["main"]["n"],
                "alt_top1": _pick_alt_top(mid)[0],
                "alt_top2": _pick_alt_top(mid)[1],
            },
            "long": {
                "main_key": long["weight_key_used"],
                "top1": long["main"]["top1"],
                "top2": long["main"]["top2"],
                "enp": long["main"]["enp"],
                "n": long["main"]["n"],
                "alt_top1": _pick_alt_top(long)[0],
                "alt_top2": _pick_alt_top(long)[1],
            },
        },
    }


def compute_cluster_strength_assessment_v2(
    run: Dict[str, Any],
) -> ClusterAssessment:
    """
    生成评估结果（使用新的 dataclass 格式）
    
    使用 choose_weights_for_panel 进行权重选择：
    1) 优先 abs(gex_total_m)
    2) 否则退回 share_pct
    
    分档规则：
      - strong (1.35): avg_enp <= 1.7
      - medium (1.20): avg_enp <= 2.3
      - weak (1.05): else
    """
    # 获取panels数据
    metadata = run.get("metadata", {})
    panels = metadata.get("panels") or run.get("panels") or []
    
    if isinstance(panels, dict):
        panels = list(panels.values())
    
    return assess_cluster_strength(panels)


# ============================================================
# 兼容旧接口
# ============================================================

def compute_cluster_strength_ratio(run: Dict[str, Any]) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    兼容旧接口，返回 (cluster_strength_ratio, metrics_dict)
    """
    assessment = compute_cluster_strength_assessment(run)
    return assessment["cluster_strength_ratio"], assessment


def compute_ECR_SER_TSR(run: Dict[str, Any]) -> Dict[str, Any]:
    """
    兼容旧接口，返回 ECR/SER/TSR（基于HHI归一化）
    同时返回新的 top1/enp 指标
    """
    assessment = compute_cluster_strength_assessment(run)
    panels = assessment["panels"]
    
    # 计算归一化HHI (用于旧接口兼容)
    def _normalized_hhi_from_panel(panel_dict: Dict[str, Any]) -> Optional[float]:
        main = panel_dict.get("main", {})
        hhi = main.get("hhi", 0)
        n = main.get("n", 0)
        if n <= 1:
            return 1.0 if n == 1 else None
        if hhi == 0:
            return None
        norm = (hhi - 1.0 / n) / (1.0 - 1.0 / n)
        return float(max(0.0, min(1.0, norm)))
    
    return {
        "ECR": _normalized_hhi_from_panel(panels["short"]),
        "SER": _normalized_hhi_from_panel(panels["mid"]),
        "TSR": _normalized_hhi_from_panel(panels["long"]),
        "n_short": panels["short"]["main"]["n"],
        "n_mid": panels["mid"]["main"]["n"],
        "n_long": panels["long"]["main"]["n"],
        # 新增指标
        "top1_short": panels["short"]["main"]["top1"],
        "top1_mid": panels["mid"]["main"]["top1"],
        "top1_long": panels["long"]["main"]["top1"],
        "enp_short": panels["short"]["main"]["enp"],
        "enp_mid": panels["mid"]["main"]["enp"],
        "enp_long": panels["long"]["main"]["enp"],
    }


def interpret_micro_structure(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    [新增] 微观结构物理含义转译层
    将 ECR/SER/TSR 数值转化为 LLM 可理解的物理状态
    """
    ecr = metrics.get("ECR") or 0
    ser = metrics.get("SER") or 0
    tsr = metrics.get("TSR") or 0
    
    # 1. 墙体物理属性 (Wall Physics) - 基于 ECR (集中度)
    # ECR 越高，筹码越集中在单一期限，墙越硬(Rigid)，容易 Pinning
    if ecr > 0.65:
        wall_type = "Rigid (刚性墙)"
        breakout_difficulty = "High"
        wall_note = "筹码高度集中，突破需巨大动能，容易引发Gamma Pinning"
    elif ecr < 0.35:
        wall_type = "Brittle (脆性墙)"
        breakout_difficulty = "Low"
        wall_note = "筹码分散，墙体薄弱，容易被穿透"
    else:
        wall_type = "Elastic (弹性墙)"
        breakout_difficulty = "Medium"
        wall_note = "结构均衡，提供正常阻力"

    # 2. 续航/接力能力 (Sustain Potential) - 基于 SER (次强结构)
    # SER 越高，说明次强期限有接力能力，趋势容易延续
    if ser > 0.55:
        sustain_potential = "High"
        sustain_note = "次级期限结构完整，突破后有接力(Relay)，趋势延续性强"
    else:
        sustain_potential = "Low"
        sustain_note = "次级结构空虚，警惕假突破(False Breakout)或缺乏后续动能"

    return {
        "wall_type": wall_type,
        "breakout_difficulty": breakout_difficulty,
        "sustain_potential": sustain_potential,
        "interpretation": f"{wall_type}，突破难度{breakout_difficulty}。{sustain_note}。",
        "raw_metrics": {
            "ECR": round(ecr, 3),
            "SER": round(ser, 3),
            "TSR": round(tsr, 3)
        }
    }


# ============================================================
# InputFileCalculator 类
# ============================================================

class InputFileCalculator:
    """
    输入文件计算器
    处理 -i 参数指定的 symbol_datetime.json 文件
    """
    
    def __init__(self, input_path: str):
        """
        初始化计算器
        
        Args:
            input_path: 输入文件路径
        """
        self.input_path = Path(input_path)
        self.data: Dict[str, Any] = {}
        self._assessment: Dict[str, Any] = {}
        self._cluster_assessment: Optional[ClusterAssessment] = None
        
    def load(self) -> Dict[str, Any]:
        """
        加载输入文件
        """
        if not self.input_path.exists():
            raise FileNotFoundError(f"输入文件不存在: {self.input_path}")
        
        self.data = load_json_with_comments(str(self.input_path))
        logger.info(f"📂 成功加载输入文件: {self.input_path}")
        
        # 提取元信息用于日志
        metadata = self.data.get("metadata", {})
        spec_targets = self.data.get("spec", {}).get("targets", {})
        symbol = spec_targets.get("symbol") or metadata.get("symbol", "UNKNOWN")
        as_of = metadata.get("as_of", "N/A")
        logger.info(f"🎯 标的: {symbol}, 日期: {as_of}")
        
        return self.data
    
    def calculate(self) -> Dict[str, Any]:
        """
        执行计算
        
        Returns:
            计算结果字典
        """
        if not self.data:
            self.load()
        
        # 检查 panels 数据是否存在
        metadata = self.data.get("metadata", {})
        panels = metadata.get("panels") or self.data.get("panels")
        if not panels:
            raise ValueError("输入文件缺少 panels 字段")
        
        logger.info(f"📋 发现 {len(panels) if isinstance(panels, list) else 'N/A'} 个 panel")
        
        # 执行评估计算（字典格式）
        self._assessment = compute_cluster_strength_assessment(self.data)
        
        # 同时执行新的 dataclass 格式评估
        self._cluster_assessment = compute_cluster_strength_assessment_v2(self.data)
        
        # [新增] 计算微观结构指标 (ECR/SER/TSR) 并转译
        raw_micro = compute_ECR_SER_TSR(self.data)
        micro_structure = interpret_micro_structure(raw_micro)

        # 提取关键结果
        summary = self._assessment["summary"]
        top_summary = self._assessment["top_summary"]
        
        result = {
            "cluster_strength_ratio": self._assessment["cluster_strength_ratio"],
            "tier": self._assessment["tier"],
            "avg_top1": summary["avg_top1_main"],
            "avg_enp": summary["avg_enp_main"],
            "micro_structure": micro_structure,  # [新增]
            # 各panel详情
            "short": {
                "top1": top_summary["short"]["top1"],
                "top2": top_summary["short"]["top2"],
                "enp": top_summary["short"]["enp"],
                "n": top_summary["short"]["n"],
            },
            "mid": {
                "top1": top_summary["mid"]["top1"],
                "top2": top_summary["mid"]["top2"],
                "enp": top_summary["mid"]["enp"],
                "n": top_summary["mid"]["n"],
            },
            "long": {
                "top1": top_summary["long"]["top1"],
                "top2": top_summary["long"]["top2"],
                "enp": top_summary["long"]["enp"],
                "n": top_summary["long"]["n"],
            },
        }
        
        return result
    
    def calculate_v2(self) -> ClusterAssessment:
        """
        执行计算（返回 ClusterAssessment dataclass）
        
        Returns:
            ClusterAssessment 对象
        """
        if not self.data:
            self.load()
        
        # 检查 panels 数据是否存在
        metadata = self.data.get("metadata", {})
        panels = metadata.get("panels") or self.data.get("panels")
        if not panels:
            raise ValueError("输入文件缺少 panels 字段")
        
        if isinstance(panels, dict):
            panels = list(panels.values())
        
        self._cluster_assessment = assess_cluster_strength(panels)
        return self._cluster_assessment
    
    def get_cluster_assessment(self) -> Optional[ClusterAssessment]:
        """
        获取 ClusterAssessment 结果
        
        Returns:
            ClusterAssessment 对象，如果还未计算则返回 None
        """
        return self._cluster_assessment
    
    def write_back(self, output_path: str = None) -> str:
        """
        将计算结果写回文件
        """
        if not self.data:
            self.load()
        
        # 执行计算（如果还没计算过）
        if not self._assessment:
            self.calculate()
        
        ratio = self._assessment.get("cluster_strength_ratio")
        
        # 更新数据结构
        if "spec" not in self.data:
            self.data["spec"] = {}
        if "targets" not in self.data["spec"]:
            self.data["spec"]["targets"] = {}
        if "gamma_metrics" not in self.data["spec"]["targets"]:
            self.data["spec"]["targets"]["gamma_metrics"] = {}
        
        self.data["spec"]["targets"]["gamma_metrics"]["cluster_strength_ratio"] = ratio
        
        # [新增] 写入微观结构分析
        if self._assessment:
             # 重新获取(确保已有)
             raw_micro = compute_ECR_SER_TSR(self.data)
             micro_data = interpret_micro_structure(raw_micro)
             self.data["spec"]["targets"]["gamma_metrics"]["micro_structure"] = micro_data

        # 如果有 ClusterAssessment 结果，也写入
        if self._cluster_assessment:
            self.data["spec"]["targets"]["gamma_metrics"]["cluster_assessment"] = {
                "tier": self._cluster_assessment.tier,
                "score": self._cluster_assessment.score,
                "avg_top1": self._cluster_assessment.avg_top1,
                "avg_enp": self._cluster_assessment.avg_enp,
                "panels": [asdict(pm) for pm in self._cluster_assessment.panels],
            }
        
        # 确定输出路径
        out_path = Path(output_path) if output_path else self.input_path
        
        # 写入文件
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        
        logger.success(f"💾 计算结果已写回: {out_path}")
        
        return str(out_path)


# ============================================================
# 入口函数
# ============================================================

def calculate_and_update(input_file: Path) -> Dict[str, Any]:
    """
    主函数：读取 symbol_datetime.json，计算 cluster_strength_ratio 并写回
    """
    try:
        calculator = InputFileCalculator(str(input_file))
        calculator.load()
        result = calculator.calculate()
        calculator.write_back()
        
        # 提取元信息
        metadata = calculator.data.get("metadata", {})
        spec_targets = calculator.data.get("spec", {}).get("targets", {})
        symbol = spec_targets.get("symbol") or metadata.get("symbol", "UNKNOWN")
        as_of = metadata.get("as_of", "N/A")
        
        return {
            "status": "success",
            "symbol": symbol,
            "as_of": as_of,
            "cluster_strength_ratio": result["cluster_strength_ratio"],
            "tier": result["tier"],
            "summary": {
                "avg_top1": result["avg_top1"],
                "avg_enp": result["avg_enp"],
            },
            "panels": {
                "short": result["short"],
                "mid": result["mid"],
                "long": result["long"],
            },
            "micro_structure": result.get("micro_structure"), # [新增]
            "file_path": str(input_file)
        }
    
    except Exception as e:
        logger.exception("❌ 执行失败")
        return {
            "status": "error",
            "error_message": str(e),
            "error_type": type(e).__name__
        }


def process_input_file(input_path: str, output_path: str = None) -> Dict[str, Any]:
    """
    处理输入文件的便捷函数
    """
    calculator = InputFileCalculator(input_path)
    calculator.load()
    result = calculator.calculate()
    calculator.write_back(output_path)
    return result


def main(input_path: str, output_path: str = None, **kwargs) -> Dict[str, Any]:
    """
    主入口函数 (Code Node 入口)
    """
    try:
        file_path = Path(input_path)
        return calculate_and_update(file_path)
    except Exception as e:
        logger.exception("❌ 执行失败")
        return {
            "status": "error",
            "error_message": str(e),
            "error_type": type(e).__name__
        }