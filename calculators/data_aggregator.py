"""
数据聚合节点 - CODE_AGGREGATOR
支持多次上传图表的增量合并和状态管理
"""

import json
from typing import Dict, List, Tuple, Any
from datetime import datetime
from utils.logger import setup_logger

logger = setup_logger(__name__)


class DataAggregator:
    """
    数据聚合器 - 支持增量补齐
    
    核心功能:
    1. 智能增量合并: 多次上传自动累积数据
    2. 字段级追踪: 记录每个字段的来源和质量
    3. 防止覆盖: 有效数据不会被无效数据覆盖
    4. 自动完成: 达到 22/22 自动进入分析流程
    """
    
    def __init__(self):
        # 会话状态缓存 (模拟 Dify 会话变量)
        self.session_state = {
            "first_parse_data": "",      # 首次解析数据
            "current_symbol": "",         # 当前股票代码
            "data_status": "initial",     # 数据状态
            "missing_count": 0            # 缺失字段数
        }
    
    def aggregate(self, 
                  current_data: Dict,
                  cached_first_data: str = "",
                  cached_symbol: str = "",
                  cached_status: str = "initial") -> Tuple[Dict, Dict]:
        """
        主聚合函数
        
        Args:
            current_data: Agent 3 当前解析结果
            cached_first_data: 缓存的首次数据 (JSON 字符串)
            cached_symbol: 缓存的股票代码
            cached_status: 缓存的数据状态
        
        Returns:
            (merged_data, session_updates)
            - merged_data: 聚合后的完整数据
            - session_updates: 需要更新的会话变量
        """
        logger.info("开始数据聚合")
        
        # 提取当前数据
        symbol = self._extract_symbol(current_data)
        current_status = current_data.get("status", "missing_data")
        
        # === 核心逻辑 1: 判断是否累积模式 ===
        is_accumulation, judgment = self._judge_accumulation_mode(
            current_data=current_data,
            cached_first_data=cached_first_data,
            cached_symbol=cached_symbol,
            cached_status=cached_status
        )
        
        logger.info(f"累积模式: {is_accumulation}, 原因: {judgment}")
        
        # === 核心逻辑 2: 增量合并 ===
        if is_accumulation:
            if not cached_first_data:
                # 第一次上传
                merged_data = current_data
                merge_history = [{
                    "round": 1,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "fields_added": self._count_valid_fields(current_data),
                    "action": "首次解析"
                }]
                last_merge_failed = False
            else:
                # 第 N 次上传 - 执行增量合并
                first_data = json.loads(cached_first_data)
                merged_data, merge_info = self._smart_merge(first_data, current_data)
                
                # 更新合并历史
                history = first_data.get("_merge_history", [])
                history.append({
                    "round": len(history) + 1,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "fields_added": merge_info["new_fields_count"],
                    "fields_updated": merge_info.get("updated_fields_count", 0),
                    "action": "增量补齐" if not merge_info.get("merge_failed") else "合并失败",
                    "failure_reason": merge_info.get("failure_reason", "")
                })
                merged_data["_merge_history"] = history
                merge_history = history
                last_merge_failed = merge_info.get("merge_failed", False)
        else:
            # 新任务 (Symbol 变化)
            merged_data = current_data
            merge_history = [{
                "round": 1,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fields_added": self._count_valid_fields(current_data),
                "action": "新任务开始"
            }]
            last_merge_failed = False
        
        # === 核心逻辑 3: 三级验证 (基于合并后的数据) ===
        validation_result = self._enhanced_validation(merged_data)
        
        # 更新状态
        if validation_result["is_complete"]:
            final_status = "ready"
            merged_data["status"] = "data_ready"
        else:
            final_status = "awaiting_data"
            merged_data["status"] = "missing_data"
        
        # 生成补齐指引
        missing_fields = validation_result["missing_fields"]
        guide = self._generate_guide(
            missing_fields=missing_fields,
            merge_history=merge_history,
            total_fields=22,
            last_merge_failed=last_merge_failed
        )
        
        # === 核心逻辑 4: 返回结构化的输出 ===
        result_data = {
            **merged_data,
            "validation_summary": validation_result["summary"],
            "判断依据": judgment,
            "_merge_history": merge_history
        }
        
        # 会话变量更新
        session_updates = {
            "first_parse_data": json.dumps(merged_data) if final_status == "awaiting_data" else "",
            "current_symbol": symbol,
            "data_status": final_status,
            "missing_count": len(missing_fields),
            "user_guide": guide
        }
        
        logger.info(f"聚合完成,状态: {final_status}, 缺失: {len(missing_fields)}")
        
        return result_data, session_updates
    
    def _judge_accumulation_mode(self, 
                                  current_data: Dict,
                                  cached_first_data: str,
                                  cached_symbol: str,
                                  cached_status: str) -> Tuple[bool, str]:
        """
        判断是否进入累积模式 (增量补齐)
        
        Returns:
            (is_accumulation, reason)
        """
        # 情况 1: 无缓存 → 首次解析
        if not cached_first_data or cached_status == "initial":
            return True, "首次上传,开始解析"
        
        # 情况 2: Symbol 变化 → 新任务
        current_symbol = self._extract_symbol(current_data)
        if current_symbol != cached_symbol:
            return False, f"Symbol 变化({cached_symbol}→{current_symbol}),开始新任务"
        
        # 情况 3: 缓存状态为 ready → 已完成,不再累积
        if cached_status == "ready":
            return False, "数据已完整,开始新任务"
        
        # 情况 4: 缓存等待补齐 → 累积模式
        if cached_status == "awaiting_data":
            return True, "检测到历史缓存,进入增量补齐模式"
        
        # 默认: 累积模式
        return True, "进入累积模式"
    
    def _smart_merge(self, first_data: Dict, new_data: Dict) -> Tuple[Dict, Dict]:
        """
        智能增量合并
        
        核心特性:
        1. 检测新数据是否为空
        2. 如果新数据为空,直接返回旧数据 (不合并)
        3. 记录合并失败的原因
        """
        merged = first_data.copy()
        
        # 提取 targets
        first_targets = self._get_target_dict(first_data)
        new_targets = self._get_target_dict(new_data)
        
        # 核心修复: 检测新数据是否为空
        new_valid_count = self._count_valid_fields_in_dict(new_targets)
        
        if new_valid_count == 0:
            # 新数据为空,不执行合并
            logger.warning("新数据无有效字段,跳过合并")
            merge_info = {
                "new_fields_count": 0,
                "updated_fields_count": 0,
                "merge_failed": True,
                "failure_reason": "新数据无有效字段(可能解析失败)"
            }
            return merged, merge_info
        
        # 统计信息
        new_fields_count = 0
        updated_fields_count = 0
        
        # 合并各个 section
        for section in ["gamma_metrics", "directional_metrics", "atm_iv", "walls"]:
            if section not in first_targets:
                first_targets[section] = {}
            
            if section in new_targets:
                for key, new_value in new_targets[section].items():
                    old_value = first_targets[section].get(key)
                    
                    if self._is_valid_value(new_value):
                        if not self._is_valid_value(old_value):
                            first_targets[section][key] = new_value
                            new_fields_count += 1
                        elif old_value != new_value:
                            first_targets[section][key] = new_value
                            updated_fields_count += 1
        
        # 合并顶层字段
        for key in ["spot_price", "em1_dollar", "symbol"]:
            old_value = first_targets.get(key)
            new_value = new_targets.get(key)
            
            if self._is_valid_value(new_value):
                if not self._is_valid_value(old_value):
                    first_targets[key] = new_value
                    new_fields_count += 1
                elif old_value != new_value:
                    first_targets[key] = new_value
                    updated_fields_count += 1
        
        # 修复: 如果没有任何新增或更新,标记为失败
        if new_fields_count == 0 and updated_fields_count == 0:
            logger.warning("合并未产生任何变化,可能数据重复或解析失败")
            merge_info = {
                "new_fields_count": 0,
                "updated_fields_count": 0,
                "merge_failed": True,
                "failure_reason": "无新增或更新字段"
            }
            return merged, merge_info
        
        # 合并 indices
        if "indices" not in merged:
            merged["indices"] = {}
        
        if "indices" in new_data:
            for index_name in ["spx", "qqq"]:
                if index_name in new_data["indices"]:
                    if index_name not in merged["indices"]:
                        merged["indices"][index_name] = {}
                    
                    for key, new_value in new_data["indices"][index_name].items():
                        old_value = merged["indices"][index_name].get(key)
                        if self._is_valid_value(new_value) and not self._is_valid_value(old_value):
                            merged["indices"][index_name][key] = new_value
        
        # 合并技术面数据
        if "technical_analysis" in new_data:
            ta = new_data["technical_analysis"]
            if ta and ta.get("ta_score", 0) > 0:
                merged["technical_analysis"] = ta
        
        # 更新 targets
        merged["targets"] = first_targets
        
        merge_info = {
            "new_fields_count": new_fields_count,
            "updated_fields_count": updated_fields_count,
            "merge_failed": False
        }
        
        return merged, merge_info
    
    def _enhanced_validation(self, data: Dict) -> Dict:
        """
        三级验证增强版 (基于合并后的数据)
        
        Returns:
            {
                "is_complete": bool,
                "missing_fields": list,
                "summary": dict
            }
        """
        target = self._get_target_dict(data)
        
        # 22 个必需字段
        required_fields = {
            # 顶层字段
            "spot_price": (target, "spot_price"),
            "em1_dollar": (target, "em1_dollar"),
            
            # walls
            "walls.call_wall": (target.get("walls", {}), "call_wall"),
            "walls.put_wall": (target.get("walls", {}), "put_wall"),
            "walls.major_wall": (target.get("walls", {}), "major_wall"),
            "walls.major_wall_type": (target.get("walls", {}), "major_wall_type"),
            
            # gamma_metrics
            "gamma_metrics.gap_distance_dollar": (target.get("gamma_metrics", {}), "gap_distance_dollar"),
            "gamma_metrics.gap_distance_em1_multiple": (target.get("gamma_metrics", {}), "gap_distance_em1_multiple"),
            "gamma_metrics.cluster_strength_ratio": (target.get("gamma_metrics", {}), "cluster_strength_ratio"),
            "gamma_metrics.net_gex": (target.get("gamma_metrics", {}), "net_gex"),
            "gamma_metrics.net_gex_sign": (target.get("gamma_metrics", {}), "net_gex_sign"),
            "gamma_metrics.vol_trigger": (target.get("gamma_metrics", {}), "vol_trigger"),
            "gamma_metrics.spot_vs_trigger": (target.get("gamma_metrics", {}), "spot_vs_trigger"),
            "gamma_metrics.monthly_cluster_override": (target.get("gamma_metrics", {}), "monthly_cluster_override"),
            
            # directional_metrics
            "directional_metrics.dex_same_dir_pct": (target.get("directional_metrics", {}), "dex_same_dir_pct"),
            "directional_metrics.vanna_dir": (target.get("directional_metrics", {}), "vanna_dir"),
            "directional_metrics.vanna_confidence": (target.get("directional_metrics", {}), "vanna_confidence"),
            "directional_metrics.iv_path": (target.get("directional_metrics", {}), "iv_path"),
            "directional_metrics.iv_path_confidence": (target.get("directional_metrics", {}), "iv_path_confidence"),
            
            # atm_iv
            "atm_iv.iv_7d": (target.get("atm_iv", {}), "iv_7d"),
            "atm_iv.iv_14d": (target.get("atm_iv", {}), "iv_14d"),
            "atm_iv.iv_source": (target.get("atm_iv", {}), "iv_source"),
        }
        
        # 检查缺失字段
        missing_fields = []
        for field_path, (parent_dict, key) in required_fields.items():
            value = parent_dict.get(key) if isinstance(parent_dict, dict) else None
            if not self._is_valid_value(value):
                missing_fields.append({
                    "field": field_path,
                    "current_value": value
                })
        
        total_required = len(required_fields)
        provided = total_required - len(missing_fields)
        completion_rate = int((provided / total_required) * 100)
        
        is_complete = len(missing_fields) == 0
        
        return {
            "is_complete": is_complete,
            "missing_fields": missing_fields,
            "summary": {
                "total_required": total_required,
                "provided": provided,
                "missing_count": len(missing_fields),
                "completion_rate": completion_rate
            }
        }
    
    def _generate_guide(self,
                        missing_fields: list,
                        merge_history: list,
                        total_fields: int,
                        last_merge_failed: bool = False) -> Dict:
        """生成智能补齐指引"""
        if not missing_fields:
            return {
                "summary": "✅ 数据完整,无需补齐",
                "commands": [],
                "progress": f"100% ({total_fields}/{total_fields})",
                "next_action": "进入分析流程"
            }
        
        provided_count = total_fields - len(missing_fields)
        progress = f"{int((provided_count/total_fields)*100)}% ({provided_count}/{total_fields})"
        
        warning = ""
        if last_merge_failed:
            warning = "\n\n⚠️ **警告**: 上次上传的数据未能成功识别,请确保:\n" \
                      "1. 图片清晰完整\n" \
                      "2. 包含目标股票的期权数据\n" \
                      "3. 命令执行结果完整显示"
        
        # 生成命令建议
        commands = []
        for item in missing_fields[:5]:  # 最多显示 5 条
            field_path = item["field"]
            cmd_info = self._suggest_command(field_path)
            commands.append(cmd_info["command"])
        
        return {
            "summary": f"❌ 当前进度 {progress}, 还需补齐 {len(missing_fields)} 个字段{warning}",
            "commands": commands,
            "progress": progress,
            "next_action": f"📋 请继续上传图表补齐剩余 {len(missing_fields)} 个字段(支持多次上传累积)"
        }
    
    def _suggest_command(self, field_path: str) -> dict:
        """根据字段路径建议命令"""
        command_map = {
            "gamma_metrics.vol_trigger": {
                "command": "!trigger SYMBOL 60",
                "description": "Gamma 触发线"
            },
            "gamma_metrics.net_gex": {
                "command": "!gexn SYMBOL 60 98",
                "description": "净 Gamma 敞口"
            },
            "walls.call_wall": {
                "command": "!gexr SYMBOL 25 7w",
                "description": "Call 墙位"
            },
            "atm_iv.iv_7d": {
                "command": "!skew SYMBOL ivmid atm 7",
                "description": "7日 ATM 波动率"
            },
            "directional_metrics.dex_same_dir_pct": {
                "command": "!dexn SYMBOL 25 14w",
                "description": "DEX 方向一致性"
            },
        }
        
        return command_map.get(field_path, {
            "command": "!gexr SYMBOL 25 7w",
            "description": field_path
        })
    
    def _extract_symbol(self, data: Dict) -> str:
        """提取股票代码"""
        target = self._get_target_dict(data)
        return target.get("symbol", data.get("symbol", "UNKNOWN"))
    
    def _count_valid_fields(self, data: Dict) -> int:
        """统计有效字段数量"""
        target = self._get_target_dict(data)
        count = 0
        
        for section in ["gamma_metrics", "directional_metrics", "atm_iv", "walls"]:
            if section in target and isinstance(target[section], dict):
                for value in target[section].values():
                    if self._is_valid_value(value):
                        count += 1
        
        for key in ["spot_price", "em1_dollar"]:
            if self._is_valid_value(target.get(key)):
                count += 1
        
        return count
    
    def _count_valid_fields_in_dict(self, target_dict: dict) -> int:
        """统计字典中的有效字段数量"""
        count = 0
        
        for section in ["gamma_metrics", "directional_metrics", "atm_iv", "walls"]:
            if section in target_dict and isinstance(target_dict[section], dict):
                for value in target_dict[section].values():
                    if self._is_valid_value(value):
                        count += 1
        
        for key in ["spot_price", "em1_dollar"]:
            if self._is_valid_value(target_dict.get(key)):
                count += 1
        
        return count
    
    def _is_valid_value(self, value: Any) -> bool:
        """判断值是否有效(非缺失)"""
        if value is None:
            return False
        if value == -999:
            return False
        if value in ["N/A", "数据不足", "", "unknown"]:
            return False
        return True
    
    def _get_target_dict(self, data: dict) -> dict:
        """
        提取 targets 字典 (增强防御性)
        
        返回优先级:
        1. 如果 targets 是非空字典 → 直接返回
        2. 如果 targets 是非空列表 → 返回第一个元素
        3. 如果 targets 为空或缺失 → 返回空字典(但会在日志中警告)
        """
        targets = data.get("targets")
        
        # 情况 1: None 或缺失
        if targets is None:
            logger.warning("targets 字段缺失")
            return {}
        
        # 情况 2: 空列表
        if isinstance(targets, list):
            if not targets:
                logger.warning("targets 是空列表")
                return {}
            return targets[0]
        
        # 情况 3: 字典
        if isinstance(targets, dict):
            if not targets:
                logger.warning("targets 是空字典")
            return targets
        
        # 情况 4: 其他类型(异常)
        logger.error(f"targets 类型异常 - {type(targets)}")
        return {}