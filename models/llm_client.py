"""
LLM 客户端封装
支持多种提供商：OpenAI, Anthropic, DeepSeek 等
增强功能：Structured Output, 重试机制, 流式输出
"""

import json
import base64
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from utils.logger import setup_logger

logger = setup_logger(__name__)


class LLMClient:
    """统一的 LLM 客户端接口"""
    
    def __init__(self, config):
        self.config = config
        self.provider = config.LLM_PROVIDER
        self.api_key = config.LLM_API_KEY
        self.base_url = config.LLM_BASE_URL
        
        # 重试配置
        self.max_retries = getattr(config, 'LLM_MAX_RETRIES', 3)
        self.retry_delay = getattr(config, 'LLM_RETRY_DELAY', 2)
        
        # 初始化客户端
        self._init_client()
    
    def _init_client(self):
        """初始化对应提供商的客户端"""
        try:
            if self.provider == "openai":
                from openai import OpenAI
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url
                )
            elif self.provider == "anthropic":
                from anthropic import Anthropic
                self.client = Anthropic(api_key=self.api_key)
            else:
                # 默认使用 OpenAI 兼容接口（适配 DeepSeek 等）
                from openai import OpenAI
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url
                )
            
            logger.info(f"✅ LLM 客户端初始化成功: {self.provider}")
            
        except Exception as e:
            logger.error(f"❌ LLM 客户端初始化失败: {e}")
            raise
    
    def chat_completion(
        self,
        model: str,
        messages: List[Dict],
        temperature: float = 0.5,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict:
        """
        统一的 Chat Completion 接口
        
        Args:
            model: 模型名称
            messages: 消息列表 [{"role": "system/user/assistant", "content": ...}]
            temperature: 温度参数
            max_tokens: 最大 token
            response_format: 响应格式（Structured Output）
            stream: 是否流式输出
            **kwargs: 其他参数（如 reasoning_format）
        
        Returns:
            响应字典（已解析 JSON）
        """
        for attempt in range(self.max_retries):
            try:
                # 处理图片内容
                processed_messages = self._process_messages(messages)
                
                # 构造请求参数
                request_params = {
                    "model": model,
                    "messages": processed_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": stream
                }
                
                # 添加 Structured Output
                if response_format:
                    request_params["response_format"] = response_format
                
                # 添加其他参数（如 reasoning_format="tagged"）
                request_params.update(kwargs)
                
                logger.info(f"🤖 调用 LLM: {model}, messages: {len(processed_messages)}, temp: {temperature}")
                
                # 调用 API
                response = self.client.chat.completions.create(**request_params)
                
                # 解析响应
                content = response.choices[0].message.content
                
                # 如果是 JSON 格式，尝试解析
                if response_format and response_format.get("type") == "json_schema":
                    try:
                        return json.loads(content)
                    except json.JSONDecodeError as e:
                        logger.error(f"⚠️ JSON 解析失败: {e}")
                        # 尝试清理并重新解析
                        cleaned = content.strip()
                        if cleaned.startswith("```json"):
                            cleaned = cleaned[7:]
                        if cleaned.endswith("```"):
                            cleaned = cleaned[:-3]
                        return json.loads(cleaned.strip())
                
                # 普通文本响应
                return {"text": content}
                
            except Exception as e:
                logger.error(f"❌ LLM 调用失败 (第 {attempt + 1}/{self.max_retries} 次): {e}")
                
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    logger.info(f"🔄 重试中...")
                else:
                    raise
    
    def _process_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        处理消息列表，支持图片输入
        
        Args:
            messages: 原始消息列表
        
        Returns:
            处理后的消息列表
        """
        processed = []
        
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            
            # 如果 content 是字符串，直接添加
            if isinstance(content, str):
                processed.append({"role": role, "content": content})
                continue
            
            # 如果 content 是列表（包含文本和图片）
            if isinstance(content, list):
                processed_content = []
                
                for item in content:
                    if item["type"] == "text":
                        processed_content.append(item)
                    
                    elif item["type"] == "image_url":
                        image_url = item["image_url"]["url"]
                        
                        # 处理本地文件路径
                        if image_url.startswith("file://"):
                            file_path = image_url[7:]  # 去掉 file://
                            base64_data = self._encode_image(file_path)
                            
                            # 检测文件类型
                            ext = Path(file_path).suffix.lower()
                            media_type_map = {
                                ".jpg": "image/jpeg",
                                ".jpeg": "image/jpeg",
                                ".png": "image/png",
                                ".gif": "image/gif",
                                ".webp": "image/webp"
                            }
                            media_type = media_type_map.get(ext, "image/jpeg")
                            
                            processed_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{base64_data}",
                                    "detail": item["image_url"].get("detail", "high")
                                }
                            })
                        else:
                            # 直接使用 URL 或已编码的 base64
                            processed_content.append(item)
                
                processed.append({"role": role, "content": processed_content})
        
        return processed
    
    def _encode_image(self, file_path: str) -> str:
        """将图片编码为 base64"""
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def test_connection(self) -> bool:
        """测试连接"""
        try:
            response = self.chat_completion(
                model=self.config.MODEL_ROUTER,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            logger.info("✅ LLM 连接测试成功")
            return True
        except Exception as e:
            logger.error(f"❌ LLM 连接测试失败: {e}")
            return False