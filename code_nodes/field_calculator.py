"""
FieldCalculator - 字段关联计算引擎
负责所有衍生字段的计算
"""

import math
from typing import Dict, Any


class FieldCalculator:
    """字段关联计算器"""
    
    def __init__(self, env_vars: Dict[str, Any]):
        """
        初始化计算器
        
        Args:
            env_vars: 环境变量字典
        """
        self.em1_sqrt_factor = env_vars.get('EM1_SQRT_FACTOR', 0.06299)  # sqrt(1/252)
    
    def calculate_all(self, data: Dict) -> Dict:
        """
        计算所有关联字段
        
        Args:
            data: 包含 targets 的完整数据
            
        Returns:
            计算完成的数据
        """
        targets = data.get('targets', {})
        
        # 1. 计算 em1_dollar（标的）
        targets = self._calculate_em1_dollar(targets)
        
        # 2. 计算 gap_distance_em1_multiple
        targets = self._calculate_gap_distance_em1(targets)
        
        # 3. 计算 em1_dollar_idx（指数）
        if 'indices' in data:
            data['indices'] = self._calculate_indices_em1(data['indices'])
        
        # 4. 验证计算结果
        validation = self._validate_calculations(targets)
        targets['_calculation_log'] = validation
        
        data['targets'] = targets
        return data
    
    def _calculate_em1_dollar(self, targets: Dict) -> Dict:
        """
        计算 EM1$ = spot_price × min(ATM_IV_7D, ATM_IV_14D) × sqrt(1/252)
        
        Args:
            targets: 标的数据
            
        Returns:
            更新后的标的数据
        """
        spot_price = self._get_nested(targets, 'spot_price')
        iv_7d = self._get_nested(targets, 'atm_iv.iv_7d')
        iv_14d = self._get_nested(targets, 'atm_iv.iv_14d')
        
        # 验证输入
        if not all([spot_price, iv_7d, iv_14d]):
            print(f"⚠️ EM1$ 计算缺失输入: spot={spot_price}, iv_7d={iv_7d}, iv_14d={iv_14d}")
            return targets
        
        if any(x == -999 for x in [spot_price, iv_7d, iv_14d]):
            print(f"⚠️ EM1$ 计算输入无效")
            return targets
        
        # 计算
        min_iv = min(iv_7d, iv_14d)
        em1_dollar = spot_price * min_iv * self.em1_sqrt_factor
        
        # 写入结果
        self._set_nested(targets, 'em1_dollar', round(em1_dollar, 2))
        
        print(f"✅ EM1$ 计算完成: {spot_price} × {min_iv:.4f} × {self.em1_sqrt_factor} = {em1_dollar:.2f}")
        
        return targets
    
    def _calculate_gap_distance_em1(self, targets: Dict) -> Dict:
        """
        计算 gap_distance_em1_multiple = gap_distance_dollar ÷ em1_dollar
        
        Args:
            targets: 标的数据
            
        Returns:
            更新后的标的数据
        """
        gap_distance_dollar = self._get_nested(targets, 'gamma_metrics.gap_distance_dollar')
        em1_dollar = self._get_nested(targets, 'em1_dollar')
        
        # 验证输入
        if not gap_distance_dollar or not em1_dollar:
            print(f"⚠️ gap_distance_em1_multiple 计算缺失输入")
            return targets
        
        if gap_distance_dollar == -999 or em1_dollar == -999:
            print(f"⚠️ gap_distance_em1_multiple 计算输入无效")
            return targets
        
        if em1_dollar == 0:
            print(f"❌ EM1$ 为 0，无法计算 gap_distance_em1_multiple")
            return targets
        
        # 计算
        gap_distance_em1 = gap_distance_dollar / em1_dollar
        
        # 写入结果
        self._set_nested(targets, 'gamma_metrics.gap_distance_em1_multiple', round(gap_distance_em1, 2))
        
        print(f"✅ gap_distance_em1_multiple 计算完成: {gap_distance_dollar} ÷ {em1_dollar} = {gap_distance_em1:.2f}")
        
        return targets
    
    def _calculate_indices_em1(self, indices: Dict) -> Dict:
        """
        计算指数的 EM1$
        
        Args:
            indices: 指数数据字典
            
        Returns:
            更新后的指数数据
        """
        for index_name in ['spx', 'qqq']:
            if index_name not in indices:
                continue
            
            index_data = indices[index_name]
            spot_idx = index_data.get('spot_idx', -999)
            
            # 对于指数，通常使用固定的 IV（如 VIX / VXN）
            # 这里简化处理：假设从 skew 命令提取的 ATM IV
            # 如果没有，跳过计算
            if spot_idx == -999:
                continue
            
            # 假设指数 IV 已经在 indices 中（需要 Agent3 提取）
            # 如果没有，可以使用默认值或跳过
            iv_idx = index_data.get('atm_iv_idx', 0.15)  # 默认 15% IV
            
            if iv_idx > 0:
                em1_dollar_idx = spot_idx * iv_idx * self.em1_sqrt_factor
                index_data['em1_dollar_idx'] = round(em1_dollar_idx, 2)
                print(f"✅ {index_name.upper()} EM1$ 计算完成: {spot_idx} × {iv_idx:.4f} × {self.em1_sqrt_factor} = {em1_dollar_idx:.2f}")
            
            indices[index_name] = index_data
        
        return indices
    
    def _validate_calculations(self, targets: Dict) -> Dict:
        """
        验证计算结果的合理性
        
        Args:
            targets: 标的数据
            
        Returns:
            验证日志
        """
        validation_log = {
            "timestamp": datetime.now().isoformat(),
            "checks": []
        }
        
        # 检查 1: EM1$ 是否在合理范围内（0.5% - 10% spot）
        em1_dollar = self._get_nested(targets, 'em1_dollar')
        spot_price = self._get_nested(targets, 'spot_price')
        
        if em1_dollar and spot_price and spot_price != -999:
            em1_pct = (em1_dollar / spot_price) * 100
            is_valid = 0.5 <= em1_pct <= 10
            validation_log["checks"].append({
                "field": "em1_dollar",
                "value": em1_dollar,
                "percentage_of_spot": round(em1_pct, 2),
                "is_valid": is_valid,
                "note": "合理范围：0.5%-10%" if is_valid else f"⚠️ 异常：{em1_pct:.2f}%"
            })
        
        # 检查 2: gap_distance_em1_multiple 是否合理（通常 < 5）
        gap_em1 = self._get_nested(targets, 'gamma_metrics.gap_distance_em1_multiple')
        if gap_em1 and gap_em1 != -999:
            is_valid = gap_em1 < 5
            validation_log["checks"].append({
                "field": "gap_distance_em1_multiple",
                "value": gap_em1,
                "is_valid": is_valid,
                "note": "合理范围：< 5" if is_valid else f"⚠️ 异常：{gap_em1:.2f}"
            })
        
        return validation_log
    
    @staticmethod
    def _get_nested(data: Dict, path: str) -> Any:
        """获取嵌套字段值（支持点号路径）"""
        keys = path.split('.')
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value if value != -999 else None
    
    @staticmethod
    def _set_nested(data: Dict, path: str, value: Any):
        """设置嵌套字段值（支持点号路径）"""
        keys = path.split('.')
        current = data
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value


from datetime import datetime


def main(aggregated_data: dict, **env_vars) -> dict:
    """
    计算节点入口函数
    
    Args:
        aggregated_data: Aggregator 输出的数据
        **env_vars: 环境变量
        
    Returns:
        {"result": 计算完成的 JSON 字符串}
    """
    try:
        import json
        
        # 解析输入
        if isinstance(aggregated_data, str):
            data = json.loads(aggregated_data)
        else:
            data = aggregated_data
        
        # 创建计算器
        calculator = FieldCalculator(env_vars)
        
        # 执行计算
        calculated_data = calculator.calculate_all(data)
        
        return {
            "result": json.dumps(calculated_data, ensure_ascii=False, indent=2)
        }
    
    except Exception as e:
        import traceback
        return {
            "result": json.dumps({
                "error": True,
                "error_message": str(e),
                "error_traceback": traceback.format_exc()
            }, ensure_ascii=False, indent=2)
        }