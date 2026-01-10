"""
动态参数计算器 - 基于 Alpha-Beta 矩阵计算 Agent2 抓取参数
"""
from typing import Dict


class MarketStateCalculator:
    """
    市场状态参数计算器
    
    基于 VIX/IVR/IV30/HV20 四维度计算动态抓取参数
    """
    
    @staticmethod
    def calculate_fetch_params(
        vix: float,
        ivr: float,
        iv30: float,
        hv20: float,
        term_structure: dict | None = None,
    ) -> Dict[str, any]:
        """
        基于 Alpha-Beta 矩阵解算 Agent2 的抓取参数
        
        Args:
            vix: VIX 指数 (如 18.5)
            ivr: IV Rank 0-100 (如 65.3)
            iv30: 30日隐含波动率 (如 42.8)
            hv20: 20日历史波动率 (如 38.2)
            term_structure: Bridge 下发的期限结构信息（可选）
            
        Returns:
            {
                "dyn_strikes": int,          # Strike范围
                "dyn_dte_short": str,        # 短期DTE (如 "14w")
                "dyn_dte_mid": str,          # 中期DTE (如 "30 w")
                "dyn_dte_long_backup": str,  # 长期DTE (如 "60 m")
                "dyn_window": int,           # 窗口大小 (如 60)
                "scenario": str,             # 场景名称 (用于日志)
                "vrp": float                 # 波动率溢价比 (用于日志)
            }
        """
        # 计算波动率溢价比 (VRP)
        vrp = iv30 / hv20 if hv20 > 0 else 1.0
        
        # 默认值 (Normal / Trend)
        params = {
            "dyn_strikes": 30,
            "dyn_dte_short": "14 w",
            "dyn_dte_mid": "30 w",
            "dyn_dte_long_backup": "60 m",
            "dyn_window": 60,
            "scenario": "Normal/Trend",
            "vrp": vrp
        }

        # 场景 1: Squeeze / Panic (双高)
        # 逻辑：市场极不稳定，只看眼前，防止穿仓
        if vrp > 1.15 or ivr > 80:
            if vix > 25:
                params.update({
                    "dyn_strikes": 50,
                    "dyn_dte_short": "3 w",
                    "dyn_dte_mid": "7 w",
                    "dyn_dte_long_backup": "14 w",
                    "dyn_window": 20,
                    "scenario": "Squeeze/Panic"
                })
            # 场景 2: Squeeze / Panic (个股独角戏)
            # 逻辑：个股爆发，大盘稳，关注稍长的爆发期
            else:
                params.update({
                    "dyn_strikes": 45,
                    "dyn_dte_short": "7 w",
                    "dyn_dte_mid": "14 w",
                    "dyn_dte_long_backup": "30 w",
                    "dyn_window": 45,
                    "scenario": "Squeeze/Panic"
                })
                
        # 场景 3: Grind / Low Vol (双低)
        # 逻辑：死鱼行情，需极长 DTE 才能看到结构
        elif vrp < 0.9 or ivr < 30:
            if vix < 15:
                params.update({
                    "dyn_strikes": 25,
                    "dyn_dte_short": "30 w",
                    "dyn_dte_mid": "60 m",
                    "dyn_dte_long_backup": "90 m",
                    "dyn_window": 90,
                    "scenario": "Grind/Low Vol"
                })
            # 场景 4: Grind / High VIX (背离)
            # 逻辑：大盘恐慌个股抗跌，避险配置
            else:
                params.update({
                    "dyn_strikes": 35,
                    "dyn_dte_short": "21 w",
                    "dyn_dte_mid": "45 w",
                    "dyn_dte_long_backup": "60 m",
                    "dyn_window": 60,
                    "scenario": "Grind/High VIX"
                })

        if term_structure:
            params = MarketStateCalculator._apply_term_structure_bias(params, term_structure)

        return params
    
    @staticmethod
    def validate_params(market_params: Dict[str, float]) -> None:
        """
        验证市场参数的合法性
        
        Args:
            market_params: 包含 vix, ivr, iv30, hv20 的字典
            
        Raises:
            ValueError: 参数不合法时抛出异常
        """
        required_keys = ["vix", "ivr", "iv30", "hv20"]
        missing_keys = [k for k in required_keys if k not in market_params or market_params[k] is None]
        
        if missing_keys:
            raise ValueError(f"缺失必需的市场参数: {missing_keys}")
        
        vix = market_params["vix"]
        ivr = market_params["ivr"]
        iv30 = market_params["iv30"]
        hv20 = market_params["hv20"]
        
        # 范围验证
        if not (0 <= ivr <= 100):
            raise ValueError(f"IVR 必须在 0-100 之间，当前值: {ivr}")
        
        if vix < 0:
            raise ValueError(f"VIX 必须为非负数，当前值: {vix}")
        
        if iv30 < 0:
            raise ValueError(f"IV30 必须为非负数，当前值: {iv30}")
        
        if hv20 <= 0:
            raise ValueError(f"HV20 必须为正数 (用于计算VRP)，当前值: {hv20}")

    @staticmethod
    def _apply_term_structure_bias(params: Dict[str, any], term_structure: Dict[str, any]) -> Dict[str, any]:
        """
        使用 Bridge 下发的 horizon_bias 调整 dyn_dte_short/mid/long_backup 与 dyn_window
        """
        hb = (term_structure or {}).get("horizon_bias", {}) or {}
        b_short = float(hb.get("short", 1.0) or 1.0)
        b_mid = float(hb.get("mid", 1.0) or 1.0)
        b_long = float(hb.get("long", 1.0) or 1.0)

        # === 1) DTE 字符串缩放 ===
        # 期望输入形如 "14 w" / "60 m"，解析数字部分再缩放
        def _scale_dte(dte_str: str, bias: float, global_scale: float = 0.3) -> str:
            import re

            if not dte_str:
                return dte_str
            match = re.match(r"^\s*(\d+)\s*([dwmy])", dte_str)
            if not match:
                return dte_str

            base = int(match.group(1))
            unit = match.group(2)

            scale_factor = 1.0 + global_scale * (bias - 1.0)
            scale_factor = max(0.5, min(1.5, scale_factor))

            new_base = int(round(base * scale_factor))
            new_base = max(3, min(365, new_base))
            return f"{new_base} {unit}"

        params["dyn_dte_short"] = _scale_dte(params.get("dyn_dte_short"), b_short)
        params["dyn_dte_mid"] = _scale_dte(params.get("dyn_dte_mid"), b_mid)
        params["dyn_dte_long_backup"] = _scale_dte(params.get("dyn_dte_long_backup"), b_long)

        # === 2) dyn_window 缩放 ===
        window = params.get("dyn_window")
        try:
            window_val = int(window)
        except (TypeError, ValueError):
            return params

        avg_bias = (b_short + b_mid + b_long) / 3.0
        window_scale = 0.3
        w_factor = 1.0 + window_scale * (avg_bias - 1.0)
        w_factor = max(0.5, min(1.5, w_factor))

        new_window = int(round(window_val * w_factor))
        new_window = max(10, min(120, new_window))
        params["dyn_window"] = new_window

        if "label" in term_structure:
            params["term_structure_label"] = term_structure["label"]
        params["term_structure_bias"] = {
            "short": b_short,
            "mid": b_mid,
            "long": b_long,
        }

        return params
