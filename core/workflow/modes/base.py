"""
工作流模式基类
定义模式接口
"""

import base64
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from loguru import logger

if TYPE_CHECKING:
    from core.workflow.engine import WorkflowEngine


class BaseMode(ABC):
    """工作流模式基类"""
    
    def __init__(self, engine: 'WorkflowEngine'):
        """
        初始化模式
        
        Args:
            engine: 工作流引擎实例
        """
        self.engine = engine
        self.agent_executor = engine.agent_executor
        self.cache_manager = engine.cache_manager
        self.state_manager = engine.state_manager
        self.env_vars = engine.env_vars
    
    @abstractmethod
    def execute(self, symbol: str, data_folder: Path, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行模式 - 子类必须实现
        
        Args:
            symbol: 股票代码
            data_folder: 数据文件夹路径
            state: 当前状态
            
        Returns:
            执行结果
        """
        pass
    
    # ============= 公共工具方法 =============
    
    def scan_images(self, folder: Path) -> List[Path]:
        """
        扫描文件夹中的图片
        
        Args:
            folder: 文件夹路径
            
        Returns:
            图片路径列表
        """
        extensions = ['*.png', '*.PNG', '*.jpg', '*.JPG', '*.jpeg', '*.JPEG']
        images = []
        
        for ext in extensions:
            images.extend(folder.glob(ext))
        
        sorted_images = sorted(images)
        logger.debug(f"📁 扫描到 {len(sorted_images)} 张图片")
        
        return sorted_images
    
    def encode_image_to_base64(self, image_path: Path) -> Optional[str]:
        """
        将图片编码为 Base64
        
        Args:
            image_path: 图片路径
            
        Returns:
            Base64 编码的图片 URL 或 None
        """
        try:
            with open(image_path, "rb") as image_file:
                base64_str = base64.b64encode(image_file.read()).decode('utf-8')
                
                # 判断 MIME 类型
                ext = image_path.suffix.lower()
                mime_type = "image/jpeg" if ext in ['.jpg', '.jpeg'] else "image/png"
                
                return f"data:{mime_type};base64,{base64_str}"
        
        except Exception as e:
            logger.error(f"❌ 图片编码失败 {image_path.name}: {e}")
            return None
    
    def safe_parse_json(self, data: Any) -> Dict[str, Any]:
        """
        安全解析 JSON
        
        Args:
            data: 要解析的数据
            
        Returns:
            解析后的字典
        """
        if isinstance(data, dict):
            return data
        elif isinstance(data, str):
            try:
                import json
                return json.loads(data)
            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析失败: {str(e)[:100]}")
                return {}
        else:
            logger.warning(f"未知数据类型: {type(data)}")
            return {}
    
    def get_nested_value(self, data: Dict, path: str, default: Any = None) -> Any:
        """
        获取嵌套字段值
        
        Args:
            data: 数据字典
            path: 字段路径（用点号分隔，如 "targets.spot_price"）
            default: 默认值
            
        Returns:
            字段值或默认值
        """
        keys = path.split('.')
        value = data
        
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
        
        return value if value != -999 else default