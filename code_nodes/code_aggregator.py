"""
CODE_AGGREGATOR - 数据聚合节点
支持多次上传数据的增量合并

从 YAML node id='1009' 迁移
"""

import json
from datetime import datetime
from typing import Dict, List, Tuple, Any


def main(
    agent3_output: dict,
    first_parse_data: str = "",
    current_symbol: str = "",
    data_status: str = "initial",
    missing_count: int = 0,
    **env_vars
) -> dict:
    """
    数据聚合节点 v5 - 增量合并优化版
    
    核心改进:
    1. 智能增量合并:多次上传自动累积数据
    2. 字段级追踪:记录每个字段的来源和质量
    3. 防止覆盖:有效数据不会被无效数据覆盖
    4. 自动完成:达到 22/22 自动进入分析流程
    
    Args:
        agent3_output: Agent 3 的数据校验结果
        first_parse_data: 首次解析的完整数据(用于累积)
        current_symbol: 当前分析的股票代码
        data_status: 数据状态(initial | awaiting_data | ready)
        missing_count: 缺失字段数量
        **env_vars: 环境变量
        
    Returns:
        {
            "result": 聚合后的完整数据 JSON,
            "first_parse_data": 更新后的缓存数据,
            "current_symbol": 股票代码,
            "data_status": 新状态,
            "missing_count": 缺失数量,
            "user_guide_summary": 用户指引摘要,
            "user_guide_commands": 需要执行的命令,
            "user_guide_progress": 进度信息,
            ...
        }
    """
    try:
        # ⭐ 新增：规范化数据结构（处理 GPT-4o 的平铺结构）
        current_data = _normalize_data_structure(agent3_output)
        
        # 🔍 调试日志 1: 检查输入数据
        print(f"📥 输入数据类型: {type(current_data)}")
        print(f"📥 targets 类型: {type(current_data.get('targets'))}")
        
        # 检查 targets 是否已经是嵌套结构
        targets = current_data.get('targets', {})
        if isinstance(targets, dict):
            has_nested = any(k in targets for k in ["gamma_metrics", "directional_metrics", "atm_iv", "walls"])
            print(f"📥 数据结构: {'嵌套结构' if has_nested else '平铺结构（已规范化）'}")
        
        symbol = extract_symbol(current_data)
        current_status = current_data.get("status", "missing_data")
        
        # === 判断是否累积模式 ===
        is_accumulation_mode, judgment = judge_accumulation_mode(
            current_data=current_data,
            cached_first_data=first_parse_data,
            cached_symbol=current_symbol,
            cached_status=data_status
        )
        
        print(f"📊 累积模式: {is_accumulation_mode}, 原因: {judgment}")
        
        if is_accumulation_mode:
            # === 增量合并 ===
            if not first_parse_data:
                # 第一次上传
                merged_data = current_data
                merge_history = [{
                    "round": 1,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "fields_added": count_valid_fields(current_data),
                    "action": "首次解析"
                }]
                last_merge_failed = False
            else:
                # 第 N 次上传 - 执行增量合并
                first_data = json.loads(first_parse_data)
                
                # 🔍 调试日志 2: 合并前的数据统计
                first_count = count_valid_fields(first_data)
                new_count = count_valid_fields(current_data)
                print(f"📊 合并前: 缓存数据 {first_count} 个字段, 新数据 {new_count} 个字段")
                
                merged_data, merge_info = smart_merge(first_data, current_data)
                
                # 🔍 调试日志 3: 合并后的结果
                merged_count = count_valid_fields(merged_data)
                print(f"📊 合并后: {merged_count} 个字段")
                print(f"📊 新增: {merge_info['new_fields_count']}, 更新: {merge_info['updated_fields_count']}")
                
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
            # 新任务
            merged_data = current_data
            merge_history = [{
                "round": 1,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fields_added": count_valid_fields(current_data),
                "action": "新任务开始"
            }]
            last_merge_failed = False
        
        # === 验证 ===
        validation_result = enhanced_validation_v2(merged_data)
        
        # 🔍 调试日志 4: 验证结果
        print(f"✅ 验证结果: 完成率 {validation_result['summary']['completion_rate']}%")
        print(f"✅ 提供字段: {validation_result['summary']['provided']}/{validation_result['summary']['total_required']}")
        
        if not isinstance(current_data, dict):
            raise ValueError(f"agent3_output 类型错误: {type(current_data)}")
        
        # 更新状态
        if validation_result["is_complete"]:
            final_status = "ready"
            merged_data["status"] = "data_ready"
        else:
            final_status = "awaiting_data"
            merged_data["status"] = "missing_data"
        
        # 生成补齐指引(基于实际缺失字段)
        missing_fields = validation_result["missing_fields"]
        补齐指引 = generate_smart_guide(
            missing_fields=missing_fields,
            merge_history=merge_history,
            total_fields=22,
            last_merge_failed=last_merge_failed,
            symbol=symbol
        )
        
        # === 输出结构化的结果 ===
        result_data = {
            **merged_data,
            "validation_summary": validation_result["summary"],
            "判断依据": judgment,
            "_merge_history": merge_history
        }
        
        return {
            "result": json.dumps(result_data, ensure_ascii=False, indent=2),
            
            # 会话变量
            "first_parse_data": json.dumps(merged_data, ensure_ascii=False) if final_status == "awaiting_data" else "",
            "current_symbol": symbol,
            "data_status": final_status,
            "missing_count": len(missing_fields),
            
            # 补齐指引(扁平化输出)
            "user_guide_summary": 补齐指引.get("summary", ""),
            "user_guide_commands": 补齐指引.get("commands_text", ""),
            "user_guide_progress": 补齐指引.get("progress", ""),
            "user_guide_priority_critical": 补齐指引.get("critical_text", ""),
            "user_guide_priority_high": 补齐指引.get("high_text", ""),
            "user_guide_priority_medium": 补齐指引.get("medium_text", ""),
            "user_guide_next_action": 补齐指引.get("next_action", ""),
            "user_guide_merge_log": 补齐指引.get("merge_log", "")
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


# ============= ⭐ 新增：数据结构规范化 =============

def _normalize_data_structure(data: dict) -> dict:
    """
    将平铺结构的数据转换为标准嵌套结构
    
    处理 GPT-4o 等模型返回的不符合 Schema 的平铺结构数据
    
    Args:
        data: 原始数据（可能是平铺或嵌套结构）
        
    Returns:
        标准嵌套结构的数据
    """
    targets = data.get("targets", {})
    
    # 检查是否已经是嵌套结构
    has_nested = any(k in targets for k in ["gamma_metrics", "directional_metrics", "atm_iv", "walls"])
    
    if has_nested:
        return data  # 已经是标准结构，无需转换
    
    # 转换平铺结构为嵌套结构
    normalized_targets = {
        "symbol": targets.get("symbol", "UNKNOWN"),
        "status": targets.get("status", "missing_data"),
        "spot_price": targets.get("spot_price", -999),
        "em1_dollar": targets.get("em1_dollar", -999),
        
        "walls": {
            "call_wall": targets.get("call_wall", -999),
            "put_wall": targets.get("put_wall", -999),
            "major_wall": targets.get("major_wall", -999),
            "major_wall_type": targets.get("major_wall_type", "N/A")
        },
        
        "gamma_metrics": {
            "gap_distance_dollar": targets.get("gap_distance_dollar", -999),
            "gap_distance_em1_multiple": targets.get("gap_distance_em1_multiple", -999),
            "cluster_strength_ratio": targets.get("cluster_strength_ratio", -999),
            "net_gex": targets.get("net_gex", -999),
            "net_gex_sign": targets.get("net_gex_sign", "N/A"),
            "vol_trigger": targets.get("vol_trigger", -999),
            "spot_vs_trigger": targets.get("spot_vs_trigger", "N/A"),
            "monthly_cluster_override": targets.get("monthly_cluster_override", "false")
        },
        
        "directional_metrics": {
            "dex_same_dir_pct": targets.get("dex_same_dir_pct", -999),
            "vanna_dir": targets.get("vanna_dir", "N/A"),
            "vanna_confidence": targets.get("vanna_confidence", "N/A"),
            "iv_path": targets.get("iv_path", "数据不足"),
            "iv_path_confidence": targets.get("iv_path_confidence", "low")
        },
        
        "atm_iv": {
            "iv_7d": targets.get("iv_7d", -999),
            "iv_14d": targets.get("iv_14d", -999),
            "iv_source": targets.get("iv_source", "N/A")
        }
    }
    
    # 保留其他可选字段
    for key in ["validation_summary", "indices", "technical_analysis", "chart_metadata", "missing_fields", "补齐指引"]:
        if key in targets:
            normalized_targets[key] = targets[key]
    
    return {
        **data,
        "targets": normalized_targets
    }


# ============= 核心函数 1: 智能判断累积模式 =============

def judge_accumulation_mode(
    current_data: dict,
    cached_first_data: str,
    cached_symbol: str,
    cached_status: str
) -> Tuple[bool, str]:
    """
    判断是否进入累积模式(增量补齐)
    
    Returns:
        (is_accumulation, reason)
    """
    # 情况 1: 无缓存 → 首次解析
    if not cached_first_data or cached_status == "initial":
        return True, "首次上传,开始解析"
    
    # 情况 2: Symbol 变化 → 新任务
    current_symbol = extract_symbol(current_data)
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


# ============= 核心函数 2: 智能合并算法 =============

def smart_merge(first_data: dict, new_data: dict) -> Tuple[dict, dict]:
    """
    智能增量合并(增强版)
    
    新增特性:
    1. 检测新数据是否为空
    2. 如果新数据为空,直接返回旧数据(不合并)
    3. 记录合并失败的原因
    """
    merged = first_data.copy()
    
    # 提取 targets
    first_targets = get_target_dict(first_data)
    new_targets = get_target_dict(new_data)
    
    # 🔥 核心修复:检测新数据是否为空
    new_valid_count = count_valid_fields_in_dict(new_targets)
    
    if new_valid_count == 0:
        # 新数据为空,不执行合并
        print("⚠️ 警告: 新数据无有效字段,跳过合并")
        merge_info = {
            "new_fields_count": 0,
            "updated_fields_count": 0,
            "merge_failed": True,
            "failure_reason": "新数据无有效字段(可能解析失败)"
        }
        return merged, merge_info  # 返回原数据
    
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
                
                if is_valid_value(new_value):
                    if not is_valid_value(old_value):
                        first_targets[section][key] = new_value
                        new_fields_count += 1
                    elif old_value != new_value:
                        first_targets[section][key] = new_value
                        updated_fields_count += 1
    
    # 合并顶层字段
    for key in ["spot_price", "em1_dollar", "symbol"]:
        old_value = first_targets.get(key)
        new_value = new_targets.get(key)
        
        if is_valid_value(new_value):
            if not is_valid_value(old_value):
                first_targets[key] = new_value
                new_fields_count += 1
            elif old_value != new_value:
                first_targets[key] = new_value
                updated_fields_count += 1
    
    # 🔥 修复:如果没有任何新增或更新,标记为失败
    if new_fields_count == 0 and updated_fields_count == 0:
        print("⚠️ 警告: 合并未产生任何变化,可能数据重复或解析失败")
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
                    if is_valid_value(new_value) and not is_valid_value(old_value):
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


# ============= 辅助函数 =============

def count_valid_fields_in_dict(target_dict: dict) -> int:
    """
    统计字典中的有效字段数量（增强版）
    
    支持两种数据结构：
    1. 标准嵌套结构（Schema 规定）
    2. 平铺结构（部分模型返回）
    """
    count = 0
    
    # === 尝试标准嵌套结构 ===
    nested_count = 0
    for section in ["gamma_metrics", "directional_metrics", "atm_iv", "walls"]:
        if section in target_dict and isinstance(target_dict[section], dict):
            for value in target_dict[section].values():
                if is_valid_value(value):
                    nested_count += 1
    
    # 检查顶层必需字段
    for key in ["spot_price", "em1_dollar"]:
        if is_valid_value(target_dict.get(key)):
            nested_count += 1
    
    # === 如果嵌套结构存在，使用嵌套计数 ===
    if nested_count > 0:
        return nested_count
    
    # === 否则尝试平铺结构 ===
    flat_required_fields = [
        "spot_price", "em1_dollar",
        # walls
        "call_wall", "put_wall", "major_wall", "major_wall_type",
        # gamma_metrics
        "gap_distance_dollar", "gap_distance_em1_multiple", 
        "cluster_strength_ratio", "net_gex", "net_gex_sign",
        "vol_trigger", "spot_vs_trigger", "monthly_cluster_override",
        # directional_metrics
        "dex_same_dir_pct", "vanna_dir", "vanna_confidence",
        "iv_path", "iv_path_confidence",
        # atm_iv
        "iv_7d", "iv_14d", "iv_source"
    ]
    
    flat_count = 0
    for field in flat_required_fields:
        if is_valid_value(target_dict.get(field)):
            flat_count += 1
    
    return flat_count


def is_valid_value(value: Any) -> bool:
    """判断值是否有效(非缺失)"""
    if value is None:
        return False
    if value == -999:
        return False
    if value in ["N/A", "数据不足", "", "unknown"]:
        return False
    return True


def get_target_dict(data: dict) -> dict:
    """
    提取 targets 字典(增强防御性)
    
    返回优先级:
    1. 如果 targets 是非空字典 → 直接返回
    2. 如果 targets 是非空列表 → 返回第一个元素
    3. 如果 targets 为空或缺失 → 返回空字典(但会在日志中警告)
    """
    targets = data.get("targets")
    
    # 优先级1: 直接是字典
    if isinstance(targets, dict) and targets:
        return targets
    
    # 优先级2: 非空列表
    if isinstance(targets, list) and targets:
        return targets[0] if isinstance(targets[0], dict) else {}
    
    # 优先级3: 回退到根节点（兼容旧格式）
    # 如果data本身包含spot_price等字段，说明targets就是根节点
    if "spot_price" in data or "symbol" in data:
        print("⚠️ targets字段缺失，尝试从根节点读取")
        return data
    
    # 无法识别
    print(f"❌ 无法提取targets，类型: {type(targets)}")
    return {}


def enhanced_validation_v2(data: dict) -> dict:
    """
    三级验证增强版(支持平铺和嵌套结构)
    
    Returns:
        {
            "is_complete": bool,
            "missing_fields": list,
            "summary": dict
        }
    """
    target = get_target_dict(data)
    
    # ⭐ 检测数据结构类型
    is_nested = any(k in target for k in ["gamma_metrics", "directional_metrics", "atm_iv", "walls"])
    
    if is_nested:
        # === 标准嵌套结构验证 ===
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
    else:
        # === ⭐ 平铺结构验证 ===
        required_fields = {
            "spot_price": (target, "spot_price"),
            "em1_dollar": (target, "em1_dollar"),
            "call_wall": (target, "call_wall"),
            "put_wall": (target, "put_wall"),
            "major_wall": (target, "major_wall"),
            "major_wall_type": (target, "major_wall_type"),
            "gap_distance_dollar": (target, "gap_distance_dollar"),
            "gap_distance_em1_multiple": (target, "gap_distance_em1_multiple"),
            "cluster_strength_ratio": (target, "cluster_strength_ratio"),
            "net_gex": (target, "net_gex"),
            "net_gex_sign": (target, "net_gex_sign"),
            "vol_trigger": (target, "vol_trigger"),
            "spot_vs_trigger": (target, "spot_vs_trigger"),
            "monthly_cluster_override": (target, "monthly_cluster_override"),
            "dex_same_dir_pct": (target, "dex_same_dir_pct"),
            "vanna_dir": (target, "vanna_dir"),
            "vanna_confidence": (target, "vanna_confidence"),
            "iv_path": (target, "iv_path"),
            "iv_path_confidence": (target, "iv_path_confidence"),
            "iv_7d": (target, "iv_7d"),
            "iv_14d": (target, "iv_14d"),
            "iv_source": (target, "iv_source")
        }
    
    # 检查缺失字段
    missing_fields = []
    for field_path, (parent_dict, key) in required_fields.items():
        value = parent_dict.get(key) if isinstance(parent_dict, dict) else None
        if not is_valid_value(value):
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


def generate_smart_guide(
    missing_fields: list,
    merge_history: list,
    total_fields: int,
    last_merge_failed: bool = False,
    symbol: str = ''
) -> dict:
    """
    生成智能补齐指引
    
    新增特性:
    1. 显示累积进度
    2. 显示合并历史
    3. 优先级动态调整
    """
    if not missing_fields:
        return {
            "summary": "✅ 数据完整,无需补齐",
            "commands_text": "无",
            "progress": f"100% ({total_fields}/{total_fields})",
            "critical_text": "无",
            "high_text": "无",
            "medium_text": "无",
            "next_action": "进入分析流程",
            "merge_log": format_merge_history(merge_history)
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
    priority_groups = {"critical":[], "high": [], "medium": []}
    
    for item in missing_fields:
        field_path = item["field"]
        cmd_info = suggest_command(field_path, symbol)
        
        priority = cmd_info["priority"]
        priority_groups[priority].append({
            "字段": field_path,
            "命令": cmd_info["command"],
            "说明": cmd_info["description"]
        })
        
        if cmd_info["command"] not in commands:
            commands.append(cmd_info["command"])
    
    # 格式化输出
    return {
        "summary": f"❌ 当前进度 {progress}, 还需补齐 {len(missing_fields)} 个字段{warning}",
        "commands_text": "\n".join(commands[:5]),  # 最多显示 5 条
        "progress": progress,
        "critical_text": format_priority_items(priority_groups["critical"]),
        "high_text": format_priority_items(priority_groups["high"]),
        "medium_text": format_priority_items(priority_groups["medium"]),
        "next_action": f"📋 请继续上传图表补齐剩余 {len(missing_fields)} 个字段(支持多次上传累积)",
        "merge_log": format_merge_history(merge_history)
    }


def suggest_command(field_path: str, symbol: str) -> dict:
    """根据字段路径建议命令"""
    # 处理嵌套字段名（如 "gamma_metrics.vol_trigger"）
    field_name = field_path.split('.')[-1] if '.' in field_path else field_path
    
    command_map = {
        "vol_trigger": {
            "command": f"!trigger {symbol} 60",
            "description": "Gamma 触发线",
            "priority": "critical"
        },
        "net_gex": {
            "command": f"!gexn {symbol} 60 98",
            "description": "净 Gamma 敞口",
            "priority": "critical"
        },
        "net_gex_sign": {
            "command": f"!gexn {symbol} 60 98",
            "description": "净 Gamma 符号",
            "priority": "critical"
        },
        "spot_vs_trigger": {
            "command": f"!trigger {symbol} 60",
            "description": "现价相对触发线",
            "priority": "critical"
        },
        "call_wall": {
            "command": f"!gexr {symbol} 25 7w",
            "description": "Call 墙位",
            "priority": "high"
        },
        "put_wall": {
            "command": f"!gexr {symbol} 25 7w",
            "description": "Put 墙位",
            "priority": "high"
        },
        "major_wall": {
            "command": f"!gexr {symbol} 25 7w",
            "description": "主墙位",
            "priority": "high"
        },
        "major_wall_type": {
            "command": f"!gexr {symbol} 25 7w",
            "description": "主墙类型",
            "priority": "high"
        },
        "gap_distance_dollar": {
            "command": f"!gexr {symbol} 25 7w",
            "description": "跳墙距离（美元）",
            "priority": "high"
        },
        "gap_distance_em1_multiple": {
            "command": f"!gexr {symbol} 25 7w",
            "description": "跳墙距离（EM1倍数）",
            "priority": "high"
        },
        "cluster_strength_ratio": {
            "command": f"!gexr {symbol} 25 7w",
            "description": "簇强度比",
            "priority": "medium"
        },
        "monthly_cluster_override": {
            "command": f"!gexr {symbol} 25 30m",
            "description": "月度簇占优",
            "priority": "medium"
        },
        "iv_7d": {
            "command": f"!skew {symbol} ivmid atm 7",
            "description": "7日 ATM 波动率",
            "priority": "high"
        },
        "iv_14d": {
            "command": f"!skew {symbol} ivmid atm 14",
            "description": "14日 ATM 波动率",
            "priority": "high"
        },
        "iv_source": {
            "command": f"!skew {symbol} ivmid atm 7",
            "description": "IV 数据源",
            "priority": "high"
        },
        "dex_same_dir_pct": {
            "command": f"!dexn {symbol} 25 14w",
            "description": "DEX 方向一致性",
            "priority": "medium"
        },
        "vanna_dir": {
            "command": f"!vanna {symbol} ntm 60 m",
            "description": "Vanna 方向",
            "priority": "medium"
        },
        "vanna_confidence": {
            "command": f"!vanna {symbol} ntm 60 m",
            "description": "Vanna 置信度",
            "priority": "medium"
        },
        "iv_path": {
            "command": f"!term {symbol} 60",
            "description": "IV 路径趋势",
            "priority": "medium"
        },
        "iv_path_confidence": {
            "command": f"!term {symbol} 60",
            "description": "IV 路径置信度",
            "priority": "medium"
        }
    }
    
    return command_map.get(field_name, {
        "command": f"!gexr {symbol} 25 7w",  # 默认命令
        "description": field_path,
        "priority": "medium"
    })


def format_priority_items(items: list) -> str:
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


def format_merge_history(history: list) -> str:
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


def extract_symbol(data: dict) -> str:
    """提取股票代码"""
    target = get_target_dict(data)
    return target.get("symbol", data.get("symbol", "UNKNOWN"))


def count_valid_fields(data: dict) -> int:
    """统计有效字段数量"""
    target = get_target_dict(data)
    return count_valid_fields_in_dict(target)