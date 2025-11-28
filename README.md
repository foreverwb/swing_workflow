# 1. 完整分析
```
python app.py analyze -s {SYMBOL} -f ./data/images --mode full
```
# 2. 补齐数据
```
python app.py analyze -s {SYMBOL} -f ./data/images --mode update --cache {SYMBOL + datetime}.json
```

# 3. 盘中刷新
```
python app.py refresh -s {SYMBOL} -f ./data/images --cache {SYMBOL + datetime}.json
```

# 4. 查看历史 -- 表格格式
```
python app.py history -s {SYMBOL}
```

# 5. 回测验证
```
python app.py backtest -s {SYMBOL} --test-date 2025-11-20 -f data/uploads/NVDA_close
```
