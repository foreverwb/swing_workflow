"""
FieldCalculator - 字段关联计算引擎（重构版）
特性：
1. 配置对象化访问（无需硬编码键名）
2. 实现 Lambda 扩展系数计算
3. 动态敏感度系数（基于 Beta 和财报日期）
4. Beta 和财报日期从配置/缓存/命令行获取
"""

import json
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from utils.config_loader import config

class FieldCalculator:
    """字段关联计算器（重构版）"""
    
    def __init__(
        self, 
        config_loader, 
        market_params: Dict[str, float] = None,
        event_data: Dict[str, Any] = None
    ):
        """
        初始化计算器
        
        Args:
            config_loader: ConfigLoader 实例
            market_params: 市场参数 (vix, ivr, iv30, hv20, beta, earning_date)
            event_data: 事件检测数据（包含 days_to_earnings）
        """
        # 一次性获取所有配置
        self.gamma_config = config_loader.get_section('gamma')
        self.beta_config = config_loader.get_section('beta')
        self.market_params = market_params or {}
        self.event_data = event_data or {}
    
    def get_beta(self, symbol: str) -> float:
        """
        获取股票 Beta 值
        
        优先级：
        1. market_params 中用户指定的 beta（命令行/缓存）
        2. 配置文件中的 stock_overrides
        3. 配置文件中的 symbol_to_sector → sector_defaults
        4. 默认值 (1.0)
        
        Args:
            symbol: 股票代码
            
        Returns:
            Beta 值
        """
        symbol_upper = symbol.upper()
        
        # 1. 优先使用 market_params 中用户指定的 beta
        user_beta = self.market_params.get('beta')
        if user_beta is not None:
            return user_beta
        
        # 2. 查找配置文件中的股票级别预设
        stock_overrides = self.beta_config.get('stock_overrides', {})
        if symbol_upper in stock_overrides:
            return stock_overrides[symbol_upper]
        
        # 3. 查找股票到板块的映射
        symbol_to_sector = self.beta_config.get('symbol_to_sector', {})
        sector_defaults = self.beta_config.get('sector_defaults', {})
        
        if symbol_upper in symbol_to_sector:
            sector = symbol_to_sector[symbol_upper]
            if sector in sector_defaults:
                return sector_defaults[sector]
        
        # 4. 返回默认值
        return self.beta_config.get('default_beta', 1.0)
    
    def calculate_t_scale(self) -> Tuple[float, Dict]:
        """
        计算波动率时间缩放系数 T_scale
        
        T_scale = (HV20 / IV30)^0.8
        
        逻辑:
        - IV > HV (溢价高) -> T_scale < 1 -> 缩短持仓时间
        - IV < HV (折价)   -> T_scale > 1 -> 延长持仓时间
        
        Returns:
            (t_scale, details_dict) 元组
        """
        hv20 = self.market_params.get('hv20', 30.0)
        iv30 = self.market_params.get('iv30', 30.0)
        
        # 防止除零
        if iv30 <= 0:
            iv30 = 30.0
        if hv20 <= 0:
            hv20 = 30.0
        
        # T_scale = (HV20 / IV30)^0.8
        t_scale = (hv20 / iv30) ** 0.8
        
        # 钳制到合理范围 [0.5, 2.0]
        t_scale_raw = t_scale
        t_scale = max(0.5, min(2.0, t_scale))
        
        # VRP (Volatility Risk Premium)
        vrp = iv30 / hv20 if hv20 > 0 else 1.0
        
        # 波动率状态判断
        if t_scale < 0.9:
            vol_state = "高IV溢价"
            vol_implication = "市场预期波动大，建议缩短持仓"
        elif t_scale > 1.1:
            vol_state = "低IV溢价"
            vol_implication = "市场预期平静，可延长持仓"
        else:
            vol_state = "IV/HV均衡"
            vol_implication = "正常持仓周期"
        
        details = {
            't_scale': round(t_scale, 3),
            't_scale_raw': round(t_scale_raw, 3),
            'hv20': hv20,
            'iv30': iv30,
            'vrp': round(vrp, 3),
            'vol_state': vol_state,
            'vol_implication': vol_implication
        }
        
        return round(t_scale, 3), details
    
    def get_days_to_earnings(self) -> Optional[int]:
        """
        获取距离财报的天数
        
        优先级：
        1. market_params 中的 earning_date（命令行/缓存）→ 计算天数
        2. event_data 中的 days_away（事件检测结果）
        
        Returns:
            距离财报天数，无数据返回 None
        """
        # 1. 优先使用 market_params 中的 earning_date
        earning_date_str = self.market_params.get('earning_date')
        if earning_date_str:
            try:
                earning_date = datetime.strptime(earning_date_str, "%Y-%m-%d")
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                days_to_earnings = (earning_date - today).days
                return days_to_earnings
            except ValueError:
                pass  # 日期格式错误，跳过
        
        # 2. 从 event_data 中提取
        events = self.event_data.get('events', {})
        earnings = events.get('earnings', {})
        
        if earnings and earnings.get('days_away') is not None:
            return earnings['days_away']
        
        return None
    
    def get_sensitivity_coeffs(self, symbol: str) -> Tuple[float, float]:
        """
        根据标的属性动态获取敏感度系数，消除魔法数字
        
        Args:
            symbol: 股票代码
            
        Returns:
            (k_sys, k_idiosync) 元组
        """
        beta = self.get_beta(symbol)
        days_to_earnings = self.get_days_to_earnings()
        
        # 从配置读取阈值
        sensitivity = self.beta_config.get('sensitivity', {})
        high_beta_threshold = sensitivity.get('high_beta_threshold', 1.3)
        low_beta_threshold = sensitivity.get('low_beta_threshold', 0.7)
        k_sys_high = sensitivity.get('k_sys_high', 0.8)
        k_sys_standard = sensitivity.get('k_sys_standard', 0.5)
        k_sys_low = sensitivity.get('k_sys_low', 0.3)
        earnings_warning_days = sensitivity.get('earnings_warning_days', 14)
        k_idiosync_high = sensitivity.get('k_idiosync_high', 1.0)
        k_idiosync_normal = sensitivity.get('k_idiosync_normal', 0.5)
        
        # 1. 动态计算 k_sys (基于 Beta)
        if beta > high_beta_threshold:
            k_sys = k_sys_high  # 高敏感（高 Beta 股票）
        elif beta < low_beta_threshold:
            k_sys = k_sys_low   # 低敏感（防御型股票）
        else:
            k_sys = k_sys_standard  # 标准
        
        # 2. 动态计算 k_idiosync (基于事件风险)
        if days_to_earnings is not None and days_to_earnings <= earnings_warning_days:
            k_idiosync = k_idiosync_high  # 临近财报，防御等级拉满
        else:
            k_idiosync = k_idiosync_normal  # 常规防御
        
        return k_sys, k_idiosync
    
    def validate_raw_fields(self, data: Dict) -> Dict:
        """验证原始字段完整性（27个，含 validation_metrics 4个）"""
        targets = data.get('targets', {})
        
        if isinstance(targets, str):
            try:
                targets = json.loads(targets)
            except json.JSONDecodeError:
                targets = {}
        
        missing_fields = []
        
        # 1. 顶层字段 (2个)
        if not self._is_valid_value(targets.get('symbol')):
            missing_fields.append({"field": "symbol", "path": "symbol"})
        if not self._is_valid_value(targets.get('spot_price')):
            missing_fields.append({"field": "spot_price", "path": "spot_price"})
        
        # 2. walls (4个)
        walls = targets.get('walls', {})
        for field in ["call_wall", "put_wall", "major_wall", "major_wall_type"]:
            if not self._is_valid_value(walls.get(field)):
                missing_fields.append({"field": field, "path": f"walls.{field}"})
        
        # 3. gamma_metrics (11个)
        gamma_metrics = targets.get('gamma_metrics', {})
        gamma_fields = ["vol_trigger", "spot_vs_trigger", "net_gex", 
                       "gap_distance_dollar"]
        for field in gamma_fields:
            if not self._is_valid_value(gamma_metrics.get(field)):
                missing_fields.append({"field": field, "path": f"gamma_metrics.{field}"})
        
        # nearby_peak
        nearby_peak = gamma_metrics.get('nearby_peak', {})
        for field in ["price", "abs_gex"]:
            if not self._is_valid_value(nearby_peak.get(field)):
                missing_fields.append({"field": f"nearby_peak_{field}", "path": f"gamma_metrics.nearby_peak.{field}"})
        
        # next_cluster_peak
        next_cluster_peak = gamma_metrics.get('next_cluster_peak', {})
        for field in ["price", "abs_gex"]:
            if not self._is_valid_value(next_cluster_peak.get(field)):
                missing_fields.append({"field": f"next_cluster_peak_{field}", "path": f"gamma_metrics.next_cluster_peak.{field}"})
        
        # 4. directional_metrics (5个)
        directional_metrics = targets.get('directional_metrics', {})
        directional_fields = ["dex_same_dir_pct", "vanna_dir", "vanna_confidence", 
                            "iv_path", "iv_path_confidence"]
        for field in directional_fields:
            if not self._is_valid_value(directional_metrics.get(field)):
                missing_fields.append({"field": field, "path": f"directional_metrics.{field}"})
        
        # 5. atm_iv (3个)
        atm_iv = targets.get('atm_iv', {})
        for field in ["iv_7d", "iv_14d", "iv_source"]:
            if not self._is_valid_value(atm_iv.get(field)):
                missing_fields.append({"field": field, "path": f"atm_iv.{field}"})
        
        # 6. validation_metrics (4个) - 允许 null，但需要记录
        validation_metrics = targets.get('validation_metrics', {})
        validation_fields = ["zero_dte_ratio", "net_volume_signal", "net_vega_exposure", "net_theta_exposure"]
        validation_missing = []
        for field in validation_fields:
            value = validation_metrics.get(field)
            # validation_metrics 允许 null，但如果整个对象不存在则记录
            if validation_metrics and value is None:
                validation_missing.append({"field": field, "path": f"validation_metrics.{field}", "severity": "high"})
        
        # 核心字段总数（不含 validation_metrics）
        core_required = 23
        core_provided = core_required - len(missing_fields)
        
        # 含 validation_metrics 的总数
        total_required = 27
        total_missing = len(missing_fields) + len(validation_missing)
        total_provided = total_required - total_missing
        
        return {
            "is_complete": len(missing_fields) == 0,  # 核心字段完整即可
            "missing_fields": missing_fields,
            "validation_missing": validation_missing,  # 单独记录验证字段缺失
            "total_required": total_required,
            "core_required": core_required,
            "provided": total_provided,
            "core_provided": core_provided,
            "completion_rate": int((core_provided / core_required) * 100),
            "validation_rate": int(((4 - len(validation_missing)) / 4) * 100) if validation_metrics else 0
        }
    
    def calculate_all(self, data: Dict) -> Dict:
        """计算所有衍生字段（3个 + 指数 + 波动率指标）"""
        targets = data.get('targets', {})
        if isinstance(targets, str):
            try:
                targets = json.loads(targets)
            except json.JSONDecodeError:
                targets = {}
        
        # 计算 em1_dollar（包含 Lambda 调整）
        targets = self._calculate_em1_dollar(targets)
        
        # 计算 gap_distance_em1_multiple
        targets = self._calculate_gap_distance_em1(targets)
        
        # 计算 cluster_strength_ratio
        targets = self._calculate_cluster_strength_ratio(targets)
        
        # 计算 monthly_cluster_override
        targets = self._calculate_monthly_cluster_override(targets)
        
        # 计算指数 EM1$
        targets = self._calculate_indices_em1(targets)
        
        # 计算 T_scale 并聚合波动率指标
        targets = self._aggregate_volatility_metrics(targets)
        
        # 验证计算结果
        validation = self._validate_calculations(targets)
        targets['_calculation_log'] = validation
        
        data['targets'] = targets
        return data
    
    def _aggregate_volatility_metrics(self, targets: Dict) -> Dict:
        """
        聚合波动率相关指标供下游使用
        
        包含:
        - lambda_factor: EM1$ 扩展系数
        - t_scale: 波动率时间缩放系数
        - 相关细节用于策略决策
        """
        # 计算 T_scale
        t_scale, t_scale_details = self.calculate_t_scale()
        
        # 从 _lambda_details 提取 lambda_factor
        lambda_details = targets.get('_lambda_details', {})
        lambda_factor = lambda_details.get('lambda_factor', 1.0)
        
        # 聚合波动率指标
        volatility_metrics = {
            # 核心指标（供下游直接使用）
            'lambda_factor': lambda_factor,
            't_scale': t_scale,
            
            # Lambda 细节
            'lambda_details': {
                'beta': lambda_details.get('beta', 1.0),
                'beta_source': lambda_details.get('beta_source', 'default'),
                'k_sys': lambda_details.get('k_sys', 0.5),
                'k_idiosync': lambda_details.get('k_idiosync', 0.5),
                'vix_premium': lambda_details.get('vix_premium', 0),
                'ivr_premium': lambda_details.get('ivr_premium', 0),
                'days_to_earnings': lambda_details.get('days_to_earnings'),
                'earning_source': lambda_details.get('earning_source', 'none'),
                'raw_em1': lambda_details.get('raw_em1', 0)
            },
            
            # T_scale 细节
            't_scale_details': t_scale_details,
            
            # 市场参数快照
            'market_snapshot': {
                'vix': self.market_params.get('vix'),
                'ivr': self.market_params.get('ivr'),
                'iv30': self.market_params.get('iv30'),
                'hv20': self.market_params.get('hv20')
            }
        }
        
        targets['volatility_metrics'] = volatility_metrics
        
        # 日志输出
        print(f"\n📊 波动率指标汇总:")
        print(f"   • Lambda Factor = {lambda_factor:.3f}")
        print(f"   • T_scale = {t_scale:.3f} ({t_scale_details['vol_state']})")
        print(f"   • VRP = {t_scale_details['vrp']:.2f} (IV30/HV20)")
        
        return targets
    
    def _calculate_em1_dollar(self, targets: Dict) -> Dict:
        """
        计算 EM1$ = Raw_EM1$ × Lambda
        
        公式：
        1. Raw_EM1$ = spot_price × min(iv_7d, iv_14d) × sqrt(1/252)
        2. Lambda = 1.0 + k_sys × max(0, (VIX - VIX_base)/100) 
                        + k_idiosync × max(0, (IVR_floor - IVR)/100)
        3. Adjusted_EM1$ = Raw_EM1$ × Lambda
        
        动态敏感度系数：
        - k_sys: 基于 Beta 动态计算（高 Beta 股票更敏感）
        - k_idiosync: 基于财报日期动态计算（临近财报提高防御）
        """
        symbol = targets.get('symbol', 'UNKNOWN')
        spot_price = targets.get('spot_price')
        atm_iv = targets.get('atm_iv', {})
        iv_7d = atm_iv.get('iv_7d')
        iv_14d = atm_iv.get('iv_14d')
        
        if not all([spot_price, iv_7d, iv_14d]):
            print(f"⚠️ EM1$ 计算缺失输入: spot={spot_price}, iv_7d={iv_7d}, iv_14d={iv_14d}")
            targets['em1_dollar'] = -999
            return targets
        
        
        # Step 1: 计算物理锚点 (Raw_EM1$)
        
        min_iv = min(iv_7d, iv_14d)
        # 从配置对象读取
        em1_sqrt_factor = self.gamma_config.em1_sqrt_factor
        raw_em1 = spot_price * min_iv * em1_sqrt_factor
        
        
        # Step 2: 计算 Lambda 扩展系数
        vix_curr = self.market_params.get('vix', 15.0)
        ivr_curr = self.market_params.get('ivr', 50.0)
        
        # 动态获取敏感度系数（基于 Beta 和财报日期）
        k_sys, k_idiosync = self.get_sensitivity_coeffs(symbol)
        
        # 从配置对象读取基准参数
        vix_base = self.gamma_config.lambda_vix_base
        ivr_floor = self.gamma_config.lambda_ivr_floor
        
        # 获取 Beta 和财报信息用于日志
        beta = self.get_beta(symbol)
        days_to_earnings = self.get_days_to_earnings()
        
        # 判断 Beta 来源
        beta_source = self._get_beta_source(symbol)
        
        # 判断财报日期来源
        earning_source = self._get_earning_source()
        
        # VIX 部分：系统性溢价
        vix_premium = k_sys * max(0, (vix_curr - vix_base) / 100)
        
        # IVR 部分：低波防爆补偿
        ivr_premium = k_idiosync * max(0, (ivr_floor - ivr_curr) / 100)
        
        # 汇总 Lambda
        lambda_factor = 1.0 + vix_premium + ivr_premium
        
        # Step 3: 最终 EM1$（调整后）
        
        adjusted_em1 = raw_em1 * lambda_factor
        
        # 保存结果
        targets['em1_dollar'] = round(adjusted_em1, 2)
        
        # 保存 Lambda 计算细节（供后续分析）
        targets['_lambda_details'] = {
            'beta': beta,
            'beta_source': beta_source,
            'days_to_earnings': days_to_earnings,
            'earning_source': earning_source,
            'k_sys': k_sys,
            'k_idiosync': k_idiosync,
            'vix_premium': round(vix_premium, 4),
            'ivr_premium': round(ivr_premium, 4),
            'lambda_factor': round(lambda_factor, 4),
            'raw_em1': round(raw_em1, 2)
        }
        
        
        # 日志输出（详细分解）
        
        print(f"✅ EM1$ 计算完成:")
        print(f"   [物理锚点] Raw_EM1$ = {spot_price} × {min_iv:.4f} × {em1_sqrt_factor} = ${raw_em1:.2f}")
        print(f"   [动态敏感度系数]")
        print(f"      • Beta = {beta:.2f} ({beta_source}) → k_sys = {k_sys}")
        earnings_info = f"{days_to_earnings}天 ({earning_source})" if days_to_earnings is not None else "无数据"
        print(f"      • 距财报 = {earnings_info} → k_idiosync = {k_idiosync}")
        print(f"   [Lambda 系数]")
        print(f"      • VIX 溢价: {k_sys} × max(0, ({vix_curr} - {vix_base})/100) = {vix_premium:.3f}")
        print(f"      • IVR 补偿: {k_idiosync} × max(0, ({ivr_floor} - {ivr_curr})/100) = {ivr_premium:.3f}")
        print(f"      • Lambda = 1.0 + {vix_premium:.3f} + {ivr_premium:.3f} = {lambda_factor:.3f}")
        print(f"   [最终结果] Adjusted_EM1$ = {raw_em1:.2f} × {lambda_factor:.3f} = ${adjusted_em1:.2f}")
        
        return targets
    
    def _get_beta_source(self, symbol: str) -> str:
        """获取 Beta 值的来源"""
        symbol_upper = symbol.upper()
        
        # 1. 用户指定
        if self.market_params.get('beta') is not None:
            return "用户指定"
        
        # 2. 股票预设
        stock_overrides = self.beta_config.get('stock_overrides', {})
        if symbol_upper in stock_overrides:
            return "股票预设"
        
        # 3. 板块映射
        symbol_to_sector = self.beta_config.get('symbol_to_sector', {})
        if symbol_upper in symbol_to_sector:
            return f"板块映射:{symbol_to_sector[symbol_upper]}"
        
        # 4. 默认值
        return "默认值"
    
    def _get_earning_source(self) -> str:
        """获取财报日期的来源"""
        # 1. 用户指定
        if self.market_params.get('earning_date'):
            return "用户指定"
        
        # 2. 事件检测
        events = self.event_data.get('events', {})
        if events.get('earnings', {}).get('days_away') is not None:
            return "事件检测"
        
        return "无数据"
    
    def _calculate_gap_distance_em1(self, targets: Dict) -> Dict:
        """计算 gap_distance_em1_multiple = gap_distance_dollar ÷ em1_dollar"""
        gamma_metrics = targets.get('gamma_metrics', {})
        gap_distance_dollar = gamma_metrics.get('gap_distance_dollar')
        em1_dollar = targets.get('em1_dollar')
        
        if not gap_distance_dollar or not em1_dollar or em1_dollar == -999:
            print(f"⚠️ gap_distance_em1_multiple 计算缺失输入")
            if 'gamma_metrics' not in targets:
                targets['gamma_metrics'] = {}
            targets['gamma_metrics']['gap_distance_em1_multiple'] = -999
            return targets
        
        gap_distance_em1 = gap_distance_dollar / em1_dollar
        
        if 'gamma_metrics' not in targets:
            targets['gamma_metrics'] = {}
        targets['gamma_metrics']['gap_distance_em1_multiple'] = round(gap_distance_em1, 2)
        
        print(f"✅ gap_distance_em1_multiple: {gap_distance_dollar} ÷ {em1_dollar} = {gap_distance_em1:.2f}")
        
        return targets
    
    def _calculate_cluster_strength_ratio(self, targets: Dict) -> Dict:
        """计算 cluster_strength_ratio = next_cluster_abs_gex ÷ nearby_abs_gex"""
        gamma_metrics = targets.get('gamma_metrics', {})
        
        nearby_peak = gamma_metrics.get('nearby_peak', {})
        next_cluster_peak = gamma_metrics.get('next_cluster_peak', {})
        
        nearby_abs_gex = nearby_peak.get('abs_gex')
        next_cluster_abs_gex = next_cluster_peak.get('abs_gex')
        
        if not nearby_abs_gex or not next_cluster_abs_gex or nearby_abs_gex == 0:
            print("⚠️ cluster_strength_ratio 计算缺失输入或 nearby_abs_gex 为 0")
            if 'gamma_metrics' not in targets:
                targets['gamma_metrics'] = {}
            targets['gamma_metrics']['cluster_strength_ratio'] = -999
            return targets
        
        ratio = next_cluster_abs_gex / nearby_abs_gex
        
        if 'gamma_metrics' not in targets:
            targets['gamma_metrics'] = {}
        targets['gamma_metrics']['cluster_strength_ratio'] = round(ratio, 2)
        
        print(f"✅ cluster_strength_ratio: {next_cluster_abs_gex:.1f} / {nearby_abs_gex:.1f} = {ratio:.2f}")
        
        return targets
    
    def _calculate_monthly_cluster_override(self, targets: Dict) -> Dict:
        """计算 monthly_cluster_override"""
        gamma_metrics = targets.get('gamma_metrics', {})
        weekly_data = gamma_metrics.get('weekly_data', {})
        monthly_data = gamma_metrics.get('monthly_data', {})
        
        weekly_cluster_strength = weekly_data.get('cluster_strength', {})
        monthly_cluster_strength = monthly_data.get('cluster_strength', {})
        
        w_cluster_strength_gex = weekly_cluster_strength.get('abs_gex')
        m_cluster_strength_gex = monthly_cluster_strength.get('abs_gex')
        
        if not w_cluster_strength_gex or not m_cluster_strength_gex:
            print("⚠️ monthly_cluster_override 计算缺失输入")
            if 'gamma_metrics' not in targets:
                targets['gamma_metrics'] = {}
            targets['gamma_metrics']['monthly_cluster_override'] = False
            return targets
        
        # 从配置对象读取
        ratio_threshold = self.gamma_config.monthly_cluster_strength_ratio
        override = (m_cluster_strength_gex / w_cluster_strength_gex >= ratio_threshold)
        
        targets['gamma_metrics']['monthly_cluster_override'] = override
        
        print(f"✅ monthly_cluster_override: {m_cluster_strength_gex:.1f} / {w_cluster_strength_gex:.1f} >= {ratio_threshold:.2f} → {override}")
        
        return targets
    
    def _calculate_indices_em1(self, data: Dict) -> Dict:
        """计算所有指数的 EM1$"""
        indices = data.get('indices', {})
        
        if not isinstance(indices, dict):
            print("⚠️ indices 不是字典类型，跳过指数 EM1$ 计算")
            return data
        
        em1_sqrt_factor = self.gamma_config.em1_sqrt_factor
        
        for idx_symbol, idx_data in indices.items():
            if not isinstance(idx_data, dict):
                continue
            
            spot_price_idx = idx_data.get('spot_price_idx')
            iv_7d = idx_data.get('iv_7d')
            iv_14d = idx_data.get('iv_14d')
            
            if not all([spot_price_idx, iv_7d, iv_14d]):
                print(f"⚠️ 指数 {idx_symbol} 缺失计算参数")
                indices[idx_symbol]['em1_dollar_idx'] = -999
                continue
            
            min_iv = min(iv_7d, iv_14d)
            em1_idx = spot_price_idx * min_iv * em1_sqrt_factor
            
            indices[idx_symbol]['em1_dollar_idx'] = round(em1_idx, 2)
            
            print(f"✅ {idx_symbol} EM1$: {spot_price_idx} × {min_iv:.4f} × {em1_sqrt_factor} = {em1_idx:.2f}")
        
        data['indices'] = indices
        return data
    
    def _validate_calculations(self, targets: Dict) -> Dict:
        """验证计算结果的合理性"""
        validation_log = {
            "timestamp": datetime.now().isoformat(),
            "checks": []
        }
        
        # 检查 EM1$ 范围
        em1_dollar = targets.get('em1_dollar')
        spot_price = targets.get('spot_price')
        
        if em1_dollar and spot_price and spot_price != -999 and em1_dollar != -999:
            em1_pct = (em1_dollar / spot_price) * 100
            is_valid = 0.5 <= em1_pct <= 10
            validation_log["checks"].append({
                "field": "em1_dollar",
                "value": em1_dollar,
                "percentage_of_spot": round(em1_pct, 2),
                "is_valid": is_valid,
                "note": "合理范围：0.5%-10%" if is_valid else f"⚠️ 异常：{em1_pct:.2f}%"
            })
        
        # 检查 gap_distance_em1_multiple
        gamma_metrics = targets.get('gamma_metrics', {})
        gap_em1 = gamma_metrics.get('gap_distance_em1_multiple')
        if gap_em1 and gap_em1 != -999:
            is_valid = gap_em1 < 5
            validation_log["checks"].append({
                "field": "gap_distance_em1_multiple",
                "value": gap_em1,
                "is_valid": is_valid,
                "note": "合理范围：< 5" if is_valid else f"⚠️ 异常：{gap_em1:.2f}"
            })
        
        # 检查 cluster_strength_ratio
        cluster_ratio = gamma_metrics.get('cluster_strength_ratio')
        if cluster_ratio and cluster_ratio != -999:
            is_valid = 0.5 <= cluster_ratio <= 3.0
            validation_log["checks"].append({
                "field": "cluster_strength_ratio",
                "value": cluster_ratio,
                "is_valid": is_valid,
                "note": "合理范围：0.5-3.0" if is_valid else f"⚠️ 异常：{cluster_ratio:.2f}"
            })
        
        return validation_log
    
    @staticmethod
    def _is_valid_value(value: Any) -> bool:
        """判断值是否有效"""
        if value is None:
            return False
        if value == -999:
            return False
        if value in ["N/A", "数据不足", "", "unknown"]:
            return False
        return True


def main(aggregated_data: dict, symbol: str, **env_vars) -> dict:
    """
    计算节点入口函数（重构版）
    
    Args:
        aggregated_data: 聚合后的数据
        symbol: 股票代码
        **env_vars: 环境变量，包含：
            - market_params: 市场参数 (vix, ivr, iv30, hv20)
            - event_data: 事件检测数据（可选，用于动态敏感度计算）
    """
    try:
        print("🔍 [Calculator] 开始验证原始字段完整性")
        # 提取数据
        payload = aggregated_data.get('result')
        
        if isinstance(payload, str):
            # 情况 1: Aggregator 返回的 JSON 字符串 (Full Mode)
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                # 兜底：如果解析失败，假设输入本身就是数据
                data = aggregated_data
        elif isinstance(payload, dict):
            # 情况 2: Refresh Mode 直接传入的字典 (修复点)
            data = payload
        else:
            # 情况 3: 兜底 (输入不含 result 包装)
            data = aggregated_data
        
        # 提取市场参数
        market_params = env_vars.get('market_params', {})
        
        # 提取事件数据（用于动态敏感度系数计算）
        event_data = env_vars.get('event_data', {})
        
        # 传入 config 实例和事件数据
        calculator = FieldCalculator(
            config, 
            market_params=market_params,
            event_data=event_data
        )
        
        # 验证原始字段
        validation = calculator.validate_raw_fields(data)
        
        print(f"\n📊 验证结果:")
        print(f"  • 完成率: {validation['completion_rate']}%")
        print(f"  • 提供字段: {validation['provided']}/{validation['total_required']}")
        print(f"  • 缺失字段: {len(validation['missing_fields'])}")
        
        if not validation["is_complete"]:
            print(f"❌ 数据不完整，缺失 {len(validation['missing_fields'])} 个字段")
            
            result = {
                "status": "incomplete",
                "data_status": "awaiting_data",
                "validation": validation,
                "targets": data.get("targets"),
                "symbol": symbol  # 修复：添加 symbol 字段
            }
            return result
        
        print(f"✅ 原始字段验证通过: {validation['provided']}/{validation['total_required']}")
        
        # 计算衍生字段
        print("\n🔧 开始计算衍生字段...")
        calculated_data = calculator.calculate_all(data)
        
        print("✅ 所有计算完成")
        print(">>" * 80)
        
        result = {
            "status": "complete",
            "data_status": "ready",
            "validation": validation,
            "symbol": symbol,  # 修复：添加 symbol 字段
            **calculated_data
        }
        return result
    
    except Exception as e:
        import traceback
        print(f"\n❌ Calculator 执行异常:")
        print(traceback.format_exc())
        return {
            "symbol": symbol,  # 修复：添加 symbol 字段
            "result": json.dumps({
                "error": True,
                "error_message": str(e),
                "error_traceback": traceback.format_exc()
            }, ensure_ascii=False, indent=2)
        }