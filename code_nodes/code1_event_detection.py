import json
from datetime import datetime, timedelta
import re

# 全局缓存字典（在工作流生命周期内保持）
_earnings_cache = {}

def get_earnings_from_alpha_vantage(symbol, api_key, enable_api, cache_days, url):
    """从Alpha Vantage获取财报日期（带缓存）"""

    # 检查开关
    enable_api_bool = str(enable_api).lower() in ['true', '1', 'yes']
    if not enable_api_bool:
        return None  # API已禁用，跳过

    # 检查缓存
    current_time = datetime.now()
    cache_key = f"earnings_{symbol}"

    if cache_key in _earnings_cache:
        cached_data, cached_time = _earnings_cache[cache_key]
        # 检查缓存是否过期
        if (current_time - cached_time).days < int(cache_days):
            return cached_data  # 返回缓存数据

    # 调用API
    try:
        import urllib.request
        import urllib.error
        
        url = f"{url}function=EARNINGS_CALENDAR&horizon=12month&apikey={api_key}&symbol={symbol}"
        
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = response.read().decode('utf-8')
        
        lines = data.strip().split('\n')
        if len(lines) > 1:
            first_earnings = lines[1].split(',')
            if len(first_earnings) >= 3:
                earnings_date = first_earnings[2]
                # 存入缓存
                _earnings_cache[cache_key] = (earnings_date, current_time)
                return earnings_date
        
        # API返回空，缓存空结果避免重复调用
        _earnings_cache[cache_key] = (None, current_time)
        return None
        
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return "API_LIMIT_REACHED"
        return None
    except Exception as e:
        return None

def detect_events(symbol, current_date_str, api_key, enable_api, cache_days, url):
    """事件检测主函数"""
    try:
        current_date = datetime.strptime(current_date_str, "%Y-%m-%d")
    except:
        current_date = datetime.now()
    
    events = []
    recommendations = {
        "no_cross_earnings": False,
        "adjust_dte": False,
        "reduce_position_size": False,
        "max_dte_suggestion": None,
        "note": "",
        "api_status": "disabled" if str(enable_api).lower() not in ['true', '1', 'yes'] else "enabled"
    }
    
    # === 1. OPEX检测 ===
    year = current_date.year
    month = current_date.month
    first_day = datetime(year, month, 1)
    days_until_friday = (4 - first_day.weekday()) % 7
    first_friday = first_day + timedelta(days=days_until_friday)
    third_friday = first_friday + timedelta(weeks=2)
    days_to_opex = (third_friday - current_date).days
    
    if -5 <= days_to_opex <= 14:
        is_quarterly = month in [3, 6, 9, 12]
        events.append({
            "type": "Quarterly_OPEX" if is_quarterly else "Monthly_OPEX",
            "date": third_friday.strftime("%Y-%m-%d"),
            "days_away": days_to_opex,
            "impact": "high" if is_quarterly else "medium"
        })
        if 0 <= days_to_opex <= 7:
            recommendations["adjust_dte"] = True
            recommendations["max_dte_suggestion"] = max(days_to_opex - 2, 3)
            recommendations["note"] += f"距离{'季度' if is_quarterly else '月度'}OPEX {days_to_opex}日，建议DTE≤{recommendations['max_dte_suggestion']}日; "
    
    # === 2. FOMC检测 ===
    fomc_dates_2025 = [
        "2025-01-28", "2025-01-29", "2025-03-18", "2025-03-19",
        "2025-05-06", "2025-05-07", "2025-06-17", "2025-06-18",
        "2025-07-29", "2025-07-30", "2025-09-16", "2025-09-17",
        "2025-10-28", "2025-10-29", "2025-12-09", "2025-12-10",
    ]
    for fomc_date_str in fomc_dates_2025:
        fomc_date = datetime.strptime(fomc_date_str, "%Y-%m-%d")
        days_to_fomc = (fomc_date - current_date).days
        if 0 <= days_to_fomc <= 30:
            events.append({
                "type": "FOMC",
                "date": fomc_date_str,
                "days_away": days_to_fomc,
                "impact": "high" if days_to_fomc <= 7 else "medium"
            })
            if days_to_fomc <= 7:
                recommendations["reduce_position_size"] = True
                recommendations["note"] += f"距离FOMC会议{days_to_fomc}日，建议减半仓位或观望; "
            break
    
    # === 3. 财报季检测 ===
    earnings_seasons = {
        "Q4": (1, 15, 2, 28), "Q1": (4, 15, 5, 31),
        "Q2": (7, 15, 8, 31), "Q3": (10, 15, 11, 30),
    }
    for quarter, (sm, sd, em, ed) in earnings_seasons.items():
        try:
            season_start = datetime(year, sm, sd)
            season_end = datetime(year, em, ed)
            if season_start <= current_date <= season_end:
                events.append({
                    "type": "Earnings_Season",
                    "date": f"{quarter} Earnings Season",
                    "days_away": 0,
                    "impact": "medium",
                    "note": f"当前处于{quarter}财报季"
                })
                recommendations["no_cross_earnings"] = True
                recommendations["max_dte_suggestion"] = 7
                recommendations["note"] += f"当前处于{quarter}财报季，不建议跨期，优先5-7日DTE; "
                break
        except:
            continue
    
    # === 4. Alpha Vantage API获取个股财报（带开关和缓存）===
    symbol_upper = symbol.upper()
    
    if str(enable_api).lower() in ['true', '1', 'yes']:
        # API已启用
        earnings_date_api = get_earnings_from_alpha_vantage(
            symbol_upper, api_key, enable_api, cache_days, url
        )
        
        if earnings_date_api and earnings_date_api != "API_LIMIT_REACHED":
            try:
                earnings_date = datetime.strptime(earnings_date_api, "%Y-%m-%d")
                days_to_earnings = (earnings_date - current_date).days
                if -5 <= days_to_earnings <= 14:
                    events.append({
                        "type": "Earnings",
                        "date": earnings_date_api,
                        "days_away": days_to_earnings,
                        "impact": "high",
                        "symbol": symbol_upper,
                        "source": "Alpha Vantage API",
                        "cached": cache_key in _earnings_cache and (current_time - _earnings_cache[cache_key][1]).days < int(cache_days)
                    })
                    if -2 <= days_to_earnings <= 5:
                        recommendations["no_cross_earnings"] = True
                        recommendations["max_dte_suggestion"] = 5
                        recommendations["note"] += f"{symbol_upper}财报{earnings_date_api}，{'已过' if days_to_earnings < 0 else '即将'}({abs(days_to_earnings)}日)，严禁跨期，建议等待或≤5日DTE; "
            except:
                pass
        elif earnings_date_api == "API_LIMIT_REACHED":
            events.append({
                "type": "API_Warning",
                "date": "N/A",
                "days_away": 0,
                "impact": "low",
                "note": "Alpha Vantage API配额用尽"
            })
            recommendations["api_status"] = "quota_exceeded"
    else:
        # API已禁用，添加提示
        if not any(e.get("type") == "Earnings_Season" for e in events):
            # 只在不在财报季时才提示
            recommendations["note"] += "（财报API已禁用，仅检测财报季）; "
    
    # === 5. 综合判断 ===
    if not recommendations["note"]:
        recommendations["note"] = "未检测到近期重大事件，可正常执行策略"
    if recommendations["max_dte_suggestion"] is None:
        recommendations["max_dte_suggestion"] = 14
    
    result = {
        "symbol": symbol_upper,
        "detection_date": current_date.strftime("%Y-%m-%d"),
        "events": events,
        "event_count": len([e for e in events if e["type"] not in ["API_Warning", "Earnings_Season"]]),
        "recommendations": recommendations,
        "risk_level": "high" if (recommendations["no_cross_earnings"] or recommendations["reduce_position_size"]) else ("medium" if recommendations["adjust_dte"] else "low"),
        "cache_info": {
            "earnings_cached_count": len(_earnings_cache),
            "api_enabled": recommendations["api_status"]
        }
    }
    return json.dumps(result, indent=2, ensure_ascii=False)

def main(user_query: str, **env_vars) -> dict:
    """
    事件检测主函数
    
    Args:
        user_query: 用户查询字符串（包含股票代码）
        **env_vars: 环境变量字典
    """
    api_key = env_vars.get('ALPHA_VANTAGE_API_KEY', '')
    url = env_vars.get('ALPHA_VANTAGE_API_URL', 'https://www.alphavantage.co/query?')
    enable_api = env_vars.get('ENABLE_EARNINGS_API', True)
    cache_days = env_vars.get('EARNINGS_CACHE_DAYS', 30)
    
    match = re.search(r'\b([A-Z]{1,5})\b', user_query.upper())
    symbol = match.group(1) if match else "UNKNOWN"
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    result = detect_events(symbol, current_date, api_key, enable_api, cache_days, url)
    return {"result": result}