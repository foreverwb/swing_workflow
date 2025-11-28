"""
Agent3 处理器 - 新增调试与数据规范化模块
负责：
1. Agent3 请求/响应的详细日志记录
2. 数据结构规范化（修复常见格式问题）
3. 对比原始响应与规范化后数据
"""

import json
from typing import Dict, Any
from loguru import logger


class Agent3Handler:
    """Agent3 增强处理器"""
    
    def __init__(self):
        self.debug_mode = True  # 调试模式开关
    
    def log_request(self, symbol: str, inputs: list, image_count: int):
        """
        记录 Agent3 请求详情
        
        Args:
            symbol: 股票代码
            inputs: 输入消息列表
            image_count: 图片数量
        """
        if not self.debug_mode:
            return
        
        logger.info("="*80)
        logger.info(f"📤 Agent3 请求详情")
        logger.info("="*80)
        logger.info(f"🎯 标的: {symbol}")
        logger.info(f"📸 图片数量: {image_count}")
        logger.info(f"📋 消息数量: {len(inputs)}")
    
    def log_response(self, symbol: str, response: Dict, parsed_data: Dict):
        """
        记录 Agent3 响应详情
        
        Args:
            symbol: 股票代码
            response: 原始响应
            parsed_data: 解析后的数据
        """
        if not self.debug_mode:
            return
        
        logger.info("="*80)
        logger.info(f"📥 Agent3 响应详情")
        logger.info("="*80)
        logger.info(f"🎯 标的: {symbol}")
        logger.info(f"🤖 模型: {response.get('model', 'Unknown')}")
        
        usage = response.get("usage", {})
        logger.info(f"📊 Token 使用:")
        logger.info(f"  • 输入: {usage.get('input_tokens', 0)}")
        logger.info(f"  • 输出: {usage.get('output_tokens', 0)}")
        
        # 打印数据结构摘要
        if "targets" in parsed_data:
            targets = parsed_data["targets"]
            logger.info(f"\n📋 数据结构:")
            logger.info(f"  • targets 类型: {type(targets).__name__}")
            
            if isinstance(targets, dict):
                logger.info(f"  • symbol: {targets.get('symbol', 'N/A')}")
                logger.info(f"  • status: {targets.get('status', 'N/A')}")
                logger.info(f"  • spot_price: {targets.get('spot_price', 'N/A')}")
                
                # 检查嵌套字段
                if "gamma_metrics" in targets:
                    logger.info(f"  • gamma_metrics: ✅ 存在")
                if "walls" in targets:
                    logger.info(f"  • walls: ✅ 存在")
                if "atm_iv" in targets:
                    logger.info(f"  • atm_iv: ✅ 存在")
            else:
                logger.warning(f"  ⚠️ targets 不是字典类型")
        
        logger.info("="*80 + "\n")
    
    def normalize_structure(self, data: Dict) -> Dict:
        """
        规范化数据结构（修复常见问题）
        
        常见问题：
        1. targets 是空列表 [] 而非字典
        2. 字段平铺在根节点而非嵌套
        3. 字段名大小写不一致
        
        Args:
            data: 原始数据
            
        Returns:
            规范化后的数据
        """
        normalized = data.copy()
        
        # 问题1: targets 为空列表
        if isinstance(normalized.get("targets"), list):
            if not normalized["targets"]:
                logger.warning("⚠️ targets 是空列表，转换为字典")
                normalized["targets"] = {
                    "symbol": "UNKNOWN",
                    "status": "missing_data",
                    "spot_price": -999,
                    "em1_dollar": -999,
                    "walls": {},
                    "gamma_metrics": {},
                    "directional_metrics": {},
                    "atm_iv": {}
                }
            else:
                logger.warning("⚠️ targets 是非空列表，提取第一个元素")
                normalized["targets"] = normalized["targets"][0]
        
        # 问题2: targets 缺失，但有其他字段
        if "targets" not in normalized:
            logger.warning("⚠️ targets 字段缺失，尝试从根节点重建")
            normalized["targets"] = self._rebuild_targets_from_root(normalized)
        
        # 问题3: 检查必需的嵌套字段
        targets = normalized.get("targets", {})
        if isinstance(targets, dict):
            if "gamma_metrics" not in targets:
                logger.warning("⚠️ gamma_metrics 缺失，初始化空字典")
                targets["gamma_metrics"] = {}
            if "walls" not in targets:
                logger.warning("⚠️ walls 缺失，初始化空字典")
                targets["walls"] = {}
            if "atm_iv" not in targets:
                logger.warning("⚠️ atm_iv 缺失，初始化空字典")
                targets["atm_iv"] = {}
            if "directional_metrics" not in targets:
                logger.warning("⚠️ directional_metrics 缺失，初始化空字典")
                targets["directional_metrics"] = {}
        
        return normalized
    
    def _rebuild_targets_from_root(self, data: Dict) -> Dict:
        """从根节点重建 targets 字典"""
        targets = {
            "symbol": data.get("symbol", "UNKNOWN"),
            "status": data.get("status", "missing_data"),
            "spot_price": data.get("spot_price", -999),
            "em1_dollar": -999,  # ⭐ 计算字段设为 -999
            "walls": {},
            "gamma_metrics": {},
            "directional_metrics": {},
            "atm_iv": {}
        }
        
        # 尝试从根节点提取墙位
        if "call_wall" in data:
            targets["walls"]["call_wall"] = data["call_wall"]
        if "put_wall" in data:
            targets["walls"]["put_wall"] = data["put_wall"]
        
        # 尝试提取 gamma 指标
        if "vol_trigger" in data:
            targets["gamma_metrics"]["vol_trigger"] = data["vol_trigger"]
        if "net_gex" in data:
            targets["gamma_metrics"]["net_gex"] = data["net_gex"]
        
        return targets
    
    def print_detailed_comparison(self, original: Dict, normalized: Dict):
        """
        打印原始数据与规范化后数据的对比
        
        Args:
            original: 原始数据
            normalized: 规范化后的数据
        """
        if not self.debug_mode:
            return
        
        logger.info("="*80)
        logger.info("🔍 数据对比分析")
        logger.info("="*80)
        
        # 对比 targets 结构
        orig_targets = original.get("targets")
        norm_targets = normalized.get("targets")
        
        logger.info(f"\n📊 targets 字段对比:")
        logger.info(f"  • 原始类型: {type(orig_targets).__name__}")
        logger.info(f"  • 规范类型: {type(norm_targets).__name__}")
        
        if isinstance(orig_targets, list):
            logger.warning(f"  ⚠️ 原始数据 targets 是列表（长度: {len(orig_targets)}）")
        
        if isinstance(norm_targets, dict):
            logger.success(f"  ✅ 规范化后 targets 是字典（字段数: {len(norm_targets)}）")
            
            # 检查嵌套字段完整性
            nested_fields = ["gamma_metrics", "walls", "directional_metrics", "atm_iv"]
            for field in nested_fields:
                orig_has = field in orig_targets if isinstance(orig_targets, dict) else False
                norm_has = field in norm_targets
                
                if not orig_has and norm_has:
                    logger.info(f"  🔧 {field}: 已补全")
                elif orig_has and norm_has:
                    logger.success(f"  ✅ {field}: 保持不变")
                else:
                    logger.warning(f"  ⚠️ {field}: 仍缺失")
        
        # 对比字段数量
        orig_field_count = self._count_fields(original)
        norm_field_count = self._count_fields(normalized)
        
        logger.info(f"\n📈 字段统计:")
        logger.info(f"  • 原始字段数: {orig_field_count}")
        logger.info(f"  • 规范字段数: {norm_field_count}")
        logger.info(f"  • 变化: {norm_field_count - orig_field_count:+d}")
        
        logger.info("="*80 + "\n")
    
    def _count_fields(self, data: Dict, prefix: str = "") -> int:
        """递归统计字段数量"""
        count = 0
        for key, value in data.items():
            count += 1
            if isinstance(value, dict):
                count += self._count_fields(value, f"{prefix}{key}.")
        return count