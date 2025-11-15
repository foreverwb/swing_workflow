"""
配置管理模块
从 YAML workflow 转换的环境变量配置
"""

import yaml
from pathlib import Path
from typing import Dict, Any


class Config:
    """配置类，管理所有环境变量和模型配置"""
    
    # === LLM 模型配置 ===
    LLM_PROVIDER = "openai"  # 提供商: openai, anthropic, deepseek, custom
    LLM_API_KEY = "your-api-key-here"
    LLM_BASE_URL = "https://api.openai.com/v1"
    
    # 不同 Agent 使用的模型（可独立配置）
    MODEL_ROUTER = "gpt-4o-mini"
    MODEL_COMMAND_GEN = "gpt-4o-mini"
    MODEL_DATA_VALIDATOR = "gpt-4o"
    MODEL_TECHNICAL = "gpt-4o"
    MODEL_SCENARIO = "gpt-4o"
    MODEL_STRATEGY = "gpt-4o"
    MODEL_COMPARISON = "gpt-4o"
    MODEL_REPORT = "gpt-4o"
    
    # === 模型通用参数 ===
    MODEL_TEMPERATURE = 0.5
    MODEL_MAX_TOKENS = 4096
    MODEL_TOP_P = 1.0
    MODEL_FREQUENCY_PENALTY = 0.0
    MODEL_PRESENCE_PENALTY = 0.0
    
    # === 模型能力配置 ===
    # 根据图片中的配置项
    MODEL_CONTEXT_LENGTH = 4096  # 模型上下文长度
    MODEL_MAX_OUTPUT_TOKENS = 4096  # 最大 token 上限
    
    # Agent Thought (链式思考)
    MODEL_AGENT_THOUGHT = False  # 默认不支持
    
    # Function Calling (工具调用)
    MODEL_FUNCTION_CALLING = "tool_call"  # tool_call, function, none
    
    # Stream Function Calling (流式工具调用)
    MODEL_STREAM_FUNCTION_CALLING = True
    
    # Vision 支持
    MODEL_VISION_SUPPORT = True
    
    # Structured Output (结构化输出)
    MODEL_STRUCTURED_OUTPUT = True
    
    # Stream Mode Auth (流模式认证)
    MODEL_STREAM_MODE_AUTH = "none"  # none, basic, bearer
    
    # 流模式返回结果分隔符
    MODEL_STREAM_DELIMITER = "\n\n"
    
    # Completion Mode (补全模式)
    MODEL_COMPLETION_MODE = "chat"  # chat, completion
    SCORE_WEIGHT_GAMMA_REGIME = 0.4
    SCORE_WEIGHT_BREAK_WALL = 0.3
    SCORE_WEIGHT_DIRECTION = 0.2
    SCORE_WEIGHT_IV = 0.1
    
    # === 破墙阈值 ===
    BREAK_WALL_THRESHOLD_LOW = 0.4
    BREAK_WALL_THRESHOLD_HIGH = 0.8
    MONTHLY_OVERRIDE_THRESHOLD = 0.7
    MONTHLY_CLUSTER_STRENGTH_RATIO = 1.5
    CLUSTER_STRENGTH_THRESHOLD_TREND = 1.2
    CLUSTER_STRENGTH_THRESHOLD_STRONG = 2.0
    
    # === DEX 方向阈值 ===
    DEX_SAME_DIR_THRESHOLD_STRONG = 70
    DEX_SAME_DIR_THRESHOLD_MEDIUM = 60
    DEX_SAME_DIR_THRESHOLD_WEAK = 50
    
    # === IV 路径阈值 ===
    IV_PATH_THRESHOLD_PCT = 10
    IV_PATH_THRESHOLD_VOL = 2
    IV_NOISE_THRESHOLD = 30
    
    # === DTE 相关 ===
    DEFAULT_DTE_WEEKLY_SHORT = 7
    DEFAULT_DTE_WEEKLY_MID = 14
    DEFAULT_DTE_MONTHLY_SHORT = 30
    DEFAULT_DTE_MONTHLY_MID = 60
    DTE_GAP_HIGH_THRESHOLD = 3
    DTE_GAP_MID_THRESHOLD = 2
    DTE_MONTHLY_ADJUSTMENT = 7
    
    # === Greeks 目标 ===
    CONSERVATIVE_DELTA_MIN = -0.1
    CONSERVATIVE_DELTA_MAX = 0.1
    CONSERVATIVE_THETA_MIN = 5.0
    CONSERVATIVE_VEGA_MAX = -10.0
    BALANCED_DELTA_RANGE = 0.2
    BALANCED_THETA_MIN = 8.0
    AGGRESSIVE_DELTA_MIN = 0.3
    AGGRESSIVE_DELTA_MAX = 0.6
    AGGRESSIVE_VEGA_MIN = 10.0
    
    # === 行权价偏移 ===
    STRIKE_CONSERVATIVE_LONG_OFFSET = 1.5
    STRIKE_BALANCED_WING_OFFSET = 1.0
    STRIKE_RATIO_SHORT_OFFSET = 0.5
    STRIKE_RATIO_LONG_OFFSET = 1.5
    STRIKE_AGGRESSIVE_LONG_OFFSET = 0.2
    
    # === 价差宽度 ===
    WIDTH_CREDIT_MIN = 0.8
    WIDTH_CREDIT_MAX = 1.0
    WIDTH_DEBIT_MIN = 1.0
    WIDTH_DEBIT_MAX = 1.2
    
    # === RR 计算 - IVR 映射 ===
    CREDIT_IVR_0_25 = 0.20
    CREDIT_IVR_25_50 = 0.30
    CREDIT_IVR_50_75 = 0.40
    CREDIT_IVR_75_100 = 0.50
    DEBIT_IVR_0_40 = 0.30
    DEBIT_IVR_40_70 = 0.40
    DEBIT_IVR_70_100 = 0.50
    
    # === Pw 计算 - 信用 ===
    PW_CREDIT_BASE = 0.5
    PW_CREDIT_CLUSTER_COEF = 0.1
    PW_CREDIT_DISTANCE_PENALTY_COEF = 0.05
    PW_CREDIT_MIN = 0.4
    PW_CREDIT_MAX = 0.85
    
    # === Pw 计算 - 借贷 ===
    PW_DEBIT_BASE = 0.3
    PW_DEBIT_DEX_COEF = 0.1
    PW_DEBIT_VANNA_COEF = 0.2
    PW_DEBIT_VANNA_WEIGHT_HIGH = 1.0
    PW_DEBIT_VANNA_WEIGHT_MEDIUM = 0.6
    PW_DEBIT_VANNA_WEIGHT_LOW = 0.3
    PW_DEBIT_MIN = 0.25
    PW_DEBIT_MAX = 0.75
    
    # === Pw 计算 - 蝶式 ===
    PW_BUTTERFLY_BODY_INSIDE = 0.65
    PW_BUTTERFLY_BODY_OFFSET_1EM = 0.45
    
    # === 止盈止损 ===
    PROFIT_TARGET_CREDIT_PCT = 30
    PROFIT_TARGET_DEBIT_PCT = 60
    STOP_LOSS_DEBIT_PCT = 50
    STOP_LOSS_CREDIT_PCT = 150
    TIME_DECAY_EXIT_DAYS = 3
    
    # === 风险管理 ===
    MAX_SINGLE_RISK_PCT = 2
    MAX_TOTAL_EXPOSURE_PCT = 10
    ENTRY_THRESHOLD_SCORE = 3
    ENTRY_THRESHOLD_PROBABILITY = 60
    LIGHT_POSITION_PROBABILITY = 50
    
    # === 指数和参数 ===
    DEFAULT_INDEX_PRIMARY = "SPX"
    DEFAULT_INDEX_SECONDARY = "QQQ"
    DEFAULT_STRIKES = 25
    DEFAULT_NET_WINDOW = 60
    EXTENDED_NET_WINDOW = 120
    EM1_SQRT_FACTOR = 0.06299
    WALL_CLUSTER_WIDTH = 3
    WALL_PEAK_MULTIPLIER = 2.0
    
    # === Alpha Vantage API ===
    ENABLE_EARNINGS_API = True
    EARNINGS_CACHE_DAYS = 30
    ALPHA_VANTAGE_API_KEY = "TKV2HLJJYKSRGR"  # 请替换为您的 API Key
    ALPHA_VANTAGE_API_URL = "https://www.alphavantage.co/query?"
    
    # === LLM 模型配置 ===
    # 您需要配置您使用的 LLM 提供商和 API Key
    LLM_PROVIDER = "openai"  # 或 "anthropic", "deepseek" 等
    LLM_API_KEY = "your-api-key-here"
    LLM_BASE_URL = "https://api.openai.com/v1"
    
    # 不同 Agent 使用的模型
    MODEL_ROUTER = "gpt-4o-mini"
    MODEL_COMMAND_GEN = "Qwen3-8B"
    MODEL_DATA_VALIDATOR = "Qwen3-VL-235B-A22B-Thinking"
    MODEL_TECHNICAL = "Qwen3-VL-235B-A22B-Thinking"
    MODEL_SCENARIO = "deepseek-v3.2-exp-thinking"
    MODEL_STRATEGY = "gpt-5"
    MODEL_COMPARISON = "deepseek-v3.2-exp-thinking"
    MODEL_REPORT = "deepseek-v3.2-exp-thinking"
    
    # 模型参数
    MODEL_TEMPERATURE = 0.5
    MODEL_MAX_TOKENS = 4000
    
    # === 会话变量配置 (用于数据累积) ===
    ENABLE_DATA_ACCUMULATION = True  # 是否启用数据累积
    MAX_ACCUMULATION_ROUNDS = 5      # 最多累积轮次
    ACCUMULATION_TIMEOUT = 3600      # 累积超时时间(秒)
    
    @classmethod
    def from_yaml(cls, yaml_path: str) -> 'Config':
        """从 YAML 文件加载配置"""
        config = cls()
        
        if Path(yaml_path).exists():
            with open(yaml_path, 'r', encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f)
            
            # 更新 LLM 基础配置
            if 'llm' in yaml_config:
                llm_config = yaml_config['llm']
                if 'provider' in llm_config:
                    config.LLM_PROVIDER = llm_config['provider']
                if 'api_key' in llm_config:
                    config.LLM_API_KEY = llm_config['api_key']
                if 'base_url' in llm_config:
                    config.LLM_BASE_URL = llm_config['base_url']
            
            # 更新模型选择配置
            if 'models' in yaml_config:
                models_config = yaml_config['models']
                model_mapping = {
                    'router': 'MODEL_ROUTER',
                    'command_gen': 'MODEL_COMMAND_GEN',
                    'data_validator': 'MODEL_DATA_VALIDATOR',
                    'technical': 'MODEL_TECHNICAL',
                    'scenario': 'MODEL_SCENARIO',
                    'strategy': 'MODEL_STRATEGY',
                    'comparison': 'MODEL_COMPARISON',
                    'report': 'MODEL_REPORT'
                }
                for yaml_key, config_key in model_mapping.items():
                    if yaml_key in models_config:
                        setattr(config, config_key, models_config[yaml_key])
            
            # 更新模型参数配置
            if 'model_params' in yaml_config:
                params = yaml_config['model_params']
                param_mapping = {
                    'temperature': 'MODEL_TEMPERATURE',
                    'max_tokens': 'MODEL_MAX_TOKENS',
                    'context_length': 'MODEL_CONTEXT_LENGTH',
                    'max_output_tokens': 'MODEL_MAX_OUTPUT_TOKENS',
                    'top_p': 'MODEL_TOP_P',
                    'frequency_penalty': 'MODEL_FREQUENCY_PENALTY',
                    'presence_penalty': 'MODEL_PRESENCE_PENALTY'
                }
                for yaml_key, config_key in param_mapping.items():
                    if yaml_key in params:
                        setattr(config, config_key, float(params[yaml_key]))
            
            # 更新模型能力配置
            if 'model_capabilities' in yaml_config:
                caps = yaml_config['model_capabilities']
                capability_mapping = {
                    'agent_thought': 'MODEL_AGENT_THOUGHT',
                    'function_calling': 'MODEL_FUNCTION_CALLING',
                    'stream_function_calling': 'MODEL_STREAM_FUNCTION_CALLING',
                    'vision_support': 'MODEL_VISION_SUPPORT',
                    'structured_output': 'MODEL_STRUCTURED_OUTPUT',
                    'stream_mode_auth': 'MODEL_STREAM_MODE_AUTH',
                    'stream_delimiter': 'MODEL_STREAM_DELIMITER',
                    'completion_mode': 'MODEL_COMPLETION_MODE'
                }
                for yaml_key, config_key in capability_mapping.items():
                    if yaml_key in caps:
                        value = caps[yaml_key]
                        # 类型转换
                        if isinstance(getattr(config, config_key), bool):
                            setattr(config, config_key, str(value).lower() in ['true', '1', 'yes', 'support', '支持'])
                        else:
                            setattr(config, config_key, value)
            
            # 更新环境变量
            if 'environment_variables' in yaml_config:
                for env_var in yaml_config['environment_variables']:
                    name = env_var.get('name')
                    value = env_var.get('value')
                    if name and hasattr(config, name):
                        # 类型转换
                        current_type = type(getattr(config, name))
                        try:
                            if current_type == bool:
                                setattr(config, name, str(value).lower() in ['true', '1', 'yes'])
                            elif current_type == int:
                                setattr(config, name, int(value))
                            elif current_type == float:
                                setattr(config, name, float(value))
                            else:
                                setattr(config, name, value)
                        except (ValueError, TypeError):
                            pass
        
        return config
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            key: value for key, value in self.__class__.__dict__.items()
            if not key.startswith('_') and not callable(value)
        }
    
    def get_env_vars(self) -> Dict[str, Any]:
        """获取所有环境变量（用于传递给计算引擎）"""
        return {
            key: getattr(self, key)
            for key in dir(self)
            if not key.startswith('_') and key.isupper()
        }