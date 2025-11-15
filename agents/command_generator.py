"""
Agent 2 - 命令生成器
根据股票代码生成数据抓取命令清单
"""

from typing import Dict
from utils.logger import setup_logger

logger = setup_logger(__name__)


class CommandGenerator:
    """命令生成器"""
    
    def __init__(self, llm_client, config):
        self.llm_client = llm_client
        self.config = config
        self.model = config.MODEL_COMMAND
    
    def generate(self, symbol: str) -> Dict:
        """
        生成数据抓取命令清单
        
        Args:
            symbol: 股票代码
        
        Returns:
            命令清单字典
        """
        try:
            logger.info(f"🤖 Agent 2: 为 {symbol} 生成命令清单...")
            
            # 构造 System Prompt
            system_prompt = self._build_system_prompt()
            
            # 构造 User Prompt
            user_prompt = f"请立即为 {symbol} 生成命令清单。"
            
            # 调用 LLM
            response = self.llm_client.chat_completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=2000
            )
            
            # 解析响应
            commands_text = response.get("text", "")
            
            logger.info(f"✅ 命令清单生成完成")
            
            return {
                "symbol": symbol,
                "commands": commands_text,
                "summary": f"为 {symbol} 生成了完整的数据抓取命令清单"
            }
            
        except Exception as e:
            logger.error(f"❌ 命令生成失败: {e}", exc_info=True)
            raise
    
    def _build_system_prompt(self) -> str:
        """构造 System Prompt"""
        env = self.config
        
        return f"""你是一个美股期权分析助手。你的唯一任务是根据用户提供的代码,严格按照【数据抓取命令清单】的格式,为每个标的(和指数)生成一个清晰的、可供用户复制粘贴去执行的命令列表。

                【预处理】
                1. 提取代码:例如 "amzn us, QQQ" -> ["AMZN", "QQQ"]
                2. 大写去重。

                【数据抓取命令清单】
                ### 必跑命令（按顺序执行）
                **1. 墙与簇识别**
                !gexr {{SYMBOL}} {env.DEFAULT_STRIKES} {env.DEFAULT_DTE_WEEKLY_SHORT} w 
                !gexr {{SYMBOL}} {env.DEFAULT_STRIKES} {env.DEFAULT_DTE_WEEKLY_MID} w

                **2. 净Γ与零Γ**
                !gexn {{SYMBOL}} {env.DEFAULT_NET_WINDOW} 98 
                !trigger {{SYMBOL}} {env.DEFAULT_NET_WINDOW}

                **3. DEX方向一致性**
                !dexn {{SYMBOL}} {env.DEFAULT_STRIKES} {env.DEFAULT_DTE_WEEKLY_MID} w

                **4. Vanna**
                !vanna {{SYMBOL}} ntm {env.DEFAULT_NET_WINDOW} m

                **5. 波动率**
                !skew {{SYMBOL}} ivmid atm {env.DEFAULT_DTE_WEEKLY_SHORT} 
                !skew {{SYMBOL}} ivmid atm {env.DEFAULT_DTE_WEEKLY_MID} 
                !skew {{SYMBOL}} ivmid ntm {env.DEFAULT_DTE_WEEKLY_MID} w 
                !term {{SYMBOL}} {env.DEFAULT_NET_WINDOW}

                ### 扩展命令（条件触发）
                **若周度簇稀疏或月度主导**： 
                !gexr {{SYMBOL}} {env.DEFAULT_STRIKES} {env.DEFAULT_DTE_MONTHLY_SHORT} m 

                **若需更远到期影响**： 
                !gexn {{SYMBOL}} {env.EXTENDED_NET_WINDOW} 98 
                !dexn {{SYMBOL}} {env.DEFAULT_STRIKES} {env.DEFAULT_DTE_MONTHLY_SHORT} w

                **若7D ATM-IV噪声大**（与14D差异>{env.IV_NOISE_THRESHOLD}%）：
                !skew {{SYMBOL}} ivmid atm 21 

                **验证Vanna稳定性**：
                !vanna {{SYMBOL}} ntm {env.DEFAULT_DTE_MONTHLY_SHORT} m 

                **解释可选**：
                !vexn {{SYMBOL}} {env.DEFAULT_DTE_MONTHLY_SHORT} 190

                ### 指数背景（必需）
                **{env.DEFAULT_INDEX_PRIMARY}（主要指数）**：
                !gexn {env.DEFAULT_INDEX_PRIMARY} {env.DEFAULT_DTE_MONTHLY_SHORT} 98 
                !trigger {env.DEFAULT_INDEX_PRIMARY} {env.DEFAULT_NET_WINDOW} 
                !skew {env.DEFAULT_INDEX_PRIMARY} ivmid atm {env.DEFAULT_DTE_WEEKLY_SHORT} 
                !skew {env.DEFAULT_INDEX_PRIMARY} ivmid atm {env.DEFAULT_DTE_WEEKLY_MID} 

                **{env.DEFAULT_INDEX_SECONDARY}（可选，科技股）**：
                !gexn {env.DEFAULT_INDEX_SECONDARY} {env.DEFAULT_DTE_MONTHLY_SHORT} 98 
                !skew {env.DEFAULT_INDEX_SECONDARY} ivmid atm {env.DEFAULT_DTE_WEEKLY_SHORT} 
                !skew {env.DEFAULT_INDEX_SECONDARY} ivmid atm {env.DEFAULT_DTE_WEEKLY_MID}

                ### iv_path
                ** iv_path: 比较今日 7D ATM-IV 与昨日/前三日,存档数据获取

                ### 回传要求 
                ✓ **每张图/输出请注明**： 
                    - 命令全文 
                    - 收盘价与当日变动（可选） 
                ✓ **若任一必跑命令输出为空或异常**： 
                    - 请直接说明，我会给替代口径 
                ✓ **数据完整性检查**： 
                    - 确保包含SPOT PRICE 
                    - 确保包含Call/Put Wall标注 
                    - 确保包含VOL_TRIGGER或Gamma Flip数值 

                --- 

                请立即为 {{SYMBOL}} 生成命令清单。
                """