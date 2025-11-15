"""
数据校验 Agent - Agent 3
负责解析期权图表、计算指标、三级验证
"""

from typing import Dict, List, Any
from pathlib import Path
from models.llm_client import LLMClient
from utils.logger import setup_logger

logger = setup_logger(__name__)


class DataValidatorAgent:
    """
    Agent 3: 数据校验与指标计算
    - 解析期权数据图表 (GEX/DEX/Vanna/IV/Skew)
    - 提取技术面指标 (EMA/RSI/BB/MACD/Volume)
    - 计算核心指标 (EM1$/gap距离/簇强度等)
    - 执行三级数据验证
    - 生成补齐索引 (若数据缺失)
    """
    
    def __init__(self, config):
        self.config = config
        self.llm_client = LLMClient(config)
        self.model = config.MODEL_DATA_VALIDATOR
        
        # ✅ System Prompt 模板 (包含占位符)
        self.system_prompt_template = """
你是期权结构和波动率特征图像解析器、数据校验和计算 Agent。

【核心任务】:
1. 解析期权数据图表(GEX/DEX/Vanna/IV/Skew)
2. 提取技术面指标(EMA/RSI/BB/MACD/Volume)
3. 计算核心指标(EM1$/gap距离/簇强度等)
4. 执行三级数据验证
5. 生成补齐索引(若数据缺失)

【目标】: 输出标准数据并严格按照【数据口径与指标定义】计算所有核心字段

【系统环境变量 - 计算参数】
- EM1$计算因子:sqrt(1/252) = {EM1_SQRT_FACTOR}
- 破墙阈值下限:{BREAK_WALL_THRESHOLD_LOW} × EM1$
- 破墙阈值上限:{BREAK_WALL_THRESHOLD_HIGH} × EM1$
- 月度占优阈值系数:{MONTHLY_OVERRIDE_THRESHOLD}
- 月度簇强度触发比:{MONTHLY_CLUSTER_STRENGTH_RATIO}
- 簇强度趋势阈值:{CLUSTER_STRENGTH_THRESHOLD_TREND}
- 簇强度极强阈值:{CLUSTER_STRENGTH_THRESHOLD_STRONG}
- 墙识别峰值倍数:{WALL_PEAK_MULTIPLIER}
- 墙识别簇宽度:{WALL_CLUSTER_WIDTH}
- DEX强信号阈值:{DEX_SAME_DIR_THRESHOLD_STRONG}%
- DEX中等信号阈值:{DEX_SAME_DIR_THRESHOLD_MEDIUM}%
- IV路径阈值:{IV_PATH_THRESHOLD_VOL} vol 或 {IV_PATH_THRESHOLD_PCT}%
- IV噪声阈值:{IV_NOISE_THRESHOLD}%
- 默认strikes:{DEFAULT_STRIKES}
- 默认NET窗口:{DEFAULT_NET_WINDOW}天

## 阶段 1: 数据提取规则

### 1.1 期权核心数据(22 必需字段)

#### A. 基础价格数据
- **spot_price**: 当前标的价格,从图表标题或最新K线提取
- **em1_dollar**: 预期单日波幅美元值
  - 公式: `Spot × min(ATM_IV_7D, ATM_IV_14D) × {EM1_SQRT_FACTOR}`
  - 优先使用 7D ATM-IV
  - 若 7D 与 14D 差异 > {IV_NOISE_THRESHOLD}%,则用 14D

#### B. 墙与簇识别
从 `!gexr SYMBOL {DEFAULT_STRIKES} 7w` 和 `14w` 输出识别:

**墙识别规则**:
- 局部峰 ≥ 相邻 γ 中位数 × {WALL_PEAK_MULTIPLIER} 倍
- 且簇宽 ≥ {WALL_CLUSTER_WIDTH} 个相邻行权价

**输出字段**:
- **call_wall**: 看涨期权墙价位
- **put_wall**: 看跌期权墙价位
- **major_wall**: Call/Put 墙中 GEX 绝对值更大者
- **major_wall_type**: "call" 或 "put"

#### C. Gamma 状态判定
从 `!trigger SYMBOL {DEFAULT_NET_WINDOW}` 提取:

- **vol_trigger**: Gamma 翻转价位(VOL_TRIGGER 或 Gamma Flip)
- **spot_vs_trigger**: 现价相对触发线位置
  - 若 SPOT > VOL_TRIGGER: "above"
  - 若 SPOT < VOL_TRIGGER: "below"
  - 若 SPOT 接近 VOL_TRIGGER (±0.3×EM1$): "near"

从 `!gexn SYMBOL {DEFAULT_NET_WINDOW} 98` 提取:
- **net_gex**: NET-GEX 数值
- **net_gex_sign**: 净 Gamma 符号
  - NET-GEX < 0: "negative_gamma"
  - NET-GEX > 0: "positive_gamma"
  - NET-GEX ≈ 0: "neutral"

#### D. 距离与强度指标
从 `!gexr` 输出的 ABS_GEX 分布计算:

- **gap_distance_dollar**: 当前价到下一 ABS_GEX 峰簇的美元距离
  - 方向: 若 spot_vs_trigger="above" 向上看 Call_Wall
  - 方向: 若 spot_vs_trigger="below" 向下看 Put_Wall

- **gap_distance_em1_multiple**: gap_distance_dollar ÷ EM1$

- **cluster_strength_ratio**: 主墙 GEX 绝对值 ÷ 次墙 GEX 绝对值
  - 若仅单峰无对照,补跑 `!gexr SYMBOL {DEFAULT_STRIKES} {DEFAULT_DTE_MONTHLY_SHORT} m`
  - 或延长 DTE 以寻参照峰

- **monthly_cluster_override**: 月度簇是否占优
  - 若月度簇强度 ≥ 周度 × {MONTHLY_CLUSTER_STRENGTH_RATIO}: true
  - 否则: false

#### E. 方向信号
从 `!dexn SYMBOL {DEFAULT_STRIKES} 14w` 提取:

- **dex_same_dir_pct**: gap 区间内同向 DEX 净和在 60 日历史中的分位百分比(0-100)

从 `!vanna SYMBOL ntm {DEFAULT_NET_WINDOW} m` 提取(三级回退):
- **vanna_dir**: Vanna 方向 ("up" | "down" | "flat")
- **vanna_confidence**: Vanna 置信度 ("high" | "medium" | "low")
  - 优先: ntm 60 day monthly → confidence = "high"
  - 若缺: ntm {DEFAULT_DTE_MONTHLY_SHORT} m → confidence = "medium"
  - 若仍缺: 按 skew 与 delta 反斜临时推断 → confidence = "low"

#### F. IV 动态
从 `!skew SYMBOL ivmid atm 7` 和 `14` 提取:

- **iv_7d**: 7 日 ATM 隐含波动率(小数形式,如 0.45)
- **iv_14d**: 14 日 ATM 隐含波动率
- **iv_source**: IV 数据源 ("7d" | "14d" | "21d_fallback")
  - 优先使用 7D
  - 若 7D 与 14D 差异 > {IV_NOISE_THRESHOLD}%,则用 14D
  - 两者皆缺时补 21D

从历史 IV 数据或 `!term SYMBOL` 推断:
- **iv_path**: IV 路径趋势 ("升" | "降" | "平" | "数据不足")
  - 比较今日 7D_ATM_IV 与昨日/前三日
  - 显著阈值: ±{IV_PATH_THRESHOLD_VOL} vol 或 ±{IV_PATH_THRESHOLD_PCT}% 相对变化

- **iv_path_confidence**: IV 路径置信度 ("high" | "medium" | "low")
  - 有历史数据: "high"
  - 仅 term structure 推断: "medium"
  - Backwardation → "升", Contango → "降"

---

### 1.2 技术面数据(可选字段)

**重要**: 技术面数据完全可选,若图表未包含技术指标,不影响 status 判定。

#### A. 图表元数据
- **platform**: 识别平台(TradingView/Thinkorswim/Yahoo Finance/其他)
- **timeframe**: 时间周期(Daily/4H/1H)
- **latest_timestamp**: 最新时间戳

#### B. 价格与均线
从图表最新 K 线提取:

- **close**: 收盘价
- **ema20**: EMA20 数值
- **ema50**: EMA50 数值
- **price_vs_ema20_pct**: (close - ema20) / ema20 × 100
- **price_vs_ema50_pct**: (close - ema50) / ema50 × 100
- **ema20_slope**: EMA20 斜率("上行" | "走平" | "下行")
- **ema50_slope**: EMA50 斜率
- **golden_cross**: 是否金叉(ema20 > ema50: true)

#### C. RSI 指标
- **rsi_value**: RSI(14) 当前值
- **rsi_zone**: RSI 区间("超买" | "中性偏强" | "中性" | "中性偏弱" | "超卖")
- **rsi_divergence**: 背离形态("顶背离" | "底背离" | "无")

#### D. 布林带
- **bb_width**: BB 宽度(上轨 - 下轨)
- **bb_width_percentile**: 当前宽度在历史中的分位(0-100)
- **bb_position**: 价格相对布林带位置("上轨上方" | "中轨上方" | "中轨" | "中轨下方" | "下轨下方")
- **bb_band_direction**: 带口方向("扩张" | "平行" | "收缩")

#### E. MACD
- **macd_histogram**: 柱状图趋势("正值扩大" | "正值收敛" | "负值扩大" | "负值收敛")
- **macd_signal_line_cross**: 快慢线交叉("金叉后第N日" | "死叉后第N日" | "无交叉")
- **macd_zero_line**: 相对零轴位置("上方" | "下方" | "接近零轴")

#### F. 成交量
- **volume_current**: 当前成交量
- **volume_avg_20d**: 20 日平均成交量
- **volume_ratio**: current / avg_20d
- **volume_status**: 成交量状态("显著放量" | "温和放量" | "正常" | "缩量")

#### G. 技术面评分
根据以下规则计算 **ta_score**(0-2 分,最多 +2):

**评分规则**:
- EMA 判断(最多 +1):
  - EMA20/50 发散向上且 golden_cross=true → +1
  - EMA20/50 走平或粘合 → +1
  - 其他 → 0

- RSI 判断(最多 +1):
  - RSI > 60 且无顶背离 → +1
  - RSI 在 40-60 → +1
  - RSI 背离 → -1

- BB 判断(最多 +1,可叠加但总分上限 2):
  - BB 宽度低分位 + 同向开口 → +1(择一计分)

**评分上限**: 最多累计 +2 分

**ta_commentary**: 简述评分理由(不超过 80 字)

---

## 阶段 2: 指数背景数据(低优先级)

默认 {DEFAULT_INDEX_PRIMARY}(SPX),必要时 {DEFAULT_INDEX_SECONDARY}(QQQ)。

从 `!gexn SPX {DEFAULT_DTE_MONTHLY_SHORT} 98` 和 `!trigger SPX {DEFAULT_NET_WINDOW}` 提取:

- **indices.spx.net_gex_idx**: SPX 的 NET-GEX
- **indices.spx.spot_idx**: SPX 现价

从 `!skew SPX ivmid atm 7` 和 `14` 计算:
- **indices.spx.em1_dollar_idx**: SPX 的 EM1$

同理处理 QQQ(可选)。

**重要**: 若指数数据全为 -999,不影响 status 判定,仅在 validation_summary.warnings 中标注。

---

## 阶段 3: 数据验证与状态判定

### 三级验证规则(决策树)

```
第一级:检查 22 个必需字段
  ├─ 若任一字段为 -999/null/"N/A"/"数据不足"
  │   └─ status = "missing_data"
  └─ 若全部有效
      └─ 进入第二级

第二级:检查指数背景
  ├─ 若 SPX 和 QQQ 全为 -999
  │   ├─ 添加 warning: "⚠️ 指数背景数据缺失,不影响个股分析"
  │   └─ 继续第三级
  └─ 若至少一个指数有效
      └─ 进入第三级

第三级:检查技术面(可选)
  ├─ 若 technical_analysis 不存在或 ta_score = 0
  │   └─ 添加 warning: "💡 技术面数据缺失,仅影响评分"
  └─ 最终 status = "data_ready"
```

### status 最终判定

**唯一判定标准**: 22 个必需字段是否全部有效

- 若全部有效 → `status = "data_ready"`
- 若任一缺失 → `status = "missing_data"`

**次要字段(不影响 status)**:
- 指数背景(indices): 缺失时仅警告
- 技术面(technical_analysis): 缺失时仅警告

---

## 阶段 4: 补齐索引生成(仅 status="missing_data" 时)

### 优先级定义

**Priority 1 (Critical)**: 影响 Gamma Regime 判断
- vol_trigger
- spot_vs_trigger
- net_gex
- net_gex_sign

**Priority 2 (High)**: 影响核心计算
- em1_dollar
- gap_distance_dollar
- gap_distance_em1_multiple
- call_wall / put_wall

**Priority 3 (Medium)**: 影响方向判断
- dex_same_dir_pct
- vanna_dir / vanna_confidence
- iv_path / iv_path_confidence

**Priority 4-5 (Low/Optional)**: 补充性字段
- cluster_strength_ratio
- monthly_cluster_override

### 补齐索引格式

为每个缺失字段生成:

- **missing_field**: 字段名
- **description**: 字段说明
- **command**: 建议执行的命令
- **alternative**: 备选方案
- **extraction_note**: 数据提取说明
- **priority**: 优先级(1-5)
- **impact**: 缺失影响说明

---

## 阶段 5: 输出规范

### 关键原则

1. **严格依赖 JSON Schema**: 不要在 prompt 中写 JSON 示例
2. **使用占位符**: 所有环境变量的引用
3. **自然语言描述**: 用决策树/规则描述,不用 Python 代码块
4. **状态一致性**: validation_summary 必须与 status 一致

### 数据质量标注

#### validation_summary 字段说明

- **total_targets**: 1(固定)
- **targets_ready**: status="data_ready" ? 1 : 0
- **total_fields_required**: 22(固定)
- **fields_provided**: 实际提供的有效字段数
- **missing_count**: 缺失字段数量
- **completion_rate**: fields_provided / 22 × 100

#### 新增字段(可选)

- **optional_fields_provided**: 技术面字段提供数量
- **background_fields_provided**: 指数背景字段提供数量
- **warnings**: 警告信息列表

---

## 关键注意事项

### 异常处理

1. **图表模糊不清**:
   - 在 chart_metadata 中标注 `"chart_quality": "low"`
   - 在 validation_summary.warnings 中说明

2. **无法识别平台**:
   - `"platform": "unknown"`

3. **缺失核心指标**:
   - 若 RSI 不可用: `"indicators_raw.rsi.available": false`

### 数据规范

1. **价格精度**: 保留 2 位小数
2. **百分比**: 保留 1 位小数(如 1.5%)
3. **比率**: 保留 2 位小数(如 3.25)
4. **RSI/IV**: 保留小数形式(0.45 而非 45%)

### 状态一致性检查

最终输出前验证:
- `targets.status` 必须与顶层 `status` 一致
- `missing_fields` 数组长度必须等于 `validation_summary.missing_count`
- `status="data_ready"` 时,`missing_fields` 和 `补齐索引` 必须为空数组

---

## 输出流程

1. 识别图表类型和时间周期
2. 提取所有可见的期权数据和技术指标
3. 执行三级数据验证
4. 计算 validation_summary
5. 若 status="missing_data",生成补齐索引
6. 输出符合 JSON Schema 的结构化数据

**重要**: 
- 不要尝试"记忆"之前的数据,专注于解析当前上传的图表内容。下游会自动聚合多次解析的结果。
- 无论图表内容如何,targets 字段必须返回字典格式,不能返回空列表 []
- 如果图表中没有可识别的数据,应该返回: { "targets": { "symbol": "UNKNOWN", "status": "missing_data", "spot_price": -999, ... } }
- 禁止返回: {"targets": []} 或 {"targets": null}
"""
    
    def validate(self, user_query: str, uploaded_files: List[str]) -> Dict:
        """
        执行数据校验
        
        Args:
            user_query: 用户查询
            uploaded_files: 上传的图表文件列表
        
        Returns:
            JSON Schema 格式的校验结果
        """
        logger.info(f"开始数据校验,文件数: {len(uploaded_files)}")
        
        # ✅ 插入环境变量到 prompt
        env_vars = self._get_env_vars_dict()
        formatted_prompt = self.system_prompt_template.format(**env_vars)
        
        # 构造消息 (包含图片)
        user_content = [
            {"type": "text", "text": f"{user_query}\n【上传文件】\n{self._format_files(uploaded_files)}"}
        ]
        
        # 添加图片
        for file_path in uploaded_files:
            if Path(file_path).exists():
                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"file://{file_path}",
                        "detail": "high"  # 高精度解析
                    }
                })
        
        messages = [
            {"role": "system", "content": formatted_prompt},
            {"role": "user", "content": user_content}
        ]
        
        # 调用 LLM (Vision + Structured Output)
        try:
            response = self.llm_client.chat_completion(
                model=self.model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": self._get_schema()
                },
                temperature=0.3,
                max_tokens=self.config.MODEL_MAX_TOKENS
            )
            
            logger.info(f"数据校验完成,状态: {response.get('status', 'unknown')}")
            return response
            
        except Exception as e:
            logger.error(f"数据校验失败: {e}", exc_info=True)
            # 返回错误格式
            return {
                "status": "missing_data",
                "error": str(e),
                "targets": {
                    "symbol": "UNKNOWN",
                    "status": "missing_data",
                    "spot_price": -999,
                    "em1_dollar": -999,
                    "walls": {
                        "call_wall": -999,
                        "put_wall": -999,
                        "major_wall": -999,
                        "major_wall_type": "N/A"
                    },
                    "gamma_metrics": {},
                    "directional_metrics": {},
                    "atm_iv": {}
                }
            }
    
    def _get_env_vars_dict(self) -> Dict[str, Any]:
        """
        获取环境变量字典 (用于格式化 prompt)
        
        Returns:
            {变量名: 值} 字典
        """
        return {
            "EM1_SQRT_FACTOR": self.config.EM1_SQRT_FACTOR,
            "BREAK_WALL_THRESHOLD_LOW": self.config.BREAK_WALL_THRESHOLD_LOW,
            "BREAK_WALL_THRESHOLD_HIGH": self.config.BREAK_WALL_THRESHOLD_HIGH,
            "MONTHLY_OVERRIDE_THRESHOLD": self.config.MONTHLY_OVERRIDE_THRESHOLD,
            "MONTHLY_CLUSTER_STRENGTH_RATIO": self.config.MONTHLY_CLUSTER_STRENGTH_RATIO,
            "CLUSTER_STRENGTH_THRESHOLD_TREND": self.config.CLUSTER_STRENGTH_THRESHOLD_TREND,
            "CLUSTER_STRENGTH_THRESHOLD_STRONG": self.config.CLUSTER_STRENGTH_THRESHOLD_STRONG,
            "WALL_PEAK_MULTIPLIER": self.config.WALL_PEAK_MULTIPLIER,
            "WALL_CLUSTER_WIDTH": self.config.WALL_CLUSTER_WIDTH,
            "DEX_SAME_DIR_THRESHOLD_STRONG": self.config.DEX_SAME_DIR_THRESHOLD_STRONG,
            "DEX_SAME_DIR_THRESHOLD_MEDIUM": self.config.DEX_SAME_DIR_THRESHOLD_MEDIUM,
            "IV_PATH_THRESHOLD_VOL": self.config.IV_PATH_THRESHOLD_VOL,
            "IV_PATH_THRESHOLD_PCT": self.config.IV_PATH_THRESHOLD_PCT,
            "IV_NOISE_THRESHOLD": self.config.IV_NOISE_THRESHOLD,
            "DEFAULT_STRIKES": self.config.DEFAULT_STRIKES,
            "DEFAULT_NET_WINDOW": self.config.DEFAULT_NET_WINDOW,
            "DEFAULT_DTE_MONTHLY_SHORT": self.config.DEFAULT_DTE_MONTHLY_SHORT,
            "DEFAULT_INDEX_PRIMARY": self.config.DEFAULT_INDEX_PRIMARY,
            "DEFAULT_INDEX_SECONDARY": self.config.DEFAULT_INDEX_SECONDARY
        }
    
    def _format_files(self, file_paths: List[str]) -> str:
        """格式化文件列表显示"""
        return "\n".join([f"- {Path(f).name}" for f in file_paths])
    
    def _get_schema(self) -> dict:
        """
        返回 JSON Schema (需要从 yml 手动复制完整 schema)
        这里提供简化版,完整版请从 yml 的 node 3001 复制
        """
        return {
            "name": "data_validation_result",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["data_ready", "missing_data"],
                        "description": "数据状态"
                    },
                    "timestamp": {
                        "type": "string",
                        "description": "时间戳,格式 YYYY-MM-DDTHH:mm:ss"
                    },
                    "targets": {
                        "type": "object",
                        "description": "标的数据(必须是字典,不能是数组)",
                        "properties": {
                            "symbol": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["ready", "missing_data"]
                            },
                            "spot_price": {
                                "type": "number",
                                "description": "现价,若缺失使用 -999"
                            },
                            "em1_dollar": {
                                "type": "number",
                                "description": "预期单日波幅,若缺失使用 -999"
                            },
                            "walls": {
                                "type": "object",
                                "properties": {
                                    "call_wall": {"type": "number"},
                                    "put_wall": {"type": "number"},
                                    "major_wall": {"type": "number"},
                                    "major_wall_type": {
                                        "type": "string",
                                        "enum": ["call", "put", "N/A"]
                                    }
                                },
                                "required": ["call_wall", "put_wall", "major_wall", "major_wall_type"]
                            },
                            "gamma_metrics": {
                                "type": "object",
                                "properties": {
                                    "gap_distance_dollar": {"type": "number"},
                                    "gap_distance_em1_multiple": {"type": "number"},
                                    "cluster_strength_ratio": {"type": "number"},
                                    "net_gex": {"type": "number"},
                                    "net_gex_sign": {
                                        "type": "string",
                                        "enum": ["positive_gamma", "negative_gamma", "neutral", "N/A"]
                                    },
                                    "vol_trigger": {"type": "number"},
                                    "spot_vs_trigger": {
                                        "type": "string",
                                        "enum": ["above", "below", "near", "N/A"]
                                    },
                                    "monthly_cluster_override": {"type": "boolean"}
                                },
                                "required": [
                                    "gap_distance_dollar",
                                    "gap_distance_em1_multiple",
                                    "cluster_strength_ratio",
                                    "net_gex",
                                    "net_gex_sign",
                                    "vol_trigger",
                                    "spot_vs_trigger",
                                    "monthly_cluster_override"
                                ]
                            },
                            "directional_metrics": {
                                "type": "object",
                                "properties": {
                                    "dex_same_dir_pct": {"type": "number"},
                                    "vanna_dir": {
                                        "type": "string",
                                        "enum": ["up", "down", "flat", "N/A"]
                                    },
                                    "vanna_confidence": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low", "N/A"]
                                    },
                                    "iv_path": {
                                        "type": "string",
                                        "enum": ["升", "降", "平", "数据不足"]
                                    },
                                    "iv_path_confidence": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"]
                                    }
                                },
                                "required": [
                                    "dex_same_dir_pct",
                                    "vanna_dir",
                                    "vanna_confidence",
                                    "iv_path",
                                    "iv_path_confidence"
                                ]
                            },
                            "atm_iv": {
                                "type": "object",
                                "properties": {
                                    "iv_7d": {"type": "number"},
                                    "iv_14d": {"type": "number"},
                                    "iv_source": {
                                        "type": "string",
                                        "enum": ["7d", "14d", "21d_fallback", "N/A"]
                                    }
                                },
                                "required": ["iv_7d", "iv_14d", "iv_source"]
                            }
                        },
                        "required": [
                            "symbol",
                            "status",
                            "spot_price",
                            "em1_dollar",
                            "walls",
                            "gamma_metrics",
                            "directional_metrics",
                            "atm_iv"
                        ]
                    },
                    "indices": {
                        "type": "object",
                        "description": "指数背景数据(可选)",
                        "properties": {
                            "spx": {
                                "type": "object",
                                "properties": {
                                    "net_gex_idx": {"type": "number"},
                                    "em1_dollar_idx": {"type": "number"},
                                    "spot_idx": {"type": "number"}
                                }
                            },
                            "qqq": {
                                "type": "object",
                                "properties": {
                                    "net_gex_idx": {"type": "number"},
                                    "em1_dollar_idx": {"type": "number"},
                                    "spot_idx": {"type": "number"}
                                }
                            }
                        }
                    },
                    "technical_analysis": {
                        "type": "object",
                        "description": "技术面数据(可选)",
                        "properties": {
                            "ta_score": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 2
                            },
                            "ta_commentary": {"type": "string"}
                        }
                    },
                    "validation_summary": {
                        "type": "object",
                        "properties": {
                            "total_targets": {"type": "integer"},
                            "targets_ready": {"type": "integer"},
                            "total_fields_required": {"type": "integer"},
                            "fields_provided": {"type": "integer"},
                            "missing_count": {"type": "integer"},
                            "completion_rate": {"type": "integer"}
                        },
                        "required": [
                            "total_targets",
                            "targets_ready",
                            "total_fields_required",
                            "fields_provided",
                            "missing_count",
                            "completion_rate"
                        ]
                    },
                    "missing_fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "target": {"type": "string"},
                                "severity": {
                                    "type": "string",
                                    "enum": ["critical", "high", "medium", "low"]
                                },
                                "category": {"type": "string"}
                            }
                        }
                    }
                },
                "required": ["status", "timestamp", "targets", "validation_summary", "missing_fields"]
            }
        }