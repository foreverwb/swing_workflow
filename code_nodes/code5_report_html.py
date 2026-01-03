"""
CODE5 - HTML 仪表盘生成节点 (Phase 3 Ultimate Merged)
特性:
1. [Architecture] 恢复 Dashboard (SPA) 架构，支持 Monitoring / Baseline / History 视图
2. [Fix] 集成策略读取路径修复 (兼容 strategies 根节点)
3. [Fix] 集成路径清洗与 Symbol 自动纠错
"""
import re
import json
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Union, List
from utils.config_loader import config

class HTMLTemplate:
    # 扩展 CSS 以支持 Tabs 和 Dashboard 布局
    CSS = """
    :root { --bg-body: #f8fafc; --bg-card: #ffffff; --text-main: #0f172a; --text-sub: #64748b; --accent: #2563eb; --accent-light: #eff6ff; --border: #e2e8f0; --success: #10b981; --warning: #f59e0b; --danger: #ef4444; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "Microsoft YaHei", sans-serif; background: var(--bg-body); color: var(--text-main); line-height: 1.6; max-width: 1200px; margin: 0 auto; padding: 20px; }
    
    /* Header */
    .main-header { display: flex; align-items: center; gap: 15px; margin-bottom: 20px; }
    .symbol-logo { width: 48px; height: 48px; border-radius: 50%; background: white; border: 1px solid var(--border); padding: 4px; object-fit: contain; }
    .header-info h1 { margin: 0; font-size: 24px; color: var(--text-main); }
    .header-info .meta { color: var(--text-sub); font-size: 13px; }

    /* Tabs */
    .tab-nav { display: flex; border-bottom: 1px solid var(--border); margin-bottom: 20px; background: var(--bg-card); border-radius: 8px 8px 0 0; overflow: hidden; }
    .tab-btn { padding: 12px 24px; border: none; background: none; cursor: pointer; font-weight: 600; color: var(--text-sub); border-bottom: 3px solid transparent; transition: all 0.2s; }
    .tab-btn:hover { background: var(--accent-light); color: var(--accent); }
    .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
    .tab-content { display: none; animation: fadeIn 0.3s; }
    .tab-content.active { display: block; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

    /* Cards */
    .card { background: var(--bg-card); border-radius: 12px; border: 1px solid var(--border); box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 20px; overflow: hidden; }
    .card-header { padding: 15px 20px; border-bottom: 1px solid var(--border); background: #f8fafc; font-weight: 600; font-size: 14px; text-transform: uppercase; color: var(--text-sub); letter-spacing: 0.5px; display: flex; justify-content: space-between; align-items: center; }
    .card-body { padding: 20px; }

    /* Components */
    .monitor-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 20px; }
    .metric-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .metric-label { color: var(--text-sub); font-size: 13px; }
    .metric-value { font-weight: 700; font-size: 16px; color: var(--text-main); }
    .progress-container { background: #f1f5f9; height: 6px; border-radius: 3px; overflow: hidden; margin-top: 4px; }
    .progress-bar { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
    
    .tag { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
    .tag-green { background: #dcfce7; color: #166534; }
    .tag-red { background: #fee2e2; color: #991b1b; }
    .tag-blue { background: #dbeafe; color: #1e40af; }
    .tag-orange { background: #ffedd5; color: #9a3412; }
    
    .delta-badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; background: #e3f2fd; color: #1565c0; margin-left: 10px; }
    .delta-long { background: #e8f5e9; color: #2e7d32; }
    .delta-short { background: #ffebee; color: #c62828; }
    .delta-neutral { background: #f3e5f5; color: #7b1fa2; }

    /* Strategy Grid */
    .strategy-container { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; margin-top: 15px; }
    .strat-card { border: 1px solid var(--border); border-radius: 8px; padding: 15px; background: #fff; transition: transform 0.2s; }
    .strat-card:hover { transform: translateY(-2px); box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
    .strat-head { display: flex; justify-content: space-between; margin-bottom: 10px; align-items: center; }
    .strat-name { font-weight: 700; color: var(--text-main); }
    .strat-setup { font-size: 13px; background: #f1f5f9; padding: 10px; border-radius: 6px; margin-top: 10px; font-family: "Menlo", "Monaco", monospace; color: #334155; line-height: 1.5; border-left: 3px solid #cbd5e1; }

    /* Markdown & Tables */
    .markdown-body h2 { border-bottom: 2px solid var(--accent); padding-bottom: 8px; font-size: 1.4em; margin-top: 1.5em; }
    .markdown-body h3 { color: var(--accent); font-size: 1.1em; margin-top: 1.2em; }
    .markdown-body blockquote { border-left: 4px solid var(--accent); background: var(--accent-light); padding: 10px 15px; margin: 15px 0; border-radius: 0 4px 4px 0; color: #1e3a8a; font-style: italic; }
    
    .data-table { width: 100%; border-collapse: collapse; font-size: 14px; }
    .data-table th { background: #f8fafc; border-bottom: 2px solid #e2e8f0; padding: 12px; text-align: left; font-weight: 600; color: var(--text-sub); }
    .data-table td { border-bottom: 1px solid #e2e8f0; padding: 12px; color: var(--text-main); }
    .data-table tr:hover { background: #f1f5f9; }
    """

    JS = """
    function openTab(evt, tabName) {
        var i, tabcontent, tablinks;
        tabcontent = document.getElementsByClassName("tab-content");
        for (i = 0; i < tabcontent.length; i++) {
            tabcontent[i].className = tabcontent[i].className.replace(" active", "");
        }
        tablinks = document.getElementsByClassName("tab-btn");
        for (i = 0; i < tablinks.length; i++) {
            tablinks[i].className = tablinks[i].className.replace(" active", "");
        }
        document.getElementById(tabName).className += " active";
        evt.currentTarget.className += " active";
    }
    """

    @classmethod
    def get_dashboard_html(cls, symbol, favicon, latest_html, analysis_html, history_html):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_dm = datetime.now().strftime("%d-%m")
        return f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>{date_dm}-{symbol}-Report</title>
            <link rel="icon" href="{favicon}">
            <style>{cls.CSS}</style>
            <script>{cls.JS}</script>
        </head>
        <body>
            <div class="main-header">
                <img src="{favicon}" class="symbol-logo" onerror="this.src='https://www.google.com/s2/favicons?domain=google.com'">
                <div class="header-info">
                    <h1>{symbol} 量化仪表盘</h1>
                    <div class="meta">最后更新: {ts} • PHASE 3 引擎</div>
                </div>
            </div>

            <div class="tab-nav">
                <button class="tab-btn active" onclick="openTab(event, 'Latest')">🔍 实时监控</button>
                <button class="tab-btn" onclick="openTab(event, 'Analysis')">📘 基准分析</button>
                <button class="tab-btn" onclick="openTab(event, 'History')">📜 历史记录</button>
            </div>

            <div id="Latest" class="tab-content active">
                {latest_html}
            </div>

            <div id="Analysis" class="tab-content">
                <div class="card">
                    <div class="card-header"><span>初始分析报告 (T0)</span></div>
                    <div class="card-body">
                        <div class="markdown-body">
                            {analysis_html}
                        </div>
                    </div>
                </div>
            </div>

            <div id="History" class="tab-content">
                <div class="card">
                    <div class="card-header"><span>快照历史</span></div>
                    <div class="card-body">
                        {history_html}
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

def get_favicon_url(symbol: str) -> str:
    domain = config.get_section("reporting").get("ticker_domains", {}).get(symbol.upper(), "google.com")
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"

def _render_progress(val, color):
    pct = min(max(val * 100, 0), 100)
    bg = {'tag-green': '#10b981', 'tag-orange': '#f59e0b', 'tag-blue': '#2563eb'}.get(color, '#cbd5e1')
    return f'<div class="progress-container"><div class="progress-bar" style="width: {pct}%; background: {bg};"></div></div>'

def _render_monitor_layer(data: Dict) -> str:
    """渲染监控面板的核心指标"""
    if not data: return "<p>暂无数据</p>"
    targets = data.get("targets") or data.get("snapshot", {}).get("targets", {})
    if not targets: return "<p>等待数据加载...</p>"
    
    spot = targets.get("spot_price", 0)
    gamma = targets.get("gamma_metrics", {})
    micro = gamma.get("micro_structure", {})
    
    # 兼容性提取
    raw = micro.get("raw_metrics", {})
    ecr = raw.get("ECR") if raw.get("ECR") is not None else micro.get("ECR", 0)
    ser = raw.get("SER") if raw.get("SER") is not None else micro.get("SER", 0)
    
    label = "刚性墙" if "Rigid" in micro.get("wall_type", "") else "脆弱墙"
    cls = "tag-green" if label == "脆弱墙" else "tag-orange"
    
    # 获取 Drift 报告 (如果有)
    drift = data.get("drift_report", {})
    drift_html = ""
    if drift and drift.get("summary"):
        actions_html = ""
        for act in drift.get("actions", []):
            color = "red" if act['type'] in ['stop_loss', 'exit'] else "green" if act['type'] == 'take_profit' else "orange"
            actions_html += f"<li><span style='color:{color};font-weight:bold'>[{act['type'].upper()}]</span> {act['reason']}</li>"
        
        drift_html = f"""
        <div class="card" style="border-left: 4px solid var(--accent);">
            <div class="card-header"><span>🛡️ 漂移监控</span></div>
            <div class="card-body">
                <div style="font-weight:bold;margin-bottom:10px;">{drift.get('summary')}</div>
                <ul style="margin:0;padding-left:20px;font-size:14px;color:var(--text-sub);">{actions_html}</ul>
            </div>
        </div>
        """

    return f"""
    {drift_html}
    <div class="monitor-grid">
        <div class="card" style="border-top:4px solid var(--accent);">
            <div class="card-header"><span>微观物理</span> <span class="tag {cls}">{label}</span></div>
            <div class="card-body">
                <div class="metric-row">
                    <div style="flex:1;">
                        <div class="metric-label">ECR (钉扎强度) <span style="float:right;">{ecr:.2f}</span></div>
                        {_render_progress(ecr, 'tag-orange' if ecr > 0.5 else 'tag-green')}
                    </div>
                </div>
                <div class="metric-row" style="margin-top:15px;">
                    <div style="flex:1;">
                        <div class="metric-label">SER (接力强度) <span style="float:right;">{ser:.2f}</span></div>
                        {_render_progress(ser, 'tag-blue' if ser > 0.5 else 'tag-red')}
                    </div>
                </div>
            </div>
        </div>
        <div class="card">
            <div class="card-header"><span>关键价位</span></div>
            <div class="card-body">
                <div class="metric-row"><span class="metric-label">现价</span> <span class="metric-value">${spot}</span></div>
                <div class="metric-row"><span class="metric-label">波动触发点</span> <span class="metric-value">${gamma.get('vol_trigger','N/A')}</span></div>
                <div class="metric-row"><span class="metric-label">看涨墙</span> <span style="color:var(--success);font-weight:700">${targets.get("walls",{}).get("call_wall")}</span></div><div class="metric-row"><span class="metric-label">看跌墙</span> <span style="color:var(--danger);font-weight:700">${targets.get("walls",{}).get("put_wall")}</span></div>
            </div>
        </div>
    </div>
    """

def _try_parse(d):
    if isinstance(d, str):
        try: return json.loads(d)
        except: return d
    return d

def _format_legs_to_natural_language(legs: Any) -> str:
    legs = _try_parse(legs)
    if not legs or legs == "{}": return "无腿部数据"
    
    legs_list = []
    if isinstance(legs, dict):
        if "action" in legs: legs_list = [legs]
        else: legs_list = list(legs.values())
    elif isinstance(legs, list):
        legs_list = legs
    
    if not legs_list: return "无腿部数据"

    lines = []
    for leg in legs_list:
        if not isinstance(leg, dict): continue
        action = (leg.get("action") or "").upper()
        contract = (leg.get("contract") or leg.get("option_type") or "").capitalize()
        strike = leg.get("strike", 0)
        
        act_map = {"BUY":"买入","SELL":"卖出","LONG":"买入","SHORT":"卖出"}
        act_cn = act_map.get(action, action)
        
        lines.append(f"• {act_cn} <strong>${strike}</strong> {contract}")
    return "<br>".join(lines)

def _render_strategy_cards(final_data: Dict, all_history: Dict = None) -> str:
    """渲染策略卡片，支持多源策略读取 (增强版)"""
    
    # 1. 尝试从 agent6_result (标准流程)
    strats = _try_parse(final_data.get("agent6_result", {}).get("strategies", []))
    
    # 2. 尝试从 snapshot (Refresh模式)
    if not strats:
        strats = _try_parse(final_data.get("snapshot", {}).get("data", {}).get("agent6_result", {}).get("strategies", []))
    
    # 3. [修复] 尝试从直接的 'strategies' 字段 (Cache JSON / Input Mode)
    if not strats:
        strategies_field = final_data.get("strategies", {})
        if isinstance(strategies_field, dict) and "strategies" in strategies_field:
            strats = _try_parse(strategies_field["strategies"])
        elif isinstance(strategies_field, list):
            strats = _try_parse(strategies_field)
    
    # 4. [新增] 尝试从 source_target.strategies 获取 (兼容缓存结构)
    if not strats:
        source_target = final_data.get("source_target", {})
        if source_target:
            strategies_field = source_target.get("strategies", {})
            if isinstance(strategies_field, dict) and "strategies" in strategies_field:
                strats = _try_parse(strategies_field["strategies"])
            elif isinstance(strategies_field, list):
                strats = _try_parse(strategies_field)
    
    # 5. [关键修复] 尝试从 all_history.source_target.strategies 获取 (Refresh 模式)
    if not strats and all_history:
        source_target = all_history.get("source_target", {})
        if source_target:
            strategies_field = source_target.get("strategies", {})
            if isinstance(strategies_field, dict) and "strategies" in strategies_field:
                strats = _try_parse(strategies_field["strategies"])
            elif isinstance(strategies_field, list):
                strats = _try_parse(strategies_field)
    
    if not strats:
        # 渲染空状态
        return '<div class="card"><div class="card-header"><span>策略推荐</span></div><div class="card-body"><div style="color:#64748b;text-align:center;padding:20px;">🚫 暂无策略推荐 (详见分析报告)</div></div></div>'
    
    html = '<div class="card"><div class="card-header"><span>策略推荐</span></div><div class="card-body"><div class="strategy-container">'
    for s in strats:
        s = _try_parse(s)
        if not isinstance(s, dict): continue
        
        name = s.get("name") or s.get("strategy_name")
        delta = s.get("delta_profile", "中性")
        thesis = s.get("thesis") or s.get("description") or s.get("rationale", "暂无说明")
        legs = s.get("legs") or s.get("setup") or s.get("structure")
        
        legs_formatted = _format_legs_to_natural_language(legs)
        badge_cls = "delta-long" if "long" in delta.lower() else "delta-short" if "short" in delta.lower() else "delta-neutral"
        
        html += f"""<div class="strat-card"><div class="strat-head"><div class="strat-name">{name}</div><span class="delta-badge {badge_cls}">{delta}</span></div><div style="font-size:13px;color:#475569;margin-bottom:8px;">{thesis}</div><div class="strat-setup">{legs_formatted}</div></div>"""
    
    return html + '</div></div></div>'

def _render_history_table(all_history: Dict) -> str:
    """渲染历史快照表格"""
    if not all_history: return "<p>暂无历史记录</p>"
    
    rows = []
    # 1. Source Target (Baseline)
    st = all_history.get("source_target", {})
    if st:
        # 兼容 timestamp 位置
        ts = st.get("timestamp", "")
        if not ts and "data" in st: ts = st["data"].get("timestamp", "")
        ts = ts[:16].replace("T", " ")
        
        t_data = st.get("data", {}).get("targets", {})
        spot = t_data.get("spot_price", "N/A")
        rows.append(f"<tr><td><span class='tag tag-blue'>基准</span></td><td>{ts}</td><td>${spot}</td><td>初始化</td></tr>")
    
    # 2. Snapshots
    snapshots = [k for k in all_history.keys() if k.startswith("snapshots_")]
    # 按 ID 排序
    snapshots.sort(key=lambda x: int(x.split("_")[1]))
    
    for key in snapshots:
        snap = all_history[key]
        targets = snap.get("targets", {})
        spot = targets.get("spot_price", "N/A")
        ts = snap.get("timestamp", "")[:16].replace("T", " ")
        note = snap.get("note", "")
        
        tag = "监控"
        cls = "tag-green"
        if "High" in note or "Alert" in note: cls = "tag-red"
        elif "Change" in note: cls = "tag-orange"
        
        rows.append(f"<tr><td><span class='tag {cls}'>{tag} #{key.split('_')[1]}</span></td><td>{ts}</td><td>${spot}</td><td>{note}</td></tr>")
    
    return f"""
    <table class="data-table">
        <thead><tr><th>类型</th><th>时间</th><th>现价</th><th>备注</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
    </table>
    """

def markdown_to_html(text: str) -> str:
    if not text: return ""
    html = []
    in_table = False
    for line in text.split('\n'):
        line = line.strip()
        if not line: continue
        line = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line)
        
        if line.startswith('|') and line.endswith('|'):
            if not in_table: html.append('<table class="data-table">'); in_table = True
            if '---' in line: continue
            cells = [c.strip() for c in line.split('|')[1:-1]]
            tag = "th" if html[-1] == '<table class="data-table">' else "td"
            row = "".join(f"<{tag}>{c}</{tag}>" for c in cells)
            html.append(f"<tr>{row}</tr>")
            continue
        elif in_table:
            html.append('</table>'); in_table = False
            
        if line.startswith('# '): html.append(f'<h1>{line[2:]}</h1>')
        elif line.startswith('## '): html.append(f'<h2>{line[3:]}</h2>')
        elif line.startswith('### '): html.append(f'<h3>{line[4:]}</h3>')
        elif line.startswith('> '): html.append(f'<blockquote>{line[2:]}</blockquote>')
        elif line.startswith('- '): html.append(f'<li>{line[2:]}</li>')
        else: html.append(f'<p>{line}</p>')
    if in_table: html.append('</table>')
    return "".join(html)

def main(symbol, final_data, mode="full", **kwargs):
    try:
        # [Fix] Symbol 自动纠错逻辑
        if not symbol or str(symbol).lower() == "symbol":
            targets = final_data.get("targets", {})
            extracted = targets.get("symbol") or final_data.get("symbol")
            if extracted:
                symbol = extracted
        
        symbol = str(symbol).upper().strip() if symbol else "UNKNOWN"
        
        # [Fix] 路径清洗：移除文件名非法字符
        safe_symbol = re.sub(r'[\\/*?:"<>|]', "", symbol)
        
        base_dir = Path(kwargs.get("output_dir", "data/output"))
        
        # 路径结构: data/output/{SYMBOL}/{YYYYMMDD}/
        date_str = datetime.now().strftime('%Y%m%d')
        save_dir = base_dir / safe_symbol / date_str
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # 文件名: dashboard.html (统一入口)
        filename = f"dashboard.html"
        save_path = save_dir / filename
        
        # 获取历史数据（提前获取，供后续使用）
        all_history = kwargs.get("all_history", {})
        
        # 1. 准备 Latest View (Monitor + Strategy)
        latest_view = _render_monitor_layer(final_data) + _render_strategy_cards(final_data, all_history)
        
        # 2. 准备 Analysis View (Markdown Report)
        # [Bug Fix] 在 refresh 模式下，BASELINE ANALYSIS 应显示原始 T0 报告
        # 而不是混合了 drift 信息的 merged_report
        
        # 优先从 all_history.source_target 获取原始 baseline report
        baseline_report_md = ""
        if all_history:
            source_target = all_history.get("source_target", {})
            # 优先从根级别获取 report（符合 save_complete_analysis 的存储结构）
            baseline_report_md = source_target.get("report", "")
            # 如果根级别没有，再尝试从 data 中获取（兼容旧格式）
            if not baseline_report_md and "data" in source_target:
                baseline_report_md = source_target["data"].get("report", "")
        
        # [Bug Fix] 回退逻辑：如果 all_history 中没有，再从 final_data 获取
        # 注意：在 refresh 模式下，final_data["report"] 是 merged_report
        # 我们需要尝试从 final_data["source_target"] 获取原始报告
        if not baseline_report_md:
            source_target_in_final = final_data.get("source_target", {})
            if source_target_in_final:
                baseline_report_md = source_target_in_final.get("report", "")
        
        # 最终回退：使用 final_data["report"]（可能是 merged 或 full 模式的原始报告）
        if not baseline_report_md:
            baseline_report_md = final_data.get("report", "")
                
        if not baseline_report_md:
            baseline_report_md = "暂无基准分析报告。"
            
        analysis_view = markdown_to_html(baseline_report_md)
        
        # 3. 准备 History View
        history_view = _render_history_table(all_history)
        
        # 4. 组装 Dashboard
        html = HTMLTemplate.get_dashboard_html(
            safe_symbol, get_favicon_url(safe_symbol),
            latest_view, analysis_view, history_view
        )
        
        with open(save_path, 'w', encoding='utf-8') as f: f.write(html)
        return {"status": "success", "html_path": str(save_path)}
    except Exception as e:
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}