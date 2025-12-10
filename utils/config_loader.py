"""
配置加载工具类（重构版）
特性：
1. 自动将 YAML 转换为对象（支持点号访问）
2. 支持环境变量覆盖（自动类型转换）
3. 单例模式（全局唯一实例）
4. 无需手动映射（删除 aliases）
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


class DotDict(dict):
    """支持点号访问的字典（递归）"""
    
    def __init__(self, data: Dict = None):
        super().__init__()
        if data:
            for key, value in data.items():
                self[key] = self._convert(value)
    
    def _convert(self, value):
        """递归转换嵌套字典为 DotDict"""
        if isinstance(value, dict):
            return DotDict(value)
        elif isinstance(value, list):
            return [self._convert(item) for item in value]
        return value
    
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"配置项不存在: {key}")
    
    def __setattr__(self, key, value):
        self[key] = value
    
    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError:
            raise AttributeError(f"配置项不存在: {key}")


class ConfigLoader:
    """配置加载器（重构版）"""
    
    _instance = None
    _config: DotDict = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_all_configs()
        return cls._instance
    
    def _load_all_configs(self):
        """加载所有配置文件"""
        base_dir = Path(__file__).parent.parent
        
        # 加载环境变量配置
        env_config_path = base_dir / "config" / "env_config.yaml"
        if env_config_path.exists():
            with open(env_config_path, 'r', encoding='utf-8') as f:
                env_data = yaml.safe_load(f)
        else:
            raise FileNotFoundError(f"环境配置文件不存在: {env_config_path}")
        
        # 加载模型配置
        model_config_path = base_dir / "config" / "model_config.yaml"
        if model_config_path.exists():
            with open(model_config_path, 'r', encoding='utf-8') as f:
                model_data = yaml.safe_load(f)
        else:
            raise FileNotFoundError(f"模型配置文件不存在: {model_config_path}")
        
        # 合并配置（转换为 DotDict）
        self._config = DotDict({
            'env': env_data,
            'models': model_data
        })
        
        # 应用环境变量覆盖
        self._apply_env_overrides()
    
    def _apply_env_overrides(self):
        """
        自动从环境变量覆盖配置
        
        规则：
        - 环境变量格式：SECTION_KEY (大写 + 下划线)
        - 例：GAMMA_LAMBDA_K_SYS=0.6 → config.env.gamma.lambda_k_sys = 0.6
        """
        for env_key, env_value in os.environ.items():
            # 跳过系统环境变量
            if env_key.startswith('_') or env_key in ['PATH', 'HOME', 'USER']:
                continue
            
            # 尝试解析为配置路径
            parts = env_key.lower().split('_')
            if len(parts) >= 2:
                try:
                    # 构建配置路径: GAMMA_LAMBDA_K_SYS → env.gamma.lambda_k_sys
                    section = parts[0]
                    key_path = '.'.join(parts[1:])
                    
                    if section in self._config.env:
                        # 设置值（自动类型转换）
                        self._set_nested_value(
                            self._config.env[section],
                            key_path,
                            self._parse_env_value(env_value)
                        )
                except Exception:
                    pass  # 忽略无法解析的环境变量
    
    def _set_nested_value(self, obj: dict, key_path: str, value: Any):
        """设置嵌套字典的值"""
        keys = key_path.split('.')
        for key in keys[:-1]:
            if key not in obj:
                obj[key] = {}
            obj = obj[key]
        obj[keys[-1]] = value
    
    @staticmethod
    def _parse_env_value(value: str) -> Any:
        """解析环境变量值（自动转换类型）"""
        if value.lower() == 'true':
            return True
        elif value.lower() == 'false':
            return False
        elif value.lower() == 'null' or value.lower() == 'none':
            return None
        
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except ValueError:
            return value
    
    # ============================================
    # 公共 API
    # ============================================
    
    def get_section(self, section_name: str) -> DotDict:
        """
        获取整个配置节（推荐方式）
        
        示例：
            gamma_config = config.get_section('gamma')
            k_sys = gamma_config.lambda_k_sys  # 点号访问
        
        Args:
            section_name: 配置节名称（env 下的一级键）
        
        Returns:
            DotDict 对象（支持点号访问）
        """
        section = self._config.env.get(section_name)
        if section is None:
            raise ValueError(f"配置节不存在: {section_name}")
        return section
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        获取配置值（点号路径，兼容旧代码）
        
        示例：
            value = config.get('gamma.lambda_k_sys', 0.5)
        
        Args:
            key_path: 配置路径（如 'gamma.lambda_k_sys'）
            default: 默认值
        
        Returns:
            配置值
        """
        keys = key_path.split('.')
        value = self._config.env
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def get_env(self, key_path: str, default: Any = None) -> Any:
        """获取环境变量配置（快捷方法，等同于 get）"""
        return self.get(key_path, default)
    
    def get_model_config(self, agent_name: str) -> DotDict:
        """获取指定 Agent 的模型配置"""
        agents_config = self._config.models.get('agents', {})
        agent_config = agents_config.get(agent_name, {})
        
        if not agent_config:
            # 返回默认配置
            return self._config.models.get('default', DotDict())
        
        return DotDict(agent_config)
    
    # ============================================
    # 快捷属性访问
    # ============================================
    
    @property
    def gamma(self) -> DotDict:
        """快捷访问 gamma 配置"""
        return self.get_section('gamma')
    
    @property
    def scoring(self) -> DotDict:
        """快捷访问 scoring 配置"""
        return self.get_section('scoring')
    
    @property
    def dte(self) -> DotDict:
        """快捷访问 dte 配置"""
        return self.get_section('dte')
    
    @property
    def direction(self) -> DotDict:
        """快捷访问 direction 配置"""
        return self.get_section('direction')
    
    @property
    def strikes(self) -> DotDict:
        """快捷访问 strikes 配置"""
        return self.get_section('strikes')


# ============================================
# 全局配置实例
# ============================================
config = ConfigLoader()

__all__ = ['config', 'ConfigLoader', 'DotDict']