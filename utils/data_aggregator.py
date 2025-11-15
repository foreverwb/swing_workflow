"""
数据聚合节点 - CODE_AGGREGATOR (Node 1009)
实现增量数据累积和智能补齐指引
"""

import json
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional


class DataAggregator:
    """数据聚合引擎,实现增量合并和补齐指引生成"""
    
    def __init__(self, config):
        self.config = config
    
    def process(
        self, 
        agent3_output: dict,
        first_parse_data: str = "",
        current_symbol: str = "",
        data_status: str = "initial",
        missing_count: int = 0
    ) -> Dict[str, Any]:
        """
        主处理流程
        
        Args:
            agent3_output: Agent 3 的数据校验结果
            first_parse_data: 缓存的首次解析数据 (JSON字符串)
            current_symbol: 缓存的股票代码
            data_status: 缓存的数据状态 (initial/awaiting_data/ready/error)
            missing_count: 缓存的缺失字段数量
        
        Returns:
            {
                "result": 合并后的完整数据 (JSON字符串),
                "first_parse_data": 更新后的缓存 (供下次使用),
                "current_symbol": 更新后的股票代码,
                "data_status": 更新后的状态,
                "missing_count": 更新后的缺失数量,
                "user_guide_*": 补齐指引的各个部分 (扁平化输出)
            }
        """
        try:
            current_data = agent3_output
            symbol = self._extract_symbol(current_data)
            current_status = current_data.get("status", "missing_data")
            
            # 判断是否累积模式
            is_accumulation, judgment = self._judge_accumulation_mode(
                current_data=current_data,
                cached_first_data=first_parse_data,
                cached_symbol=current_symbol,
                cached_status=data_status
            )
            
            # 执行合并或新建
            if is_accumulation:
                if not first_parse_data:
                    # 首次上传
                    merged_data = current_data
                    merge_history = [{
                        "round": 1,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "fields_added": self._count_valid_fields(current_data),
                        "action": "首次解析"
                    }]
                    last_merge_failed = False
                else:
                    # 增量合并
                    first_data = json.loads(first_parse_data)
                    merged_data, merge_info = self._smart_merge(first_data, current_data)
                    
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
                # 新任务
                merged_data = current_data
                merge_history = [{
                    "round": 1,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "fields_added": self._count_valid_fields(current_data),
                    "action": "新任务开始"
                }]
                last_merge_failed = False
            
            # 验证合并后的数据
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
            guide = self._generate_smart_guide(
                missing_fields=missing_fields,
                merge_history=merge_history,
                total_fields=22,
                last_merge_failed=last_merge_failed
            )
            
            # 组装结果
            result_data = {
                **merged_data,
                "validation_summary": validation_result["summary"],
                "判断依据": judgment,
                "_merge_history": merge_history
            }
            
            return {
                "result": json.dumps(result_data, ensure_ascii=False, indent=2),
                
                # 会话变量更新
                "first_parse_data": json.dumps(merged_data, ensure_ascii=False) if final_status == "awaiting_data" else "",
                "current_symbol": symbol,
                "data_status": final_status,
                "missing_count": len(missing_fields),
                
                # 补齐指引 (扁平化输出)
                "user_guide_summary": guide.get("summary", ""),
                "user_guide_commands": guide.get("commands_text", ""),
                "user_guide_progress": guide.get("progress", ""),
                "user_guide_priority_critical": guide.get("critical_text", ""),
                "user_guide_priority_high": guide.get("high_text", ""),
                "user_guide_priority_medium": guide.get("medium_text", ""),
                "user_guide_next_action": guide.get("next_action", ""),
                "user_guide_merge_log": guide.get("merge_log", "")
            }
        
        except Exception as e:
            import traceback
            return {
                "result": json.dumps({
                    "error": True,
                    "error_message": str(e),
                    "error_traceback": traceback.format_exc()
                }, ensure_ascii=False, indent=2),
                "first_parse_data": first_parse_data,
                "current_symbol": current_symbol,
                "data_status": "error",
                "missing_count": 0,
                "user_guide_summary": f"⚠️ 系统错误: {str(e)}",
                "user_guide_commands": "",
                "user_guide_progress": "",
                "user_guide_priority_critical": "",
                "user_guide_priority_high": "",
                "user_guide_priority_medium": "",
                "user_guide_next_action": "请检查数据后重试",
                "user_guide_merge_log": ""
            }
    
    # ============= 核心方法 1: 累积模式判断 =============
    
    def _judge_accumulation_mode(
        self, 
        current_data: dict,
        cached_first_data: str,
        cached_symbol: str,
        cached_status: str
    ) -> Tuple[bool, str]:
        """判断是否进入累积模式"""
        # 情况 1: 无缓存 → 首次解析
        if not cached_first_data or cached_status == "initial":
            return True, "首次上传,开始解析"
        
        # 情况 2: Symbol 变化 → 新任务
        current_symbol = self._extract_symbol(current_data)
        if current_symbol != cached_symbol:
            return False, f"Symbol变化({cached_symbol}→{current_symbol}),开始新任务"
        
        # 情况 3: 缓存状态为 ready → 已完成,不再累积
        if cached_status == "ready":
            return False, "数据已完整,开始新任务"
        
        # 情况 4: 缓存等待补齐 → 累积模式
        if cached_status == "awaiting_data":
            return True, "检测到历史缓存,进入增量补齐模式"
        
        return True, "进入累积模式"
    
    # ============= 核心方法 2: 智能合并 =============
    
    def _smart_merge(self, first_data: dict, new_data: dict) -> Tuple[dict, dict]:
        """智能增量合并,防止有效数据被覆盖"""
        merged = first_data.copy()
        
        first_targets = self._get_target_dict(first_data)
        new_targets = self._get_target_dict(new_data)
        
        # 检测新数据是否为空
        new_valid_count = self._count_valid_fields_in_dict(new_targets)
        
        if new_valid_count == 0:
            print("⚠️ 警告: 新数据无有效字段,跳过合并")
            return merged, {
                "new_fields_count": 0,
                "updated_fields_count": 0,
                "merge_failed": True,
                "failure_reason": "新数据无有效字段(可能解析失败)"
            }
        
        new_fields_count = 0
        updated_fields_count = 0
        
        # 合并各 section
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
        
        # 检查合并结果
        if new_fields_count == 0 and updated_fields_count == 0:
            print("⚠️ 警告: 合并未产生任何变化")
            return merged, {
                "new_fields_count": 0,
                "updated_fields_count": 0,
                "merge_failed": True,
                "failure_reason": "无新增或更新字段"
            }
        
        # 合并 indices 和 technical_analysis
        if "indices" in new_data:
            if "indices" not in merged:
                merged["indices"] = {}
            for index_name in ["spx", "qqq"]:
                if index_name in new_data["indices"]:
                    if index_name not in merged["indices"]:
                        merged["indices"][index_name] = {}
                    for key, new_value in new_data["indices"][index_name].items():
                        old_value = merged["indices"][index_name].get(key)
                        if self._is_valid_value(new_value) and not self._is_valid_value(old_value):
                            merged["indices"][index_name][key] = new_value
        
        if "technical_analysis" in new_data:
            ta = new_data["technical_analysis"]
            if ta and ta.get("ta_score", 0) > 0:
                merged["technical_analysis"] = ta
        
        merged["targets"] = first_targets
        
        return merged, {
            "new_fields_count": new_fields_count,
            "updated_fields_count": updated_fields_count,
            "merge_failed": False
        }
    
    # ============= 核心方法 3: 增强验证 =============
    
    def _enhanced_validation(self, data: dict) -> dict:
        """三级验证,基于合并后的数据"""
        target = self._get_target_dict(data)
        
        # 22 个必需字段定义
        required_fields = {
            "spot_price": (target, "spot_price"),
            "em1_dollar": (target, "em1_dollar"),
            "walls.call_wall": (target.get("walls", {}), "call_wall"),
            "walls.put_wall": (target.get("walls", {}), "put_wall"),
            "walls.major_wall": (target.get("walls", {}), "major_wall"),
            "walls.major_wall_type": (target.get("walls", {}), "major_wall_type"),
            "gamma_metrics.gap_distance_dollar": (target.get("gamma_metrics", {}), "gap_distance_dollar"),
            "gamma_metrics.gap_distance_em1_multiple": (target.get("gamma_metrics", {}), "gap_distance_em1_multiple"),
            "gamma_metrics.cluster_strength_ratio": (target.get("gamma_metrics", {}), "cluster_strength_ratio"),
            "gamma_metrics.net_gex": (target.get("gamma_metrics", {}), "net_gex"),
            "gamma_metrics.net_gex_sign": (target.get("gamma_metrics", {}), "net_gex_sign"),
            "gamma_metrics.vol_trigger": (target.get("gamma_metrics", {}), "vol_trigger"),
            "gamma_metrics.spot_vs_trigger": (target.get("gamma_metrics", {}), "spot_vs_trigger"),
            "gamma_metrics.monthly_cluster_override": (target.get("gamma_metrics", {}), "monthly_cluster_override"),
            "directional_metrics.dex_same_dir_pct": (target.get("directional_metrics", {}), "dex_same_dir_pct"),
            "directional_metrics.vanna_dir": (target.get("directional_metrics", {}), "vanna_dir"),
            "directional_metrics.vanna_confidence": (target.get("directional_metrics", {}), "vanna_confidence"),
            "directional_metrics.iv_path": (target.get("directional_metrics", {}), "iv_path"),
            "directional_metrics.iv_path_confidence": (target.get("directional_metrics", {}), "iv_path_confidence"),
            "atm_iv.iv_7d": (target.get("atm_iv", {}), "iv_7d"),
            "atm_iv.iv_14d": (target.get("atm_iv", {}), "iv_14d"),
            "atm_iv.iv_source": (target.get("atm_iv", {}), "iv_source"),
        }
        
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
        
        return {
            "is_complete": len(missing_fields) == 0,
            "missing_fields": missing_fields,
            "summary": {
                "total_required": total_required,
                "provided": provided,
                "missing_count": len(missing_fields),
                "completion_rate": completion_rate
            }
        }
    
    # ============= 核心方法 4: 智能指引生成 =============
    
    def _generate_smart_guide(
        self, 
        missing_fields: list,
        merge_history: list,
        total_fields: int,
        last_merge_failed: bool = False
    ) -> dict:
        """生成智能补齐指引"""
        if not missing_fields:
            return {
                "summary": "✅ 数据完整,无需补齐",
                "commands_text": "无",
                "progress": f"100% ({total_fields}/{total_fields})",
                "critical_text": "无",
                "high_text": "无",
                "medium_text": "无",
                "next_action": "进入分析流程",
                "merge_log": self._format_merge_history(merge_history)
            }
        
        provided_count = total_fields - len(missing_fields)
        progress = f"{int((provided_count/total_fields)*100)}% ({provided_count}/{total_fields})"
        
        warning = ""
        if last_merge_failed:
            warning = "\n\n⚠️ **警告**: 上次上传的数据未能成功识别,请确保:\n" \
                      "1. 图片清晰完整\n" \
                      "2. 包含目标股票的期权数据\n" \
                      "3. 命令执行结果完整显示"
        
        # 根据字段路径生成命令建议
        commands = []
        priority_groups = {"critical": [], "high": [], "medium": []}
        
        for item in missing_fields:
            field_path = item["field"]
            cmd_info = self._suggest_command(field_path)
            
            priority = cmd_info["priority"]
            priority_groups[priority].append({
                "字段": field_path,
                "命令": cmd_info["command"],
                "说明": cmd_info["description"]
            })
            
            if cmd_info["command"] not in commands:
                commands.append(cmd_info["command"])
        
        return {
            "summary": f"❌ 当前进度 {progress}, 还需补齐 {len(missing_fields)} 个字段{warning}",
            "commands_text": "\n".join(commands[:5]),  # 最多显示 5 条
            "progress": progress,
            "critical_text": self._format_priority_items(priority_groups["critical"]),
            "high_text": self._format_priority_items(priority_groups["high"]),
            "medium_text": self._format_priority_items(priority_groups["medium"]),
            "next_action": f"📋 请继续上传图表补齐剩余 {len(missing_fields)} 个字段(支持多次上传累积)",
            "merge_log": self._format_merge_history(merge_history)
        }
    
    # ============= 辅助方法 =============
    
    def _extract_symbol(self, data: dict) -> str:
        """提取股票代码"""
        target = self._get_target_dict(data)
        return target.get("symbol", data.get("symbol", "UNKNOWN"))
    
    def _get_target_dict(self, data: dict) -> dict:
        """提取 targets 字典"""
        targets = data.get("targets")
        
        if targets is None:
            return {}
        
        if isinstance(targets, list):
            if not targets:
                return {}
            return targets[0]
        
        if isinstance(targets, dict):
            return targets
        
        return {}
    
    def _is_valid_value(self, value: Any) -> bool:
        """判断值是否有效"""
        if value is None:
            return False
        if value == -999:
            return False
        if value in ["N/A", "数据不足", "", "unknown"]:
            return False
        return True
    
    def _count_valid_fields(self, data: dict) -> int:
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
    
    def _suggest_command(self, field_path: str) -> dict:
        """根据字段路径建议命令"""
        command_map = {
            "gamma_metrics.vol_trigger": {
                "command": "!trigger SYMBOL 60",
                "description": "Gamma 触发线",
                "priority": "critical"
            },
            "gamma_metrics.net_gex": {
                "command": "!gexn SYMBOL 60 98",
                "description": "净 Gamma 敞口",
                "priority": "critical"
            },
            "walls.call_wall": {
                "command": "!gexr SYMBOL 25 7w",
                "description": "Call 墙位",
                "priority": "high"
            },
            "atm_iv.iv_7d": {
                "command": "!skew SYMBOL ivmid atm 7",
                "description": "7日 ATM 波动率",
                "priority": "high"
            },
            "directional_metrics.dex_same_dir_pct": {
                "command": "!dexn SYMBOL 25 14w",
                "description": "DEX 方向一致性",
                "priority": "medium"
            },
        }
        
        return command_map.get(field_path, {
            "command": "!gexr SYMBOL 25 7w",
            "description": field_path,
            "priority": "medium"
        })
    
    def _format_priority_items(self, items: list) -> str:
        """格式化优先级列表"""
        if not items:
            return "无"
        
        result = []
        for i, item in enumerate(items, 1):
            result.append(
                f"{i}. **{item['字段']}**\n"
                f"   - 命令: `{item['命令']}`\n"
                f"   - 说明: {item['说明']}"
            )
        return "\n\n".join(result)
    
    def _format_merge_history(self, history: list) -> str:
        """格式化合并历史"""
        if not history:
            return "无历史记录"
        
        lines = []
        for record in history:
            lines.append(
                f"第{record['round']}轮 ({record['timestamp']}): "
                f"{record['action']}, "
                f"新增 {record.get('fields_added', 0)} 个字段"
            )
        return "\n".join(lines)