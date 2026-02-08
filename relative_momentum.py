"""
使用 IBKR API 计算行业ETF相对SPY的相对动量(RelMom)
实现您策略文档中的相对动量计算
"""

from ib_insync import *
import pandas as pd
import numpy as np
from datetime import datetime

class RelativeMomentumCalculator:
    """相对动量计算器"""
    
    def __init__(self, ib_connection):
        self.ib = ib_connection
        
    def get_price_data(self, symbol, duration='80 D'):
        """
        获取股票/ETF的历史价格数据
        
        参数:
        - symbol: 股票代码
        - duration: 数据长度
        
        返回:
        - DataFrame with date and close price
        """
        try:
            stock = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(stock)
            
            bars = self.ib.reqHistoricalData(
                stock,
                endDateTime='',
                durationStr=duration,
                barSizeSetting='1 day',
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )
            
            if not bars:
                print(f"⚠️ 未获取到 {symbol} 的数据")
                return None
            
            df = util.df(bars)
            df = df[['date', 'close']].copy()
            df.columns = ['date', symbol]
            
            return df
            
        except Exception as e:
            print(f"❌ 获取 {symbol} 数据失败: {e}")
            return None
    
    def calculate_relative_strength(self, industry_df, spy_df):
        """
        计算相对强度 RS(t) = Price_industry(t) / Price_spy(t)
        
        参数:
        - industry_df: 行业ETF价格数据
        - spy_df: SPY价格数据
        
        返回:
        - DataFrame with RS and RS changes
        """
        # 合并数据，确保日期对齐
        industry_symbol = [col for col in industry_df.columns if col != 'date'][0]
        spy_symbol = [col for col in spy_df.columns if col != 'date'][0]
        
        merged = pd.merge(
            industry_df,
            spy_df,
            on='date',
            how='inner'
        )
        
        # 计算相对强度 RS(t)
        merged['RS'] = merged[industry_symbol] / merged[spy_symbol]
        
        # 计算不同周期的RS变化
        # RS_5D 变化 = (RS(t) - RS(t-5)) / RS(t-5)
        merged['RS_5D_change'] = merged['RS'].pct_change(5)
        
        # RS_20D 变化
        merged['RS_20D_change'] = merged['RS'].pct_change(20)
        
        # RS_63D 变化 (约3个月)
        merged['RS_63D_change'] = merged['RS'].pct_change(63)
        
        return merged
    
    def calculate_rel_mom(self, rs_df):
        """
        计算相对动量 RelMom
        
        公式:
        RelMom = 0.45 × RS_20D变化 + 0.35 × RS_63D变化 + 0.20 × RS_5D变化
        
        参数:
        - rs_df: 包含RS变化的DataFrame
        
        返回:
        - DataFrame with RelMom column added
        """
        rs_df['RelMom'] = (
            0.45 * rs_df['RS_20D_change'] +
            0.35 * rs_df['RS_63D_change'] +
            0.20 * rs_df['RS_5D_change']
        )
        
        return rs_df
    
    def analyze_sector_vs_spy(self, sector_symbol, benchmark='SPY'):
        """
        完整分析：计算行业ETF相对SPY的相对动量
        
        参数:
        - sector_symbol: 行业ETF代码 (如 'XLK', 'XLF', 'XLE')
        - benchmark: 基准指数 (默认 'SPY')
        
        返回:
        - 完整的分析结果
        """
        print(f"\n{'='*70}")
        print(f"分析 {sector_symbol} 相对 {benchmark} 的相对动量")
        print(f"{'='*70}")
        
        # 1. 获取行业ETF数据
        print(f"\n[1/3] 获取 {sector_symbol} 数据...")
        sector_df = self.get_price_data(sector_symbol)
        
        if sector_df is None:
            return None
        
        print(f"✅ 获取到 {len(sector_df)} 天的数据")
        
        # 2. 获取SPY数据
        print(f"\n[2/3] 获取 {benchmark} 数据...")
        spy_df = self.get_price_data(benchmark)
        
        if spy_df is None:
            return None
        
        print(f"✅ 获取到 {len(spy_df)} 天的数据")
        
        # 3. 计算相对强度和相对动量
        print(f"\n[3/3] 计算相对动量...")
        
        rs_df = self.calculate_relative_strength(sector_df, spy_df)
        result_df = self.calculate_rel_mom(rs_df)
        
        # 显示最新结果
        latest = result_df.iloc[-1]
        
        # 安全处理日期格式
        date_str = latest['date'].strftime('%Y-%m-%d') if hasattr(latest['date'], 'strftime') else str(latest['date'])
        
        print(f"\n📊 {sector_symbol} vs {benchmark} 最新数据 ({date_str}):")
        print(f"   {sector_symbol} 价格: ${latest[sector_symbol]:.2f}")
        print(f"   {benchmark} 价格: ${latest[benchmark]:.2f}")
        print(f"   相对强度 RS: {latest['RS']:.4f}")
        
        print(f"\n📈 相对强度变化:")
        print(f"   RS 5日变化:  {latest['RS_5D_change']:.2%}")
        print(f"   RS 20日变化: {latest['RS_20D_change']:.2%}")
        print(f"   RS 63日变化: {latest['RS_63D_change']:.2%}")
        
        print(f"\n🎯 相对动量 RelMom: {latest['RelMom']:.2%}")
        
        # 评估相对动量强弱
        rel_mom_value = latest['RelMom']
        if rel_mom_value > 0.05:
            print("   ✅ 强势！显著跑赢大盘")
        elif rel_mom_value > 0.02:
            print("   🟢 较强，略微跑赢大盘")
        elif rel_mom_value > -0.02:
            print("   🟡 中性，与大盘同步")
        elif rel_mom_value > -0.05:
            print("   🟠 较弱，略微跑输大盘")
        else:
            print("   🔴 弱势，显著跑输大盘")
        
        return result_df
    
    def compare_multiple_sectors(self, sector_symbols, benchmark='SPY'):
        """
        批量比较多个行业ETF的相对动量
        
        参数:
        - sector_symbols: 行业ETF列表
        - benchmark: 基准指数
        
        返回:
        - 排名结果
        """
        print(f"\n{'='*70}")
        print(f"批量分析多个行业ETF相对 {benchmark} 的动量")
        print(f"{'='*70}")
        
        results = []
        
        for sector in sector_symbols:
            print(f"\n处理 {sector}...")
            
            result_df = self.analyze_sector_vs_spy(sector, benchmark)
            
            if result_df is not None:
                latest = result_df.iloc[-1]
                results.append({
                    'sector': sector,
                    'price': latest[sector],
                    'RS': latest['RS'],
                    'RS_5D': latest['RS_5D_change'],
                    'RS_20D': latest['RS_20D_change'],
                    'RS_63D': latest['RS_63D_change'],
                    'RelMom': latest['RelMom']
                })
            
            self.ib.sleep(1)  # 避免请求过快
        
        # 创建排名DataFrame
        ranking_df = pd.DataFrame(results)
        
        # 按RelMom排序
        ranking_df = ranking_df.sort_values('RelMom', ascending=False)
        
        return ranking_df
    



# ============= 使用示例 =============

if __name__ == "__main__":
    
    # 连接IBKR
    ib = IB()
    ib.connect('127.0.0.1', 4002, clientId=1)
    ib.reqMarketDataType(3)  # 延迟数据
    
    print("✅ 已连接到 IBKR")
    
    # 创建计算器
    calc = RelativeMomentumCalculator(ib)
    
    # ===== 示例1: 单个行业ETF分析 =====
    print("\n" + "="*70)
    print("示例1: XLK 相对动量分析")
    print("="*70)
    
    xlk_result = calc.analyze_sector_vs_spy('XLK', 'SPY')
    
    # ===== 示例2: 批量比较多个行业ETF =====
    print("\n" + "="*70)
    print("示例2: 多个行业ETF相对动量排名")
    print("="*70)
    
    sector_etfs = ['XLK', 'XLV']
    
    ranking = calc.compare_multiple_sectors(sector_etfs, 'SPY')
    
    if ranking is not None and not ranking.empty:
        print("\n📊 行业ETF相对动量排名:")
        print("="*70)
        print(ranking.to_string(index=False))
        
        # 显示Top3和Bottom3
        print(f"\n🏆 Top 3 最强行业:")
        top3 = ranking.head(3)
        for _, row in top3.iterrows():
            print(f"   {row['sector']:4s}: RelMom = {row['RelMom']:+.2%}")
        
        print(f"\n⚠️ Bottom 3 最弱行业:")
        bottom3 = ranking.tail(3)
        for _, row in bottom3.iterrows():
            print(f"   {row['sector']:4s}: RelMom = {row['RelMom']:+.2%}")
    
    # 断开连接
    ib.disconnect()
    
    print("\n" + "="*70)
    print("✅ 所有分析完成!")
    print("="*70)