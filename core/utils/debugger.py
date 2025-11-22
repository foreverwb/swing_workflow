"""
调试输出工具
从 workflow_engine.py 中提取的调试函数
"""

import json
from typing import Dict, Any, Optional


class Debugger:
    """调试输出工具类"""
    
    @staticmethod
    def print_agent_response(agent_name: str, response: Dict, truncate: Optional[int] = None):
        """
        打印 Agent 响应数据
        
        Args:
            agent_name: Agent 名称
            response: 响应字典
            truncate: 截断长度（可选，用于长文本）
        """
        print("\n" + "="*80)
        print(f"📤 {agent_name} 返回数据")
        print("="*80)
        
        # 打印元数据
        if "model" in response:
            print(f"🤖 模型: {response['model']}")
        if "usage" in response:
            usage = response["usage"]
            print(f"📊 Token使用: 输入={usage.get('input_tokens', 0)}, 输出={usage.get('output_tokens', 0)}")
        
        # 打印内容
        content = response.get("content", {})
        
        if isinstance(content, dict):
            print(f"\n📋 内容类型: dict")
            print(f"📋 字段数量: {len(content)}")
            
            # 打印主要字段
            if truncate:
                content_str = json.dumps(content, ensure_ascii=False, indent=2)
                if len(content_str) > truncate:
                    print(f"\n{content_str[:truncate]}...")
                    print(f"\n[内容过长，已截断至 {truncate} 字符]")
                else:
                    print(f"\n{content_str}")
            else:
                # 打印关键字段摘要
                key_fields = ["symbol", "status", "total_score", "scenario_classification", "strategies"]
                print(f"\n🔑 关键字段:")
                for key in key_fields:
                    if key in content:
                        value = content[key]
                        if isinstance(value, (dict, list)):
                            print(f"  • {key}: {type(value).__name__} (长度: {len(value)})")
                        else:
                            print(f"  • {key}: {value}")
        
        elif isinstance(content, str):
            print(f"\n📋 内容类型: str")
            print(f"📋 内容长度: {len(content)} 字符")
            if truncate and len(content) > truncate:
                print(f"\n{content[:truncate]}...")
                print(f"\n[内容过长，已截断至 {truncate} 字符]")
            else:
                print(f"\n{content}")
        
        else:
            print(f"\n📋 内容类型: {type(content)}")
            print(f"\n{content}")
        
        print("="*80 + "\n")
    
    @staticmethod
    def print_code_node_result(node_name: str, result: Dict):
        """
        打印 Code Node 结果
        
        Args:
            node_name: 节点名称
            result: 结果字典
        """
        print("\n" + "="*80)
        print(f"🔧 {node_name} 执行结果")
        print("="*80)
        
        # 检查是否有错误
        if "error" in result or (isinstance(result.get("result"), str) and "error" in result["result"]):
            print(f"❌ 执行失败")
            print(f"\n{json.dumps(result, ensure_ascii=False, indent=2)}")
            print("="*80 + "\n")
            return
        
        # 打印结果
        result_data = result.get("result", {})
        
        if isinstance(result_data, str):
            # 尝试解析 JSON
            try:
                parsed = json.loads(result_data)
                print(f"📋 结果类型: JSON (已解析)")
                
                # 打印关键信息
                if isinstance(parsed, dict):
                    print(f"📋 字段数量: {len(parsed)}")
                    
                    # 提取关键字段
                    key_indicators = [
                        "symbol", "status", "data_status", "missing_count",
                        "validation_summary", "total_score", "em1_dollar",
                        "calculation_log", "event_count", "risk_level"
                    ]
                    
                    print(f"\n🔑 关键指标:")
                    for key in key_indicators:
                        if key in parsed:
                            value = parsed[key]
                            if isinstance(value, dict):
                                print(f"  • {key}: {json.dumps(value, ensure_ascii=False)}")
                            else:
                                print(f"  • {key}: {value}")
                
                # 打印前500字符的完整JSON
                full_json = json.dumps(parsed, ensure_ascii=False, indent=2)
                if len(full_json) > 500:
                    print(f"\n📄 完整数据（前500字符）:")
                    print(full_json[:500] + "...")
                else:
                    print(f"\n📄 完整数据:")
                    print(full_json)
                    
            except json.JSONDecodeError:
                print(f"📋 结果类型: str (非JSON)")
                print(f"📋 内容长度: {len(result_data)} 字符")
                if len(result_data) > 500:
                    print(f"\n{result_data[:500]}...")
                else:
                    print(f"\n{result_data}")
        
        elif isinstance(result_data, dict):
            print(f"📋 结果类型: dict")
            print(f"📋 字段数量: {len(result_data)}")
            print(f"\n{json.dumps(result_data, ensure_ascii=False, indent=2)[:500]}...")
        else:
            print(f"📋 结果类型: {type(result_data)}")
            print(f"\n{result_data}")
        
        print("="*80 + "\n")
    
    @staticmethod
    def print_data_summary(title: str, data: Dict):
        """
        打印数据摘要
        
        Args:
            title: 标题
            data: 数据字典
        """
        print("\n" + "="*80)
        print(f"📊 {title}")
        print("="*80)
        
        if not isinstance(data, dict):
            print(f"⚠️ 数据类型错误: {type(data)}")
            print("="*80 + "\n")
            return
        
        # 提取关键信息
        if "targets" in data:
            targets = data["targets"]
            if isinstance(targets, dict):
                print(f"✅ targets 类型: dict")
                print(f"✅ Symbol: {targets.get('symbol', 'N/A')}")
                print(f"✅ Status: {targets.get('status', 'N/A')}")
                print(f"✅ Spot Price: {targets.get('spot_price', 'N/A')}")
                print(f"✅ EM1 Dollar: {targets.get('em1_dollar', 'N/A')}")
                
                # 检查嵌套字段
                if "gamma_metrics" in targets:
                    gm = targets["gamma_metrics"]
                    print(f"\n📈 Gamma Metrics:")
                    print(f"  • vol_trigger: {gm.get('vol_trigger', 'N/A')}")
                    print(f"  • spot_vs_trigger: {gm.get('spot_vs_trigger', 'N/A')}")
                    print(f"  • net_gex: {gm.get('net_gex', 'N/A')}")
                
                if "walls" in targets:
                    walls = targets["walls"]
                    print(f"\n🧱 Walls:")
                    print(f"  • call_wall: {walls.get('call_wall', 'N/A')}")
                    print(f"  • put_wall: {walls.get('put_wall', 'N/A')}")
                    print(f"  • major_wall: {walls.get('major_wall', 'N/A')}")
            else:
                print(f"⚠️ targets 类型: {type(targets)}")
        
        if "validation_summary" in data:
            vs = data["validation_summary"]
            print(f"\n✔️ 验证摘要:")
            print(f"  • 完成率: {vs.get('completion_rate', 0)}%")
            print(f"  • 提供字段: {vs.get('provided', 0)}/{vs.get('total_required', 22)}")
            print(f"  • 缺失字段: {vs.get('missing_count', 0)}")
        
        print("="*80 + "\n")