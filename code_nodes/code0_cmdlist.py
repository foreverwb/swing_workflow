"""
Code Node 2: 命令清单生成器 (v3.3 - Fix DTE Formatting)
修复:
1. DTE 参数提取逻辑优化：仅提取数字，确保与模板中的 w/m 单位之间有正确空格
   解决 '!gexr LLY 25 30w' -> '!gexr LLY 25 30 w'
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import yaml
import re  # [新增] 引入正则用于提取数字


class CommandGroup(Enum):
    """命令分组枚举"""
    CORE_STRUCTURE = "核心结构"
    FLOWS = "供需流向"
    VOLATILITY = "波动率锚点"
    IV_PATH = "IV Path & Validation"
    EXTENDED = "扩展命令"
    INDEX_BACKGROUND = "指数背景"


@dataclass
class CommandTemplate:
    """命令模板数据类"""
    group: CommandGroup
    description: str
    template: str
    order: int = 0
    enabled: bool = True
    condition: Optional[str] = None


# ============================================================
# 核心配置：命令模板列表
# ============================================================

COMMAND_TEMPLATES: List[CommandTemplate] = [
    # ========== 1. 核心结构 (Walls & Clusters) ==========
    CommandTemplate(
        group=CommandGroup.CORE_STRUCTURE,
        description="[战术视图] 捕捉近端摩擦与周度博弈 (Weekly Friction)",
        template="!gexr {symbol} {strikes} {dte_short} w",
        order=1
    ),
    CommandTemplate(
        group=CommandGroup.CORE_STRUCTURE,
        description="[战略视图] 锁定机构核心仓位与磁力目标 (Monthly Structure)",
        template="!gexr {symbol} {strikes} {dte_mid} m",
        order=2
    ),
    # [新增] 增强指令：Skew Adjusted GEX
    CommandTemplate(
        group=CommandGroup.CORE_STRUCTURE,
        description="[结构修正] Skew Adjusted GEX (真实对冲墙，抗IV扭曲)",
        template="!gexs {symbol} {strikes} {dte_short}",
        order=3
    ),
    
    # ========== 2. 供需流向 (Flows) ==========
    CommandTemplate(
        group=CommandGroup.FLOWS,
        description="净Gamma与触发线 (全周期)",
        template="!gexn {symbol} {window} 98",
        order=10
    ),
    CommandTemplate(
        group=CommandGroup.FLOWS,
        description="Trigger Line",
        template="!trigger {symbol} {window}",
        order=11
    ),
    # [新增] 增强指令：Max Pain
    CommandTemplate(
        group=CommandGroup.FLOWS,
        description="[情绪锚点] Max Pain (仅在震荡/低波场景参考)",
        template="!max {symbol}",
        order=12,
        condition="scenario in ['Grind', 'Range', 'Low Vol']"
    ),
    CommandTemplate(
        group=CommandGroup.FLOWS,
        description="Vanna Exposure (使用 m 过滤，聚焦长期持仓对冲压力)",
        template="!vanna {symbol} ntm {window} m",
        order=13
    ),
    CommandTemplate(
        group=CommandGroup.FLOWS,
        description="Delta Exposure (与中期结构对齐)",
        template="!dexn {symbol} {strikes} {dte_mid}",
        order=14
    ),
    
    # ========== 3. 波动率锚点 (Volatility Anchors) ==========
    CommandTemplate(
        group=CommandGroup.VOLATILITY,
        description="[物理锚点] 7日 Skew (用于 Raw_EM1$)",
        template="!skew {symbol} ivmid atm 7",
        order=20
    ),
    CommandTemplate(
        group=CommandGroup.VOLATILITY,
        description="[物理锚点] 14日 Skew",
        template="!skew {symbol} ivmid atm 14",
        order=21
    ),
    CommandTemplate(
        group=CommandGroup.VOLATILITY,
        description="[定价基准] 30日 Skew (Monthly 公允价值)",
        template="!skew {symbol} ivmid atm 30 m",
        order=22
    ),
    CommandTemplate(
        group=CommandGroup.VOLATILITY,
        description="Term Structure",
        template="!term {symbol} 60",
        order=23
    ),
    # [新增] 增强指令：Volatility Smile
    CommandTemplate(
        group=CommandGroup.VOLATILITY,
        description="[定价分析] Vol Smile (指导 Ratio/Spread 定价)",
        template="!smile {symbol} {dte_mid}",
        order=24
    ),
    
    # ========== 4. IV Path & Validation ==========
    CommandTemplate(
        group=CommandGroup.IV_PATH,
        description="确认 IV 趋势",
        template="v_path: {symbol} 7D ATM-IV 对比 3 日 skew 数据",
        order=30
    ),
    CommandTemplate(
        group=CommandGroup.IV_PATH,
        description="[真实意图] 确认今日资金流向 (用于证伪)",
        template="!volumen {symbol} {strikes} {dte_short}",
        order=31
    ),
    CommandTemplate(
        group=CommandGroup.IV_PATH,
        description="[波动率底牌] Dealer Vega 敞口",
        template="!vexn {symbol} {strikes} {dte_mid}",
        order=32
    ),
    
    # ========== 5. 扩展命令（条件触发）==========
    CommandTemplate(
        group=CommandGroup.EXTENDED,
        description="长期备份 (如果 dyn_dte_mid 已是月度)",
        template="!gexr {symbol} {strikes} {dte_long}",
        order=40
    ),
    
    # ========== 6. 指数背景（必需）==========
    CommandTemplate(
        group=CommandGroup.INDEX_BACKGROUND,
        description="SPX 净Gamma",
        template="!gexn SPX {window} 98",
        order=50
    ),
    CommandTemplate(
        group=CommandGroup.INDEX_BACKGROUND,
        description="SPX 7日 Skew",
        template="!skew SPX ivmid atm 7",
        order=51
    ),
    CommandTemplate(
        group=CommandGroup.INDEX_BACKGROUND,
        description="QQQ 净Gamma (Big Tech)",
        template="!gexn QQQ {window} 98",
        order=53
    ),
    CommandTemplate(
        group=CommandGroup.INDEX_BACKGROUND,
        description="QQQ 7日 Skew",
        template="!skew QQQ ivmid atm 7",
        order=54
    ),
]


class CommandListGenerator:
    """命令清单生成器"""
    
    def __init__(self, templates: List[CommandTemplate] = None):
        self.templates = templates or COMMAND_TEMPLATES.copy()
    
    def generate(
        self,
        symbol: str,
        pre_calc: Dict[str, Any],
        market_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        生成命令清单
        """
        # 提取参数
        params = self._extract_params(symbol, pre_calc)
        
        # 过滤并排序模板
        active_templates = self._filter_templates(pre_calc)
        
        # 生成命令
        commands = []
        for tpl in active_templates:
            cmd = self._render_template(tpl, params)
            commands.append(cmd)
        
        # 格式化输出
        content = self._format_output(commands, symbol, pre_calc, market_params)
        
        return {
            "status": "success",
            "content": content,
            "commands": commands,
            "summary": {
                "total_commands": len(commands),
                "scenario": pre_calc.get("scenario", "N/A")
            }
        }
    
    def _extract_params(self, symbol: str, pre_calc: Dict) -> Dict[str, str]:
        """
        提取模板参数
        [修正] 仅提取 DTE 的数字部分，避免 '30w' 这种带单位的字符串破坏模板格式
        """
        
        def _clean_dte(val):
            """提取字符串中的数字"""
            if val is None: return "30"
            # 将 '30 w', '14d', '60 m' 等转换为纯数字字符串 '30', '14', '60'
            digits = "".join(filter(str.isdigit, str(val)))
            return digits if digits else "30"

        return {
            "symbol": symbol.upper(),
            "strikes": str(pre_calc.get("dyn_strikes", 30)),
            # 使用 _clean_dte 处理 DTE 参数
            "dte_short": _clean_dte(pre_calc.get("dyn_dte_short", "14")),
            "dte_mid": _clean_dte(pre_calc.get("dyn_dte_mid", "30")),
            "dte_long": _clean_dte(pre_calc.get("dyn_dte_long_backup", "60")),
            "window": str(pre_calc.get("dyn_window", 60)),
        }
    
    def _filter_templates(self, pre_calc: Dict) -> List[CommandTemplate]:
        active = []
        for tpl in self.templates:
            if not tpl.enabled: continue
            if tpl.condition:
                if not self._evaluate_condition(tpl.condition, pre_calc): continue
            active.append(tpl)
        return sorted(active, key=lambda x: x.order)
    
    def _evaluate_condition(self, condition: str, pre_calc: Dict) -> bool:
        try:
            env = {
                "scenario": pre_calc.get("scenario", ""),
                "vrp": pre_calc.get("vrp", 1.0),
                "strikes": pre_calc.get("dyn_strikes", 30)
            }
            return eval(condition, {"__builtins__": {}}, env)
        except Exception:
            return True 
    
    def _render_template(self, tpl: CommandTemplate, params: Dict[str, str]) -> Dict:
        return {
            "group": tpl.group.value,
            "description": tpl.description,
            "command": tpl.template.format(**params),
            "order": tpl.order
        }
    
    def _format_output(self, commands: List[Dict], symbol: str, pre_calc: Dict, market_params: Optional[Dict]) -> str:
        lines = []
        lines.append(f"# {symbol.upper()} 双轨制数据抓取命令清单")
        lines.append(f"# 市场场景: {pre_calc.get('scenario', 'N/A')}")
        lines.append("")
        
        current_group = None
        group_num = 0
        for cmd in commands:
            group = cmd["group"]
            if group != current_group:
                current_group = group
                group_num += 1
                lines.append(f"#### {group_num}. {group}")
            lines.append(f"# {cmd['description']}")
            lines.append(cmd["command"])
            lines.append("")
        
        return "\n".join(lines)


# ============================================================
# 主函数：兼容 code_nodes 调用约定
# ============================================================

def main(symbol: str, pre_calc: Dict[str, Any], market_params: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    generator = CommandListGenerator()
    return generator.generate(symbol, pre_calc, market_params)


# ============================================================
# 便捷函数：直接获取命令文本
# ============================================================

def generate_command_list(
    symbol: str,
    pre_calc: Dict[str, Any],
    market_params: Optional[Dict[str, Any]] = None
) -> str:
    """
    便捷函数：直接返回命令清单文本
    """
    result = main(symbol, pre_calc, market_params)
    return result.get("content", "")