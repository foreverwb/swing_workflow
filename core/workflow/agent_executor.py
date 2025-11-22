"""
Agent 执行器
统一 Agent 调用接口
"""

from typing import Dict, Any, List, Optional, Callable
from loguru import logger

from core.model_client import ModelClientManager
from core.utils.debugger import Debugger


class AgentExecutor:
    """Agent 执行器 - 统一调用接口"""
    
    def __init__(self, model_client: ModelClientManager, env_vars: Dict[str, Any]):
        """
        初始化 Agent 执行器
        
        Args:
            model_client: 模型客户端管理器
            env_vars: 环境变量字典
        """
        self.model_client = model_client
        self.env_vars = env_vars
        self.debugger = Debugger()
    
    def execute_agent(
        self,
        agent_name: str,
        messages: List[Dict],
        json_schema: Optional[Dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行 Agent - 统一入口
        
        Args:
            agent_name: Agent 名称
            messages: 消息列表
            json_schema: JSON Schema（用于结构化输出）
            **kwargs: 其他参数
            
        Returns:
            响应字典
        """
        logger.info(f"🔄 [{agent_name}] 开始执行")
        
        # 调用模型
        response = self.model_client.chat_completion(
            messages=messages,
            agent_name=agent_name,
            json_schema=json_schema,
            **kwargs
        )
        
        # 调试输出
        self.debugger.print_agent_response(agent_name, response)
        
        logger.success(f"✅ [{agent_name}] 执行完成")
        
        return response
    
    def execute_vision_agent(
        self,
        agent_name: str,
        inputs: List[Dict],
        json_schema: Optional[Dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行视觉 Agent
        
        Args:
            agent_name: Agent 名称
            inputs: 输入列表（包含图片）
            json_schema: JSON Schema
            **kwargs: 其他参数
            
        Returns:
            响应字典
        """
        logger.info(f"📸 [{agent_name}] 开始执行（视觉模式）")
        
        # 调用模型
        response = self.model_client.responses_create(
            inputs=inputs,
            agent_name=agent_name,
            json_schema=json_schema,
            **kwargs
        )
        
        # 调试输出
        self.debugger.print_agent_response(agent_name, response)
        
        logger.success(f"✅ [{agent_name}] 执行完成（视觉模式）")
        
        return response
    
    def execute_code_node(
        self,
        node_name: str,
        func: Callable,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行 Code Node
        
        Args:
            node_name: 节点名称
            func: 执行函数
            **kwargs: 函数参数
            
        Returns:
            执行结果
        """
        logger.info(f"🔧 [{node_name}] 开始执行")
        
        try:
            # 执行函数
            result = func(**kwargs)
            
            # 调试输出
            self.debugger.print_code_node_result(node_name, result)
            
            logger.success(f"✅ [{node_name}] 执行完成")
            
            return result
        
        except Exception as e:
            logger.error(f"❌ [{node_name}] 执行失败: {str(e)}")
            return {
                "error": True,
                "error_message": str(e),
                "error_type": type(e).__name__
            }