"""
缓存管理器
负责分析结果、快照的持久化
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from loguru import logger


class CacheManager:
    """缓存管理器"""
    
    def __init__(self, cache_dir: Path = Path("data/cache")):
        """
        初始化缓存管理器
        
        Args:
            cache_dir: 缓存目录
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def get_cache_file(self, symbol: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{symbol}_analysis.json"
    
    def load_cache(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        加载缓存
        
        Args:
            symbol: 股票代码
            
        Returns:
            缓存数据或 None
        """
        cache_file = self.get_cache_file(symbol)
        
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
        report: str
    ):
        """
        保存完整分析结果
        
        Args:
            symbol: 股票代码
            initial_data: 初始数据
            scenario: 场景分析
            strategies: 策略列表
            ranking: 策略排序
            report: 最终报告
        """
        cache_file = self.get_cache_file(symbol)
        
        # 加载现有缓存
        cached = self.load_cache(symbol)
        
        if not cached:
            cached = {
                "symbol": symbol,
                "created_at": datetime.now().isoformat(),
                "last_updated": None,
                "analysis": {},
                "greeks_snapshots": [],
                "backtest_records": []
            }
        
        # 更新分析结果
        cached["analysis"] = {
            "status": "completed",
            "initial_date": datetime.now().strftime("%Y-%m-%d"),
            "initial_spot": self._get_nested_value(initial_data, "targets.spot_price"),
            "scenario": scenario,
            "strategies": strategies,
            "ranking": ranking,
            "report": report
        }
        
        cached["last_updated"] = datetime.now().isoformat()
        
        # 保存首次快照
        if not cached["greeks_snapshots"]:
            snapshot = self._create_snapshot(
                snapshot_id=0,
                snapshot_type="initial_analysis",
                data=initial_data,
                note="完整分析"
            )
            cached["greeks_snapshots"].append(snapshot)
        
        # 保存缓存
        self._save_cache(cache_file, cached)
        logger.success(f"✅ 完整分析结果已保存: {cache_file}")
    
    def save_greeks_snapshot(
        self,
        symbol: str,
        data: Dict,
        note: str = ""
    ) -> Dict[str, Any]:
        """
        保存 Greeks 快照
        
        Args:
            symbol: 股票代码
            data: 完整数据
            note: 快照备注
            
        Returns:
            快照保存结果
        """
        cache_file = self.get_cache_file(symbol)
        
        # 加载现有缓存
        cached = self.load_cache(symbol)
        
        if not cached:
            cached = {
                "symbol": symbol,
                "created_at": datetime.now().isoformat(),
                "last_updated": None,
                "analysis": {},
                "greeks_snapshots": [],
                "backtest_records": []
            }
        
        # 获取上一次快照
        previous_snapshot = cached["greeks_snapshots"][-1] if cached["greeks_snapshots"] else None
        
        # 创建新快照
        snapshot_id = len(cached["greeks_snapshots"])
        new_snapshot = self._create_snapshot(
            snapshot_id=snapshot_id,
            snapshot_type="intraday_refresh" if snapshot_id > 0 else "initial_analysis",
            data=data,
            note=note
        )
        
        # 计算变化
        if previous_snapshot:
            new_snapshot["changes"] = self._calculate_snapshot_changes(
                previous_snapshot,
                new_snapshot
            )
        
        # 添加快照
        cached["greeks_snapshots"].append(new_snapshot)
        cached["last_updated"] = datetime.now().isoformat()
        
        # 保存缓存
        self._save_cache(cache_file, cached)
        logger.success(f"✅ 快照已保存: {cache_file}")
        
        return {
            "status": "success",
            "snapshot": new_snapshot,
            "cache_file": str(cache_file)
        }
    
    def get_snapshots(self, symbol: str) -> List[Dict[str, Any]]:
        """
        获取所有快照
        
        Args:
            symbol: 股票代码
            
        Returns:
            快照列表
        """
        cached = self.load_cache(symbol)
        
        if not cached:
            return []
        
        return cached.get("greeks_snapshots", [])
    
    def get_last_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取最后一次快照
        
        Args:
            symbol: 股票代码
            
        Returns:
            最后一次快照或 None
        """
        snapshots = self.get_snapshots(symbol)
        
        if not snapshots:
            return None
        
        return snapshots[-1]
    
    def add_backtest_record(self, symbol: str, record: Dict[str, Any]):
        """
        添加回测记录
        
        Args:
            symbol: 股票代码
            record: 回测记录
        """
        cache_file = self.get_cache_file(symbol)
        cached = self.load_cache(symbol)
        
        if not cached:
            logger.warning(f"未找到 {symbol} 的缓存，无法添加回测记录")
            return
        
        if "backtest_records" not in cached:
            cached["backtest_records"] = []
        
        record["timestamp"] = datetime.now().isoformat()
        cached["backtest_records"].append(record)
        
        self._save_cache(cache_file, cached)
        logger.info(f"✅ 回测记录已添加")
    
    def _create_snapshot(
        self,
        snapshot_id: int,
        snapshot_type: str,
        data: Dict,
        note: str = ""
    ) -> Dict[str, Any]:
        """创建快照对象"""
        targets = data.get("targets", {})
        
        return {
            "snapshot_id": snapshot_id,
            "type": snapshot_type,
            "timestamp": datetime.now().isoformat(),
            "note": note,
            "spot_price": targets.get("spot_price"),
            "em1_dollar": targets.get("em1_dollar"),
            "vol_trigger": self._get_nested_value(targets, "gamma_metrics.vol_trigger"),
            "spot_vs_trigger": self._get_nested_value(targets, "gamma_metrics.spot_vs_trigger"),
            "net_gex": self._get_nested_value(targets, "gamma_metrics.net_gex"),
            "call_wall": self._get_nested_value(targets, "walls.call_wall"),
            "put_wall": self._get_nested_value(targets, "walls.put_wall"),
            "iv_7d": self._get_nested_value(targets, "atm_iv.iv_7d"),
            "iv_14d": self._get_nested_value(targets, "atm_iv.iv_14d"),
            "data": data,
            "changes": None
        }
    
    def _calculate_snapshot_changes(
        self,
        old_snapshot: Dict,
        new_snapshot: Dict
    ) -> Optional[Dict[str, Any]]:
        """计算两次快照的变化"""
        changes = {}
        
        key_fields = [
            "spot_price", "em1_dollar", "vol_trigger",
            "call_wall", "put_wall", "net_gex",
            "iv_7d", "iv_14d"
        ]
        
        for field in key_fields:
            old_value = old_snapshot.get(field)
            new_value = new_snapshot.get(field)
            
            if old_value is None or new_value is None:
                continue
            
            if old_value == -999 or new_value == -999:
                continue
            
            if old_value != new_value:
                change_info = {
                    "old": old_value,
                    "new": new_value
                }
                
                # 计算百分比变化
                if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
                    if old_value != 0:
                        pct_change = ((new_value - old_value) / old_value) * 100
                        change_info["change_pct"] = round(pct_change, 2)
                
                changes[field] = change_info
        
        return changes if changes else None
    
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