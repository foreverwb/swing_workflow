### Shell Config
```
cd ~/quantitative_workflow  
echo "alias quick='python $(pwd)/app.py quick'" >> ~/.zshrc
echo "alias analyze='python $(pwd)/app.py analyze'" >> ~/.zshrc
echo "alias update='python $(pwd)/app.py update'" >> ~/.zshrc
echo "alias refresh='python $(pwd)/app.py refresh'" >> ~/.zshrc
source ~/.zshrc
```

### 生成命令清单（两种方式）
```
quick symbol -v {.vix}

---

analyze symbol -p '{"vix":18,"ivr":65,"iv30":42,"hv20":38}'  # JSON 字符串
```

### 完整分析
```
analyze symbol -f ./data/images -c symbol_20251206.json
```

### 增量更新（独立命令，更简洁）
```
update symbol -f ./data/images -c symbol_20251206.json
```

### 刷新快照
```
refresh symbol -f ./data/images -c symbol_20251206.json
```
### 生成参数模板
```
params --example -o symbol.json
```


### 数据流向

```
app.py (analyze/refresh)
    ↓ 从缓存加载 market_params + dyn_params
    ↓ 存入 env_vars
command.execute()
    ↓ 传递 market_params, dyn_params
engine.run()
    ↓ 传递给模式处理器
mode.execute(symbol, data_folder, state, market_params, dyn_params)
    ↓ 
pipeline / code_nodes (使用展开后的 env_vars)
```

```

```
