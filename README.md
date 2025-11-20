# 1. 生成命令清单
python app.py cmdlist --symbol NVDA

# 2. 完整分析（首次）
python app.py analyze --symbol NVDA --json data/NVDA_20251119.json --output reports/NVDA.md

# 3. 盘中刷新
python app.py analyze --symbol NVDA --json data/NVDA_20251119.json --triggered
```
quantitative_workflow
├─ README.md
├─ app.py
├─ code_nodes
│  ├─ __init__.py
│  ├─ code1_event_detection.py
│  ├─ code2_scoring.py
│  ├─ code3_strategy_calc.py
│  ├─ code4_comparison.py
│  └─ code_aggregator.py
├─ config
│  ├─ env_config.yaml
│  └─ model_config.yaml
├─ core
│  ├─ __init__.py
│  ├─ file_handler.py
│  ├─ model_client.py
│  └─ workflow_engine.py
├─ data
│  ├─ commands
│  │  ├─ NVDA_commands_20251119_145723.txt
│  │  └─ NVDA_commands_20251119_155755.txt
│  ├─ input
│  │  └─ NVDA_20251119.json
│  └─ output
├─ logs
│  └─ logger.py
├─ prompts
│  ├─ __init__.py
│  ├─ agent2_cmdlist.py
│  ├─ agent3_validate.py
│  ├─ agent5_scenario.py
│  ├─ agent6_strategy.py
│  ├─ agent7_comparison.py
│  └─ agent8_report.py
├─ requirements.txt
├─ schemas
│  ├─ __init__.py
│  ├─ agent3_schema.py
│  ├─ agent5_schema.py
│  ├─ agent6_schema.py
│  └─ agent7_schema.py
└─ utils
   ├─ __init__.py
   ├─ config_loader.py
   └─ helpers.py

```