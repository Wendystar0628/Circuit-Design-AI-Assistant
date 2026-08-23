# Circuit Design AI - Main Package
"""
电路AI设计助理 - 基于LLM的电路设计自动化工具

Architecture:
- frontend/desktop Electron + React 单窗口桌面界面
- desktop_backend/ 本地认证 REST/WebSocket 适配器
- application/     应用层 (项目、会话、服务生命周期编排)
- domain/          领域层 (LLM、仿真、RAG 与知识检索)
- infrastructure/  基础设施层 (配置、持久化、适配器)
- shared/          共享内核层 (ServiceLocator、EventBus)

当前运行时状态边界：
- React 根上下文管理桌面导航、当前项目与活动文档
- ApplicationRuntime 是 Python 服务生命周期唯一所有者
- SessionStateManager/ContextManager 管理对话会话与消息
- SessionStateProjector 将 ProjectService/RAG 状态写入轻量 API 读模型
"""

__version__ = "0.1.0"
__author__ = "Circuit Design AI Team"
