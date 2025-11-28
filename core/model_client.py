"""
模型客户端封装
仅支持 OpenAI 兼容接口（包括 Responses API）
⭐ 新增：支持 Strict JSON Schema Mode
"""

import os
import json
from typing import Dict, Any, List, Optional
from loguru import logger
import copy
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

def _sanitize_json_schema_for_vision(schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        递归规范化 JSON Schema 以满足 vision_structured_output 的要求：
        - 对含 properties 的 object 节点，确保 additionalProperties=False（若未提供）。
        - 对含 properties 的 object 节点，确保 required 是数组并包含 properties 中的每个键（补齐缺失项）。
        返回深拷贝后的 schema，不修改原对象。
        """
        def _rec(node):
            if not isinstance(node, dict):
                return node

            node = dict(node)  # shallow copy for safety

            node_type = node.get("type")
            has_props = isinstance(node.get("properties"), dict)

            # 如果是 object 类型或含 properties，则视为 object 节点
            if node_type == "object" or has_props:
                # additionalProperties 要显式为 False（若为 dict，递归）
                if "additionalProperties" not in node:
                    node["additionalProperties"] = False
                elif isinstance(node["additionalProperties"], dict):
                    node["additionalProperties"] = _rec(node["additionalProperties"])

                # 规范 required：必须存在且包含所有 properties 的键
                if has_props:
                    prop_keys = list(node["properties"].keys())
                    existing_required = node.get("required")
                    if isinstance(existing_required, list):
                        # 补齐缺失的 keys
                        missing = [k for k in prop_keys if k not in existing_required]
                        if missing:
                            node["required"] = existing_required + missing
                    else:
                        # 若不存在 required 或格式不对，直接设置为所有属性键
                        node["required"] = prop_keys

            # 递归处理 properties
            if isinstance(node.get("properties"), dict):
                for k, v in list(node["properties"].items()):
                    node["properties"][k] = _rec(v)

            # patternProperties
            if isinstance(node.get("patternProperties"), dict):
                for k, v in list(node["patternProperties"].items()):
                    node["patternProperties"][k] = _rec(v)

            # items（数组元素）
            it = node.get("items")
            if isinstance(it, dict):
                node["items"] = _rec(it)
            elif isinstance(it, list):
                node["items"] = [_rec(x) for x in it]

            # 组合关键字
            for comb in ("allOf", "anyOf", "oneOf"):
                if isinstance(node.get(comb), list):
                    node[comb] = [_rec(s) for s in node[comb]]

            # 如果 additionalProperties 本身是 schema，则递归
            ap = node.get("additionalProperties")
            if isinstance(ap, dict):
                node["additionalProperties"] = _rec(ap)

            return node

        return _rec(copy.deepcopy(schema))


class ModelClient:
    """OpenAI 兼容模型客户端"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化模型客户端
        
        Args:
            config: 模型配置字典
        """
        if not OPENAI_AVAILABLE:
            raise ImportError("请安装: pip install openai")
        
        self.config = config
        self.provider = config.get('provider', 'openai')
        self.model = config.get('model', 'gpt-4o')
        self.api_key = self._get_api_key_from_env()
        self.base_url = self._get_base_url_from_env()
        self.temperature = config.get('temperature', 0.3)
        self.max_tokens = config.get('max_tokens', 4096)
        self.timeout = config.get('timeout', 120)
        self.supports_vision = config.get('supports_vision', False)
        
        if not self.api_key:
            raise ValueError(f"未找到 API Key，请配置或设置环境变量 OPENAI_API_KEY 或 DMXAPI_KEY")
        
        # 初始化 OpenAI 客户端
        client_kwargs = {'api_key': self.api_key}
        if self.base_url:
            client_kwargs['base_url'] = self.base_url
        if self.timeout:
            client_kwargs['timeout'] = self.timeout
        
        self.client = OpenAI(**client_kwargs)
        logger.debug(f"{self.provider.upper()} 客户端初始化: {self.model}")
        
    
    def _get_api_key_from_env(self) -> Optional[str]:
        """从 .env 环境变量获取 API Key（唯一入口）"""
        api_key = os.environ.get('API_KEY')
        if api_key:
            return api_key
    
    def _get_base_url_from_env(self) -> Optional[str]:
        """从 .env 环境变量获取 Base URL"""
        # 优先级1: 通用配置
        base_url = os.environ.get('API_BASE_URL')
        if base_url:
            return base_url
        
        # 优先级2: 兼容旧配置
        return os.environ.get('OPENAI_BASE_URL') or self.config.get('base_url')
    
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_schema: Optional[Dict] = None,
        use_strict_mode: bool = True,  # ⭐ 新增参数
        **kwargs
    ) -> Dict[str, Any]:
        """
        聊天补全接口
        
        Args:
            messages: 消息列表
            temperature: 温度
            max_tokens: 最大token数
            json_schema: JSON Schema（用于结构化输出）
            use_strict_mode: 是否使用严格模式（仅当 json_schema 存在时有效）
            
        Returns:
            响应字典
        """
        request_params = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature
        }
        
        # ⭐ 关键改进：支持 Strict JSON Schema
        if json_schema:
            if use_strict_mode:
                # Strict Mode: 模型必须 100% 遵守 Schema
                sanitized_schema = _sanitize_json_schema_for_vision(json_schema)
                request_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_output",  # 可自定义名称
                        "schema": sanitized_schema,
                        "strict": True  # 🔑 关键！开启严格模式
                    }
                }
                logger.debug("✅ 已启用 Strict JSON Schema Mode")
            else:
                # 兼容模式：仅要求 JSON 格式
                request_params["response_format"] = {"type": "json_object"}
                logger.debug("ℹ️ 使用兼容 JSON 模式（非严格）")
        
        try:
            response = self.client.chat.completions.create(**request_params)
            content = response.choices[0].message.content
            
            # JSON 解析
            if json_schema and content:
                try:
                    content = json.loads(content)
                    logger.debug("✅ JSON 解析成功")
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️ JSON 解析失败: {str(e)[:100]}，返回原始文本")
            
            return {
                "content": content,
                "usage": {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens
                },
                "model": response.model
            }
        
        except Exception as e:
            logger.error(f"API 调用失败: {str(e)}")
            raise
    
    def responses_create(
        self,
        inputs: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_schema: Optional[Dict] = None,
        use_strict_mode: bool = True,  # ⭐ 新增参数
        **kwargs
    ) -> Dict[str, Any]:
        """
        OpenAI Responses API 接口适配器（Vision 支持）
        ⭐ 新增：支持 Strict JSON Schema Mode
        
        Args:
            inputs: 输入列表（在 Agent3 中，这实际上是 messages 列表）
            temperature: 温度
            max_tokens: 最大token数
            json_schema: JSON Schema
            use_strict_mode: 是否使用严格模式
            
        Returns:
            响应字典
        """
        request_params = {
            "model": self.model,
            "messages": inputs,  # 将 inputs 重命名为 messages
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature
        }
        
        # ⭐ 关键改进：支持 Strict JSON Schema（视觉模型）
        if json_schema:
            if use_strict_mode:
                # Strict Mode: 视觉模型也支持
                sanitized_schema = _sanitize_json_schema_for_vision(json_schema)
                request_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "vision_structured_output",
                        "schema": sanitized_schema,
                        "strict": True  # 🔑 视觉模型的严格模式
                    }
                }
                logger.debug("✅ 已启用 Vision Strict JSON Schema Mode")
            else:
                # 兼容模式
                request_params["response_format"] = {"type": "json_object"}
                logger.debug("ℹ️ 使用兼容 JSON 模式（非严格）")
        
        # ⭐ 对于视觉模型，在 system prompt 中强调 JSON 输出（双重保险）
        if self.supports_vision and json_schema:
            for msg in inputs:
                if msg.get("role") == "system":
                    original_content = msg["content"]
                    msg["content"] = (
                        "**CRITICAL: You must respond with ONLY valid JSON. "
                        "No markdown, no explanations, no code blocks. "
                        "Just pure JSON starting with { and ending with }.**\n\n"
                        + original_content
                    )
                    break
        
        try:
            logger.debug(f"调用 Chat Completions (Vision): model={self.model}, messages={len(inputs)} 条")
            
            # 使用标准的 chat.completions.create 替代 responses.create
            response = self.client.chat.completions.create(**request_params)
            
            # 适配返回格式
            content = response.choices[0].message.content
            
            # JSON 解析逻辑
            if json_schema and content:
                try:
                    # 清理可能的 Markdown 标记
                    import re
                    json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
                    if json_match:
                        content = json.loads(json_match.group(1))
                    else:
                        content = json.loads(content)
                    logger.debug("✅ JSON 解析成功")
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️ JSON 解析失败: {str(e)[:100]}，返回原始文本")
            
            return {
                "content": content,
                "usage": {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens
                },
                "model": response.model
            }
        
        except Exception as e:
            logger.error(f"Vision API 调用失败: {str(e)}")
            raise


class ModelClientManager:
    """
    多模型客户端管理器
    支持为不同 Agent 配置不同的模型
    """
    
    def __init__(self, config_path: str = "config/model_config.yaml"):
        """
        初始化管理器
        
        Args:
            config_path: 配置文件路径
        """
        import yaml
        from pathlib import Path
        
        # 加载 YAML 配置
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"模型配置文件不存在: {config_path}")
        
        with open(config_file, 'r', encoding='utf-8') as f:
            self.full_config = yaml.safe_load(f)
        
        self.default_config = self.full_config.get('default', {})
        self.agents_config = self.full_config.get('agents', {})
        self._clients_cache = {}  # Agent客户端缓存
        
        logger.info(f"模型客户端管理器初始化完成")
        logger.info(f"默认模型: {self.default_config.get('provider')}/{self.default_config.get('model')}")
        logger.info(f"已配置 {len(self.agents_config)} 个Agent模型")
    
    def _merge_config(self, agent_config: Dict, default_config: Dict) -> Dict:
        """合并 Agent 配置和默认配置"""
        merged = default_config.copy()
        merged.update(agent_config)
        return merged
    
    def get_client(self, agent_name: str = "default") -> ModelClient:
        """
        获取指定 Agent 的客户端
        
        Args:
            agent_name: Agent名称
            
        Returns:
            模型客户端实例
        """
        # 检查缓存
        if agent_name in self._clients_cache:
            return self._clients_cache[agent_name]
        
        # 获取 Agent 配置
        if agent_name in self.agents_config:
            agent_config = self.agents_config[agent_name]
            full_config = self._merge_config(agent_config, self.default_config)
        else:
            full_config = self.default_config
        
        # 创建客户端
        client = ModelClient(full_config)
        
        # 缓存
        self._clients_cache[agent_name] = client
        
        logger.info(
            f"为 [{agent_name}] 创建客户端: "
            f"{full_config.get('provider')}/{full_config.get('model')}"
        )
        
        return client
    
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        agent_name: str = "default",
        json_schema: Optional[Dict] = None,
        use_strict_mode: bool = True,  # ⭐ 新增参数
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        统一的聊天补全接口
        ⭐ 新增：支持 Strict JSON Schema Mode
        
        Args:
            messages: 消息列表
            agent_name: Agent名称
            json_schema: JSON Schema
            use_strict_mode: 是否使用严格模式（默认 True）
            temperature: 温度
            max_tokens: 最大token数
            
        Returns:
            响应字典
        """
        client = self.get_client(agent_name)
        
        logger.info(f"[{agent_name}] 调用模型: {client.provider}/{client.model}")
        
        if json_schema and use_strict_mode:
            logger.info(f"[{agent_name}] 🔒 启用 Strict JSON Schema Mode")
        
        result = client.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_schema=json_schema,
            use_strict_mode=use_strict_mode,
            **kwargs
        )
        
        # 添加 Agent 信息
        result['agent_name'] = agent_name
        result['provider'] = client.provider
        
        logger.success(
            f"[{agent_name}] ✓ 完成 "
            f"(输入:{result['usage']['input_tokens']} "
            f"输出:{result['usage']['output_tokens']})"
        )
        
        return result
    
    def responses_create(
        self,
        inputs: List[Dict[str, Any]],
        agent_name: str = "agent3",
        json_schema: Optional[Dict] = None,
        use_strict_mode: bool = True,  # ⭐ 新增参数
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        OpenAI Responses API 接口（用于 Agent3 多图片输入）
        ⭐ 新增：支持 Strict JSON Schema Mode
        
        Args:
            inputs: 输入列表
            agent_name: Agent名称
            json_schema: JSON Schema
            use_strict_mode: 是否使用严格模式（默认 True）
            temperature: 温度
            max_tokens: 最大token数
            
        Returns:
            响应字典
        """
        client = self.get_client(agent_name)
        
        logger.info(f"[{agent_name}] 调用 Responses API: {client.provider}/{client.model}")
        
        if json_schema and use_strict_mode:
            logger.info(f"[{agent_name}] 🔒 启用 Vision Strict JSON Schema Mode")
        
        result = client.responses_create(
            inputs=inputs,
            temperature=temperature,
            max_tokens=max_tokens,
            json_schema=json_schema,
            use_strict_mode=use_strict_mode,
            **kwargs
        )
        
        # 添加 Agent 信息
        result['agent_name'] = agent_name
        result['provider'] = client.provider
        
        logger.success(
            f"[{agent_name}] ✓ Responses API 完成 "
            f"(输入:{result['usage']['input_tokens']} "
            f"输出:{result['usage']['output_tokens']})"
        )
        
        return result
    
    def get_model_info(self, agent_name: str = "default") -> Dict[str, Any]:
        """获取指定 Agent 的模型信息"""
        client = self.get_client(agent_name)
        return {
            "agent_name": agent_name,
            "provider": client.provider,
            "model": client.model,
            "supports_vision": client.supports_vision,
            "temperature": client.temperature,
            "max_tokens": client.max_tokens
        }
    
    def list_all_agents(self) -> List[str]:
        """列出所有配置的 Agent"""
        return list(self.agents_config.keys())


# 工厂函数（向后兼容）
class ModelClientFactory:
    """模型客户端工厂"""
    
    @staticmethod
    def create_from_config(config_path: str = "config/model_config.yaml") -> ModelClientManager:
        """
        从配置文件创建管理器
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            ModelClientManager 实例
        """
        return ModelClientManager(config_path)