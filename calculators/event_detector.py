"""
事件检测引擎 - CODE1
检测 FOMC、OPEX、财报等重大事件
"""

import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from utils.logger import setup_logger

logger = setup_logger(__name__)


class EventDetector:
    """事件检测引擎"""
    
    def __init__(self, config):
        self.config = config
        # 财报缓存 (在工作流生命周期内保持)
        self._earnings_cache = {}
    
    def detect(self, user_query: str, current_date: Optional[datetime] = None) -> Dict:
        """
        检测事件主函数
        
        Args:
            user_query: 用户输入 (包含股票代码)
            current_date: 当前日期 (默认为今天)
        
        Returns:
            事件检测结果
        """
        if current_date is None:
            current_date = datetime.now()
        
        # 提取股票代码
        symbol = self._extract_symbol(user_query)
        
        logger.info(f"开始事件检测: {symbol}, 日期: {current_date.strftime('%Y-%m-%d')}")
        
        events = []
        recommendations = {
            "no_cross_earnings": False,
            "adjust_dte": False,
            "reduce_position_size": False,
            "max_dte_suggestion": None,
            "note": "",
            "api_status": "enabled" if self.config.ENABLE_EARNINGS_API else "disabled"
        }
        
        # === 1. OPEX 检测 ===
        opex_event = self._detect_opex(current_date)
        if opex_event:
            events.append(opex_event)
            days_to_opex = opex_event["days_away"]
            if 0 <= days_to_opex <= 7:
                recommendations["adjust_dte"] = True
                recommendations["max_dte_suggestion"] = max(days_to_opex - 2, 3)
                recommendations["note"] += f"距离{'季度' if opex_event['type'] == 'Quarterly_OPEX' else '月度'}OPEX {days_to_opex}日,建议DTE≤{recommendations['max_dte_suggestion']}日; "
        
        # === 2. FOMC 检测 ===
        fomc_event = self._detect_fomc(current_date)
        if fomc_event:
            events.append(fomc_event)
            days_to_fomc = fomc_event["days_away"]
            if days_to_fomc <= 7:
                recommendations["reduce_position_size"] = True
                recommendations["note"] += f"距离FOMC会议{days_to_fomc}日,建议减半仓位或观望; "
        
        # === 3. 财报季检测 ===
        earnings_season_event = self._detect_earnings_season(current_date)
        if earnings_season_event:
            events.append(earnings_season_event)
            recommendations["no_cross_earnings"] = True
            recommendations["max_dte_suggestion"] = 7
            recommendations["note"] += f"当前处于{earnings_season_event['date']}财报季,不建议跨期,优先5-7日DTE; "
        
        # === 4. Alpha Vantage API 获取个股财报 ===
        if self.config.ENABLE_EARNINGS_API:
            earnings_event = self._get_earnings_from_api(symbol, current_date)
            if earnings_event:
                events.append(earnings_event)
                days_to_earnings = earnings_event["days_away"]
                if -2 <= days_to_earnings <= 5:
                    recommendations["no_cross_earnings"] = True
                    recommendations["max_dte_suggestion"] = 5
                    recommendations["note"] += f"{symbol}财报{earnings_event['date']},{'已过' if days_to_earnings < 0 else '即将'}({abs(days_to_earnings)}日),严禁跨期,建议等待或≤5日DTE; "
        
        # === 5. 综合判断 ===
        if not recommendations["note"]:
            recommendations["note"] = "未检测到近期重大事件,可正常执行策略"
        if recommendations["max_dte_suggestion"] is None:
            recommendations["max_dte_suggestion"] = 14
        
        # 风险等级
        risk_level = self._calculate_risk_level(recommendations)
        
        result = {
            "symbol": symbol,
            "detection_date": current_date.strftime("%Y-%m-%d"),
            "events": events,
            "event_count": len([e for e in events if e["type"] not in ["API_Warning", "Earnings_Season"]]),
            "recommendations": recommendations,
            "risk_level": risk_level,
            "cache_info": {
                "earnings_cached_count": len(self._earnings_cache),
                "api_enabled": recommendations["api_status"]
            }
        }
        
        logger.info(f"事件检测完成: {len(events)} 个事件, 风险等级: {risk_level}")
        return result
    
    def _detect_opex(self, current_date: datetime) -> Optional[Dict]:
        """检测 OPEX (每月第三个周五)"""
        year = current_date.year
        month = current_date.month
        
        # 计算第三个周五
        first_day = datetime(year, month, 1)
        days_until_friday = (4 - first_day.weekday()) % 7
        first_friday = first_day + timedelta(days=days_until_friday)
        third_friday = first_friday + timedelta(weeks=2)
        
        days_to_opex = (third_friday - current_date).days
        
        # 检测窗口: -5 到 +14 天
        if -5 <= days_to_opex <= 14:
            is_quarterly = month in [3, 6, 9, 12]
            return {
                "type": "Quarterly_OPEX" if is_quarterly else "Monthly_OPEX",
                "date": third_friday.strftime("%Y-%m-%d"),
                "days_away": days_to_opex,
                "impact": "high" if is_quarterly else "medium"
            }
        
        return None
    
    def _detect_fomc(self, current_date: datetime) -> Optional[Dict]:
        """检测 FOMC 会议"""
        # 2025 年 FOMC 日期
        fomc_dates_2025 = [
            "2025-01-28", "2025-01-29", "2025-03-18", "2025-03-19",
            "2025-05-06", "2025-05-07", "2025-06-17", "2025-06-18",
            "2025-07-29", "2025-07-30", "2025-09-16", "2025-09-17",
            "2025-10-28", "2025-10-29", "2025-12-09", "2025-12-10",
        ]
        
        for fomc_date_str in fomc_dates_2025:
            fomc_date = datetime.strptime(fomc_date_str, "%Y-%m-%d")
            days_to_fomc = (fomc_date - current_date).days
            
            # 检测窗口: 0 到 +30 天
            if 0 <= days_to_fomc <= 30:
                return {
                    "type": "FOMC",
                    "date": fomc_date_str,
                    "days_away": days_to_fomc,
                    "impact": "high" if days_to_fomc <= 7 else "medium"
                }
        
        return None
    
    def _detect_earnings_season(self, current_date: datetime) -> Optional[Dict]:
        """检测财报季"""
        year = current_date.year
        
        earnings_seasons = {
            "Q4": (1, 15, 2, 28),  # (start_month, start_day, end_month, end_day)
            "Q1": (4, 15, 5, 31),
            "Q2": (7, 15, 8, 31),
            "Q3": (10, 15, 11, 30),
        }
        
        for quarter, (sm, sd, em, ed) in earnings_seasons.items():
            try:
                season_start = datetime(year, sm, sd)
                season_end = datetime(year, em, ed)
                
                if season_start <= current_date <= season_end:
                    return {
                        "type": "Earnings_Season",
                        "date": f"{quarter} Earnings Season",
                        "days_away": 0,
                        "impact": "medium",
                        "note": f"当前处于{quarter}财报季"
                    }
            except ValueError:
                continue
        
        return None
    
    def _get_earnings_from_api(self, symbol: str, current_date: datetime) -> Optional[Dict]:
        """从 Alpha Vantage API 获取财报日期 (带缓存)"""
        symbol = symbol.upper()
        cache_key = f"earnings_{symbol}"
        
        # 检查缓存
        if cache_key in self._earnings_cache:
            cached_data, cached_time = self._earnings_cache[cache_key]
            cache_age = (current_date - cached_time).days
            
            if cache_age < self.config.EARNINGS_CACHE_DAYS:
                logger.info(f"使用缓存的财报数据: {symbol}")
                if cached_data:
                    days_away = (datetime.strptime(cached_data, "%Y-%m-%d") - current_date).days
                    return {
                        "type": "Earnings",
                        "date": cached_data,
                        "days_away": days_away,
                        "impact": "high",
                        "symbol": symbol,
                        "source": "Alpha Vantage API (cached)"
                    }
                return None
        
        # 调用 API
        try:
            import urllib.request
            import urllib.error
            
            api_key = self.config.ALPHA_VANTAGE_API_KEY
            url = f"{self.config.ALPHA_VANTAGE_API_URL}function=EARNINGS_CALENDAR&horizon=12month&apikey={api_key}&symbol={symbol}"
            
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as response:
                data = response.read().decode('utf-8')
            
            # 解析 CSV 响应
            lines = data.strip().split('\n')
            if len(lines) > 1:
                first_earnings = lines[1].split(',')
                if len(first_earnings) >= 3:
                    earnings_date = first_earnings[2]
                    
                    # 存入缓存
                    self._earnings_cache[cache_key] = (earnings_date, current_date)
                    
                    days_away = (datetime.strptime(earnings_date, "%Y-%m-%d") - current_date).days
                    
                    # 只返回 14 天窗口内的财报
                    if -5 <= days_away <= 14:
                        logger.info(f"API 获取财报: {symbol} - {earnings_date}")
                        return {
                            "type": "Earnings",
                            "date": earnings_date,
                            "days_away": days_away,
                            "impact": "high",
                            "symbol": symbol,
                            "source": "Alpha Vantage API"
                        }
            
            # API 返回空,缓存空结果
            self._earnings_cache[cache_key] = (None, current_date)
            return None
            
        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.warning("Alpha Vantage API 配额用尽")
                return {
                    "type": "API_Warning",
                    "date": "N/A",
                    "days_away": 0,
                    "impact": "low",
                    "note": "Alpha Vantage API配额用尽"
                }
            return None
        except Exception as e:
            logger.error(f"API 调用失败: {e}")
            return None
    
    def _extract_symbol(self, user_query: str) -> str:
        """从用户查询中提取股票代码"""
        match = re.search(r'\b([A-Z]{1,5})\b', user_query.upper())
        return match.group(1) if match else "UNKNOWN"
    
    def _calculate_risk_level(self, recommendations: Dict) -> str:
        """计算风险等级"""
        if recommendations["no_cross_earnings"] or recommendations["reduce_position_size"]:
            return "high"
        elif recommendations["adjust_dte"]:
            return "medium"
        else:
            return "low"