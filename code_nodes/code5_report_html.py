"""
CODE5 - HTML 报告生成节点 (v3.5.3 - Direct Icon Link)
"""
import re
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger
import traceback
from utils.config_loader import config

class HTMLTemplate:
    CSS = """
    :root {
        --bg-body: #f8fafc; --bg-card: #ffffff; 
        --text-main: #0f172a; --text-sub: #64748b;
        --accent: #2563eb; --accent-light: #eff6ff;
        --border: #e2e8f0;
        --success: #10b981; --warning: #f59e0b; --danger: #ef4444;
    }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "Microsoft YaHei", sans-serif; background: var(--bg-body); color: var(--text-main); line-height: 1.6; max-width: 1200px; margin: 0 auto; padding: 20px; }
    
    /* Card System */
    .card { background: var(--bg-card); border-radius: 12px; border: 1px solid var(--border); box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 20px; overflow: hidden; }
    .card-header { padding: 15px 20px; border-bottom: 1px solid var(--border); background: #f8fafc; font-weight: 600; font-size: 14px; text-transform: uppercase; color: var(--text-sub); letter-spacing: 0.5px; display: flex; justify-content: space-between; align-items: center; }
    .card-body { padding: 20px; }
    
    /* Monitor Grid */
    .monitor-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 30px; }
    
    /* Metrics */
    .metric-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .metric-label { color: var(--text-sub); font-size: 13px; }
    .metric-value { font-weight: 700; font-size: 16px; color: var(--text-main); }
    .metric-sub { font-size: 11px; color: var(--text-sub); }
    
    /* Progress Bar */
    .progress-container { background: #f1f5f9; height: 6px; border-radius: 3px; overflow: hidden; margin-top: 4px; }
    .progress-bar { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
    
    /* Tags */
    .tag { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
    .tag-green { background: #dcfce7; color: #166534; }
    .tag-red { background: #fee2e2; color: #991b1b; }
    .tag-blue { background: #dbeafe; color: #1e40af; }
    .tag-orange { background: #ffedd5; color: #9a3412; }
    
    /* Header */
    .main-header { display: flex; align-items: center; gap: 15px; margin-bottom: 30px; }
    .symbol-logo { width: 48px; height: 48px; border-radius: 50%; background: white; border: 1px solid var(--border); padding: 4px; object-fit: contain; }
    .header-info h1 { margin: 0; font-size: 24px; color: var(--text-main); }
    .header-info .meta { color: var(--text-sub); font-size: 13px; }

    /* Markdown Overrides */
    .markdown-body h2 { border-bottom: 2px solid var(--accent); padding-bottom: 8px; font-size: 1.4em; margin-top: 1.5em; }
    .markdown-body h3 { color: var(--accent); font-size: 1.1em; margin-top: 1.2em; }
    .markdown-body blockquote { border-left: 4px solid var(--accent); background: var(--accent-light); padding: 10px 15px; margin: 15px 0; border-radius: 0 4px 4px 0; color: #1e3a8a; }
    """

    @classmethod
    def get_html(cls, symbol: str, favicon: str, monitor_html: str, report_html: str) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 备用 Logo
        
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{symbol}-RPT-{datetime.now().strftime("%Y-%m-%d")}</title>
    <link rel="icon" href="{favicon}">
    <style>{cls.CSS}</style>
</head>
<body>
    <div class="main-header">
        <img src="{favicon}" class="symbol-logo" onerror="this.src='{favicon}'">
        <div class="header-info">
            <h1>{symbol}--{datetime.now().strftime("%Y-%m-%d")}</h1>
            <div class="meta">生成时间: {ts} • PHASE 3 引擎</div>
        </div>
    </div>

    {monitor_html}

    <div class="card">
        <div class="card-header">
            <span>基础与战术报告</span>
            <span>AGENT 8</span>
        </div>
        <div class="card-body">
            <div class="markdown-body">
                {report_html}
            </div>
        </div>
    </div>
</body>
</html>"""

def get_favicon_url(symbol: str) -> str:
    """
    根据 Symbol 获取 Favicon URL
    逻辑: 
    1. 从 config 中查找对应的 domain (如 TSLA -> tesla.com)
    2. 使用 Google S2 Favicon API 生成图标链接
    """
    try:
        domains = config.get("reporting", {}).get("ticker_domains", {})
    except:
        domains = {}
        
    domain = domains.get(symbol.upper())
    
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"

def _render_progress(value: float, color_class: str) -> str:
    pct = min(max(value * 100, 0), 100)
    color_map = {'tag-green': '#10b981', 'tag-red': '#ef4444', 'tag-blue': '#2563eb', 'tag-orange': '#f59e0b'}
    bg = color_map.get(color_class, '#cbd5e1')
    return f'<div class="progress-container"><div class="progress-bar" style="width: {pct}%; background: {bg};"></div></div>'

def _render_monitor_layer(data: Dict) -> str:
    if not data: return ""
    
    targets = data.get("targets", data)
    
    # 1. 基础数据
    spot = targets.get("spot_price", 0)
    gamma_metrics = targets.get("gamma_metrics", {})
    micro = gamma_metrics.get("micro_structure", {})
    wall_type = micro.get("wall_type", "Unknown")
    ecr = micro.get("raw_metrics", {}).get("ECR", 0)
    ser = micro.get("raw_metrics", {}).get("SER", 0)
    
    # 2. 决策可视化逻辑
    verdict_title = "交易决策 (VERDICT)"
    verdict_val = "观望 (NEUTRAL)"
    verdict_class = "tag-blue"
    
    if spot == 0:
        verdict_title = "数据完整性"
        verdict_val = "严重缺失 (FAIL)"
        verdict_class = "tag-red"
    elif "Brittle" in wall_type:
        verdict_title = "交易决策"
        verdict_val = "机会 (OPPORTUNITY)"
        verdict_class = "tag-green"
    elif "Rigid" in wall_type:
        verdict_title = "交易决策"
        verdict_val = "谨慎 (CAUTION)"
        verdict_class = "tag-orange"

    # [汉化] 墙体标签
    wall_label = wall_type.split(' ')[0]
    if "Rigid" in wall_type: wall_label = "刚性 (RIGID)"
    elif "Brittle" in wall_type: wall_label = "脆性 (BRITTLE)"
    
    wall_tag = "tag-orange" if "Rigid" in wall_type else ("tag-green" if "Brittle" in wall_type else "tag-blue")
    
    anchors = targets.get("sentiment_anchors", {})
    vol_surf = targets.get("vol_surface", {})
    
    btn_text = "ABSTAIN" if spot == 0 else ("强力入场 (ENTER)" if "Brittle" in wall_type else "轻仓试探 (PROBE)")
    
    return f"""
    <div class="monitor-grid">
        <div class="card" style="border-top: 4px solid var(--{verdict_class.split('-')[1]});">
            <div class="card-header">
                <span>{verdict_title}</span>
                <span class="tag {verdict_class}">{verdict_val}</span>
            </div>
            <div class="card-body">
                <div class="metric-row">
                    <div style="font-size: 13px; color: var(--text-sub);">
                        { "价格数据缺失" if spot == 0 else wall_type }
                    </div>
                </div>
                <div class="metric-row" style="margin-top: 10px;">
                     <div class="tag {verdict_class}" style="width: 100%; text-align: center; padding: 6px; font-size: 12px;">
                        { btn_text }
                     </div>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <span>微观物理 (MICRO PHYSICS)</span>
                <span class="tag {wall_tag}">{wall_label}</span>
            </div>
            <div class="card-body">
                <div class="metric-row">
                    <div style="flex: 1;">
                        <div class="metric-label">ECR (钉住风险) <span style="float:right;">{ecr:.2f}</span></div>
                        {_render_progress(ecr, 'tag-orange' if ecr > 0.5 else 'tag-green')}
                    </div>
                </div>
                <div class="metric-row" style="margin-top: 15px;">
                    <div style="flex: 1;">
                        <div class="metric-label">SER (接力能力) <span style="float:right;">{ser:.2f}</span></div>
                        {_render_progress(ser, 'tag-blue' if ser > 0.5 else 'tag-red')}
                    </div>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <span>情绪与波动 (SENTIMENT)</span>
                <span class="tag tag-blue">{vol_surf.get("smile_steepness", "N/A")}</span>
            </div>
            <div class="card-body">
                 <div class="metric-row">
                    <div>
                        <div class="metric-label">Max Pain (最大痛点)</div>
                        <div class="metric-value">${anchors.get("max_pain", 0)}</div>
                    </div>
                    <div style="text-align: right;">
                         <div class="metric-label">P/C Ratio</div>
                         <div class="metric-value">{anchors.get("put_call_ratio", "N/A")}</div>
                    </div>
                </div>
                <div class="metric-row" style="margin-top: 15px; background: #f8fafc; padding: 10px; border-radius: 6px;">
                    <div style="width: 100%;">
                        <div class="metric-label" style="margin-bottom: 4px;">期权墙结构 (Walls)</div>
                        <div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: 600;">
                            <span style="color: var(--danger);">Put: ${targets.get("walls", {}).get("put_wall")}</span>
                            <span style="color: var(--success);">Call: ${targets.get("walls", {}).get("call_wall")}</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """

def markdown_to_html(text: str) -> str:
    if not text: return ""
    lines = text.split('\n')
    html = []
    for line in lines:
        line = line.strip()
        if line.startswith('### '): html.append(f'<h3>{line[4:]}</h3>'); continue
        if line.startswith('## '): html.append(f'<h2>{line[3:]}</h2>'); continue
        if line.startswith('# '): html.append(f'<h1>{line[2:]}</h1>'); continue
        if line.startswith('- **'): 
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line[2:])
            html.append(f'<li>{content}</li>'); continue
        if line: 
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line)
            html.append(f'<p>{content}</p>')
    return '\n'.join(html)

def main(mode: str = "report", symbol: str = "UNKNOWN", output_dir: str = "data/output", report_markdown: str = None, start_date: str = None, current_data: dict = None, **kwargs) -> Dict[str, Any]:
    try:
        symbol = symbol.upper()
    
        favicon = get_favicon_url(symbol)
        
        # 1. 生成监控层 HTML
        monitor_html = _render_monitor_layer(current_data)
        
        # 2. 生成报告层 HTML
        report_html = markdown_to_html(report_markdown)
        
        # 3. 组装完整页面
        full_html = HTMLTemplate.get_html(symbol, favicon, monitor_html, report_html)
        
        # 4. 保存
        date_str = start_date if start_date else datetime.now().strftime("%Y-%m-%d")
        date_clean = date_str.replace("-", "")
        save_path = Path(output_dir) / symbol / date_clean / f"{symbol}_{date_clean}.html"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(full_html)
            
        return {"status": "success", "html_path": str(save_path)}
        
    except Exception as e:
        logger.error(f"HTML 生成失败: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}