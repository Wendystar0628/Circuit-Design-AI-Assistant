#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Vendor 资源验证脚本

验证 ngspice、嵌入模型、重排序模型是否正确配置和可用。
此脚本独立于主测试文件，用于深入诊断配置问题。

运行方式：
    cd circuit_design_ai
    python tests/verify_vendor_resources.py
"""

import sys
import os
import platform
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_header(title: str):
    """打印标题"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_section(title: str):
    """打印小节标题"""
    print(f"\n--- {title} ---")


def check_file_exists(path: Path, description: str) -> bool:
    """检查文件是否存在"""
    exists = path.exists()
    status = "✅ 存在" if exists else "❌ 不存在"
    print(f"  {description}: {status}")
    if exists:
        if path.is_file():
            size_mb = path.stat().st_size / (1024 * 1024)
            print(f"    路径: {path}")
            print(f"    大小: {size_mb:.2f} MB")
        else:
            print(f"    路径: {path}")
    return exists


def verify_ngspice():
    """验证 ngspice 配置"""
    print_header("ngspice 仿真引擎验证")
    
    # 1. 检查目录结构
    print_section("1. 目录结构检查")
    
    vendor_ngspice = PROJECT_ROOT / "vendor" / "ngspice"
    print(f"  vendor/ngspice 目录: {'✅ 存在' if vendor_ngspice.exists() else '❌ 不存在'}")
    
    # 检查 Windows 目录（当前平台）
    current_platform = platform.system()
    print(f"  当前平台: {current_platform}")
    
    if current_platform == "Windows":
        win64_dir = vendor_ngspice / "win64" / "Spice64_dll"
        dll_dir = win64_dir / "dll-vs"
        ngspice_dll = dll_dir / "ngspice.dll"
        lib_dir = win64_dir / "lib" / "ngspice"
        
        check_file_exists(win64_dir, "win64/Spice64_dll 目录")
        check_file_exists(dll_dir, "dll-vs 目录")
        check_file_exists(ngspice_dll, "ngspice.dll")
        check_file_exists(lib_dir, "lib/ngspice 目录")
        
        # 检查 OpenMP 依赖
        omp_dll = dll_dir / "libomp140.x86_64.dll"
        check_file_exists(omp_dll, "libomp140.x86_64.dll")
    
    # 2. 测试配置模块
    print_section("2. 配置模块测试")
    
    try:
        # 重置模块状态（强制重新配置）
        import infrastructure.utils.ngspice_config as ngspice_config
        
        # 重置状态变量
        ngspice_config._ngspice_configured = False
        ngspice_config._ngspice_available = False
        ngspice_config._ngspice_path = None
        ngspice_config._configuration_error = None
        
        # 获取详细信息
        info = ngspice_config.get_ngspice_info()
        print(f"  配置前状态:")
        print(f"    configured: {info['configured']}")
        print(f"    available: {info['available']}")
        print(f"    base_path: {info['base_path']}")
        print(f"    platform: {info['platform']}")
        print(f"    packaged: {info['packaged']}")
        
        # 执行配置
        print("\n  执行 configure_ngspice()...")
        result = ngspice_config.configure_ngspice()
        print(f"  配置结果: {'✅ 成功' if result else '❌ 失败'}")
        
        # 获取配置后信息
        info = ngspice_config.get_ngspice_info()
        print(f"\n  配置后状态:")
        print(f"    configured: {info['configured']}")
        print(f"    available: {info['available']}")
        print(f"    path: {info['path']}")
        print(f"    error: {info['error']}")
        
        # 检查路径计算
        print_section("3. 路径计算诊断")
        base_path = ngspice_config._get_base_path()
        print(f"  _get_base_path(): {base_path}")
        
        # 手动计算预期路径
        if current_platform == "Windows":
            expected_base = base_path / "vendor" / "ngspice" / "win64" / "Spice64_dll"
            expected_dll = expected_base / "dll-vs" / "ngspice.dll"
            print(f"  预期 ngspice 基础目录: {expected_base}")
            print(f"  预期 ngspice.dll 路径: {expected_dll}")
            print(f"  预期路径存在: {'✅' if expected_dll.exists() else '❌'}")
            
            # 测试 _find_ngspice_path
            found_path = ngspice_config._find_ngspice_path(base_path, "Windows")
            print(f"  _find_ngspice_path() 返回: {found_path}")
        
    except Exception as e:
        print(f"  ❌ 配置模块测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 3. 测试 PySpice 加载
    print_section("4. PySpice 加载测试")
    
    try:
        from PySpice.Spice.NgSpice.Shared import NgSpiceShared
        print(f"  PySpice 导入: ✅ 成功")
        print(f"  NgSpiceShared.LIBRARY_PATH: {getattr(NgSpiceShared, 'LIBRARY_PATH', 'N/A')}")
    except ImportError as e:
        print(f"  PySpice 导入: ⚠️ 未安装 ({e})")
    except Exception as e:
        print(f"  PySpice 导入: ❌ 失败 ({e})")


def verify_embedding_model():
    """验证嵌入模型配置"""
    print_header("嵌入模型验证 (gte-modernbert-base)")
    
    # 1. 检查目录结构
    print_section("1. 目录结构检查")
    
    model_dir = PROJECT_ROOT / "vendor" / "models" / "embeddings" / "gte-modernbert-base"
    check_file_exists(model_dir, "模型目录")
    
    # 检查必需文件
    required_files = ["config.json", "model.safetensors", "tokenizer.json"]
    all_exist = True
    for filename in required_files:
        exists = check_file_exists(model_dir / filename, filename)
        all_exist = all_exist and exists
    
    print(f"\n  必需文件完整性: {'✅ 完整' if all_exist else '❌ 不完整'}")
    
    # 2. 测试配置模块
    print_section("2. 配置模块测试")
    
    try:
        import infrastructure.utils.model_config as model_config
        
        # 重置状态
        model_config._models_configured = False
        model_config._embedding_model_path = None
        model_config._reranker_model_path = None
        model_config._configuration_errors = {}
        
        # 获取详细信息
        info = model_config.get_model_info()
        print(f"  配置前状态:")
        print(f"    configured: {info['configured']}")
        print(f"    base_path: {info['base_path']}")
        
        # 执行配置
        print("\n  执行 configure_models()...")
        result = model_config.configure_models()
        print(f"  配置结果: {'✅ 成功' if result else '❌ 失败'}")
        
        # 获取配置后信息
        info = model_config.get_model_info()
        print(f"\n  嵌入模型状态:")
        print(f"    available: {info['embedding']['available']}")
        print(f"    path: {info['embedding']['path']}")
        print(f"    error: {info['embedding']['error']}")
        
        # 路径诊断
        print_section("3. 路径计算诊断")
        base_path = model_config._get_base_path()
        print(f"  _get_base_path(): {base_path}")
        
        expected_path = base_path / "vendor" / "models" / "embeddings" / "gte-modernbert-base"
        print(f"  预期模型路径: {expected_path}")
        print(f"  预期路径存在: {'✅' if expected_path.exists() else '❌'}")
        
        # 测试 _find_local_model_path
        from infrastructure.utils.model_config import ModelType
        found_path = model_config._find_local_model_path(ModelType.EMBEDDING)
        print(f"  _find_local_model_path(EMBEDDING) 返回: {found_path}")
        
        # 测试 _validate_model_path
        if found_path:
            valid = model_config._validate_model_path(found_path, ModelType.EMBEDDING)
            print(f"  _validate_model_path() 返回: {valid}")
        
    except Exception as e:
        print(f"  ❌ 配置模块测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 3. 测试模型加载
    print_section("4. 模型加载测试")
    
    try:
        from sentence_transformers import SentenceTransformer
        print(f"  sentence_transformers 导入: ✅ 成功")
        
        model_path = model_config.get_embedding_model_path()
        print(f"  模型路径: {model_path}")
        
        # 尝试加载模型（可能需要较长时间）
        print("  正在加载模型（可能需要几秒钟）...")
        model = SentenceTransformer(model_path, trust_remote_code=True)
        print(f"  模型加载: ✅ 成功")
        print(f"  模型维度: {model.get_sentence_embedding_dimension()}")
        
        # 测试编码
        test_text = "This is a test sentence for embedding."
        embedding = model.encode(test_text)
        print(f"  测试编码: ✅ 成功 (维度: {len(embedding)})")
        
    except ImportError as e:
        print(f"  sentence_transformers 导入: ⚠️ 未安装 ({e})")
    except Exception as e:
        print(f"  模型加载测试: ❌ 失败 ({e})")
        import traceback
        traceback.print_exc()


def verify_reranker_model():
    """验证重排序模型配置"""
    print_header("重排序模型验证 (mxbai-rerank-base-v1)")
    
    # 1. 检查目录结构
    print_section("1. 目录结构检查")
    
    model_dir = PROJECT_ROOT / "vendor" / "models" / "rerankers" / "mxbai-rerank-base-v1"
    check_file_exists(model_dir, "模型目录")
    
    # 检查必需文件
    required_files = ["config.json", "model.safetensors", "tokenizer.json"]
    all_exist = True
    for filename in required_files:
        exists = check_file_exists(model_dir / filename, filename)
        all_exist = all_exist and exists
    
    print(f"\n  必需文件完整性: {'✅ 完整' if all_exist else '❌ 不完整'}")
    
    # 2. 测试配置模块
    print_section("2. 配置模块测试")
    
    try:
        import infrastructure.utils.model_config as model_config
        
        # 获取配置后信息（假设已在嵌入模型测试中配置）
        info = model_config.get_model_info()
        print(f"  重排序模型状态:")
        print(f"    available: {info['reranker']['available']}")
        print(f"    path: {info['reranker']['path']}")
        print(f"    error: {info['reranker']['error']}")
        
        # 路径诊断
        print_section("3. 路径计算诊断")
        base_path = model_config._get_base_path()
        
        expected_path = base_path / "vendor" / "models" / "rerankers" / "mxbai-rerank-base-v1"
        print(f"  预期模型路径: {expected_path}")
        print(f"  预期路径存在: {'✅' if expected_path.exists() else '❌'}")
        
        # 测试 _find_local_model_path
        from infrastructure.utils.model_config import ModelType
        found_path = model_config._find_local_model_path(ModelType.RERANKER)
        print(f"  _find_local_model_path(RERANKER) 返回: {found_path}")
        
        # 测试 _validate_model_path
        if found_path:
            valid = model_config._validate_model_path(found_path, ModelType.RERANKER)
            print(f"  _validate_model_path() 返回: {valid}")
        
    except Exception as e:
        print(f"  ❌ 配置模块测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 3. 测试模型加载
    print_section("4. 模型加载测试")
    
    try:
        from sentence_transformers import CrossEncoder
        print(f"  CrossEncoder 导入: ✅ 成功")
        
        model_path = model_config.get_reranker_model_path()
        print(f"  模型路径: {model_path}")
        
        # 尝试加载模型
        print("  正在加载模型（可能需要几秒钟）...")
        model = CrossEncoder(model_path, trust_remote_code=True)
        print(f"  模型加载: ✅ 成功")
        
        # 测试重排序
        query = "What is machine learning?"
        documents = [
            "Machine learning is a subset of artificial intelligence.",
            "The weather is nice today.",
            "Deep learning uses neural networks."
        ]
        
        pairs = [[query, doc] for doc in documents]
        scores = model.predict(pairs)
        print(f"  测试重排序: ✅ 成功")
        print(f"  分数: {scores}")
        
    except ImportError as e:
        print(f"  CrossEncoder 导入: ⚠️ 未安装 ({e})")
    except Exception as e:
        print(f"  模型加载测试: ❌ 失败 ({e})")
        import traceback
        traceback.print_exc()


def main():
    """主函数"""
    print("=" * 60)
    print("  Vendor 资源验证脚本")
    print("=" * 60)
    print(f"\n项目根目录: {PROJECT_ROOT}")
    print(f"Python 版本: {sys.version}")
    print(f"操作系统: {platform.system()} {platform.release()}")
    
    # 验证各项资源
    verify_ngspice()
    verify_embedding_model()
    verify_reranker_model()
    
    # 总结
    print_header("验证完成")
    print("\n如果看到 ❌ 标记，请检查对应的配置或文件。")
    print("如果配置模块返回的路径与预期不符，可能是路径计算逻辑有问题。")


if __name__ == "__main__":
    main()
