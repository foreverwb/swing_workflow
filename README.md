# 1. 完整分析
```
python app.py analyze -s NVDA -f data/uploads/NVDA
```
# 2. 补齐数据
```
python app.py analyze -s NVDA -f data/uploads/NVDA_补充 --mode update
```

# 3. 盘中刷新
```
python app.py refresh -s NVDA -f data/uploads/NVDA_1400 -n "收盘前观测"
```

# 4. 查看历史 -- 表格格式
```
python app.py history -s NVDA
```

# 5. 回测验证
```
python app.py backtest -s NVDA --test-date 2025-11-20 -f data/uploads/NVDA_close
```
