"""
数据验证工具（修复版）
修复：支持完整路径作为 cache_file 参数
"""

import re
import json
from typing import Tuple
from datetime import datetime
from pathlib import Path


def validate_symbol(symbol: str) -> Tuple[bool, str]:
    """验证股票代码"""
    if not symbol:
        return False, "股票代码不能为空"
    
    symbol = symbol.strip().upper()
    
    # 检查是否为保留关键字
    reserved_keywords = ["UNKNOWN", "TEST", "N/A", "NULL", "NONE", "ERROR"]
    if symbol in reserved_keywords:
        return False, f"'{symbol}' 是保留关键字，不能作为股票代码"
    
    # 检查长度（1-10个字符）
    if len(symbol) < 1 or len(symbol) > 10:
        return False, f"股票代码长度必须在 1-10 之间，当前: {len(symbol)}"
    
    # 检查字符（仅允许字母、数字、点号、短横线）
    if not re.match(r'^[A-Z0-9\.\-]+$', symbol):
        return False, f"股票代码只能包含字母、数字、点号和短横线"
    
    # 检查是否以数字开头（通常无效）
    if symbol[0].isdigit():
        return False, f"股票代码不能以数字开头"
    
    return True, symbol


def normalize_symbol(symbol: str) -> str:
    """标准化股票代码（无验证版本）"""
    if not symbol:
        return "UNKNOWN"
    
    return symbol.strip().upper()


def validate_cache_file(cache_file: str, symbol: str) -> tuple[bool, str, dict]:
    """
    验证缓存文件的合法性（支持路径输入）
    
    Args:
        cache_file: 缓存文件名或路径
            支持格式：
            - 文件名：NVDA_20251201.json
            - 相对路径：./data/output/NVDA/20251201/NVDA_20251201.json
            - 绝对路径：/path/to/NVDA_20251201.json
        symbol: 股票代码
        
    Returns:
        (is_valid, error_message, cache_info)
    """
    # ⭐ 修复：提取文件名（兼容路径输入）
    cache_path = Path(cache_file)
    filename = cache_path.name
    
    # 1. 解析文件名
    match = re.match(r'(\w+)_(\d{8})\.json', filename)
    if not match:
        return False, f"缓存文件名格式错误，应为 {{SYMBOL}}_{{YYYYMMDD}}.json", {}
    
    file_symbol = match.group(1)
    file_date = match.group(2)
    
    # 2. 验证股票代码匹配
    if file_symbol.upper() != symbol.upper():
        return False, f"缓存文件股票代码 ({file_symbol}) 与参数不匹配 ({symbol})", {}
    
    # 3. 验证日期格式
    try:
        parsed_date = datetime.strptime(file_date, "%Y%m%d")
    except ValueError:
        return False, f"缓存文件日期格式错误: {file_date}", {}
    
    # 4. 检查文件是否存在（优先使用用户路径）
    if cache_path.exists():
        final_cache_path = cache_path
    else:
        # 回退到标准路径
        final_cache_path = Path(f"data/output/{symbol}/{file_date}/{filename}")
        if not final_cache_path.exists():
            return False, f"缓存文件不存在: {final_cache_path}", {}
    
    # 5. 加载并验证文件内容
    try:
        with open(final_cache_path, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
    except Exception as e:
        return False, f"缓存文件读取失败: {str(e)}", {}
    
    # 6. 验证内部日期一致性
    start_date = cache_data.get("start_date", "")
    if start_date:
        internal_date = start_date.replace("-", "")
        if internal_date != file_date:
            return False, (
                f"缓存文件内部日期不匹配！\n"
                f"  文件名日期: {file_date}\n"
                f"  内部日期: {internal_date} ({start_date})"
            ), {}
    
    cache_info = {
        "symbol": file_symbol,
        "date": file_date,
        "parsed_date": parsed_date,
        "cache_path": final_cache_path,  # ⭐ 返回实际路径
        "start_date": start_date,
        "has_source_target": cache_data.get("source_target") is not None,
        "snapshot_count": sum(1 for k in cache_data.keys() if k.startswith("snapshots_"))
    }
    
    return True, "", cache_info