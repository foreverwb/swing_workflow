"""
FieldCalculator - 字段关联计算引擎 (Phase 3 Final)
特性：
1. [Schema] 兼容嵌套的 micro_structure.raw_metrics 读取
2. [Check] 增强 validate_raw_fields 的鲁棒性
3. [Logic] 包含动态敏感度系数 (Beta/Earnings) 和 Lambda 计算
"""

import json
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from utils.config_loader import config
from loguru import logger
import traceback

class FieldCalculator:
    """字段关联计算器（重构版）"""
    
    def __init__(
        self, 
        config_loader, 
        market_params: Dict[str, float] = None,
        event_data: Dict[str, Any] = None
    ):
        self.gamma_config = config_loader.get_section('gamma')
        self.beta_config = config_loader.get_section('beta')
        self.market_params = market_params or {}
        self.event_data = event_data or {}
    
    def _perform_sanity_check(self, targets: Dict) -> Tuple[bool, list]:
        errors = []
        spot = targets.get('spot_price')
        
        if not isinstance(spot, (int, float)) or spot <= 0:
            errors.append(f"现价异常: {spot}")
            return False, errors
            
        walls = targets.get('walls', {})
        for name, price in walls.items():
            if isinstance(price, (int, float)) and price > 0:
                diff_pct = abs(price - spot) / spot
                if diff_pct > 0.5:
                    errors.append(f"{name} {price} 偏离现价 {spot} 超过 50% ({diff_pct:.1%})")
        
        atm_iv = targets.get('atm_iv', {})
        for name, iv in atm_iv.items():
            if isinstance(iv, (int, float)):
                iv_val = iv / 100.0 if iv > 5 else iv 
                if iv_val > 5.0:
                    errors.append(f"{name} {iv} 异常过高")
                if iv_val < 0.05 and iv_val > 0:
                    errors.append(f"{name} {iv} 异常过低")
                    
        return len(errors) == 0, errors
    
    def get_beta(self, symbol: str) -> float:
        symbol_upper = symbol.upper()
        user_beta = self.market_params.get('beta')
        if user_beta is not None: return user_beta
        
        stock_overrides = self.beta_config.get('stock_overrides', {})
        if symbol_upper in stock_overrides: return stock_overrides[symbol_upper]
        
        symbol_to_sector = self.beta_config.get('symbol_to_sector', {})
        sector_defaults = self.beta_config.get('sector_defaults', {})
        
        if symbol_upper in symbol_to_sector:
            sector = symbol_to_sector[symbol_upper]
            if sector in sector_defaults: return sector_defaults[sector]
        
        return self.beta_config.get('default_beta', 1.0)
    
    def calculate_t_scale(self) -> Tuple[float, Dict]:
        hv20 = self.market_params.get('hv20') or 30.0
        iv30 = self.market_params.get('iv30') or 30.0
        
        if iv30 <= 0: iv30 = 30.0
        if hv20 <= 0: hv20 = 30.0
        
        t_scale = (hv20 / iv30) ** 0.8
        t_scale_raw = t_scale
        t_scale = max(0.5, min(2.0, t_scale))
        
        vrp = iv30 / hv20 if hv20 > 0 else 1.0
        
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
        earning_date_str = self.market_params.get('earning_date')
        if earning_date_str:
            try:
                earning_date = datetime.strptime(earning_date_str, "%Y-%m-%d")
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                return (earning_date - today).days
            except ValueError: pass
        
        events = self.event_data.get('events', {})
        earnings = events.get('earnings', {})
        if earnings and earnings.get('days_away') is not None:
            return earnings['days_away']
        return None
    
    def get_sensitivity_coeffs(self, symbol: str) -> Tuple[float, float]:
        beta = self.get_beta(symbol)
        days_to_earnings = self.get_days_to_earnings()
        
        sensitivity = self.beta_config.get('sensitivity', {})
        # 读取阈值配置
        high_beta_threshold = sensitivity.get('high_beta_threshold', 1.3)
        low_beta_threshold = sensitivity.get('low_beta_threshold', 0.7)
        k_sys_high = sensitivity.get('k_sys_high', 0.8)
        k_sys_standard = sensitivity.get('k_sys_standard', 0.5)
        k_sys_low = sensitivity.get('k_sys_low', 0.3)
        earnings_warning_days = sensitivity.get('earnings_warning_days', 14)
        k_idiosync_high = sensitivity.get('k_idiosync_high', 1.0)
        k_idiosync_normal = sensitivity.get('k_idiosync_normal', 0.5)
        
        if beta > high_beta_threshold: k_sys = k_sys_high
        elif beta < low_beta_threshold: k_sys = k_sys_low
        else: k_sys = k_sys_standard
        
        if days_to_earnings is not None and days_to_earnings <= earnings_warning_days:
            k_idiosync = k_idiosync_high
        else:
            k_idiosync = k_idiosync_normal
        
        return k_sys, k_idiosync
    
    def _extract_micro_metric(self, micro_structure: Dict, key: str) -> Optional[float]:
        """[新增] 智能提取微观指标，兼容嵌套结构"""
        # 1. 尝试从 raw_metrics 中提取 (系统生成格式)
        raw_metrics = micro_structure.get("raw_metrics")
        if isinstance(raw_metrics, dict):
            val = raw_metrics.get(key)
            if self._is_valid_value(val): return val
            
        # 2. 尝试从顶层提取 (手工/旧格式)
        val = micro_structure.get(key)
        if self._is_valid_value(val): return val
        
        return None

    def validate_raw_fields(self, data: Dict) -> Dict:
        targets = data.get('targets', {})
        if isinstance(targets, str):
            try: targets = json.loads(targets)
            except json.JSONDecodeError: targets = {}
        
        missing_fields = []
        is_sane, sanity_errors = self._perform_sanity_check(targets)
        
        # 1. Top Level
        if not self._is_valid_value(targets.get('symbol')):
            missing_fields.append({"field": "symbol", "path": "symbol"})
        if not self._is_valid_value(targets.get('spot_price')):
            missing_fields.append({"field": "spot_price", "path": "spot_price"})
        
        # 2. Walls
        walls = targets.get('walls', {})
        for field in ["call_wall", "put_wall", "major_wall"]:
            if not self._is_valid_value(walls.get(field)):
                missing_fields.append({"field": field, "path": f"walls.{field}"})
        
        # 3. Gamma Metrics
        gamma_metrics = targets.get('gamma_metrics', {})
        for field in ["vol_trigger", "spot_vs_trigger", "net_gex", "gap_distance_dollar"]:
            if not self._is_valid_value(gamma_metrics.get(field)):
                missing_fields.append({"field": field, "path": f"gamma_metrics.{field}"})

        # 3.1 Structural Peaks
        structural_peaks = gamma_metrics.get('structural_peaks', {})
        if not structural_peaks:
             missing_fields.append({"field": "structural_peaks", "path": "gamma_metrics.structural_peaks", "severity": "critical"})
        else:
            if not self._is_valid_value(structural_peaks.get("nearby_peak", {}).get("price")):
                missing_fields.append({"field": "nearby_peak_price", "path": "gamma_metrics.structural_peaks.nearby_peak.price"})

        # 3.2 Micro Structure (ECR) - [修复: 使用智能提取]
        micro_structure = gamma_metrics.get('micro_structure', {})
        ecr_val = self._extract_micro_metric(micro_structure, "ECR")
        
        if ecr_val is None:
             missing_fields.append({"field": "ECR", "path": "gamma_metrics.micro_structure.[raw_metrics].ECR", "severity": "critical"})
        
        # 4. Directional
        directional_metrics = targets.get('directional_metrics', {})
        for field in ["dex_bias", "dex_bias_strength", "vanna_dir", "vanna_confidence", "iv_path", "iv_path_confidence"]:
            if not self._is_valid_value(directional_metrics.get(field)):
                missing_fields.append({"field": field, "path": f"directional_metrics.{field}"})
        
        # 5. ATM IV
        atm_iv = targets.get('atm_iv', {})
        for field in ["iv_7d", "iv_14d", "iv_source"]:
            if not self._is_valid_value(atm_iv.get(field)):
                missing_fields.append({"field": field, "path": f"atm_iv.{field}"})
        
        # 6. Vol Surface (Skew)
        vol_surface = targets.get('vol_surface', {})
        if not self._is_valid_value(vol_surface.get("smile_steepness")):
             missing_fields.append({"field": "smile_steepness", "path": "vol_surface.smile_steepness"})
        
        # 7. Validation Metrics
        validation_metrics = targets.get('validation_metrics', {})
        for field in ["net_volume_signal", "net_vega_exposure"]:
            if validation_metrics and validation_metrics.get(field) is None:
                missing_fields.append({"field": field, "path": f"validation_metrics.{field}", "severity": "low"})
        
        if not is_sane:
            for err in sanity_errors:
                missing_fields.append({"field": "SANITY_CHECK", "path": "root", "reason": err, "severity": "critical"})
        
        total_required = 25
        provided = total_required - len(missing_fields)
        
        return {
            "is_complete": is_sane and len([f for f in missing_fields if f.get("severity") != "low"]) == 0,
            "missing_fields": missing_fields,
            "total_required": total_required,
            "provided": provided,
            "completion_rate": int((provided / total_required) * 100)
        }
    
    def calculate_all(self, data: Dict) -> Dict:
        targets = data.get('targets', {})
        if isinstance(targets, str):
            try: targets = json.loads(targets)
            except json.JSONDecodeError: targets = {}
        
        targets = self._calculate_em1_dollar(targets)
        targets = self._calculate_gap_distance_em1(targets)
        # [Fix] 启用 cluster_strength_ratio 计算
        targets = self._calculate_cluster_strength_ratio(targets) 
        targets = self._calculate_indices_em1(targets)
        targets = self._aggregate_volatility_metrics(targets)
        
        validation = self._validate_calculations(targets)
        targets['_calculation_log'] = validation
        
        data['targets'] = targets
        return data
    
    def _aggregate_volatility_metrics(self, targets: Dict) -> Dict:
        t_scale, t_scale_details = self.calculate_t_scale()
        lambda_details = targets.get('_lambda_details', {})
        lambda_factor = lambda_details.get('lambda_factor', 1.0)
        
        volatility_metrics = {
            'lambda_factor': lambda_factor,
            't_scale': t_scale,
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
            't_scale_details': t_scale_details,
            'market_snapshot': {
                'vix': self.market_params.get('vix'),
                'ivr': self.market_params.get('ivr'),
                'iv30': self.market_params.get('iv30'),
                'hv20': self.market_params.get('hv20')
            }
        }
        targets['volatility_metrics'] = volatility_metrics
        print(f"\n📊 波动率指标: Lambda={lambda_factor:.3f}, T_scale={t_scale:.3f}")
        return targets
    
    def _calculate_em1_dollar(self, targets: Dict) -> Dict:
        symbol = targets.get('symbol', 'UNKNOWN')
        spot_price = targets.get('spot_price')
        atm_iv = targets.get('atm_iv', {})
        iv_7d = atm_iv.get('iv_7d')
        iv_14d = atm_iv.get('iv_14d')
        
        if not all([spot_price, iv_7d, iv_14d]):
            targets['em1_dollar'] = -999
            return targets
        
        min_iv = min(iv_7d, iv_14d)
        em1_sqrt_factor = self.gamma_config.em1_sqrt_factor
        raw_em1 = spot_price * min_iv * em1_sqrt_factor
        
        vix_curr = self.market_params.get('vix') or 15.0
        ivr_curr = self.market_params.get('ivr') or 50.0
        k_sys, k_idiosync = self.get_sensitivity_coeffs(symbol)
        vix_base = self.gamma_config.lambda_vix_base
        ivr_floor = self.gamma_config.lambda_ivr_floor
        
        vix_premium = k_sys * max(0, (vix_curr - vix_base) / 100)
        ivr_premium = k_idiosync * max(0, (ivr_floor - ivr_curr) / 100)
        lambda_factor = 1.0 + vix_premium + ivr_premium
        adjusted_em1 = raw_em1 * lambda_factor
        
        targets['em1_dollar'] = round(adjusted_em1, 2)
        targets['_lambda_details'] = {
            'beta': self.get_beta(symbol),
            'beta_source': self._get_beta_source(symbol),
            'days_to_earnings': self.get_days_to_earnings(),
            'earning_source': self._get_earning_source(),
            'k_sys': k_sys, 'k_idiosync': k_idiosync,
            'vix_premium': round(vix_premium, 4), 'ivr_premium': round(ivr_premium, 4),
            'lambda_factor': round(lambda_factor, 4), 'raw_em1': round(raw_em1, 2)
        }
        return targets
    
    def _get_beta_source(self, symbol: str) -> str:
        if self.market_params.get('beta') is not None: return "用户指定"
        stock_overrides = self.beta_config.get('stock_overrides', {})
        if symbol.upper() in stock_overrides: return "股票预设"
        symbol_to_sector = self.beta_config.get('symbol_to_sector', {})
        if symbol.upper() in symbol_to_sector: return f"板块映射:{symbol_to_sector[symbol.upper()]}"
        return "默认值"
    
    def _get_earning_source(self) -> str:
        if self.market_params.get('earning_date'): return "用户指定"
        events = self.event_data.get('events', {})
        if events.get('earnings', {}).get('days_away') is not None: return "事件检测"
        return "无数据"
    
    def _calculate_gap_distance_em1(self, targets: Dict) -> Dict:
        gamma_metrics = targets.get('gamma_metrics', {})
        gap_distance_dollar = gamma_metrics.get('gap_distance_dollar')
        em1_dollar = targets.get('em1_dollar')
        
        if not gap_distance_dollar or not em1_dollar or em1_dollar == -999:
            if 'gamma_metrics' not in targets: targets['gamma_metrics'] = {}
            targets['gamma_metrics']['gap_distance_em1_multiple'] = -999
            return targets
        
        gap_distance_em1 = gap_distance_dollar / em1_dollar
        targets['gamma_metrics']['gap_distance_em1_multiple'] = round(gap_distance_em1, 2)
        return targets

    def _calculate_cluster_strength_ratio(self, targets: Dict) -> Dict:
        """
        计算 cluster_strength_ratio
        
        优先级：
        1. 使用已经存在的 cluster_strength_ratio (从 code_input_calc 写入的)
        2. 如果不存在，从 structural_peaks 计算
        """
        gamma_metrics = targets.get('gamma_metrics', {})
        
        # [Fix] 优先使用已经计算好的 cluster_strength_ratio
        existing_ratio = gamma_metrics.get('cluster_strength_ratio')
        if existing_ratio is not None and existing_ratio != -999 and self._is_valid_value(existing_ratio):
            # 已经有有效值，直接返回
            print(f"📊 使用已有 cluster_strength_ratio: {existing_ratio}")
            return targets
        
        # [Fix] 否则从 structural_peaks 计算
        peaks = gamma_metrics.get('structural_peaks', {})
        nearby_peak = peaks.get('nearby_peak', {})
        next_cluster_peak = peaks.get('secondary_peak') or peaks.get('next_cluster_peak', {})
        
        nearby_abs_gex = nearby_peak.get('abs_gex')
        next_cluster_abs_gex = next_cluster_peak.get('abs_gex')
        
        if not nearby_abs_gex or not next_cluster_abs_gex or nearby_abs_gex == 0:
            if 'gamma_metrics' not in targets: targets['gamma_metrics'] = {}
            targets['gamma_metrics']['cluster_strength_ratio'] = -999
            return targets
        
        ratio = next_cluster_abs_gex / nearby_abs_gex
        targets['gamma_metrics']['cluster_strength_ratio'] = round(ratio, 2)
        return targets
    
    def _calculate_indices_em1(self, data: Dict) -> Dict:
        indices = data.get('indices', {})
        if not isinstance(indices, dict): return data
        
        em1_sqrt_factor = self.gamma_config.em1_sqrt_factor
        for idx_symbol, idx_data in indices.items():
            if not isinstance(idx_data, dict): continue
            spot = idx_data.get('spot_price_idx')
            iv7 = idx_data.get('iv_7d')
            iv14 = idx_data.get('iv_14d')
            
            if not all([spot, iv7, iv14]):
                indices[idx_symbol]['em1_dollar_idx'] = -999
                continue
            
            min_iv = min(iv7, iv14)
            em1_idx = spot * min_iv * em1_sqrt_factor
            indices[idx_symbol]['em1_dollar_idx'] = round(em1_idx, 2)
        
        data['indices'] = indices
        return data
    
    def _validate_calculations(self, targets: Dict) -> Dict:
        validation_log = {"timestamp": datetime.now().isoformat(), "checks": []}
        em1_dollar = targets.get('em1_dollar')
        spot_price = targets.get('spot_price')
        if em1_dollar and spot_price and spot_price != -999:
            em1_pct = (em1_dollar / spot_price) * 100
            is_valid = 0.5 <= em1_pct <= 10
            validation_log["checks"].append({
                "field": "em1_dollar", "value": em1_dollar, "is_valid": is_valid,
                "note": "合理范围：0.5%-10%" if is_valid else f"⚠️ 异常：{em1_pct:.2f}%"
            })
        return validation_log
    
    @staticmethod
    def _is_valid_value(value: Any) -> bool:
        if value is None: return False
        if value == -999: return False
        if value in ["N/A", "数据不足", "", "unknown"]: return False
        return True

def main(aggregated_data: dict, symbol: str, **env_vars) -> dict:
    print("----------- calculator start ------------")
    try:
        logger.info("🔧 [FieldCalculator] 开始执行字段计算")
        print("🔍 [Calculator] 开始验证原始字段完整性")
        payload = aggregated_data.get('result')
        
        if isinstance(payload, str):
            try: data = json.loads(payload)
            except json.JSONDecodeError: data = aggregated_data
        elif isinstance(payload, dict):
            data = payload
        else:
            data = aggregated_data
        
        market_params = env_vars.get('market_params', {})
        event_data = env_vars.get('event_data', {})
        
        logger.info(f"   输入数据 keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        logger.info(f"   market_params: VIX={market_params.get('vix')}")
        
        calculator = FieldCalculator(config, market_params=market_params, event_data=event_data)
        validation = calculator.validate_raw_fields(data)
        
        logger.info(f"📊 验证结果: 完成率 {validation['completion_rate']}%")
        print(f"\n📊 验证结果: 完成率 {validation['completion_rate']}%")
        
        if validation['missing_fields']:
            critical = [f for f in validation['missing_fields'] if f.get('severity') == 'critical']
            if critical:
                logger.warning(f"🚨 严重缺失字段: {[item.get('path') for item in critical]}")
                print(f"\n🚨 严重缺失:")
                for item in critical: print(f"    • {item.get('path')} ({item.get('reason','')})")
        
        if not validation["is_complete"]:
            logger.warning(f"❌ [FieldCalculator] 数据不完整，无法计算")
            result = {"data_status": "awaiting_data", "validation": validation, "targets": data.get("targets"), "symbol": symbol}
            return result
        
        logger.info("🔧 开始计算衍生字段...")
        print("\n🔧 开始计算衍生字段...")
        calculated_data = calculator.calculate_all(data)
        
        logger.success(f"✅ [FieldCalculator] 计算完成, data_status=ready")
        result = {"data_status": "ready", "validation": validation, "symbol": symbol, **calculated_data}
        print("----------- calculator end ------------")

        return result
    
    except Exception as e:
        logger.error(f"❌ [FieldCalculator] 执行异常: {str(e)}")
        print(f"\n❌ Calculator 执行异常: {str(e)}")
        print(traceback.format_exc())
        return {"symbol": symbol, "result": json.dumps({"error": True, "error_message": str(e)}, ensure_ascii=False)}