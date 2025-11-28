"""
缓存管理器（重构版）
职责：
1. 管理完整分析结果缓存
2. 管理希腊值快照（支持多次 refresh）
3. 快照对比功能
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from loguru import logger
import re


class CacheManager:
    """缓存管理器（重构版）"""
    
    def __init__(self):
        """初始化缓存管理器"""
        # 完整分析输出目录
        self.output_dir = Path("data/output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 临时缓存目录
        self.temp_dir = Path("data/temp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    # ============================================
    # 完整分析结果缓存
    # ============================================
    
    def _get_output_filename(self, symbol: str, start_date: str = None) -> Path:
        """
        获取输出文件路径
        
        格式：data/output/{SYMBOL}/{SYMBOL}_{start_date}.json
        
        Args:
            symbol: 股票代码
            start_date: 分析开始日期（YYYYMMDD），不指定则使用今天
            
        Returns:
            输出文件路径
        """
        if not start_date:
            start_date = datetime.now().strftime("%Y%m%d")
        
        symbol_dir = self.output_dir / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)
        
        return symbol_dir / f"{symbol}_{start_date}.json"
    
    def get_cache_file(self, symbol: str, start_date: str = None) -> Path:
        """获取缓存文件路径（向后兼容）"""
        return self._get_output_filename(symbol, start_date)
    
    def load_analysis(self, symbol: str, start_date: str = None) -> Optional[Dict[str, Any]]:
        """
        加载完整分析结果
        
        Args:
            symbol: 股票代码
            start_date: 分析开始日期（YYYYMMDD），不指定则查找最新
            
        Returns:
            缓存数据或 None
        """
        if start_date:
            # 加载指定日期的分析
            cache_file = self._get_output_filename(symbol, start_date)
        else:
            # 查找最新的分析文件
            symbol_dir = self.output_dir / symbol
            if not symbol_dir.exists():
                return None
            
            analysis_files = sorted(symbol_dir.glob(f"{symbol}_*.json"), reverse=True)
            if not analysis_files:
                return None
            
            cache_file = analysis_files[0]
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载缓存失败: {e}")
            return None
    
    def save_complete_analysis(
        self,
        symbol: str,
        initial_data: Dict,
        scenario: Dict,
        strategies: Dict,
        ranking: Dict,
        report: str,
        start_date: str = None,
        cache_file: str = None  # ⭐ 新增：支持指定缓存文件
    ):
        """
        保存完整分析结果到 source_target
        
        Args:
            symbol: 股票代码
            initial_data: 初始数据（计算后的完整数据）
            scenario: 场景分析
            strategies: 策略列表
            ranking: 策略排序
            report: 最终报告
            start_date: 分析开始日期（YYYYMMDD）
            cache_file: 指定缓存文件名（如 NVDA_20251127.json）
        """
        if not start_date:
            start_date = datetime.now().strftime("%Y%m%d")
        
        # ⭐ 支持指定缓存文件
        if cache_file:
            # 从文件名提取 start_date
            match = re.match(r'(\w+)_(\d{8})\.json', cache_file)
            if match:
                start_date = match.group(2)
            cache_path = self.output_dir / symbol / cache_file
        else:
            cache_path = self._get_output_filename(symbol, start_date)
        
        # 加载现有缓存
        if cache_path.exists():
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
        else:
            # 创建新缓存
            cached = {
                "symbol": symbol,
                "start_date": datetime.strptime(start_date, "%Y%m%d").strftime("%Y-%m-%d"),
                "created_at": datetime.now().isoformat()
            }
        
        # ⭐ 写入 source_target（计算后的完整数据 + scenario）
        cached["source_target"] = {
            "timestamp": datetime.now().isoformat(),
            "data": initial_data,  # 包含 23个原始字段 + 3个计算字段
            "scenario": scenario,
            "strategies": strategies,
            "ranking": ranking,
            "report": report
        }
        
        cached["last_updated"] = datetime.now().isoformat()
        
        # 保存缓存
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._save_cache(cache_path, cached)
        logger.success(f"✅ 完整分析结果已保存: {cache_path}")
    
    def add_backtest_record(self, symbol: str, record: Dict[str, Any], start_date: str = None):
        """
        添加回测记录
        
        Args:
            symbol: 股票代码
            record: 回测记录
            start_date: 分析开始日期
        """
        cached = self.load_analysis(symbol, start_date)
        
        if not cached:
            logger.warning(f"未找到 {symbol} 的缓存，无法添加回测记录")
            return
        
        if "backtest_records" not in cached:
            cached["backtest_records"] = []
        
        record["timestamp"] = datetime.now().isoformat()
        cached["backtest_records"].append(record)
        
        cache_file = self._get_output_filename(symbol, cached.get("start_date"))
        self._save_cache(cache_file, cached)
        logger.info(f"✅ 回测记录已添加")
    
    # ============================================
    # 希腊值快照管理（refresh 快照）
    # ============================================
    
    def save_greeks_snapshot(
        self,
        symbol: str,
        data: Dict,
        note: str = "",
        is_initial: bool = False,
        cache_file_name: str = None
    ) -> Dict:
        """
        保存希腊值快照（支持多次 refresh）
        
        数据格式：
        {
            "start_date": "2025-11-27",
            "source_target": {...},  # 最初的完整数据
            "snapshots_1": {...},    # 第1次 refresh
            "snapshots_2": {...},    # 第2次 refresh
            ...
        }
        
        Args:
            symbol: 股票代码
            data: 完整数据
            note: 备注
            is_initial: 是否为初始分析（source_target）
            cache_file_name: 缓存文件名（如 NVDA_20251127.json）
            
        Returns:
            保存结果
        """
        # 确定快照文件路径
        if cache_file_name:
            # 使用指定的缓存文件名
            snapshot_file = self._get_output_filename(
                symbol, 
                cache_file_name.replace(f"{symbol}_", "").replace(".json", "")
            )
        else:
            # 使用当前日期
            snapshot_file = self._get_output_filename(symbol)
        
        # 提取 targets 数据
        targets = data.get("targets", {})
        
        # 创建快照记录
        snapshot_record = {
            "timestamp": datetime.now().isoformat(),
            "note": note,
            "targets": targets
        }
        
        # 读取现有快照文件
        if snapshot_file.exists():
            with open(snapshot_file, 'r', encoding='utf-8') as f:
                snapshots_data = json.load(f)
        else:
            # 首次创建
            snapshots_data = {
                "symbol": symbol,
                "start_date": datetime.now().strftime("%Y-%m-%d"),
                "source_target": None
            }
        
        if is_initial:
            # 保存初始数据到 source_target
            snapshots_data["source_target"] = snapshot_record
            logger.info(f"✅ 保存初始分析数据到 source_target")
        else:
            # 计算 refresh 次数
            snapshot_count = sum(1 for key in snapshots_data.keys() if key.startswith("snapshots_"))
            next_snapshot_key = f"snapshots_{snapshot_count + 1}"
            
            snapshots_data[next_snapshot_key] = snapshot_record
            logger.info(f"✅ 保存第 {snapshot_count + 1} 次 refresh 快照")
        
        # 保存文件
        with open(snapshot_file, 'w', encoding='utf-8') as f:
            json.dump(snapshots_data, f, ensure_ascii=False, indent=2)
        
        logger.success(f"💾 快照已保存: {snapshot_file}")
        
        return {
            "status": "success",
            "snapshot_file": str(snapshot_file),
            "snapshot": snapshot_record,
            "total_snapshots": sum(1 for k in snapshots_data.keys() if k.startswith("snapshots_"))
        }
    
    def load_latest_greeks_snapshot(self, symbol: str) -> Optional[Dict]:
        """
        加载最新的希腊值快照
        
        Args:
            symbol: 股票代码
            
        Returns:
            最新快照数据，如果不存在返回 None
        """
        snapshot_file = self._get_snapshot_filename(symbol)
        
        if not snapshot_file.exists():
            logger.warning(f"未找到快照文件: {snapshot_file}")
            return None
        
        with open(snapshot_file, 'r', encoding='utf-8') as f:
            snapshots_data = json.load(f)
        
        # 获取最新的快照
        snapshot_keys = [k for k in snapshots_data.keys() if k.startswith("snapshots_")]
        
        if not snapshot_keys:
            # 如果没有 refresh 快照，返回 source_target
            return snapshots_data.get("source_target")
        
        # 返回最后一个快照
        latest_key = sorted(snapshot_keys, key=lambda x: int(x.split("_")[1]))[-1]
        return snapshots_data[latest_key]
    
    def get_all_snapshots(self, symbol: str) -> Optional[Dict]:
        """
        获取所有快照数据
        
        Args:
            symbol: 股票代码
            
        Returns:
            完整的快照文件内容
        """
        snapshot_file = self._get_snapshot_filename(symbol)
        
        if not snapshot_file.exists():
            return None
        
        with open(snapshot_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    # ============================================
    # 快照对比功能
    # ============================================
    
    def compare_snapshots(self, symbol: str, from_num: int, to_num: int) -> Optional[Dict]:
        """
        对比两个快照的差异
        
        Args:
            symbol: 股票代码
            from_num: 起始快照编号（0 表示 source_target）
            to_num: 结束快照编号
            
        Returns:
            对比结果字典
        """
        snapshots_data = self.get_all_snapshots(symbol)
        
        if not snapshots_data:
            logger.warning(f"未找到 {symbol} 的快照数据")
            return None
        
        # 获取起始快照
        if from_num == 0:
            from_snapshot = snapshots_data.get("source_target")
            from_label = "source_target"
        else:
            from_key = f"snapshots_{from_num}"
            from_snapshot = snapshots_data.get(from_key)
            from_label = f"快照 #{from_num}"
        
        # 获取结束快照
        to_key = f"snapshots_{to_num}"
        to_snapshot = snapshots_data.get(to_key)
        to_label = f"快照 #{to_num}"
        
        if not from_snapshot or not to_snapshot:
            logger.warning(f"快照不存在: {from_label} 或 {to_label}")
            return None
        
        # 提取 targets 数据
        from_targets = from_snapshot.get("targets", {})
        to_targets = to_snapshot.get("targets", {})
        
        # 对比关键字段
        changes = {}
        
        # 1. spot_price
        from_price = from_targets.get("spot_price")
        to_price = to_targets.get("spot_price")
        if from_price and to_price and from_price != to_price:
            change_pct = ((to_price - from_price) / from_price) * 100
            changes["spot_price"] = {
                "from": from_price,
                "to": to_price,
                "change": round(to_price - from_price, 2),
                "change_pct": round(change_pct, 2)
            }
        
        # 2. gamma_metrics
        from_gamma = from_targets.get("gamma_metrics", {})
        to_gamma = to_targets.get("gamma_metrics", {})
        
        for field in ["net_gex", "vol_trigger", "gap_distance_dollar"]:
            from_val = from_gamma.get(field)
            to_val = to_gamma.get(field)
            if from_val and to_val and from_val != to_val:
                change_pct = ((to_val - from_val) / from_val) * 100 if from_val != 0 else 0
                changes[f"gamma_metrics.{field}"] = {
                    "from": from_val,
                    "to": to_val,
                    "change": round(to_val - from_val, 2),
                    "change_pct": round(change_pct, 2)
                }
        
        # spot_vs_trigger 变化（字符串）
        from_trigger = from_gamma.get("spot_vs_trigger")
        to_trigger = to_gamma.get("spot_vs_trigger")
        if from_trigger != to_trigger:
            changes["gamma_metrics.spot_vs_trigger"] = {
                "from": from_trigger,
                "to": to_trigger,
                "changed": True
            }
        
        # 3. walls
        from_walls = from_targets.get("walls", {})
        to_walls = to_targets.get("walls", {})
        
        for field in ["call_wall", "put_wall", "major_wall"]:
            from_val = from_walls.get(field)
            to_val = to_walls.get(field)
            if from_val and to_val and from_val != to_val:
                change_pct = ((to_val - from_val) / from_val) * 100 if from_val != 0 else 0
                changes[f"walls.{field}"] = {
                    "from": from_val,
                    "to": to_val,
                    "change": round(to_val - from_val, 2),
                    "change_pct": round(change_pct, 2)
                }
        
        # 4. atm_iv
        from_iv = from_targets.get("atm_iv", {})
        to_iv = to_targets.get("atm_iv", {})
        
        for field in ["iv_7d", "iv_14d"]:
            from_val = from_iv.get(field)
            to_val = to_iv.get(field)
            if from_val and to_val and from_val != to_val:
                change_pct = ((to_val - from_val) / from_val) * 100 if from_val != 0 else 0
                changes[f"atm_iv.{field}"] = {
                    "from": from_val,
                    "to": to_val,
                    "change": round(to_val - from_val, 2),
                    "change_pct": round(change_pct, 2)
                }
        
        return {
            "from_snapshot": {
                "label": from_label,
                "timestamp": from_snapshot.get("timestamp"),
                "note": from_snapshot.get("note")
            },
            "to_snapshot": {
                "label": to_label,
                "timestamp": to_snapshot.get("timestamp"),
                "note": to_snapshot.get("note")
            },
            "changes": changes,
            "total_changes": len(changes)
        }
    
    # ============================================
    # 辅助方法
    # ============================================
    
    def _save_cache(self, cache_file: Path, data: Dict[str, Any]):
        """保存缓存到文件"""
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    @staticmethod
    def _get_nested_value(data: Dict, path: str):
        """获取嵌套字段值（支持点号路径）"""
        keys = path.split('.')
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value if value != -999 else None