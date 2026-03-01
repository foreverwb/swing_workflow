# Swing Quant Workflow

---

## 目录

- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [命令详解](#命令详解)
- [系统架构](#系统架构)
- [核心字段说明](#核心字段说明)
- [配置说明](#配置说明)
- [项目结构](#项目结构)
- [开发指南](#开发指南)

---

## 功能特性

- **智能图表解析**: 基于 Vision AI 自动解析期权图表数据
- **四维评分系统**: Gamma Regime / Break Wall / Direction / IV 综合评分
- **场景推演**: 基于 GEX 结构推演 Trend/Range/Transition 市场场景
- **策略生成**: 自动生成保守/均衡/进取三种策略组合
- **风险管理**: 内置 0DTE 噪音检测、量价背离过滤、一票否决机制
- **盘中监控**: 支持 Refresh 模式实时监控 Gamma 漂移

---

## 快速开始

### 环境要求

- Python 3.10+
- OpenAI API Key (支持 GPT-4o/Claude 等视觉模型)

### 安装

```bash
# 克隆项目
git clone <repository-url>
cd swing_workflow

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入 API_KEY
```

### 基本使用

```bash
# 1. 生成命令清单（获取需要抓取的数据）
python app.py analyze NVDA -p '{"vix":18,"ivr":65,"iv30":42,"hv20":38}'

# 2. 完整分析（解析图表 → 生成策略）
python app.py analyze NVDA -f ./data/images --cache NVDA_20251206.json

# 3. 快速分析（自动从 VA API 获取参数）
python app.py quick NVDA -v 18.5 -f ./data -c NVDA_20251206.json

# 4. 批量准备（按日期批量生成命令清单 + 输入模板）
python app.py mass -d 2026-01-04
python app.py mass -d 2026-01-04 -s NVDA -s AAPL

# 5. 盘中刷新（监控 Gamma 漂移）
python app.py refresh NVDA -f ./data/latest -c NVDA_20251206.json
```

---

## 命令详解

### analyze - 智能分析

```bash
python app.py analyze <SYMBOL> [OPTIONS]
```

| 参数 | 简写 | 说明 | 示例 |
|------|------|------|------|
| `--folder` | `-f` | 数据文件夹路径 | `-f ./data/images` |
| `--input` | `-i` | 输入 JSON 文件路径 | `-i ./data/input.json` |
| `--params` | `-p` | 市场参数 JSON | `-p '{"vix":18,...}'` |
| `--cache` | `-c` | 缓存文件名 | `-c NVDA_20251206.json` |
| `--output` | `-o` | 输出文件路径 | `-o ./reports/` |
| `--calc-only` | - | 仅计算 cluster_strength | `--calc-only` |

**三种模式**:
1. **生成命令清单** (无 `-f`): 输出数据抓取命令
2. **完整分析** (有 `-f`): 图表解析 → 策略生成
3. **输入文件分析** (有 `-i`): 从 JSON 读取数据执行分析

### quick - 快速分析

```bash
python app.py quick <SYMBOL> -v <VIX> [-d <YYYY-MM-DD>] [OPTIONS]
```

自动从 VA API 获取 IVR/IV30/HV20 等参数。

| 参数 | 简写 | 说明 |
|------|------|------|
| `--vix` | `-v` | VIX 指数（必需） |
| `--target-date` | `-t` / `-d` | 目标日期 |
| `--folder` | `-f` | 数据文件夹 |
| `--cache` | `-c` | 缓存文件 |

> 输出目录日期规则：`data/output/{symbol}/{date}/` 中的 `date` 使用 `-d/-t` 指定日期（格式化为 `YYYYMMDD`）；未指定时使用命令执行日期。

### mass - 批量准备

```bash
python app.py mass [-d <YYYY-MM-DD>] [OPTIONS]
mass -d 2026-01-04
```

按日期批量拉取 VA 参数，并为多个 symbol 生成：
- 命令清单（Mode A 轻量流程）
- 输入模板：`data/input/<YYYY-MM-DD>/{symbol}_i_<YYYY-MM-DD>.json`

| 参数 | 简写 | 说明 |
|------|------|------|
| `--date` | `-d` | 目标日期（可选，格式 `YYYY-MM-DD`，默认当天） |
| `--symbol` | `-s` | 指定 symbol，可重复或逗号分隔（如 `-s NVDA -s AAPL` 或 `-s NVDA,AAPL`） |
| `--va-url` | - | VA API 服务地址 |
| `--model-config` | - | 模型配置文件路径 |

> 输出目录日期规则：`data/output/{symbol}/{date}/` 中的 `date` 使用 `-d` 指定日期（格式化为 `YYYYMMDD`）；未指定时使用命令执行日期。
>
> `source` 已固定为 `swing`，无需再传 `--source` 参数。
>
> 简化命令：项目根目录提供了可执行脚本 `mass`，可直接运行 `mass -d 2026-01-04`（若当前 shell 未包含项目目录到 `PATH`，请使用 `./mass -d 2026-01-04`）。

### refresh - 盘中刷新

```bash
python app.py refresh <SYMBOL> -f <FOLDER> -c <CACHE>
```

仅运行 Agent3 + Calculator，监控 Gamma 漂移并生成风控建议。

### update - 增量更新

```bash
python app.py update <SYMBOL> -f <FOLDER> -c <CACHE>
```

在现有缓存基础上补齐缺失字段。

### params - 生成参数模板

```bash
python app.py params -o params.json --example
```

---

## 系统架构

### 数据流向图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              数据输入层                                       │
│  用户上传图表 + 命令参数 (--vix, --ivr, --beta, --earning)                   │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Pre-Calculator - 市场状态计算                              │
│  计算动态参数：dyn_strikes, dyn_dte, dyn_window, scenario                    │
│  应用 micro_boundary 约束：strikes 上限、degradation gate                    │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Code 0 - 命令清单生成                                      │
│  生成数据抓取命令：!gexr, !trigger, !dexn, !vanna, !skew 等                  │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Agent 3 - 图表解析 (Vision AI)                            │
│  解析图表数据，输出结构化 JSON                                                │
│  RuntimeLabel: 为每张图片注入语义约束                                         │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Field Calculator - 字段计算引擎                            │
│  ① 验证原始字段完整性 (25 个)                                                 │
│  ② 计算衍生字段：em1_dollar, t_scale, lambda, gap_distance                   │
│  ③ Sanity Check：金融逻辑校验                                                │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
              ┌─────────────────────┴─────────────────────┐
              │                                           │
              ▼                                           ▼
┌─────────────────────────────┐           ┌─────────────────────────────────┐
│  Code 1 - 事件检测           │           │  Code 2 - 四维评分               │
│  财报/FOMC/OPEX 事件检测     │           │  Gamma/Break/Direction/IV 评分  │
└─────────────────────────────┘           └─────────────────────────────────┘
              │                                           │
              └─────────────────────┬─────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Agent 5 - 场景分析                                        │
│  基于 GEX 结构推演市场场景 (Trend/Range/Transition)                          │
│  前置验证：假突破/波动率陷阱/0DTE 噪音检测                                    │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Code 3 - 策略计算引擎                                      │
│  ① validation_flags：熔断检查、策略偏好、置信度惩罚                           │
│  ② 动态参数：strikes, DTE, Pw, RR                                            │
│  ③ R > 1.8 风险回报强制校验                                                  │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Agent 6 - 策略生成                                        │
│  生成 3 个策略：保守/均衡/进取                                               │
│  包含：legs, execution_plan, risk_management                                │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Code 4 - 策略对比                                         │
│  质量过滤 + 综合评分：EV(40%) + RAR(30%) + Pw(20%) + Quality(10%)            │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Agent 7 - 策略排序                                        │
│  应用质量过滤，输出 Top 3 策略推荐                                            │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Agent 8 + Code 5 - 报告生成                               │
│  Markdown 报告 → HTML 可视化报告                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 运行模式

| 模式 | 命令 | 说明 |
|------|------|------|
| Full | `analyze -f` | 完整分析流程 |
| Update | `update` | 增量补齐缺失字段 |
| Refresh | `refresh` | 盘中监控 Gamma 漂移 |
| Quick | `quick` | 自动获取参数的快速分析 |
| Mass | `mass -d` | 按日期批量准备命令清单与输入模板 |

---

## 核心字段说明

### 原始字段 (25个)

#### 顶层字段 (2个)
| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | string | 股票代码 |
| `spot_price` | number | 当前股价 |

#### walls (3个)
| 字段 | 类型 | 说明 |
|------|------|------|
| `call_wall` | number | Call Wall 价格 |
| `put_wall` | number | Put Wall 价格 |
| `major_wall` | number | 主要阻力/支撑墙 |

#### gamma_metrics (8个)
| 字段 | 类型 | 说明 |
|------|------|------|
| `vol_trigger` | number | Gamma Flip 价格 |
| `spot_vs_trigger` | string | "above" / "below" |
| `net_gex` | number | 净 Gamma 敞口 |
| `gap_distance_dollar` | number | 距最近墙的距离 ($) |
| `nearby_peak.price` | number | 最近峰值价格 |
| `nearby_peak.abs_gex` | number | 最近峰值 GEX |
| `next_cluster_peak.price` | number | 次要峰值价格 |
| `next_cluster_peak.abs_gex` | number | 次要峰值 GEX |

#### directional_metrics (6个)
| 字段 | 类型 | 说明 |
|------|------|------|
| `dex_bias` | string | DEX 方向偏好 |
| `dex_bias_strength` | string | DEX 强度 |
| `vanna_dir` | string | Vanna 方向 |
| `vanna_confidence` | string | Vanna 置信度 |
| `iv_path` | string | IV 路径 |
| `iv_path_confidence` | string | IV 路径置信度 |

#### atm_iv (3个)
| 字段 | 类型 | 说明 |
|------|------|------|
| `iv_7d` | number | 7日 ATM IV |
| `iv_14d` | number | 14日 ATM IV |
| `iv_source` | string | IV 数据来源 |

#### validation_metrics (2个，可选)
| 字段 | 类型 | 说明 |
|------|------|------|
| `net_volume_signal` | string | 净成交量方向 |
| `net_vega_exposure` | string | Dealer Vega 敞口 |

### 计算字段

| 字段 | 公式 |
|------|------|
| `em1_dollar` | Spot × min(IV_7d, IV_14d) × √(1/252) × λ |
| `t_scale` | (HV20 / IV30)^0.8 |
| `lambda` | 1 + k_sys × VIX_premium + k_idiosync × IVR_premium |
| `gap_distance_em1_multiple` | gap_distance_dollar / em1_dollar |
| `cluster_strength_ratio` | nearby_peak.abs_gex / next_cluster_peak.abs_gex |

---

## 配置说明

### env_config.yaml

```yaml
gamma:
  em1_sqrt_factor: 0.063          # √(1/252)
  monthly_cluster_strength_ratio: 1.5  # 月度结构覆盖阈值
  
beta:
  default_beta: 1.0
  sector_defaults:
    tech: 1.2
    financials: 1.1
    utilities: 0.7
  sensitivity:
    high_beta_threshold: 1.3
    low_beta_threshold: 0.7

validation:
  zero_dte_noise_threshold: 0.5
  confidence_penalty_rate: 0.3
```

### model_config.yaml

```yaml
default:
  provider: openai
  model: gpt-4o
  temperature: 0.3
  max_tokens: 4096

agents:
  agent3:
    model: gpt-4o
    temperature: 0.1
    supports_vision: true
```

---

## 项目结构

```
swing_workflow/
├── app.py                    # CLI 入口
├── requirements.txt          # 依赖清单
├── config/                   # 配置文件
│   ├── env_config.yaml       # 环境配置
│   ├── model_config.yaml     # 模型配置
│   ├── cmdlist_config.yaml   # 命令清单配置
│   └── runtime_label_config.yaml  # RuntimeLabel 配置
├── commands/                 # CLI 命令处理器
│   ├── analyze_command.py
│   ├── quick_command.py
│   ├── mass_command.py
│   ├── refresh_command.py
│   ├── backtest_command.py
│   └── history_command.py
├── core/                     # 核心模块
│   ├── model_client.py       # API 客户端
│   ├── file_handler.py       # 文件处理
│   ├── error_handler.py      # 错误处理
│   └── workflow/             # 工作流引擎
│       ├── engine.py         # 主引擎
│       ├── pipeline.py       # 分析流水线
│       ├── cache_manager.py  # 缓存管理
│       ├── state_manager.py  # 状态管理
│       ├── drift_engine.py   # Gamma 漂移引擎
│       └── modes/            # 运行模式
├── code_nodes/               # 计算节点
│   ├── pre_calculator.py     # 市场状态计算
│   ├── field_calculator.py   # 字段计算引擎
│   ├── code0_cmdlist.py      # 命令清单生成
│   ├── code1_event_detection.py  # 事件检测
│   ├── code2_scoring.py      # 四维评分
│   ├── code3_strategy_calc.py    # 策略计算
│   ├── code4_comparison.py   # 策略对比
│   ├── code5_report_html.py  # HTML 报告
│   ├── code_input_calc.py    # 输入文件计算
│   └── runtime_label_builder.py  # RuntimeLabel 构建
├── prompts/                  # Agent Prompt
│   ├── agent3_validate.py
│   ├── agent5_scenario.py
│   ├── agent6_strategy.py
│   ├── agent7_comparison.py
│   └── agent8_report.py
├── schemas/                  # JSON Schema
│   ├── agent3_schema.py
│   ├── agent5_schema.py
│   ├── agent6_schema.py
│   └── agent7_schema.py
├── utils/                    # 工具函数
│   ├── config_loader.py      # 配置加载器
│   ├── console_printer.py    # 控制台美化
│   ├── formatters.py         # 安全格式化
│   ├── validators.py         # 数据验证
│   ├── helpers.py            # 辅助函数
│   └── va_client.py          # VA API 客户端
├── tests/                    # 测试
│   └── test_boundary_integration.py  # micro_boundary 集成测试
├── logs/                     # 日志目录
└── data/                     # 数据目录
    ├── output/               # 分析输出
    └── temp/                 # 临时缓存
```

---

## 开发指南

### 代码风格

- 遵循 PEP 8 规范
- 使用 Type Hints
- Docstring 格式: Google Style

### 运行测试

```bash
# 语法检查
python -m py_compile app.py

# 单元测试（boundary 集成）
python -m pytest tests/test_boundary_integration.py -v

# 静态分析
pip install vulture
vulture . --min-confidence 80
```

### 添加新的 Code Node

1. 在 `code_nodes/` 创建新文件
2. 实现 `main(**kwargs) -> dict` 函数
3. 在 `code_nodes/__init__.py` 导出
4. 在 `pipeline.py` 中添加步骤

### 添加新的 Agent

1. 在 `prompts/` 创建 Prompt 文件
2. 在 `schemas/` 创建 JSON Schema
3. 在 `model_config.yaml` 添加配置
4. 在 `pipeline.py` 中调用

---

## 许可证

MIT License

---

## 更新日志

### v2.0.0 (2025-12)

- 新增 RuntimeLabel 机制，提升图表解析准确性
- 重构 Calculator 模块，支持 Lambda 扩展系数
- 新增 Drift Engine 盘中监控
- 优化错误处理和美化输出
- 修复代码冗余问题

### v2.1.0 (2026-01)

- **[Task 3] micro_boundary 集成**
  - `MarketStateCalculator.calculate_fetch_params()` 新增 `boundary` 参数，消费 Bridge 下发的 `micro_boundary` 字段
  - `_apply_boundary_constraints()` 实现 strikes 上限约束（`effective_strikes`）和 swing overlay 建议值约束（只缩不扩）
  - `MassCommand.execute()` 新增 degradation gate：`blocked` 模式的 symbol 跳过并记录 `BOUNDARY_BLOCKED` 错误
  - `partial` / `fallback` 模式 symbol 继续执行，strikes/window 受 boundary 约束
  - 日志增强：输出 `boundary_mode` 和约束后的 `dyn_strikes`
  - 向后兼容：无 boundary 或 `boundary=None` / `boundary={}` 时行为与改造前完全一致
  - 新增 `tests/test_boundary_integration.py` 单元测试
