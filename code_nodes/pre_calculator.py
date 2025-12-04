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
        hv20: float
    ) -> Dict[str, any]:
        """
        基于 Alpha-Beta 矩阵解算 Agent2 的抓取参数
        
        Args:
            vix: VIX 指数 (如 18.5)
            ivr: IV Rank 0-100 (如 65.3)
            iv30: 30日隐含波动率 (如 42.8)
            hv20: 20日历史波动率 (如 38.2)
            
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
                    "dyn_dte_short": "3w",
                    "dyn_dte_mid": "7w",
                    "dyn_dte_long_backup": "14w",
                    "dyn_window": 20,
                })
            # 场景 2: Squeeze / Panic (个股独角戏)
            # 逻辑：个股爆发，大盘稳，关注稍长的爆发期
            else:
                params.update({
                    "dyn_strikes": 45,
                    "dyn_dte_short": "7w",
                    "dyn_dte_mid": "14w",
                    "dyn_dte_long_backup": "30 w",
                    "dyn_window": 45,
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
                })
            # 场景 4: Grind / High VIX (背离)
            # 逻辑：大盘恐慌个股抗跌，避险配置
            else:
                params.update({
                    "dyn_strikes": 35,
                    "dyn_dte_short": "21w",
                    "dyn_dte_mid": "45w",
                    "dyn_dte_long_backup": "60 m",
                    "dyn_window": 60,
                })
        
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
