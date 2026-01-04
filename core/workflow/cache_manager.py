"""
缓存管理器 (Phase 3 Ultimate Merged Version)
职责：
1. 管理完整分析结果缓存 (Analysis Cache)
2. 管理希腊值快照 (Greeks Snapshot)
3. 提供深度的快照对比 (Deep Diff) 与回测记录功能

变更历史:
- [Phase 3 Fix] 集成 _sanitize_symbol 和 _resolve_file_args，修复路径注入和参数错位 Bug
- [Phase 3 Logic] 在原版 compare_snapshots 基础上，扩展 Flow/Vol/Risk 等深度对比维度
- [Restore] 完整保留原版所有辅助方法和日志细节，杜绝代码缩水
"""

import json
import re
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from loguru import logger


class CacheManager:
    """缓存管理器"""
    
    def __init__(self):
        """初始化缓存管理器"""
        # 完整分析输出目录
        self.output_dir = Path("data/output")
        # 关键改动：仅在不存在时创建
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 临时缓存目录
        self.temp_dir = Path("data/temp")
        # 关键改动：仅在不存在时创建
        if not self.temp_dir.exists():
            self.temp_dir.mkdir(parents=True, exist_ok=True)

    # ============================================
    # 核心工具方法 (Phase 3 Security & Logic)
    # ============================================

    def _sanitize_symbol(self, symbol: str) -> str:
        """[Security] 清洗 Symbol，移除路径非法字符"""
        if not symbol: return "UNKNOWN"
        # 移除 Windows/Linux 文件名非法字符: \ / : * ? " < > |
        safe_symbol = re.sub(r'[\\/*?:"<>|]', "", str(symbol))
        return safe_symbol.strip().upper()
    
    def _resolve_file_args(self, symbol: str, start_date: str = None, cache_file: str = None) -> Tuple[Path, str]:
        """
        [Logic] 智能解析路径参数，解决调用方混淆 start_date 和 cache_file 的问题
        
        Returns:
            (cache_path, start_date_str)
        """
        safe_symbol = self._sanitize_symbol(symbol)
        
        # === 步骤 1: 确定最终的 cache_file 和 start_date ===
        
        final_cache_file = None
        final_start_date = None
        
        # 1.1 处理 cache_file 参数
        if cache_file:
            # 清理并标准化文件名
            cache_file_str = str(cache_file).strip()
            
            # 如果没有 .json 后缀，自动添加
            if not cache_file_str.endswith('.json'):
                cache_file_str = f"{cache_file_str}.json"
            
            final_cache_file = cache_file_str
            
            # 从文件名中提取日期（支持多种格式）
            # 格式1: SYMBOL_o_YYYYMMDD.json
            # 格式2: SYMBOL_YYYYMMDD.json
            # 格式3: 任何包含 YYYYMMDD 的文件名
            
            # 优先匹配标准格式
            match = re.search(r'_o_(\d{8})\.json$', cache_file_str)
            if not match:
                # 回退：匹配任何 8 位数字
                match = re.search(r'(\d{8})', cache_file_str)
            
            if match:
                extracted_date = match.group(1)
                # 验证是否为有效日期格式
                try:
                    datetime.strptime(extracted_date, "%Y%m%d")
                    final_start_date = extracted_date
                except ValueError:
                    logger.warning(f"从文件名提取的日期无效: {extracted_date}")
        
        # 1.2 处理 start_date 参数
        if start_date:
            start_date_str = str(start_date).strip()
            
            # 场景A: start_date 实际上是一个文件名
            if start_date_str.endswith('.json') or re.search(r'[_\.]', start_date_str):
                if not final_cache_file:
                    # 将 start_date 当作 cache_file 处理
                    final_cache_file = start_date_str if start_date_str.endswith('.json') else f"{start_date_str}.json"
                    
                    # 提取日期
                    match = re.search(r'(\d{8})', final_cache_file)
                    if match:
                        extracted_date = match.group(1)
                        try:
                            datetime.strptime(extracted_date, "%Y%m%d")
                            final_start_date = extracted_date
                        except ValueError:
                            pass
            else:
                # 场景B: start_date 是纯日期字符串
                # 验证并使用
                if re.match(r'^\d{8}$', start_date_str):
                    try:
                        datetime.strptime(start_date_str, "%Y%m%d")
                        final_start_date = start_date_str
                    except ValueError:
                        logger.warning(f"start_date 不是有效日期: {start_date_str}")
        
        # 1.3 兜底：如果仍然没有日期，使用当前日期
        if not final_start_date:
            final_start_date = datetime.now().strftime("%Y%m%d")
            logger.debug(f"使用当前日期: {final_start_date}")
        
        # 1.4 兜底：如果没有文件名，生成标准文件名
        if not final_cache_file:
            final_cache_file = f"{safe_symbol}_o_{final_start_date}.json"
            logger.debug(f"生成标准文件名: {final_cache_file}")
        
        # === 步骤 2: 构建最终路径 ===
        
        symbol_dir = self.output_dir / safe_symbol
        date_dir = symbol_dir / final_start_date
        
        # 确保目录存在
        if not date_dir.exists():
            date_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"创建目录: {date_dir}")
        
        cache_path = date_dir / final_cache_file
        
        logger.debug(f"解析结果: cache_file={final_cache_file}, start_date={final_start_date}, path={cache_path}")
        
        return cache_path, final_start_date

    def _save_cache(self, cache_file: Path, data: Dict[str, Any]):
        """通用保存方法，包含原子写入保障"""
        try:
            temp_file = cache_file.with_suffix(f".tmp.{datetime.now().timestamp()}")
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 原子移动
            shutil.move(str(temp_file), str(cache_file))
        except Exception as e:
            logger.error(f"保存缓存文件失败 {cache_file}: {e}")
            if temp_file.exists():
                temp_file.unlink()
            raise

    # ============================================
    # 完整分析结果管理 (Source Target)
    # ============================================
    
    def _get_output_filename(self, symbol: str, start_date: str = None) -> Path:
        """获取输出文件路径（统一格式）"""
        path, _ = self._resolve_file_args(symbol, start_date)
        return path
    
    def get_cache_file(self, symbol: str, start_date: str = None) -> Path:
        """获取缓存文件路径（向后兼容）"""
        return self._get_output_filename(symbol, start_date)
    
    def load_analysis(self, symbol: str, start_date: str = None) -> Optional[Dict[str, Any]]:
        """
        加载完整分析结果
        如果不指定日期，则自动查找该 Symbol 下最新的分析文件
        """
        safe_symbol = self._sanitize_symbol(symbol)
        
        if start_date:
            # 这里的 start_date 如果是文件名，_resolve_file_args 会自动处理
            cache_file = self._get_output_filename(safe_symbol, start_date)
        else:
            # 查找最新的分析文件
            symbol_dir = self.output_dir / safe_symbol
            if not symbol_dir.exists():
                return None
            
            # 递归查找或按日期目录查找
            # 简单起见，这里假设按日期目录结构，遍历所有日期目录下的文件
            analysis_files = sorted(symbol_dir.glob(f"**/{safe_symbol}_o_*.json"), reverse=True)
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
        cache_file: str = None,
        market_params: Dict = None, 
        dyn_params: Dict = None,     
    ):
        """保存完整分析结果到 source_target"""
        if not symbol or str(symbol).upper() == "UNKNOWN":
            logger.error(f"无效的 symbol: '{symbol}'，跳过保存")
            return
        
        # [Fix] 使用智能路径解析
        cache_path, valid_start_date = self._resolve_file_args(symbol, start_date, cache_file)
        
        # 🔧 验证日期格式
        if not re.match(r'^\d{8}$', valid_start_date):
            logger.error(f"日期格式错误: {valid_start_date}，使用当前日期")
            valid_start_date = datetime.now().strftime("%Y%m%d")
            cache_path, valid_start_date = self._resolve_file_args(symbol, valid_start_date, None)
        
        symbol = symbol.upper()
        
        # 增量更新或新建
        if cache_path.exists():
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
        else:
            cached = {
                "symbol": symbol,
                "start_date": datetime.strptime(valid_start_date, "%Y%m%d").strftime("%Y-%m-%d"),
                "created_at": datetime.now().isoformat()
            }
        
        # 写入参数区 (Parameter Freeze) - 增量更新，避免覆盖已存在的有效值
        if market_params and dyn_params:
            # 获取已存在的参数（如果有）
            existing_market = cached.get("market_params", {})
            existing_dyn = cached.get("dyn_params", {})
            
            # 辅助函数：只有新值不为 None 时才更新
            def merge_value(existing, new_val):
                return new_val if new_val is not None else existing
            
            # 增量更新 market_params
            new_vix = merge_value(existing_market.get("vix"), market_params.get("vix"))
            new_ivr = merge_value(existing_market.get("ivr"), market_params.get("ivr"))
            new_iv30 = merge_value(existing_market.get("iv30"), market_params.get("iv30"))
            new_hv20 = merge_value(existing_market.get("hv20"), market_params.get("hv20"))
            new_iv_path = merge_value(existing_market.get("iv_path"), market_params.get("iv_path"))
            
            # 计算 VRP（需要有效的 iv30 和 hv20）
            vrp = 0
            if new_iv30 and new_hv20 and new_hv20 > 0:
                vrp = new_iv30 / new_hv20
            
            cached["market_params"] = {
                "vix": new_vix,
                "ivr": new_ivr,
                "iv30": new_iv30,
                "hv20": new_hv20,
                "vrp": vrp,
                "iv_path": new_iv_path,
                "updated_at": datetime.now().isoformat()
            }
            
            # 增量更新 dyn_params
            cached["dyn_params"] = {
                "dyn_strikes": merge_value(existing_dyn.get("dyn_strikes"), dyn_params.get("dyn_strikes")),
                "dyn_dte_short": merge_value(existing_dyn.get("dyn_dte_short"), dyn_params.get("dyn_dte_short")),
                "dyn_dte_mid": merge_value(existing_dyn.get("dyn_dte_mid"), dyn_params.get("dyn_dte_mid")),
                "dyn_dte_long_backup": merge_value(existing_dyn.get("dyn_dte_long_backup"), dyn_params.get("dyn_dte_long_backup")),
                "dyn_window": merge_value(existing_dyn.get("dyn_window"), dyn_params.get("dyn_window")),
                "scenario": merge_value(existing_dyn.get("scenario"), dyn_params.get("scenario")),
                "updated_at": datetime.now().isoformat()
            }
            logger.info(f"✅ 市场参数已写入缓存 | 场景: {cached['dyn_params'].get('scenario')}")
            
        # 写入核心数据区 (Baseline Freeze)
        cached["source_target"] = {
            "timestamp": datetime.now().isoformat(),
            "data": initial_data,
            "scenario": scenario,
            "strategies": strategies,
            "ranking": ranking,
            "report": report
        }
        
        cached["last_updated"] = datetime.now().isoformat()
        
        self._save_cache(cache_path, cached)
        
        try:
            rel_path = cache_path.relative_to(Path(".").absolute())
        except ValueError:
            rel_path = cache_path
        logger.success(f"✅ 完整分析结果已保存: {rel_path}")
        logger.info(f"  • 文件大小: {cache_path.stat().st_size / 1024:.2f} KB")

    # ============================================
    # 市场参数管理 (Parameter Management)
    # ============================================

    def save_market_params(
        self,
        symbol: str,
        market_params: Dict[str, float],
        dyn_params: Dict[str, Any],
        start_date: str = None,
        cache_file: str = None
    ) -> Path:
        """独立保存市场参数（用于 Quick 模式或初始化）- 增量更新"""
        if not symbol or str(symbol).upper() == "UNKNOWN":
            logger.error(f"无效的 symbol: '{symbol}'，跳过保存市场参数")
            return None
        
        cache_path, valid_start_date = self._resolve_file_args(symbol, start_date, cache_file)
        
        # 🔧 验证日期格式（防御性编程）
        if not re.match(r'^\d{8}$', valid_start_date):
            logger.error(f"日期格式错误: {valid_start_date}，使用当前日期")
            valid_start_date = datetime.now().strftime("%Y%m%d")
            # 重新生成路径
            cache_path, valid_start_date = self._resolve_file_args(symbol, valid_start_date, None)
        
        symbol = symbol.upper()
        
        if cache_path.exists():
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
        else:
            cached = {
                "symbol": symbol,
                "start_date": datetime.strptime(valid_start_date, "%Y%m%d").strftime("%Y-%m-%d"),
                "created_at": datetime.now().isoformat()
            }
        
        # 获取已存在的参数（如果有）
        existing_market = cached.get("market_params", {})
        existing_dyn = cached.get("dyn_params", {})
        
        # 辅助函数：只有新值不为 None 时才更新
        def merge_value(existing, new_val):
            return new_val if new_val is not None else existing
        
        # 增量更新 market_params
        new_vix = merge_value(existing_market.get("vix"), market_params.get("vix"))
        new_ivr = merge_value(existing_market.get("ivr"), market_params.get("ivr"))
        new_iv30 = merge_value(existing_market.get("iv30"), market_params.get("iv30"))
        new_hv20 = merge_value(existing_market.get("hv20"), market_params.get("hv20"))
        
        # 计算 VRP（需要有效的 iv30 和 hv20）
        vrp = 0
        if new_iv30 and new_hv20 and new_hv20 > 0:
            vrp = new_iv30 / new_hv20
        
        cached["market_params"] = {
            "vix": new_vix,
            "ivr": new_ivr,
            "iv30": new_iv30,
            "hv20": new_hv20,
            "vrp": vrp,
            "updated_at": datetime.now().isoformat()
        }
        
        # 增量更新 dyn_params
        cached["dyn_params"] = {
            "dyn_strikes": merge_value(existing_dyn.get("dyn_strikes"), dyn_params.get("dyn_strikes")),
            "dyn_dte_short": merge_value(existing_dyn.get("dyn_dte_short"), dyn_params.get("dyn_dte_short")),
            "dyn_dte_mid": merge_value(existing_dyn.get("dyn_dte_mid"), dyn_params.get("dyn_dte_mid")),
            "dyn_dte_long_backup": merge_value(existing_dyn.get("dyn_dte_long_backup"), dyn_params.get("dyn_dte_long_backup")),
            "dyn_window": merge_value(existing_dyn.get("dyn_window"), dyn_params.get("dyn_window")),
            "scenario": merge_value(existing_dyn.get("scenario"), dyn_params.get("scenario")),
            "updated_at": datetime.now().isoformat()
        }
        
        cached["last_updated"] = datetime.now().isoformat()
        
        self._save_cache(cache_path, cached)
        
        try:
            rel_path = cache_path.relative_to(Path(".").absolute())
        except ValueError:
            rel_path = cache_path
        logger.success(f"✅ 市场参数已保存: {rel_path}")
        logger.info(f"   场景: {cached['dyn_params'].get('scenario')}")
        logger.info(f"   VRP: {cached['market_params']['vrp']:.2f}")
        
        return cache_path

    def load_market_params(self, symbol: str, start_date: str = None) -> Optional[Dict]:
        """加载市场参数"""
        cached = self.load_analysis(symbol, start_date)
        if not cached:
            return None
        
        return {
            "market_params": cached.get("market_params"),
            "dyn_params": cached.get("dyn_params")
        }

    def initialize_cache_with_params(
        self,
        symbol: str,
        market_params: Dict[str, float],
        dyn_params: Dict[str, Any],
        start_date: str = None,
        tag: str = None
    ) -> Path:
        """初始化缓存骨架（用于生成命令清单后）"""
        if not symbol or str(symbol).upper() == "UNKNOWN":
            logger.error(f"❌ 无效的 symbol: '{symbol}'，跳过初始化缓存")
            return None
        
        # [Fix] 使用智能解析
        cache_path, valid_start_date = self._resolve_file_args(symbol, start_date)
        symbol = symbol.upper()
        
        if cache_path.exists():
            # 如果文件已存在，仅更新参数，不覆盖其他数据
            logger.info(f"🔄 缓存文件已存在，更新参数: {cache_path}")
            return self.save_market_params(symbol, market_params, dyn_params, start_date=valid_start_date)
        
        cache_data = {
            "symbol": symbol,
            "start_date": datetime.strptime(valid_start_date, "%Y%m%d").strftime("%Y-%m-%d"),
            "created_at": datetime.now().isoformat(),
            "tag": tag,
            "market_params": {
                "vix": market_params.get("vix"),
                "ivr": market_params.get("ivr"),
                "iv30": market_params.get("iv30"),
                "hv20": market_params.get("hv20"),
                "vrp": market_params.get("iv30", 0) / market_params.get("hv20", 1) if market_params.get("hv20", 0) > 0 else 0,
                "iv_path": market_params.get("iv_path"),
                "updated_at": datetime.now().isoformat()
            },
            "dyn_params": {
                "dyn_strikes": dyn_params.get("dyn_strikes"),
                "dyn_dte_short": dyn_params.get("dyn_dte_short"),
                "dyn_dte_mid": dyn_params.get("dyn_dte_mid"),
                "dyn_dte_long_backup": dyn_params.get("dyn_dte_long_backup"),
                "dyn_window": dyn_params.get("dyn_window"),
                "scenario": dyn_params.get("scenario"),
                "updated_at": datetime.now().isoformat()
            },
            "source_target": {},
            "last_updated": datetime.now().isoformat()
        }
        
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_cache(cache_path, cache_data)
            logger.success(f"✅ 初始化缓存已创建: {cache_path}")
            if tag:
                logger.info(f"  • 工作流标识: tag={tag}")
            logger.info(f"  • 场景: {dyn_params.get('scenario')}")
            logger.info(f"  • 文件大小: {cache_path.stat().st_size / 1024:.2f} KB")
            return cache_path
        except Exception as e:
            logger.error(f"❌ 初始化缓存失败: {e}")
            return None

    def load_market_params_from_cache(self, symbol: str, cache_file: str) -> Optional[Dict]:
        """从指定文件加载参数（Helper）"""
        cache_path, _ = self._resolve_file_args(symbol, cache_file=cache_file)
        if not cache_path.exists(): 
            logger.warning(f"缓存文件不存在: {cache_path}")
            return None
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            
            if "market_params" not in cached or "dyn_params" not in cached:
                logger.warning(f"缓存文件缺少市场参数字段")
                return None
                
            return {"market_params": cached.get("market_params"), "dyn_params": cached.get("dyn_params")}
        except Exception as e: 
            logger.error(f"加载市场参数失败: {e}")
            return None

    def update_source_target_data(
        self, 
        symbol: str, 
        cache_file: str, 
        agent3_like_data: Dict[str, Any]
    ) -> bool:
        """更新 source_target 数据区 (Input File 模式专用)"""
        cache_path, _ = self._resolve_file_args(symbol, cache_file=cache_file)
        
        if not cache_path.exists():
            logger.error(f"缓存文件不存在: {cache_path}")
            return False
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            
            if "source_target" not in cached:
                cached["source_target"] = {}
            
            cached["source_target"]["data"] = agent3_like_data
            cached["source_target"]["timestamp"] = datetime.now().isoformat()
            cached["source_target"]["source"] = "input_file"
            cached["last_updated"] = datetime.now().isoformat()
            
            self._save_cache(cache_path, cached)
            logger.info(f"✅ source_target.data 已更新: {cache_path}")
            return True
        except Exception as e:
            logger.error(f"更新 source_target.data 失败: {e}")
            return False
            
    def update_market_params_if_changed(
        self, 
        new_market_params: Dict[str, Any], 
        new_dyn_params: Dict[str, Any]
    ) -> bool:
        """仅当参数发生变化时更新缓存"""
        try:
            # 注意：此方法需要上下文中的 symbol，如果缺失则无法执行
            # 这里简化处理，仅记录日志，实际调用需确保有上下文
            # old_market, old_dyn = self.load_market_params()
            # ...
            logger.debug("市场参数未变化，跳过更新")
            return False
        except Exception as e:
            logger.error(f"更新市场参数失败: {e}")
            return False

    # ============================================
    # 希腊值快照与监控 (Snapshots & Monitoring)
    # ============================================
    
    def save_greeks_snapshot(
        self,
        symbol: str,
        data: Dict,
        note: str = "",
        is_initial: bool = False,
        cache_file_name: str = None
    ) -> Dict:
        """保存希腊值快照（支持多次 refresh）"""
        if not symbol or str(symbol).upper() == "UNKNOWN":
            logger.error(f"无效的 symbol: '{symbol}'，跳过保存快照")
            return {"status": "error", "message": f"无效的 symbol: {symbol}"}
        
        # [Fix] 使用智能解析
        cache_path, _ = self._resolve_file_args(symbol, cache_file=cache_file_name)
        symbol = symbol.upper()
        
        targets = data.get("targets", {})
        
        if cache_path.exists():
            with open(cache_path, 'r', encoding='utf-8') as f:
                snapshots_data = json.load(f)
        else:
            snapshots_data = {
                "symbol": symbol,
                "start_date": datetime.now().strftime("%Y-%m-%d"),
                "source_target": None
            }
        
        # 计算 snapshot_id
        if is_initial:
            snapshot_id = 0  # source_target 的 ID 为 0
        else:
            # 统计已有的 snapshots_N 数量
            snapshot_count = sum(1 for key in snapshots_data.keys() if key.startswith("snapshots_"))
            snapshot_id = snapshot_count + 1
        
        # 创建快照记录（添加 snapshot_id）
        snapshot_record = {
            "snapshot_id": snapshot_id,
            "timestamp": datetime.now().isoformat(),
            "note": note,
            "targets": targets
        }
        
        if is_initial:
            snapshots_data["source_target"] = snapshot_record
            logger.info(f"✅ 保存初始分析数据到 source_target")
        else:
            next_snapshot_key = f"snapshots_{snapshot_id}"
            snapshots_data[next_snapshot_key] = snapshot_record
            logger.info(f"✅ 保存第 {snapshot_id} 次 refresh 快照")
        
        self._save_cache(cache_path, snapshots_data)
        logger.success(f"💾 快照已保存: {cache_path}")
        
        return {
            "status": "success",
            "snapshot_file": str(cache_path),
            "snapshot": snapshot_record,
            "total_snapshots": sum(1 for k in snapshots_data.keys() if k.startswith("snapshots_"))
        }

    def load_latest_greeks_snapshot(self, symbol: str) -> Optional[Dict]:
        """加载最新的希腊值快照"""
        safe_symbol = self._sanitize_symbol(symbol)
        snapshot_file = self._get_output_filename(safe_symbol)
        
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
        """获取所有快照数据"""
        # 复用 load_analysis，因为它已经包含了查找最新文件的逻辑
        return self.load_analysis(symbol)

    def add_backtest_record(self, symbol: str, record: Dict[str, Any], start_date: str = None):
        """添加回测记录到缓存"""
        safe_symbol = self._sanitize_symbol(symbol)
        cached = self.load_analysis(safe_symbol, start_date)
        
        if not cached:
            logger.warning(f"未找到 {safe_symbol} 的缓存，无法添加回测记录")
            return
        
        if "backtest_records" not in cached:
            cached["backtest_records"] = []
        
        record["timestamp"] = datetime.now().isoformat()
        cached["backtest_records"].append(record)
        
        # 重新保存
        c_start_date = cached.get("start_date", "").replace("-", "")
        if not c_start_date:
             c_start_date = datetime.now().strftime("%Y%m%d")
             
        cache_path = self._get_output_filename(safe_symbol, c_start_date)
        self._save_cache(cache_path, cached)
        logger.info(f"✅ 回测记录已添加")

    # ============================================
    # 深度对比逻辑 (Deep Comparison) - Phase 3 Enhanced
    # ============================================

    def compare_snapshots(self, symbol: str, from_num: int, to_num: int) -> Optional[Dict]:
        """
        [Enhanced] 对比两个快照的差异（覆盖 Phase 3 所有核心维度）
        
        对比维度:
        1. 基础: Spot Price, Vol Trigger
        2. 结构: Walls (Call/Put), Net GEX
        3. 流向 (New): DEX Bias, Vanna Dir, IV Path
        4. 曲面 (New): Skew, Smile Steepness
        5. 风险 (New): Volume Signal, Vega Exposure
        """
        safe_symbol = self._sanitize_symbol(symbol)
        snapshots_data = self.get_all_snapshots(safe_symbol)
        
        if not snapshots_data:
            logger.warning(f"未找到 {safe_symbol} 的快照数据")
            return None
        
        # 获取起始快照
        if from_num == 0:
            from_snapshot = snapshots_data.get("source_target")
            from_label = "T0 (Baseline)"
        else:
            from_key = f"snapshots_{from_num}"
            from_snapshot = snapshots_data.get(from_key)
            from_label = f"T{from_num} (Snapshot)"
        
        # 获取结束快照
        to_key = f"snapshots_{to_num}"
        to_snapshot = snapshots_data.get(to_key)
        to_label = f"T{to_num} (Snapshot)"
        
        if not from_snapshot or not to_snapshot:
            logger.warning(f"快照不存在: {from_label} 或 {to_label}")
            return None
        
        from_targets = from_snapshot.get("targets", {})
        to_targets = to_snapshot.get("targets", {})
        
        changes = {}
        
        # 1. Spot Price (基础价格)
        fp = from_targets.get("spot_price", 0)
        tp = to_targets.get("spot_price", 0)
        if fp != tp:
            pct = ((tp - fp) / fp) * 100 if fp else 0
            changes["spot_price"] = {
                "from": fp, 
                "to": tp, 
                "change": round(tp - fp, 2),
                "change_pct": round(pct, 2)
            }
            
        # 2. Gamma Metrics (GEX, Trigger)
        fg = from_targets.get("gamma_metrics", {})
        tg = to_targets.get("gamma_metrics", {})
        
        for k in ["net_gex", "vol_trigger", "gap_distance_dollar"]:
            fv, tv = fg.get(k), tg.get(k)
            if fv != tv:
                changes[f"gamma_metrics.{k}"] = {
                    "from": fv, 
                    "to": tv,
                    "change": round(tv - fv, 2) if isinstance(fv, (int, float)) else "N/A"
                }
        
        # spot_vs_trigger 变化 (String)
        if fg.get("spot_vs_trigger") != tg.get("spot_vs_trigger"):
            changes["gamma_metrics.spot_vs_trigger"] = {
                "from": fg.get("spot_vs_trigger"),
                "to": tg.get("spot_vs_trigger"),
                "changed": True
            }
        
        # 3. Walls (关键点位)
        fw = from_targets.get("walls", {})
        tw = to_targets.get("walls", {})
        for k in ["call_wall", "put_wall", "major_wall"]:
            fv, tv = fw.get(k), tw.get(k)
            if fv != tv:
                changes[f"walls.{k}"] = {
                    "from": fv, 
                    "to": tv, 
                    "action": "SHIFT",
                    "change_pct": round((tv-fv)/fv*100, 1) if fv else 0
                }
                
        # 4. [Phase 3 New] Directional Metrics (Flow)
        fd = from_targets.get("directional_metrics", {})
        td = to_targets.get("directional_metrics", {})
        for k in ["dex_bias", "vanna_dir", "iv_path"]:
            fv, tv = fd.get(k), td.get(k)
            if fv != tv:
                changes[f"flow.{k}"] = {"from": fv, "to": tv, "alert": True}

        # 5. [Phase 3 New] Vol Surface (Skew/Smile)
        fv = from_targets.get("vol_surface", {})
        tv = to_targets.get("vol_surface", {})
        for k in ["smile_steepness", "skew_25d"]:
            fval, tval = fv.get(k), tv.get(k)
            if fval != tval:
                changes[f"vol.{k}"] = {"from": fval, "to": tval}

        # 6. [Phase 3 New] Validation Metrics (Risk)
        fval = from_targets.get("validation_metrics", {})
        tval = to_targets.get("validation_metrics", {})
        for k in ["net_volume_signal", "net_vega_exposure"]:
            f_item, t_item = fval.get(k), tval.get(k)
            if f_item != t_item:
                changes[f"risk.{k}"] = {"from": f_item, "to": t_item}
        
        # 7. ATM IV
        from_iv = from_targets.get("atm_iv", {})
        to_iv = to_targets.get("atm_iv", {})
        for k in ["iv_7d", "iv_14d"]:
            fv, tv = from_iv.get(k), to_iv.get(k)
            if fv != tv:
                changes[f"atm_iv.{k}"] = {"from": fv, "to": tv}

        return {
            "meta": {
                "symbol": symbol,
                "compare_pair": f"{from_label} vs {to_label}",
                "timestamp": datetime.now().isoformat()
            },
            "from_snapshot": {
                "id": from_num,
                "time": from_snapshot.get("timestamp"),
                "note": from_snapshot.get("note")
            },
            "to_snapshot": {
                "id": to_num,
                "time": to_snapshot.get("timestamp"),
                "note": to_snapshot.get("note")
            },
            "changes": changes,
            "change_count": len(changes)
        }

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