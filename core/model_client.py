"""
模型客户端封装
支持多模型编排：每个 Agent 可以使用不同的模型
"""

import os
import json
import base64
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from loguru import logger

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class BaseModelClient:
    """模型客户端基类"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化模型客户端
        
        Args:
            config: 模型配置字典
        """
        self.config = config
        self.provider = config.get('provider', 'dmxapi')
        self.model = config.get('model', 'gpt-4o')
        self.api_key = config.get('api_key') or self._get_api_key_from_env()
        self.base_url = config.get('base_url')
        self.temperature = config.get('temperature', 0.3)
        self.max_tokens = config.get('max_tokens', 4096)
        self.timeout = config.get('timeout', 120)
        self.supports_vision = config.get('supports_vision', False)
        
        if not self.api_key:
            raise ValueError(f"未找到 API Key，请配置或设置环境变量")
    
    def _get_api_key_from_env(self) -> Optional[str]:
        """从环境变量获取 API Key"""
        env_keys = {
            'anthropic': 'ANTHROPIC_API_KEY',
            'openai': 'OPENAI_API_KEY',
            'dmxapi': 'DMXAPI_KEY'
        }
        env_var = env_keys.get(self.provider)
        if env_var:
            return os.environ.get(env_var)
        return None
    
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """聊天补全（子类实现）"""
        raise NotImplementedError
    
    def create_image_message(
        self,
        text: str,
        image_paths: List[Union[str, Path]]
    ) -> Dict[str, Any]:
        """创建包含图片的消息（子类实现）"""
        raise NotImplementedError


class AnthropicClient(BaseModelClient):
    """Anthropic Claude 客户端"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("请安装: pip install anthropic")
        
        client_kwargs = {'api_key': self.api_key}
        if self.base_url:
            client_kwargs['base_url'] = self.base_url
        
        self.client = Anthropic(**client_kwargs)
        logger.debug(f"Anthropic 客户端初始化: {self.model}")
    
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Claude 聊天补全"""
        
        # 分离 system 消息
        system_content = None
        conversation = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                conversation.append(msg)
        
        request_params = {
            "model": self.model,
            "messages": conversation,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature
        }
        
        if system_content:
            request_params["system"] = system_content
        
        # JSON Schema 支持
        if kwargs.get('json_schema'):
            request_params["response_format"] = {
                "type": "json_schema",
                "json_schema": kwargs['json_schema']
            }
        
        try:
            response = self.client.messages.create(**request_params)
            content = response.content[0].text if response.content else ""
            
            # JSON 解析
            if kwargs.get('json_schema') and content:
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    logger.warning("JSON解析失败")
            
            return {
                "content": content,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens
                },
                "model": response.model
            }
        
        except Exception as e:
            logger.error(f"Claude API 调用失败: {str(e)}")
            raise
    
    def create_image_message(
        self,
        text: str,
        image_paths: List[Union[str, Path]]
    ) -> Dict[str, Any]:
        """创建包含图片的消息（Anthropic 格式）"""
        content = []
        
        for img_path in image_paths:
            img_path = Path(img_path)
            if not img_path.exists():
                continue
            
            with open(img_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            media_type = f"image/{img_path.suffix[1:]}"
            if img_path.suffix.lower() == '.jpg':
                media_type = "image/jpeg"
            
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_data
                }
            })
        
        if text:
            content.append({"type": "text", "text": text})
        
        return {"role": "user", "content": content}


class OpenAICompatibleClient(BaseModelClient):
    """OpenAI 兼容客户端"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        if not OPENAI_AVAILABLE:
            raise ImportError("请安装: pip install openai")
        
        client_kwargs = {'api_key': self.api_key}
        if self.base_url:
            client_kwargs['base_url'] = self.base_url
        if self.timeout:
            client_kwargs['timeout'] = self.timeout
        
        self.client = OpenAI(**client_kwargs)
        logger.debug(f"{self.provider.upper()} 客户端初始化: {self.model}")
    
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """OpenAI 兼容接口聊天补全"""
        
        request_params = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature
        }
        
        if kwargs.get('json_schema'):
            request_params["response_format"] = {"type": "json_object"}
        
        try:
            response = self.client.chat.completions.create(**request_params)
            content = response.choices[0].message.content
            
            # JSON 解析
            if kwargs.get('json_schema') and content:
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    logger.warning("JSON解析失败")
            
            return {
                "content": content,
                "usage": {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens
                },
                "model": response.model
            }
        
        except Exception as e:
            logger.error(f"{self.provider.upper()} API 调用失败: {str(e)}")
            raise
    
    def create_image_message(
        self,
        text: str,
        image_paths: List[Union[str, Path]]
    ) -> Dict[str, Any]:
        """创建包含图片的消息（OpenAI Vision 格式）"""
        content = [{"type": "text", "text": text}]
        
        for img_path in image_paths:
            img_path = Path(img_path)
            if not img_path.exists():
                continue
            
            with open(img_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            media_type = img_path.suffix[1:].lower()
            if media_type == 'jpg':
                media_type = 'jpeg'
            
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/{media_type};base64,{image_data}"
                }
            })
        
        return {"role": "user", "content": content}


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
        
        # 直接加载 YAML 配置
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
    
    def _create_client(self, config: Dict[str, Any]) -> BaseModelClient:
        """根据配置创建客户端"""
        provider = config.get('provider', 'dmxapi').lower()
        
        if provider == 'anthropic':
            return AnthropicClient(config)
        elif provider in ['openai', 'dmxapi']:
            return OpenAICompatibleClient(config)
        else:
            raise ValueError(f"不支持的提供商: {provider}")
    
    def get_client(self, agent_name: str = "default") -> BaseModelClient:
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
        client = self._create_client(full_config)
        
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
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        统一的聊天补全接口
        
        Args:
            messages: 消息列表
            agent_name: Agent名称
            json_schema: JSON Schema
            temperature: 温度
            max_tokens: 最大token数
            
        Returns:
            响应字典
        """
        client = self.get_client(agent_name)
        
        logger.info(f"[{agent_name}] 调用模型: {client.provider}/{client.model}")
        
        result = client.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_schema=json_schema,
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
    
    def create_image_message(
        self,
        text: str,
        image_paths: List[Union[str, Path]],
        agent_name: str = "agent3"
    ) -> Dict[str, Any]:
        """
        创建包含图片的消息
        
        Args:
            text: 文本内容
            image_paths: 图片路径列表
            agent_name: Agent名称（默认agent3，因为它需要视觉）
            
        Returns:
            消息字典
        """
        client = self.get_client(agent_name)
        
        if not client.supports_vision:
            logger.warning(f"[{agent_name}] 模型不支持视觉，但仍尝试发送图片")
        
        return client.create_image_message(text, image_paths)
    
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
    """模型客户端工厂（向后兼容接口）"""
    
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