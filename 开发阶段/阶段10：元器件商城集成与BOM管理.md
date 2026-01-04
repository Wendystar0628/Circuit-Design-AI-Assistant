## 阶段十：元器件商城集成与BOM管理 (1.5周)

> **目标**：集成嘉立创商城API，实现元器件参数查询、库存检查、BOM成本估算、SPICE模型自动获取

> **⚠️ 本阶段统一管理提示**：
> - 元器件 API 调用必须通过 ExternalServiceManager（自动获得重试/熔断）
> - 元器件缓存通过 CacheManager 管理，避免频繁请求
> - 元器件数据通过 FileManager 持久化到本地
> - 新增 UI 面板需实现 `retranslate_ui()` 方法

> **⚠️ 跨阶段依赖检查**：
> - 开始本阶段前，必须确认以下模块已正确实现并读取其源码：
>   - `domain/llm/external_service_manager.py` - 外部服务调用接口
>   - `infrastructure/persistence/file_manager.py` - 文件操作接口
>   - `shared/event_bus.py` - 事件发布订阅机制
>   - `domain/simulation/executor/spice_executor.py` - SPICE 仿真执行器

> **📚 嘉立创商城 API 参考**：
> - 官方网站：https://www.szlcsc.com/
> - API 文档：https://www.szlcsc.com/api.html（需注册开发者账号）
> - 搜索接口：支持型号搜索、参数筛选、分类浏览
> - 数据接口：元器件规格参数、数据手册下载、SPICE 模型获取
> - 库存接口：实时库存查询、价格阶梯、交期信息

> **🎯 集成价值分析**：
> - **元器件参数自动获取**：LLM 设计电路时可查询真实元器件规格，避免凭"记忆"生成不准确参数
> - **设计可制造性验证**：检查设计中使用的元器件是否有货、是否停产
> - **BOM 成本估算**：在设计阶段就考虑成本因素，帮助用户做出经济性决策
> - **仿真模型关联**：自动下载元器件的 SPICE 模型，提高仿真精度

> **⚠️ 功能边界说明**：
> - 本模块定位为"分析和查询助手"，不提供元器件替换功能
> - 所有查询结果仅供参考，用户需自行决定是否采纳并手动修改电路文件
> - 系统不会自动修改用户的电路设计文件

---

### 10.0 元器件域架构概览

> **架构设计原则**：
> - 单一职责：每个模块专注于一个明确的职责
> - 开闭原则：通过适配器模式支持扩展其他元器件商城
> - 依赖倒置：高层模块依赖抽象接口，不依赖具体实现
> - 缓存优先：减少 API 调用次数，提升响应速度

#### 10.0.1 元器件域目录结构

```
domain/component/
├── __init__.py
├── models/                          # 数据模型定义
│   ├── __init__.py
│   ├── component.py                 # 元器件数据类
│   ├── normalized_specs.py          # 标准化规格数据类
│   ├── search_result.py             # 搜索结果数据类
│   ├── bom_item.py                  # BOM 条目数据类
│   └── spice_model.py               # SPICE 模型数据类
├── normalizer/                      # 参数标准化层
│   ├── __init__.py
│   ├── parameter_normalizer.py      # 参数标准化器（入口）
│   ├── value_parser.py              # 数值解析器
│   └── unit_converter.py            # 单位转换器
├── service/                         # 服务层
│   ├── __init__.py
│   ├── component_service.py         # 元器件服务门面类
│   ├── search_service.py            # 元器件搜索服务
│   ├── bom_analyzer.py              # BOM 分析器
│   └── model_downloader.py          # SPICE 模型下载器
├── adapter/                         # 商城适配器
│   ├── __init__.py
│   ├── base_adapter.py              # 适配器抽象基类
│   ├── lcsc_adapter.py              # 嘉立创适配器
│   └── lcsc_response_parser.py      # 嘉立创响应解析器
├── cache/                           # 缓存管理
│   ├── __init__.py
│   ├── component_cache.py           # 元器件缓存
│   └── model_cache.py               # SPICE 模型缓存
└── tools/                           # LLM 工具定义
    ├── __init__.py
    └── component_tools.py           # 元器件相关工具
```



#### 10.0.2 元器件数据流图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        元器件查询数据流转路径                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [LLM 工具调用 / 用户搜索]                                               │
│       │                                                                 │
│       ▼                                                                 │
│  ComponentService.search_component(query)                               │
│       │                                                                 │
│       ├──► ComponentCache.get(query_hash)                               │
│       │         │                                                       │
│       │         ├─ 缓存命中 ──► 直接返回                                │
│       │         │                                                       │
│       │         └─ 缓存未命中 ──► 继续查询                              │
│       │                                                                 │
│       ├──► SearchService.search()                                       │
│       │         │                                                       │
│       │         ├──► LCSCAdapter.search(query)                          │
│       │         │         │                                             │
│       │         │         ├──► ExternalServiceManager.call()            │
│       │         │         │         │                                   │
│       │         │         │         ▼                                   │
│       │         │         │    [嘉立创 API 请求]                         │
│       │         │         │                                             │
│       │         │         └──► LCSCResponseParser.parse()               │
│       │         │                   │                                   │
│       │         │                   ▼                                   │
│       │         │              [原始 Component 列表]                     │
│       │         │                                                       │
│       │         ├──► ParameterNormalizer.normalize_batch()              │
│       │         │         │                                             │
│       │         │         ▼                                             │
│       │         │    [标准化后的 Component 列表]                         │
│       │         │                                                       │
│       │         └──► ComponentCache.set(query_hash, results)            │
│       │                                                                 │
│       ▼                                                                 │
│  [返回搜索结果]                                                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                        BOM 分析数据流转路径                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [用户触发 BOM 分析]                                                     │
│       │                                                                 │
│       ▼                                                                 │
│  BOMAnalyzer.analyze_circuit(circuit_file)                              │
│       │                                                                 │
│       ├──► CircuitAnalyzer.extract_components()                         │
│       │         │                                                       │
│       │         ▼                                                       │
│       │    [元器件清单：R1=10K, C1=100nF, ...]                          │
│       │                                                                 │
│       ├──► ComponentService.batch_search(components)                    │
│       │         │                                                       │
│       │         ▼                                                       │
│       │    [匹配的商城元器件列表（已标准化）]                            │
│       │                                                                 │
│       ├──► 库存检查 + 价格查询                                          │
│       │         │                                                       │
│       │         ▼                                                       │
│       │    [库存状态、价格阶梯]                                          │
│       │                                                                 │
│       └──► 生成 BOM 报告                                                │
│                 │                                                       │
│                 ▼                                                       │
│            [BOMReport: 总成本、库存状态、可用性摘要]                      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                        SPICE 模型获取数据流转路径                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [仿真前模型检查 / LLM 请求模型]                                         │
│       │                                                                 │
│       ▼                                                                 │
│  ModelDownloader.get_model(component_id)                                │
│       │                                                                 │
│       ├──► ModelCache.get(component_id)                                 │
│       │         │                                                       │
│       │         ├─ 缓存命中 ──► 返回本地模型路径                        │
│       │         │                                                       │
│       │         └─ 缓存未命中 ──► 继续下载                              │
│       │                                                                 │
│       ├──► LCSCAdapter.get_spice_model(component_id)                    │
│       │         │                                                       │
│       │         ▼                                                       │
│       │    [下载 SPICE 模型文件]                                         │
│       │                                                                 │
│       ├──► 保存到 vendor/models/spice/{component_id}.lib                │
│       │                                                                 │
│       ├──► ModelCache.set(component_id, local_path)                     │
│       │                                                                 │
│       └──► 返回本地模型路径                                             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 10.0.3 元器件事件定义

> **设计原则**：集中定义所有元器件相关事件常量，避免事件名拼写错误，便于追踪发布者和订阅者

- [ ] **文件路径**：`shared/events/component_events.py`
- [ ] **事件常量定义**：
  ```python
  class ComponentEvents:
      """元器件相关事件定义"""
      
      # 搜索事件
      SEARCH_STARTED = "component.search_started"
      SEARCH_COMPLETE = "component.search_complete"
      SEARCH_ERROR = "component.search_error"
      
      # BOM 分析事件
      BOM_ANALYSIS_STARTED = "component.bom_analysis_started"
      BOM_ANALYSIS_PROGRESS = "component.bom_analysis_progress"
      BOM_ANALYSIS_COMPLETE = "component.bom_analysis_complete"
      BOM_ANALYSIS_ERROR = "component.bom_analysis_error"
      
      # 库存事件
      STOCK_CHECK_COMPLETE = "component.stock_check_complete"
      STOCK_LOW_WARNING = "component.stock_low_warning"
      COMPONENT_DISCONTINUED = "component.discontinued"
      
      # SPICE 模型事件
      MODEL_DOWNLOAD_STARTED = "component.model_download_started"
      MODEL_DOWNLOAD_COMPLETE = "component.model_download_complete"
      MODEL_DOWNLOAD_ERROR = "component.model_download_error"
      MODEL_NOT_AVAILABLE = "component.model_not_available"
  ```
- [ ] **被调用方**：所有元器件相关模块通过导入此常量类使用事件名

---

### 10.1 元器件数据模型 (`domain/component/models/`)

> **设计原则**：使用 dataclass 定义标准化数据结构，确保类型安全，提供 IDE 自动补全支持

#### 10.1.1 `component.py` - 元器件数据类

- [ ] **文件路径**：`domain/component/models/component.py`
- [ ] **职责**：定义元器件的标准化数据结构
- [ ] **数据类定义**：
  - `Component` - 元器件基础信息
    - `component_id: str` - 商城元器件 ID
    - `part_number: str` - 型号/料号
    - `manufacturer: str` - 制造商
    - `description: str` - 描述
    - `category: str` - 分类（电阻/电容/运放等）
    - `subcategory: Optional[str]` - 子分类（如电容的：陶瓷/电解/钽电容）
    - `package: str` - 封装（0603/0805/DIP-8等）
    - `datasheet_url: Optional[str]` - 数据手册链接
    - `spice_model_available: bool` - 是否有 SPICE 模型
    - `raw_specifications: Dict[str, str]` - API 返回的原始规格参数
    - `normalized_specs: Optional[NormalizedSpecs]` - 标准化后的规格参数
    - `stock_info: StockInfo` - 库存信息
    - `price_info: PriceInfo` - 价格信息
  - `StockInfo` - 库存信息
    - `in_stock: bool` - 是否有货
    - `quantity: int` - 库存数量
    - `lead_time: Optional[str]` - 交期
    - `is_discontinued: bool` - 是否停产
    - `last_updated: str` - 最后更新时间
  - `PriceInfo` - 价格信息
    - `currency: str` - 货币单位（CNY）
    - `price_breaks: List[PriceBreak]` - 价格阶梯
    - `min_order_quantity: int` - 最小起订量
  - `PriceBreak` - 价格阶梯
    - `quantity: int` - 数量
    - `unit_price: float` - 单价
- [ ] **核心方法**：
  - `to_dict()` - 序列化为字典
  - `from_dict(data)` - 从字典反序列化
  - `get_price_for_quantity(qty)` - 根据数量获取单价
  - `is_available()` - 判断是否可购买
  - `has_normalized_specs()` - 判断是否已完成参数标准化
- [ ] **被调用方**：所有元器件相关模块

#### 10.1.2 `normalized_specs.py` - 标准化规格数据类

- [ ] **文件路径**：`domain/component/models/normalized_specs.py`
- [ ] **职责**：定义经过标准化处理后的元器件规格参数
- [ ] **设计说明**：
  - API 返回的参数格式混乱（如 "10uF", "10u", "10 microfarad" 表示同一值）
  - 本数据类存储标准化后的数值，便于后续比对和匹配
  - 所有数值统一使用基本单位（欧姆、法拉、亨利、伏特、瓦特）
- [ ] **数据类定义**：
  - `NormalizedSpecs` - 标准化规格参数
    - `value_numeric: Optional[float]` - 标称值数值（基本单位）
    - `value_unit: Optional[str]` - 标称值单位（Ω/F/H）
    - `value_display: Optional[str]` - 显示用字符串（如 "10kΩ"）
    - `tolerance_percent: Optional[float]` - 容差百分比（如 1.0 表示 ±1%）
    - `voltage_rating_v: Optional[float]` - 额定电压（伏特）
    - `power_rating_w: Optional[float]` - 额定功率（瓦特）
    - `temperature_coefficient_ppm: Optional[float]` - 温度系数（ppm/°C）
    - `operating_temp_min_c: Optional[float]` - 最低工作温度（摄氏度）
    - `operating_temp_max_c: Optional[float]` - 最高工作温度（摄氏度）
    - `normalization_success: bool` - 标准化是否成功
    - `normalization_errors: List[str]` - 标准化过程中的错误信息
- [ ] **核心方法**：
  - `to_dict()` - 序列化为字典
  - `from_dict(data)` - 从字典反序列化
  - `is_value_compatible(other, tolerance_factor)` - 判断数值是否兼容
  - `is_voltage_sufficient(required_v)` - 判断耐压是否满足要求
  - `is_power_sufficient(required_w)` - 判断功率是否满足要求
- [ ] **被调用方**：`ParameterNormalizer`、`SearchService`、`BOMAnalyzer`

#### 10.1.3 `bom_item.py` - BOM 条目数据类

- [ ] **文件路径**：`domain/component/models/bom_item.py`
- [ ] **职责**：定义 BOM 条目和分析报告的数据结构
- [ ] **数据类定义**：
  - `BOMItem` - BOM 单条记录
    - `reference: str` - 位号（如 R1、C2、U1）
    - `value: str` - 标称值（如 10K、100nF）
    - `footprint: Optional[str]` - 封装
    - `quantity: int` - 数量
    - `matched_component: Optional[Component]` - 匹配的商城元器件
    - `match_confidence: float` - 匹配置信度（0-1）
    - `status: BOMItemStatus` - 状态
  - `BOMItemStatus` - BOM 条目状态枚举
    - `MATCHED` - 已匹配且有货
    - `LOW_STOCK` - 已匹配但库存不足
    - `OUT_OF_STOCK` - 已匹配但缺货
    - `DISCONTINUED` - 已停产
    - `NOT_FOUND` - 未找到匹配
    - `MULTIPLE_MATCHES` - 多个匹配需用户选择
  - `BOMReport` - BOM 分析报告
    - `circuit_file: str` - 电路文件路径
    - `items: List[BOMItem]` - BOM 条目列表
    - `total_cost: float` - 总成本估算
    - `currency: str` - 货币单位
    - `availability_summary: AvailabilitySummary` - 可用性摘要
    - `warnings: List[str]` - 警告信息
    - `generated_at: str` - 生成时间
  - `AvailabilitySummary` - 可用性摘要
    - `total_items: int` - 总条目数
    - `matched_count: int` - 已匹配数
    - `in_stock_count: int` - 有货数
    - `out_of_stock_count: int` - 缺货数
    - `discontinued_count: int` - 停产数
    - `not_found_count: int` - 未找到数
- [ ] **核心方法**：
  - `to_dict()` - 序列化为字典
  - `from_dict(data)` - 从字典反序列化
  - `get_availability_rate()` - 获取可用率
  - `get_items_by_status(status)` - 按状态筛选条目
- [ ] **被调用方**：`BOMAnalyzer`、`BOMDialog`

#### 10.1.4 `spice_model.py` - SPICE 模型数据类

- [ ] **文件路径**：`domain/component/models/spice_model.py`
- [ ] **职责**：定义 SPICE 模型的数据结构
- [ ] **数据类定义**：
  - `SpiceModel` - SPICE 模型信息
    - `model_id: str` - 模型 ID
    - `component_id: str` - 关联的元器件 ID
    - `model_type: SpiceModelType` - 模型类型
    - `model_name: str` - 模型名称（.model 或 .subckt 名称）
    - `local_path: Optional[str]` - 本地文件路径
    - `download_url: Optional[str]` - 下载链接
    - `file_size: Optional[int]` - 文件大小（字节）
    - `checksum: Optional[str]` - 文件校验和
    - `downloaded_at: Optional[str]` - 下载时间
  - `SpiceModelType` - 模型类型枚举
    - `PRIMITIVE` - 原始模型（.model）
    - `SUBCIRCUIT` - 子电路模型（.subckt）
    - `BEHAVIORAL` - 行为模型
- [ ] **核心方法**：
  - `is_downloaded()` - 判断是否已下载
  - `get_include_statement()` - 生成 .include 语句
- [ ] **被调用方**：`ModelDownloader`、`SpiceExecutor`

---

### 10.2 商城适配器模块组 (`domain/component/adapter/`)

> **设计原则**：采用适配器模式，将商城 API 的具体实现与业务逻辑解耦，便于后续扩展其他元器件商城

#### 10.2.1 `base_adapter.py` - 适配器抽象基类

- [ ] **文件路径**：`domain/component/adapter/base_adapter.py`
- [ ] **职责**：定义元器件商城适配器的统一接口
- [ ] **抽象基类 `ComponentMarketAdapter`**：
  - `get_name()` - 返回商城名称
  - `search(query, filters)` - 搜索元器件（返回原始数据，由标准化层处理）
  - `get_component_detail(component_id)` - 获取元器件详情
  - `check_stock(component_ids)` - 批量检查库存
  - `get_price(component_id, quantity)` - 获取价格
  - `get_spice_model(component_id)` - 获取 SPICE 模型
  - `get_datasheet_url(component_id)` - 获取数据手册链接
- [ ] **搜索过滤器 `SearchFilters`**：
  - `category: Optional[str]` - 分类
  - `manufacturer: Optional[str]` - 制造商
  - `package: Optional[str]` - 封装
  - `in_stock_only: bool` - 仅显示有货
  - `min_quantity: Optional[int]` - 最小库存
  - `max_price: Optional[float]` - 最高单价
- [ ] **被调用方**：`SearchService`、`ComponentService`

#### 10.2.2 `lcsc_adapter.py` - 嘉立创适配器

- [ ] **文件路径**：`domain/component/adapter/lcsc_adapter.py`
- [ ] **职责**：实现嘉立创商城 API 的适配器
- [ ] **继承**：`ComponentMarketAdapter`（抽象基类）
- [ ] **核心功能**：
  - `search(query, filters)` - 调用嘉立创搜索 API
  - `get_component_detail(component_id)` - 获取元器件详情
  - `check_stock(component_ids)` - 批量库存查询
  - `get_price(component_id, quantity)` - 价格查询
  - `get_spice_model(component_id)` - 下载 SPICE 模型
- [ ] **API 端点配置**：
  - 搜索接口：`/api/products/search`
  - 详情接口：`/api/products/{id}`
  - 库存接口：`/api/products/stock`
  - 模型接口：`/api/products/{id}/spice`
- [ ] **认证方式**：
  - API Key 认证（存储在 CredentialManager）
  - 请求头：`Authorization: Bearer {api_key}`
- [ ] **请求限流**：
  - 遵守嘉立创 API 限流规则
  - 默认限制：10 次/秒
  - 超限时自动等待重试
- [ ] **依赖**：`ExternalServiceManager`（HTTP 请求）、`LCSCResponseParser`（响应解析）
- [ ] **被调用方**：`SearchService`、`ModelDownloader`

#### 10.2.3 `lcsc_response_parser.py` - 嘉立创响应解析器

- [ ] **文件路径**：`domain/component/adapter/lcsc_response_parser.py`
- [ ] **职责**：解析嘉立创 API 响应，转换为原始数据结构（不做标准化）
- [ ] **核心功能**：
  - `parse_search_response(response)` - 解析搜索结果
  - `parse_component_detail(response)` - 解析元器件详情
  - `parse_stock_response(response)` - 解析库存信息
  - `parse_price_response(response)` - 解析价格信息
  - `parse_model_response(response)` - 解析模型信息
- [ ] **字段映射**：
  - 将嘉立创 API 字段映射到 `Component.raw_specifications`
  - 保留原始格式，不做单位转换（由标准化层处理）
  - 处理字段缺失，记录缺失字段
- [ ] **错误处理**：
  - API 返回错误码时抛出对应异常
  - 数据格式异常时记录日志并返回部分结果
- [ ] **被调用方**：`LCSCAdapter`

---

### 10.3 参数标准化层 (`domain/component/normalizer/`)

> **设计原则**：
> - API 返回的参数格式混乱，必须经过标准化才能用于后续比对
> - 标准化层作为数据清洗的唯一入口，所有元器件数据必须经过此层处理
> - 标准化失败不阻塞流程，但需记录错误信息供调试

#### 10.3.1 `parameter_normalizer.py` - 参数标准化器

- [ ] **文件路径**：`domain/component/normalizer/parameter_normalizer.py`
- [ ] **职责**：作为参数标准化的统一入口，协调各子模块完成标准化
- [ ] **核心功能**：
  - `normalize(component)` - 标准化单个元器件的参数
  - `normalize_batch(components)` - 批量标准化
  - `normalize_value(raw_value, category)` - 标准化单个参数值
- [ ] **标准化流程**：
  1. 从 `Component.raw_specifications` 提取原始参数
  2. 调用 `ValueParser` 解析数值和单位
  3. 调用 `UnitConverter` 转换为基本单位
  4. 生成 `NormalizedSpecs` 对象
  5. 记录标准化过程中的错误
- [ ] **错误处理**：
  - 解析失败时记录到 `NormalizedSpecs.normalization_errors`
  - 设置 `normalization_success = False`
  - 不抛出异常，允许流程继续
- [ ] **依赖**：`ValueParser`、`UnitConverter`
- [ ] **被调用方**：`SearchService`、`ComponentService`

#### 10.3.2 `value_parser.py` - 数值解析器

- [ ] **文件路径**：`domain/component/normalizer/value_parser.py`
- [ ] **职责**：解析各种格式的元器件参数值，提取数值和单位
- [ ] **核心功能**：
  - `parse_resistance(raw_value)` - 解析电阻值
  - `parse_capacitance(raw_value)` - 解析电容值
  - `parse_inductance(raw_value)` - 解析电感值
  - `parse_voltage(raw_value)` - 解析电压值
  - `parse_power(raw_value)` - 解析功率值
  - `parse_tolerance(raw_value)` - 解析容差值
  - `parse_temperature(raw_value)` - 解析温度值
- [ ] **支持的输入格式示例**：
  - 电阻：`"10K"`, `"10k"`, `"10 kΩ"`, `"10kOhm"`, `"10000"`, `"10.0K"`
  - 电容：`"10uF"`, `"10u"`, `"10 microfarad"`, `"10µF"`, `"0.01mF"`, `"10000nF"`
  - 电压：`"50V"`, `"50 V"`, `"50Volt"`, `"50VDC"`
  - 容差：`"±1%"`, `"1%"`, `"+/-1%"`, `"±1 %"`
  - 温度：`"-40~+85°C"`, `"-40 to 85 C"`, `"-40/+85"`
- [ ] **返回值**：`ParsedValue` 数据类
  - `numeric_value: Optional[float]` - 解析出的数值
  - `unit: Optional[str]` - 解析出的单位
  - `success: bool` - 解析是否成功
  - `error_message: Optional[str]` - 错误信息
- [ ] **被调用方**：`ParameterNormalizer`

#### 10.3.3 `unit_converter.py` - 单位转换器

- [ ] **文件路径**：`domain/component/normalizer/unit_converter.py`
- [ ] **职责**：将各种单位转换为基本单位
- [ ] **核心功能**：
  - `to_ohms(value, unit)` - 转换为欧姆
  - `to_farads(value, unit)` - 转换为法拉
  - `to_henries(value, unit)` - 转换为亨利
  - `to_volts(value, unit)` - 转换为伏特
  - `to_watts(value, unit)` - 转换为瓦特
  - `to_celsius(value, unit)` - 转换为摄氏度
- [ ] **单位映射表**：
  - 电阻：`{"Ω": 1, "mΩ": 1e-3, "kΩ": 1e3, "MΩ": 1e6, "ohm": 1, "kohm": 1e3, ...}`
  - 电容：`{"F": 1, "mF": 1e-3, "µF": 1e-6, "uF": 1e-6, "nF": 1e-9, "pF": 1e-12, ...}`
  - 电感：`{"H": 1, "mH": 1e-3, "µH": 1e-6, "uH": 1e-6, "nH": 1e-9, ...}`
- [ ] **格式化输出**：
  - `format_resistance(ohms)` - 格式化为可读字符串（如 10000 → "10kΩ"）
  - `format_capacitance(farads)` - 格式化为可读字符串（如 1e-6 → "1µF"）
- [ ] **被调用方**：`ParameterNormalizer`

---

### 10.4 元器件服务模块组 (`domain/component/service/`)

> **初始化顺序**：阶段十启动时初始化，依赖 ExternalServiceManager、ComponentCache、ParameterNormalizer，注册到 ServiceLocator

#### 10.4.1 `component_service.py` - 元器件服务门面类

- [ ] **文件路径**：`domain/component/service/component_service.py`
- [ ] **职责**：作为元器件功能的统一入口，协调各子模块
- [ ] **核心功能**：
  - `search_component(query, filters)` - 搜索元器件（返回标准化后的结果）
  - `get_component_detail(component_id)` - 获取元器件详情
  - `batch_search(components)` - 批量搜索（用于 BOM 分析）
  - `check_availability(component_ids)` - 检查可用性
  - `get_spice_model(component_id)` - 获取 SPICE 模型
  - `estimate_cost(bom_items)` - 估算成本
- [ ] **缓存策略**：
  - 搜索结果缓存 1 小时
  - 元器件详情缓存 24 小时
  - 库存信息缓存 15 分钟
  - 价格信息缓存 1 小时
- [ ] **依赖模块**：
  - `SearchService` - 搜索服务
  - `ParameterNormalizer` - 参数标准化
  - `BOMAnalyzer` - BOM 分析
  - `ModelDownloader` - 模型下载
  - `ComponentCache` - 缓存管理
- [ ] **被调用方**：`tool_executor.py`（LLM 工具调用）、`ComponentPanel`（UI）

#### 10.4.2 `search_service.py` - 元器件搜索服务

- [ ] **文件路径**：`domain/component/service/search_service.py`
- [ ] **职责**：专注于元器件搜索逻辑
- [ ] **核心功能**：
  - `search(query, filters, adapter)` - 执行搜索
  - `parse_component_value(value_str)` - 解析元器件值（如 "10K" → 10000）
  - `match_by_specs(specs, candidates)` - 按规格匹配（基于 NormalizedSpecs）
  - `rank_results(results, query)` - 结果排序
- [ ] **智能搜索策略**：
  - 支持型号精确搜索（如 "LM741"）
  - 支持参数模糊搜索（如 "10K 0603 电阻"）
  - 支持规格范围搜索（如 "100nF ±10% 50V"）
- [ ] **结果排序规则**：
  - 型号匹配度优先
  - 有货优先于缺货
  - 常用封装优先
  - 价格从低到高
- [ ] **标准化集成**：
  - 搜索完成后调用 `ParameterNormalizer.normalize_batch()` 处理结果
  - 确保返回的 Component 对象包含 `normalized_specs`
- [ ] **被调用方**：`ComponentService`

#### 10.4.3 `bom_analyzer.py` - BOM 分析器

- [ ] **文件路径**：`domain/component/service/bom_analyzer.py`
- [ ] **职责**：从电路文件提取元器件清单并进行分析
- [ ] **核心功能**：
  - `analyze_circuit(circuit_file)` - 分析电路文件生成 BOM
  - `extract_components(circuit_content)` - 提取元器件列表
  - `match_components(bom_items)` - 匹配商城元器件
  - `calculate_cost(bom_items, quantity)` - 计算成本
  - `generate_report(bom_items)` - 生成 BOM 报告
- [ ] **元器件提取规则**：
  - 电阻：`R{name} {node1} {node2} {value}` → 提取 value
  - 电容：`C{name} {node1} {node2} {value}` → 提取 value
  - 电感：`L{name} {node1} {node2} {value}` → 提取 value
  - 二极管：`D{name} ...` → 提取型号
  - 晶体管：`Q{name} ...` / `M{name} ...` → 提取型号
  - 运放：`X{name} ... {model}` → 提取 model
- [ ] **匹配策略**：
  - 优先按型号精确匹配
  - 无型号时按参数匹配（基于 NormalizedSpecs）
  - 多个匹配时返回最佳匹配和备选列表
- [ ] **成本计算**：
  - 根据数量选择合适的价格阶梯
  - 考虑最小起订量
  - 汇总总成本
- [ ] **被调用方**：`ComponentService`、`BOMDialog`

#### 10.4.4 `model_downloader.py` - SPICE 模型下载器

- [ ] **文件路径**：`domain/component/service/model_downloader.py`
- [ ] **职责**：管理 SPICE 模型的下载和本地存储，所有外部下载必须经过用户确认
- [ ] **核心功能**：
  - `get_model(component_id)` - 获取模型（优先本地缓存）
  - `check_model_availability(component_id)` - 检查商城是否有该模型（不下载）
  - `request_download(component_id)` - 请求下载模型（发送事件，等待用户确认）
  - `execute_download(component_id)` - 执行实际下载（仅在用户确认后调用）
  - `validate_model(model_path)` - 验证模型文件有效性
  - `get_local_models()` - 获取已下载的模型列表
  - `clear_cache()` - 清理模型缓存
- [ ] **用户确认机制**：
  - `request_download()` 发布 `MODEL_DOWNLOAD_REQUESTED` 事件
  - 依赖健康面板订阅该事件，展示待下载模型列表
  - 用户点击"确认下载"后，面板调用 `execute_download()`
  - 下载完成后发布 `MODEL_DOWNLOAD_COMPLETE` 事件
  - 绝不自动下载外部模型，避免引入错误版本
- [ ] **存储位置**：
  - 下载目录：`~/.circuit_design_ai/spice_models/`
  - 文件命名：`{component_id}.lib` 或 `{component_id}.sub`
- [ ] **模型验证**：
  - 检查文件是否包含有效的 .model 或 .subckt 定义
  - 验证模型名称与元器件匹配
  - 检查文件完整性（校验和）
- [ ] **与依赖健康服务集成**：
  - 作为 `ExternalResolver` 的解析源之一
  - 提供 `check_model_availability()` 供解析策略查询
  - 下载完成后通知 `DependencyHealthService` 更新报告
- [ ] **被调用方**：`ComponentService`、`ExternalResolver`、`DependencyHealthPanel`

---

### 10.5 缓存管理模块组 (`domain/component/cache/`)

#### 10.5.1 `component_cache.py` - 元器件缓存

- [ ] **文件路径**：`domain/component/cache/component_cache.py`
- [ ] **职责**：管理元器件搜索结果和详情的缓存
- [ ] **核心功能**：
  - `get(cache_key)` - 获取缓存
  - `set(cache_key, data, ttl)` - 设置缓存
  - `invalidate(cache_key)` - 失效指定缓存
  - `invalidate_all()` - 清空所有缓存
  - `get_stats()` - 获取缓存统计
- [ ] **缓存策略**：
  - 搜索结果：TTL 1 小时，LRU 淘汰
  - 元器件详情：TTL 24 小时，LRU 淘汰
  - 库存信息：TTL 15 分钟，主动刷新
  - 价格信息：TTL 1 小时，LRU 淘汰
- [ ] **缓存键设计**：
  - 搜索：`search:{query_hash}:{filters_hash}`
  - 详情：`detail:{component_id}`
  - 库存：`stock:{component_id}`
  - 价格：`price:{component_id}:{quantity}`
- [ ] **持久化**：
  - 缓存数据持久化到 `~/.circuit_design_ai/component_cache.json`
  - 启动时加载，关闭时保存
  - 过期数据在加载时自动清理
- [ ] **被调用方**：`ComponentService`、`SearchService`

#### 10.5.2 `model_cache.py` - SPICE 模型缓存

- [ ] **文件路径**：`domain/component/cache/model_cache.py`
- [ ] **职责**：管理已下载 SPICE 模型的索引
- [ ] **核心功能**：
  - `get(component_id)` - 获取模型本地路径
  - `set(component_id, local_path, metadata)` - 记录已下载模型
  - `remove(component_id)` - 删除模型记录
  - `list_all()` - 列出所有已下载模型
  - `get_total_size()` - 获取缓存总大小
  - `cleanup_old(max_age_days)` - 清理过期模型
- [ ] **索引结构**：
  ```python
  {
    "component_id": {
      "local_path": str,
      "model_name": str,
      "model_type": str,
      "file_size": int,
      "checksum": str,
      "downloaded_at": str,
      "last_used": str,
    }
  }
  ```
- [ ] **存储位置**：
  - 索引文件：`~/.circuit_design_ai/spice_models/index.json`
  - 模型文件：`~/.circuit_design_ai/spice_models/{component_id}.lib`
- [ ] **被调用方**：`ModelDownloader`

---

### 10.6 LLM 工具定义 (`domain/component/tools/`)

#### 10.6.1 `component_tools.py` - 元器件相关工具

- [ ] **文件路径**：`domain/component/tools/component_tools.py`
- [ ] **职责**：定义 LLM 可调用的元器件相关工具 Schema
- [ ] **工具清单**：
  - **搜索工具**：
    - `search_component` - 搜索元器件
      - 参数：`query`（搜索关键词）、`category`（分类，可选）、`in_stock_only`（仅有货，可选）
      - 返回：元器件列表（型号、规格、库存、价格）
    - `get_component_detail` - 获取元器件详情
      - 参数：`component_id`（元器件 ID）
      - 返回：完整规格参数、数据手册链接、SPICE 模型可用性
  - **库存工具**：
    - `check_availability` - 检查元器件可用性
      - 参数：`component_ids`（元器件 ID 列表）
      - 返回：库存状态、数量、交期
  - **BOM 工具**：
    - `analyze_bom` - 分析电路 BOM
      - 参数：`circuit_file`（电路文件路径，可选，默认当前电路）
      - 返回：BOM 报告（元器件清单、匹配状态、总成本）
    - `estimate_cost` - 估算成本
      - 参数：`bom_items`（BOM 条目列表）、`quantity`（生产数量）
      - 返回：总成本、单板成本、价格明细
  - **模型工具**：
    - `get_spice_model` - 获取 SPICE 模型
      - 参数：`component_id`（元器件 ID）
      - 返回：模型文件路径、.include 语句
- [ ] **Schema 格式**：遵循 OpenAI Function Calling 规范
- [ ] **工具注册**：在 `tool_registry.py` 中注册这些工具
- [ ] **被调用方**：`tool_executor.py`（LLM 工具调用）

---

### 10.7 元器件面板 (`presentation/panels/`)

> **⚠️ UI架构对齐**：本节设计遵循阶段一 1.7 节定义的 UI 层架构规范：
> - ComponentViewModel 继承自 `BaseViewModel`，遵循统一的 ViewModel 模式
> - 面板通过 `PanelManager` 注册，通过 `TabController` 管理标签页切换（TAB_COMPONENT）
> - 元器件搜索事件通过 `UIEventBridge` 桥接到 UI 层
> - 与信息面板的通信通过 EventBus（搜索结果同步到信息面板）

#### 10.7.1 `component_panel.py` - 元器件搜索面板

- [ ] **文件路径**：`presentation/panels/component_panel.py`
- [ ] **职责**：提供元器件搜索和浏览的 UI 界面，通过 ViewModel 获取数据
- [ ] **位置**：右栏标签页（与对话面板并列，TAB_COMPONENT）
- [ ] **视觉设计**：
  - 面板标题栏：显示"元器件"或"Components"
  - 搜索区域：搜索框 + 分类筛选下拉框 + 仅有货复选框
  - 结果列表：卡片式显示，每个元器件一张卡片
  - 详情区域：选中元器件后显示详细规格
- [ ] **国际化支持**：
  - 实现 `retranslate_ui()` 方法
  - 订阅 `EVENT_LANGUAGE_CHANGED` 事件
- [ ] **核心功能**：
  - `search(query)` - 执行搜索
  - `show_detail(component)` - 显示元器件详情
  - `download_model(component)` - 下载 SPICE 模型
- [ ] **元器件卡片显示内容**：
  - 型号（加粗）
  - 制造商
  - 规格摘要（值、封装）
  - 库存状态图标（绿色有货/黄色低库存/红色缺货）
  - 单价（显示最低阶梯价）
  - SPICE 模型可用标识
- [ ] **详情面板显示内容**：
  - 完整规格参数表格
  - 价格阶梯表格
  - 数据手册链接（可点击打开）
  - SPICE 模型下载按钮
- [ ] **交互**：
  - 单击卡片 → 显示详情
  - 右键菜单：查看详情、下载模型、复制型号
- [ ] **被调用方**：`main_window.py`（布局）、`TabController`（标签页管理）

#### 10.7.1.1 `component_view_model.py` - ViewModel 层

- [ ] **文件路径**：`presentation/panels/component/component_view_model.py`
- [ ] **职责**：作为 UI 与 ComponentService 之间的中间层，隔离 component_panel 与数据层的直接依赖
- [ ] **继承**：`BaseViewModel`（阶段一 1.7.2 节定义）
- [ ] **核心属性**（供 UI 绑定）：
  - `search_results` - 搜索结果列表（`DisplayComponent` 类型）
  - `selected_component` - 当前选中的元器件详情
  - `is_searching` - 是否正在搜索
  - `filter_category` - 当前筛选分类
  - `filter_in_stock` - 是否仅显示有货
  - `download_progress` - 模型下载进度
- [ ] **核心方法**：
  - `search(query)` - 执行搜索（委托给 ComponentService）
  - `load_detail(component_id)` - 加载元器件详情
  - `format_component(component)` - 将原始数据转换为 DisplayComponent
  - `download_model(component_id)` - 下载 SPICE 模型
- [ ] **事件订阅**：
  - 订阅 `SEARCH_COMPLETE` 更新搜索结果
  - 订阅 `MODEL_DOWNLOAD_PROGRESS` 更新下载进度
  - 订阅 `MODEL_DOWNLOAD_COMPLETE` 完成下载
  - 订阅 `STOCK_LOW_WARNING` 显示库存预警
- [ ] **DisplayComponent 数据结构**（UI 友好格式）：
  - `id` - 元器件唯一标识
  - `model` - 型号
  - `manufacturer` - 制造商
  - `specs_summary` - 规格摘要
  - `stock_status` - 库存状态（in_stock/low_stock/out_of_stock）
  - `stock_icon` - 库存状态图标
  - `price_display` - 格式化的价格显示
  - `has_spice_model` - 是否有 SPICE 模型
- [ ] **与 TabController 集成**：
  - 搜索完成时，若当前不在元器件标签页，更新徽章计数
  - 切换到元器件标签页时，清除徽章
- [ ] **被调用方**：`component_panel.py`

#### 10.7.2 `bom_dialog.py` - BOM 分析对话框

- [ ] **文件路径**：`presentation/dialogs/bom_dialog.py`
- [ ] **职责**：显示 BOM 分析结果和成本估算
- [ ] **触发方式**：
  - 菜单栏"工具"→"BOM 分析"
  - 工具栏 BOM 按钮
  - LLM 调用 `analyze_bom` 工具后自动弹出
- [ ] **对话框布局**：
  ```
  ┌─────────────────────────────────────────────────────────────┐
  │  BOM Analysis / BOM 分析                               [×]  │
  ├─────────────────────────────────────────────────────────────┤
  │                                                             │
  │  Circuit File / 电路文件：amplifier.cir                     │
  │                                                             │
  │  ┌─────────────────────────────────────────────────────────┐│
  │  │ ⚠️ 查询结果仅供参考，请以实际采购时的商城数据为准        ││
  │  └─────────────────────────────────────────────────────────┘│
  │                                                             │
  │  ┌─────────────────────────────────────────────────────┐   │
  │  │ Ref  │ Value   │ Package │ Status │ Price  │ Match  │   │
  │  ├─────────────────────────────────────────────────────┤   │
  │  │ R1   │ 10K     │ 0603    │ ✓ 有货 │ ¥0.01  │ 98%    │   │
  │  │ R2   │ 10K     │ 0603    │ ✓ 有货 │ ¥0.01  │ 98%    │   │
  │  │ C1   │ 100nF   │ 0603    │ ⚠ 低库存│ ¥0.02  │ 95%    │   │
  │  │ U1   │ LM741   │ DIP-8   │ ✗ 缺货 │ -      │ 100%   │   │
  │  └─────────────────────────────────────────────────────┘   │
  │                                                             │
  │  Summary / 摘要：                                           │
  │  - Total Items / 总条目：4                                  │
  │  - In Stock / 有货：2 (50%)                                 │
  │  - Low Stock / 低库存：1 (25%)                              │
  │  - Out of Stock / 缺货：1 (25%)                             │
  │                                                             │
  │  Estimated Cost / 估算成本：¥12.50 (Qty: 10)                │
  │                                                             │
  │  [Export CSV] [Close / 关闭]                                │
  │                                                             │
  └─────────────────────────────────────────────────────────────┘
  ```
- [ ] **提示条**：
  - 位置：BOM 表格上方
  - 样式：浅蓝色背景，深色文字，带信息图标
  - 内容："查询结果仅供参考，请以实际采购时的商城数据为准"
  - 国际化：支持中英文切换
- [ ] **核心功能**：
  - `load_bom(circuit_file)` - 加载并分析 BOM
  - `export_csv()` - 导出 BOM 为 CSV
  - `update_quantity(qty)` - 更新生产数量重新计算成本
- [ ] **状态图标**：
  - ✓ 绿色：有货
  - ⚠ 黄色：低库存（<100）
  - ✗ 红色：缺货或停产
  - ? 灰色：未找到匹配
- [ ] **国际化支持**：
  - 实现 `retranslate_ui()` 方法
  - 订阅 `EVENT_LANGUAGE_CHANGED` 事件
- [ ] **被调用方**：`main_window.py`（菜单触发）、`tool_executor.py`（工具调用后显示）

---

### 10.8 配置管理扩展

#### 10.8.1 凭证管理扩展

- [ ] **扩展 `credential_manager.py`**：
  - 新增凭证类型：`CREDENTIAL_TYPE_COMPONENT = "component"`
  - 支持存储嘉立创 API Key
- [ ] **凭证存储结构扩展**：
  ```python
  {
    "component": {
      "lcsc": {
        "api_key": "encrypted_value",
        "updated_at": "2024-01-01T00:00:00Z"
      }
    }
  }
  ```

#### 10.8.2 配置管理扩展

- [ ] **扩展 `config_manager.py`**：
  - 新增配置字段：
    - `component_provider: str` - 当前元器件商城（默认 "lcsc"）
    - `component_cache_ttl: int` - 缓存过期时间（秒）
    - `auto_check_stock: bool` - 仿真前自动检查库存
    - `auto_download_model: bool` - 自动下载缺失的 SPICE 模型

#### 10.8.3 设置常量扩展

- [ ] **扩展 `settings.py`**：
  ```python
  # 元器件商城相关常量
  COMPONENT_PROVIDER_LCSC = "lcsc"
  SUPPORTED_COMPONENT_PROVIDERS = [COMPONENT_PROVIDER_LCSC]
  DEFAULT_COMPONENT_PROVIDER = COMPONENT_PROVIDER_LCSC
  
  # 缓存相关常量
  DEFAULT_COMPONENT_CACHE_TTL = 3600  # 1小时
  DEFAULT_STOCK_CACHE_TTL = 900       # 15分钟
  DEFAULT_PRICE_CACHE_TTL = 3600      # 1小时
  
  # API 相关常量
  LCSC_API_BASE_URL = "https://www.szlcsc.com/api"
  LCSC_API_RATE_LIMIT = 10  # 每秒请求数
  ```

---

### 10.9 与其他阶段的集成点

#### 10.9.1 与阶段三（LLM 工具系统）集成

- [ ] **工具注册**：
  - 在 `tool_registry.py` 中注册元器件相关工具
  - 工具 Schema 定义在 `component_tools.py`
- [ ] **工具执行**：
  - 在 `tool_dispatcher.py` 中添加元器件工具的处理器映射
  - `search_component` → `component_service.search_component()`
  - `get_component_detail` → `component_service.get_component_detail()`
  - `check_availability` → `component_service.check_availability()`
  - `analyze_bom` → `bom_analyzer.analyze_circuit()`
  - `get_spice_model` → `model_downloader.get_model()`
- [ ] **上下文注入**：
  - 在 `implicit_context_collector.py` 中添加元器件上下文收集
  - 当用户讨论元器件选型时，自动注入相关元器件信息

#### 10.9.2 与阶段二（依赖健康检查）集成

- [ ] **作为外部解析策略**：
  - `ModelDownloader` 作为 `ExternalResolver` 的一个解析源
  - 当 `DependencyHealthService` 检测到缺失的 SPICE 模型时，可通过 `ExternalResolver` 调用 `ModelDownloader` 尝试从商城下载
  - 下载操作必须经过用户确认，不自动执行
- [ ] **用户确认机制**：
  - 在依赖健康面板中展示可从商城下载的模型列表
  - 用户点击"下载"按钮后才执行实际下载
  - 下载完成后自动更新依赖健康报告
- [ ] **模型来源标识**：
  - 从商城下载的模型在依赖健康报告中标注来源为"嘉立创商城"
  - 用户可查看模型的元器件 ID、下载时间等元数据

#### 10.9.3 与阶段四（仿真引擎）集成

- [ ] **仿真前依赖检查**：
  - 在 `spice_executor.py` 的 `execute()` 方法中调用 `DependencyHealthService.get_cached_report()`
  - 若存在未解决的缺失依赖，阻止仿真并返回明确错误
  - 错误信息中包含"打开依赖健康面板"的操作建议
- [ ] **模型路径注入**：
  - 自动生成 `.include` 语句
  - 将下载的模型路径添加到仿真配置中

#### 10.9.4 与阶段五（RAG 知识检索）集成

- [ ] **元器件数据索引**：
  - 将常用元器件的规格参数索引到知识库
  - 支持语义搜索（如"低噪声运放推荐"）
- [ ] **数据手册索引**：
  - 下载的数据手册可索引到 `documents` 集合
  - 支持从数据手册中检索技术参数

#### 10.9.5 与阶段六至八（工作流编排）集成

- [ ] **设计流程集成**：
  - 在 `initial_design_node` 中，LLM 可调用元器件搜索工具选择合适的元器件
  - 在 `simulation_node` 前，依赖健康检查已在项目打开时完成，此处仅做最终确认
- [ ] **检查点选项扩展**：
  - 新增"分析 BOM"选项，显示当前设计的元器件清单和成本
  - 新增"检查库存"选项，验证设计的可制造性

---

### 10.10 与统一信息展示面板集成

> **⚠️ 架构说明**：元器件商城模块的信息展示、日志查看、复制导出等功能统一由阶段九的"统一信息展示面板"（Unified Info Panel）负责。本阶段仅定义商城事件和数据结构，不实现独立的日志服务、导出服务或日志查看器面板。

> **设计原则**：
> - 职责单一：商城模块专注于元器件搜索和 BOM 分析，信息展示由统一面板负责
> - 事件驱动：商城模块发布结构化事件，统一面板订阅并处理
> - 格式化分离：领域层事件只携带结构化业务数据，格式化逻辑由阶段九的格式化器负责

#### 10.10.1 商城事件数据规范

##### `SEARCH_COMPLETE` 事件数据（元器件搜索）

- [ ] **事件名**：`ComponentEvents.SEARCH_COMPLETE`
- [ ] **数据结构**：
  ```python
  {
    "query": str,                    # 搜索关键词
    "results": List[Component],      # 搜索结果列表
    "total_count": int,              # 结果总数
    "search_time_ms": float,         # 搜索耗时
  }
  ```

##### `BOM_ANALYSIS_COMPLETE` 事件数据

- [ ] **事件名**：`ComponentEvents.BOM_ANALYSIS_COMPLETE`
- [ ] **数据结构**：
  ```python
  {
    "circuit_file": str,             # 电路文件路径
    "report": BOMReport,             # BOM 报告对象
    "total_cost": float,             # 总成本
    "availability_rate": float,      # 可用率
  }
  ```

##### `MODEL_DOWNLOAD_COMPLETE` 事件数据

- [ ] **事件名**：`ComponentEvents.MODEL_DOWNLOAD_COMPLETE`
- [ ] **数据结构**：
  ```python
  {
    "component_id": str,             # 元器件 ID
    "model_path": str,               # 模型本地路径
    "model_type": str,               # 模型类型
  }
  ```

##### `STOCK_LOW_WARNING` 事件数据

- [ ] **事件名**：`ComponentEvents.STOCK_LOW_WARNING`
- [ ] **数据结构**：
  ```python
  {
    "component_id": str,             # 元器件 ID
    "part_number": str,              # 型号
    "current_stock": int,            # 当前库存
    "required_quantity": int,        # 需求数量
  }
  ```

#### 10.10.2 统一信息面板集成点

> **集成说明**：元器件商城模块的输出信息将自动推送到统一信息展示面板（阶段九 9.0 节），便于用户集中查看和管理

- [ ] **元器件搜索结果卡片**：`ComponentInfoCollector`（阶段九）订阅 `SEARCH_COMPLETE` 事件，创建 `InfoCard`
- [ ] **BOM 分析报告卡片**：`ComponentInfoCollector` 订阅 `BOM_ANALYSIS_COMPLETE` 事件，创建 `InfoCard`
- [ ] **模型下载状态卡片**：`ComponentInfoCollector` 订阅 `MODEL_DOWNLOAD_COMPLETE` 事件，创建 `InfoCard`
- [ ] **库存预警卡片**：`ComponentInfoCollector` 订阅 `STOCK_LOW_WARNING` 事件，创建 `InfoCard`
- [ ] **格式化职责**：由阶段九的 `ComponentFormatter` 负责生成展示文本
- [ ] **复制导出功能**：由统一信息面板的 `export_dialog.py` 统一提供

---

### 10.11 阶段检查点

#### 10.11.1 功能验证检查项

- [ ] 元器件搜索功能正常，能返回准确结果
- [ ] 元器件详情获取正常，规格参数完整
- [ ] 参数标准化功能正常，各种格式的参数值能正确解析
- [ ] 库存查询功能正常，状态显示准确
- [ ] BOM 分析功能正常，能正确提取电路元器件
- [ ] SPICE 模型下载功能正常，模型可用于仿真
- [ ] 缓存机制正常，减少重复 API 调用
- [ ] LLM 工具调用正常，能正确执行元器件相关操作

#### 10.11.2 参数标准化验证检查项

- [ ] 电阻值解析正常（"10K", "10k", "10 kΩ", "10kOhm" 等）
- [ ] 电容值解析正常（"10uF", "10u", "10 microfarad", "10µF" 等）
- [ ] 电压值解析正常（"50V", "50 V", "50Volt" 等）
- [ ] 容差值解析正常（"±1%", "1%", "+/-1%" 等）
- [ ] 温度范围解析正常（"-40~+85°C", "-40 to 85 C" 等）
- [ ] 单位转换正确（kΩ → Ω, µF → F 等）
- [ ] 标准化失败时正确记录错误信息

#### 10.11.3 集成验证检查项

- [ ] 与 LLM 工具系统集成正常
- [ ] 与仿真引擎集成正常，模型自动下载可用
- [ ] 与 RAG 知识检索集成正常（可选）
- [ ] 与工作流编排集成正常
- [ ] UI 面板显示正常，交互流畅
- [ ] 国际化支持正常

#### 10.11.4 统一信息面板集成验证检查项

- [ ] **事件发布验收**：
  - 元器件搜索完成后 `SEARCH_COMPLETE` 事件正确发布
  - BOM 分析完成后 `BOM_ANALYSIS_COMPLETE` 事件正确发布
  - 模型下载完成后 `MODEL_DOWNLOAD_COMPLETE` 事件正确发布
  - 库存预警时 `STOCK_LOW_WARNING` 事件正确发布
  - 事件数据结构符合规范
- [ ] **集成验收**：
  - 阶段九的 `ComponentInfoCollector` 能正确订阅并处理事件
  - 元器件搜索结果卡片在统一信息面板正确显示
  - BOM 分析报告卡片在统一信息面板正确显示
