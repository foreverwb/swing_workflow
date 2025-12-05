"""
FieldCalculator - 字段关联计算引擎（重构版）
特性：
1. 配置对象化访问（无需硬编码键名）
2. 实现 Lambda 扩展系数计算
3. 删除冗余的 _parse_env_vars 方法
"""

import json
from typing import Dict, Any
from datetime import datetime
from utils.config_loader import config

class FieldCalculator:
    """字段关联计算器（重构版）"""
    
    def __init__(self, config_loader, market_params: Dict[str, float] = None):
        """
        初始化计算器
        
        Args:
            config_loader: ConfigLoader 实例
            market_params: 市场参数 (vix, ivr, iv30, hv20)
        """
        # ⭐ 一次性获取所有 gamma 配置
        self.gamma_config = config_loader.get_section('gamma')
        self.market_params = market_params or {}
    
    def validate_raw_fields(self, data: Dict) -> Dict:
        """验证原始字段完整性（23个）"""
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
        
        total_required = 23
        provided = total_required - len(missing_fields)
        
        return {
            "is_complete": len(missing_fields) == 0,
            "missing_fields": missing_fields,
            "total_required": total_required,
            "provided": provided,
            "completion_rate": int((provided / total_required) * 100)
        }
    
    def calculate_all(self, data: Dict) -> Dict:
        """计算所有衍生字段（3个 + 指数）"""
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
        
        # 验证计算结果
        validation = self._validate_calculations(targets)
        targets['_calculation_log'] = validation
        
        data['targets'] = targets
        return data
    
    def _calculate_em1_dollar(self, targets: Dict) -> Dict:
        """
        计算 EM1$ = Raw_EM1$ × Lambda
        
        公式：
        1. Raw_EM1$ = spot_price × min(iv_7d, iv_14d) × sqrt(1/252)
        2. Lambda = 1.0 + k_sys × max(0, (VIX - VIX_base)/100) 
                        + k_idiosync × max(0, (IVR_floor - IVR)/100)
        3. Adjusted_EM1$ = Raw_EM1$ × Lambda
        """
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
        # ⭐ 从配置对象读取
        em1_sqrt_factor = self.gamma_config.em1_sqrt_factor
        raw_em1 = spot_price * min_iv * em1_sqrt_factor
        
        
        # Step 2: 计算 Lambda 扩展系数
        vix_curr = self.market_params.get('vix', 15.0)
        ivr_curr = self.market_params.get('ivr', 50.0)
        
        # ⭐ 从配置对象读取 Lambda 参数
        k_sys = self.gamma_config.lambda_k_sys
        k_idiosync = self.gamma_config.lambda_k_idiosync
        vix_base = self.gamma_config.lambda_vix_base
        ivr_floor = self.gamma_config.lambda_ivr_floor
        
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
        
        
        # 日志输出（详细分解）
        
        print(f"✅ EM1$ 计算完成:")
        print(f"   [物理锚点] Raw_EM1$ = {spot_price} × {min_iv:.4f} × {em1_sqrt_factor} = ${raw_em1:.2f}")
        print(f"   [Lambda 系数]")
        print(f"      • VIX 溢价: {k_sys} × max(0, ({vix_curr} - {vix_base})/100) = {vix_premium:.3f}")
        print(f"      • IVR 补偿: {k_idiosync} × max(0, ({ivr_floor} - {ivr_curr})/100) = {ivr_premium:.3f}")
        print(f"      • Lambda = 1.0 + {vix_premium:.3f} + {ivr_premium:.3f} = {lambda_factor:.3f}")
        print(f"   [最终结果] Adjusted_EM1$ = {raw_em1:.2f} × {lambda_factor:.3f} = ${adjusted_em1:.2f}")
        
        return targets
    
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
        
        # ⭐ 从配置对象读取
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
    """计算节点入口函数（重构版）"""
    try:
        print("🔍 [Calculator] 开始验证原始字段完整性")
        # 提取数据
        result_str = aggregated_data.get('result')
        if isinstance(result_str, str):
            data = json.loads(result_str)
        else:
            data = aggregated_data
        
        # 提取市场参数
        market_params = env_vars.get('market_params', {})
        
        # ⭐ 传入 config 实例
        calculator = FieldCalculator(config, market_params=market_params)
        
        # 验证原始字段
        validation = calculator.validate_raw_fields(data.get('result'))
        
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
                "targets": data.get("targets")
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
            **calculated_data
        }
        return result
    
    except Exception as e:
        import traceback
        print(f"\n❌ Calculator 执行异常:")
        print(traceback.format_exc())
        return {
            "result": json.dumps({
                "error": True,
                "error_message": str(e),
                "error_traceback": traceback.format_exc()
            }, ensure_ascii=False, indent=2)
        }