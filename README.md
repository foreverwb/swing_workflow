### 1. cmd list
```
python app.py analyze -s {SYMBOL}
```

### 2. full analyze
```
python app.py analyze -s {SYMBOL} -f ./data/images
```
### 3. update
```
python app.py analyze -s {SYMBOL} -f ./data/images --mode update --cache {SYMBOL + datetime}.json
```

### 3. refresh
```
python app.py refresh -s {SYMBOL} -f ./data/images --cache {SYMBOL + datetime}.json
```

### 4. history
```
python app.py history -s {SYMBOL}
```

### 5. back test verification
```
python app.py backtest -s {SYMBOL} --test-date 2025-11-20 -f data/uploads/NVDA_close
```
