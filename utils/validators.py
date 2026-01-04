"""
数据验证工具（修复版）
修复：支持完整路径作为 cache_file 参数
"""

import re
import json
from typing import Tuple, Optional
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
            - 文件名：NVDA_o_20251201.json 或 NVDA_o_20251201
            - 相对路径：./data/output/NVDA/20251201/NVDA_o_20251201.json
            - 绝对路径：/path/to/NVDA_o_20251201.json
        symbol: 股票代码
        
    Returns:
        (is_valid, error_message, cache_info)
    """
    # 修复：提取文件名（兼容路径输入）
    cache_path = Path(cache_file)
    filename = cache_path.name
    
    # [Fix] 自动补全 .json 后缀
    if not filename.endswith('.json'):
        filename = f"{filename}.json"
        cache_path = cache_path.parent / filename if cache_path.parent != Path('.') else Path(filename)
    
    # 1. 解析文件名
    match = re.match(r'(\w+)_o_(\d{8})\.json', filename)
    if not match:
        return False, f"缓存文件名格式错误，应为 {{SYMBOL}}_o_{{YYYYMMDD}}.json", {}
    
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
        "cache_path": final_cache_path,  # 返回实际路径
        "start_date": start_date,
        "has_source_target": cache_data.get("source_target") is not None,
        "snapshot_count": sum(1 for k in cache_data.keys() if k.startswith("snapshots_"))
    }
    
    return True, "", cache_info


def resolve_input_file_path(input_arg: str, symbol: str = None) -> Tuple[Optional[Path], str]:
    """
    智能解析输入文件路径
    
    支持的输入格式：
    1. 完整路径: data/input/INTC_i_20250103.json
    2. 相对路径: INTC_i_20250103.json
    3. 无后缀: INTC_i_20250103
    4. 模糊匹配: symbol_i_datetime (自动查找最新)
    
    Args:
        input_arg: 用户输入的文件路径/名称
        symbol: 股票代码（用于模糊匹配）
        
    Returns:
        (resolved_path, error_message)
    """
    from loguru import logger
    
    # 1. 清理输入
    input_str = str(input_arg).strip()
    
    # 2. 如果是完整路径且存在，直接返回
    input_path = Path(input_str)
    if input_path.exists() and input_path.is_file():
        logger.debug(f"✅ 使用完整路径: {input_path}")
        return input_path, None
    
    # 3. 尝试添加 data/input/ 前缀
    if not input_str.startswith("data/input/"):
        input_str_with_prefix = f"data/input/{input_str}"
        
        # 3.1 尝试直接路径
        candidate = Path(input_str_with_prefix)
        if candidate.exists() and candidate.is_file():
            logger.debug(f"✅ 补全路径: {candidate}")
            return candidate, None
        
        # 3.2 尝试添加 .json 后缀
        if not input_str.endswith('.json'):
            candidate_with_ext = Path(f"{input_str_with_prefix}.json")
            if candidate_with_ext.exists() and candidate_with_ext.is_file():
                logger.debug(f"✅ 补全路径+后缀: {candidate_with_ext}")
                return candidate_with_ext, None
    
    # 4. 如果有 symbol，尝试模糊匹配（查找最新文件）
    if symbol:
        input_dir = Path("data/input")
        if input_dir.exists():
            # 构建匹配模式
            # 支持: symbol_i_* 或 *_i_* 格式
            pattern = f"{symbol.upper()}_i_*.json"
            
            matching_files = sorted(
                input_dir.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            if matching_files:
                latest_file = matching_files[0]
                logger.info(f"📂 自动匹配到最新文件: {latest_file.name}")
                return latest_file, None
    
    # 5. 所有尝试失败
    error_msg = f"未找到输入文件: {input_arg}"
    
    # 提供可能的文件列表
    input_dir = Path("data/input")
    if input_dir.exists():
        available = [f.name for f in input_dir.glob("*.json")][:5]
        if available:
            error_msg += f"\n💡 data/input/ 目录下的文件:\n   - " + "\n   - ".join(available)
    
    return None, error_msg