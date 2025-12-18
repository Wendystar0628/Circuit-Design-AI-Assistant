"""
GLM-4.6V 视觉模型 API 测试脚本

用于直接测试 API 调用，排查图片上传问题。
"""

import base64
import json
import os
import sys

import httpx

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_vision_api_with_url():
    """测试使用 URL 图片的 API 调用"""
    print("=" * 60)
    print("测试 1: 使用 URL 图片")
    print("=" * 60)
    
    # 从配置获取 API Key
    try:
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_CONFIG_MANAGER
        config_manager = ServiceLocator.get(SVC_CONFIG_MANAGER)
        api_key = config_manager.get_api_key()
    except Exception:
        # 如果无法从配置获取，尝试从环境变量获取
        api_key = os.environ.get("ZHIPU_API_KEY", "")
    
    if not api_key:
        print("错误: 未找到 API Key")
        return False
    
    # 构建请求体（使用官方示例的 URL）
    request_body = {
        "model": "glm-4.6v",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://cdn.bigmodel.cn/static/logo/register.png"
                        }
                    },
                    {
                        "type": "text",
                        "text": "这张图片显示了什么？"
                    }
                ]
            }
        ],
        "thinking": {"type": "enabled"},
        "stream": False
    }
    
    print(f"请求体: {json.dumps(request_body, indent=2, ensure_ascii=False)}")
    
    # 发送请求
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    
    try:
        response = httpx.post(
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            json=request_body,
            headers=headers,
            timeout=60.0
        )
        
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.text[:500]}...")
        
        if response.status_code == 200:
            print("✓ URL 图片测试成功!")
            return True
        else:
            print("✗ URL 图片测试失败!")
            return False
            
    except Exception as e:
        print(f"请求异常: {e}")
        return False


def test_vision_api_with_base64(image_path: str = None):
    """测试使用 Base64 图片的 API 调用"""
    print("\n" + "=" * 60)
    print("测试 2: 使用 Base64 图片")
    print("=" * 60)
    
    # 从配置获取 API Key
    try:
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_CONFIG_MANAGER
        config_manager = ServiceLocator.get(SVC_CONFIG_MANAGER)
        api_key = config_manager.get_api_key()
    except Exception:
        api_key = os.environ.get("ZHIPU_API_KEY", "")
    
    if not api_key:
        print("错误: 未找到 API Key")
        return False
    
    # 如果没有提供图片路径，创建一个简单的测试图片
    if not image_path:
        # 使用一个简单的 1x1 红色 PNG 图片（base64 编码）
        # 这是一个有效的最小 PNG 文件
        test_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
        mime_type = "image/png"
        print("使用测试图片 (1x1 红色 PNG)")
    else:
        # 读取并编码图片
        if not os.path.isfile(image_path):
            print(f"错误: 图片文件不存在: {image_path}")
            return False
        
        ext = os.path.splitext(image_path)[1].lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        mime_type = mime_types.get(ext, "image/png")
        
        with open(image_path, "rb") as f:
            test_base64 = base64.b64encode(f.read()).decode("utf-8")
        
        print(f"使用图片: {image_path}")
        print(f"MIME 类型: {mime_type}")
        print(f"Base64 长度: {len(test_base64)}")
    
    # 构建请求体
    request_body = {
        "model": "glm-4.6v",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{test_base64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": "这张图片显示了什么？"
                    }
                ]
            }
        ],
        "thinking": {"type": "enabled"},
        "stream": False
    }
    
    # 打印请求体（不打印完整 base64）
    request_preview = json.loads(json.dumps(request_body))
    url = request_preview["messages"][0]["content"][0]["image_url"]["url"]
    request_preview["messages"][0]["content"][0]["image_url"]["url"] = url[:50] + "..."
    print(f"请求体: {json.dumps(request_preview, indent=2, ensure_ascii=False)}")
    
    # 发送请求
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    
    try:
        response = httpx.post(
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            json=request_body,
            headers=headers,
            timeout=60.0
        )
        
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.text[:500]}...")
        
        if response.status_code == 200:
            print("✓ Base64 图片测试成功!")
            return True
        else:
            print("✗ Base64 图片测试失败!")
            return False
            
    except Exception as e:
        print(f"请求异常: {e}")
        return False


def test_current_implementation():
    """测试当前实现的消息构建"""
    print("\n" + "=" * 60)
    print("测试 3: 当前实现的消息构建")
    print("=" * 60)
    
    try:
        from domain.llm.context_manager import ContextManager
        from domain.llm.message_types import Attachment
        
        # 创建 ContextManager
        cm = ContextManager()
        
        # 模拟添加带图片的消息
        # 创建一个模拟的附件
        class MockAttachment:
            def __init__(self):
                self.type = "image"
                self.name = "test.png"
                self.path = "test.png"  # 不存在的文件
        
        class MockMessage:
            def __init__(self):
                self.role = "user"
                self.content = "这是什么图片？"
                self.attachments = [MockAttachment()]
        
        # 测试消息转换
        msg = MockMessage()
        result = cm._convert_message_for_llm(msg)
        
        print(f"转换结果: {json.dumps(result, indent=2, ensure_ascii=False, default=str)}")
        
        # 检查结果格式
        if isinstance(result.get("content"), list):
            print("✓ 内容是列表格式")
            for i, item in enumerate(result["content"]):
                print(f"  [{i}] type={item.get('type')}")
        else:
            print("✗ 内容不是列表格式")
        
        return True
        
    except Exception as e:
        print(f"测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("GLM-4.6V 视觉模型 API 测试")
    print("=" * 60)
    
    # 测试 1: URL 图片
    test_vision_api_with_url()
    
    # 测试 2: Base64 图片
    test_vision_api_with_base64()
    
    # 测试 3: 当前实现
    test_current_implementation()
    
    print("\n" + "=" * 60)
    print("测试完成")
