# 原理图布局引擎重构设计文档

## 1. 文档目标

本文档用于指导 `circuit_design_ai` 中仿真面板原理图页的布局引擎重构工作。

本次重构的核心目标不是继续修补现有通用图布局，而是把当前 `ELK.js + 通用分层图 + 通用正交边` 的方案，替换为一个面向电路图语义的专用布局模型，使其在**不依赖 schematic 几何数据**的前提下，尽可能获得更美观、更专业、更稳定的绘制效果。

本文档只聚焦：

- 现有布局链路与问题边界
- 新布局模型的权威职责划分
- 需要新增和替换的关键文件
- 布局、符号朝向、连线、标签、渲染之间的全链路关系
- 后续真实落地时的实施顺序

本文档不包含具体实现代码。

---

## 2. 当前代码事实

以下事实已经基于当前前端代码核对：

- 原理图布局入口位于 `frontend/simulation-panel/src/components/tabs/schematicLayout.ts`
- 原理图页主入口位于 `frontend/simulation-panel/src/components/tabs/SchematicTab.tsx`
- 当前渲染主画布位于 `frontend/simulation-panel/src/components/tabs/SchematicCanvasSurface.tsx`
- 元件符号几何定义位于 `frontend/simulation-panel/src/components/tabs/symbolRegistry.tsx`
- 当前权威输入为 `frontend/simulation-panel/src/types/state.ts` 中的 `SchematicDocumentState`
- 当前 `SchematicTab` 在 `document_id` 或 `revision` 变化时调用 `computeSchematicLayout` 重新计算布局
- 当前 `schematicLayout.ts` 仍然依赖 `elkjs`，并把原理图问题转换为通用图节点、端口、边后交给 ELK 处理
- 当前 `SchematicCanvasSurface.tsx` 只消费 `layoutResult`，并不负责电路语义布局决策
- 仓库内仍存在旧的 `frontend/simulation-panel/src/components/tabs/SchematicCanvas.tsx`，其中包含已经不应继续作为权威来源的旧布局与旧渲染逻辑

---

## 3. 本次重构目标与硬约束

### 3.1 必达目标

- 用新的原理图语义布局模型替换当前 ELK 通用图布局
- 布局结果必须更贴近真实电路图阅读习惯，而不是只满足“图能摊开”
- 元件布局、旋转朝向、引脚出线方向、网络主干走向、标签落点都必须由同一套权威模型统一决定
- 前端最终必须只保留一条布局权威路径，避免多个布局来源并存
- 当前已有交互能力必须继续可用：
  - 平移
  - 缩放
  - Fit
  - 选中元件
  - 查看属性
- 对于未使用 schematic 几何数据的自动布局，优先提升整体可读性、规整性、器件朝向正确性和布线简洁度

### 3.2 硬约束

- 当前 `schematicDocument` 仍然是唯一权威输入，前端不能发明第二份文档真相
- 本次不能保留旧设计兼容层，替换后旧的非权威路径应直接删除
- 不允许继续让 ELK 作为实际布局核心，只做“外面包一层新接口、里面还是 ELK”不符合本次要求
- 本次暂不实现基于 schematic 几何数据的绘制
- 本次暂不引入手工拖拽布局编辑
- 每次真实代码修改后都需要重新构建 `simulation-panel`

### 3.3 本次非目标

- 不追求在首版自动布局中恢复 LTspice 级别的人工绘图质量
- 不在这一步实现导线手工编辑
- 不在这一步实现基于用户交互的器件手动旋转与持久化
- 不在这一步解决后端解析层所有 SPICE 方言差异

---

## 4. 推荐方案摘要

推荐方案是：**用前端自有的电路语义布局引擎替换 ELK**。

新的布局内核不再把问题抽象为“通用图自动布局”，而是直接围绕电路图的核心语义做布局：

- 元件类型分层
- 网络重要性分级
- 方向性器件朝向决策
- 主干网络优先直行
- 支路短接入主干
- 同类器件成组排列
- 标签与导线协同放置

新的布局结果仍由 `SchematicCanvasSurface.tsx` 消费，但布局计算结果的数据来源必须改为新的语义布局器，而不是 ELK 结果翻译层。

---

## 5. 替换边界与权威职责

### 5.1 需要保留的权威层

- `SchematicDocumentState`：权威输入文档
- `SchematicTab.tsx`：布局调度、视图状态、选中态与错误态管理
- `SchematicCanvasSurface.tsx`：权威渲染消费者
- `symbolRegistry.tsx`：权威符号几何与引脚锚点定义入口

### 5.2 需要替换的权威层

- `schematicLayout.ts` 中基于 ELK 的图构建、图布局、边结果转换逻辑
- 任何以“通用图节点/边”为中心、而不是以“电路图阅读语义”为中心的布局决策逻辑
- 旧 `SchematicCanvas.tsx` 中残留的旧布局与旧渲染辅助逻辑

### 5.3 需要删除的内容方向

- `elkjs` 依赖
- ELK 相关 import、graph builder、layout option、edge section 翻译代码
- 旧的重复布局实现与重复渲染路径
- 已不再是权威来源的 pin text / old canvas helper 等遗留设计

---

## 6. 需要修改的文件

本节只保留文件级摘要，具体实施顺序以第 11 节为准。

### 6.1 现有文件

- `frontend/simulation-panel/src/components/tabs/schematicLayout.ts`
  - 保留为原理图布局的单一对外出口
  - 内部替换为新的语义布局实现
- `frontend/simulation-panel/src/components/tabs/SchematicCanvasSurface.tsx`
  - 对齐新的组件朝向、引脚位置、导线段和标签结果
- `frontend/simulation-panel/src/components/tabs/SchematicTab.tsx`
  - 保持布局触发条件，但错误文案、状态表达和调度语义需要改为新布局引擎
- `frontend/simulation-panel/src/components/tabs/symbolRegistry.tsx`
  - 扩展符号朝向、引脚朝向决策、必要的旋转支持
- `frontend/simulation-panel/package.json`
  - 删除 `elkjs`
- `frontend/simulation-panel/package-lock.json`
  - 同步清理 `elkjs`

### 6.2 建议新增文件

- `frontend/simulation-panel/src/components/tabs/schematicSemanticLayout.ts`
  - 承载新的语义布局主实现
- `frontend/simulation-panel/src/components/tabs/schematicLayoutTypes.ts`
  - 如果现有 `schematicLayout.ts` 类型过于混杂，可抽离公共布局类型
- `frontend/simulation-panel/src/components/tabs/schematicPlacementHeuristics.ts`
  - 如果实现体量较大，可拆分放置策略和路由策略

是否拆文件以实际代码体量为准，但最终对外仍应收束为唯一权威布局入口。

---

## 7. 新布局模型的核心设计

### 7.1 核心思想

新的布局器不再追求“图论意义上的自动排版最优”，而是追求“电路图阅读意义上的可理解性”。

因此布局模型应优先回答以下问题：

- 哪些元件应被放在主信号流路径上
- 哪些器件天然应横向摆放，哪些应纵向摆放
- 哪些网络应成为主干，哪些只是短支路
- 一个网络标签应该贴近哪一段导线，才能最容易被人识别
- 一个三极管或 MOS 的符号应如何旋转，才能让关键引脚更自然地朝向其主要连接对象

### 7.2 布局阶段建议

建议把布局分成以下阶段：

1. 文档规范化
2. 元件语义分类
3. 连接图分析
4. 主方向与主干网络识别
5. 组件分组与粗放置
6. 器件朝向决策
7. 引脚出线侧决策
8. 正交导线生成
9. 标签落点与避让
10. 结果边界计算

### 7.3 组件放置原则

- 信号链主路径优先沿单一主方向展开，默认从左到右
- 电源网络优先上方，地网络优先下方
- 两端器件如电阻、电容、电感、二极管应优先顺着其连接主方向摆放
- 有明显输入/输出语义的器件，如运放、受控源、部分子电路 block，应让输入朝左、输出朝右
- BJT、MOS 等方向敏感器件必须让基极/栅极与主要驱动侧对齐，集电极/漏极更靠上，发射极/源极更靠下或更贴近返回路径
- 相同作用域或同一子电路内的组件应保持分组连续，避免被无关网络打散

### 7.4 连线原则

- 主干网络优先直线、少拐点
- 支路应尽量短距离挂接到主干，而不是形成层层折返
- 单条网络如果连接多个器件，应优先形成“主干 + 垂直接入”而不是多条对等折线
- 导线转折应尽量保持 90 度，避免冗余 Z 字折线
- 导线锚点必须严格吸附到符号引脚锚点，避免视觉上“图标和导线没连上”

### 7.5 标签原则

- 网络标签必须贴近真实连接段，而不是远离节点飘浮
- 组件名称和值标签要与符号朝向协同，不应压住主干导线
- 标签落点要和组件体、导线段、其它标签做基本避让

---

## 8. 渲染层对齐要求

渲染层本身不应再自行发明布局几何。

`SchematicCanvasSurface.tsx` 需要严格消费新布局结果中的：

- 组件位置
- 组件朝向或旋转信息
- 符号绘制区域
- 引脚绝对坐标
- 导线正交段
- 网络标签位置
- 组件标签位置
- 整体 bounds

如果当前渲染层还在本地推导某些位置，则这些逻辑应尽量回收进新布局引擎，避免再次形成“双重几何来源”。

---

## 9. 验证标准

完成重构后，至少应满足以下结果：

- 删除 ELK 依赖后仍能稳定生成布局
- 大多数两端器件能顺着主要连线方向摆放
- BJT、MOS、运放等方向敏感器件的符号与引脚连接关系明显更自然
- 网络主干的折线数量显著下降
- 节点标签更靠近真实连接点
- 不再出现明显的“导线没接到引脚上”的视觉错误
- 现有原理图页交互能力无回归
- `simulation-panel` 构建通过

---

## 10. 风险与实施原则

### 10.1 主要风险

- 自动判断主信号流方向可能在某些复杂拓扑下不稳定
- 器件朝向规则过弱会导致图面仍然别扭，规则过强则可能误判
- 自研正交路由如果过于简化，容易在多分支网络上产生碰撞或堆叠
- 若布局结果类型设计不干净，渲染层容易再次补几何，重新引入双权威问题

### 10.2 实施原则

- 宁可先做一套清晰、稳定、可扩展的专用布局器，也不要继续叠补丁修 ELK 结果
- 宁可先删除旧路径再补齐新路径，也不要长期并存两套权威设计
- 布局模型中的“器件放置、器件朝向、网络路由、标签放置”必须一体设计，不能拆成互相打架的独立小修补

---

## 11. 全链路实现步骤

本节已经吸收前文的目标、约束、替换边界、渲染要求和验证标准。实际开发时，优先按本节逐步推进。

### 第 1 步：先冻结权威边界，明确哪些代码必须被替换和删除

目标：在真正改动前先锁定“谁是输入、谁是输出、谁必须消失”，避免后面又回到旧逻辑补丁式演进。

实施点：

- 明确 `SchematicDocumentState` 是唯一布局输入
- 明确 `SchematicLayoutResult` 仍是唯一渲染输出协议
- 明确 `schematicLayout.ts` 是唯一对外布局入口，后续所有布局能力都必须经由这里收束
- 明确 `SchematicCanvasSurface.tsx` 是唯一主画布消费者
- 确认 `SchematicCanvas.tsx` 不再作为任何布局或渲染权威来源
- 确认本次重构后不允许保留 ELK 路径作为 fallback
- 盘点当前 `schematicLayout.ts` 中哪些函数纯属 ELK 翻译层，后续应整体删除而不是保留

开发提示：

- 这一步的价值是先切断“旧设计继续存活”的借口
- 如果边界不先冻结，后面很容易在实现压力下保留旧逻辑兜底，最终达不到彻底重构目标

输出：

- 明确的替换边界
- 明确的待删除代码清单
- 明确的新布局引擎唯一入口

### 第 2 步：重建布局结果模型，让输出结构服务于电路语义而不是服务于 ELK 翻译

目标：先把布局结果结构整理成适合语义布局的数据模型，再开始写算法，避免新算法被旧结果结构反向绑死。

实施点：

- 审核当前 `SchematicLayoutResult`、`SchematicLayoutComponent`、`SchematicLayoutPin`、`SchematicLayoutNet`、`SchematicLayoutBounds` 等类型
- 为组件增加明确的朝向或旋转表达，例如 `rotation`、`orientation` 或等价字段
- 为布局结果中的引脚记录权威绝对坐标，而不是只保留相对位置等待渲染层再次推导
- 让每条网络输出主干段、支路段或至少输出稳定的正交 polyline 段集合
- 让标签位置成为布局器直接输出，而不是渲染层二次猜测
- 如当前类型过度耦合 ELK 结果结构，应在这一步先拆干净

开发提示：

- 新的数据模型必须为后续“组件旋转 + 主干路由 + 标签协同”提供空间
- 如果结果模型仍然只适合“节点盒子 + ELK edge sections”，后面算法再好也会受限

输出：

- 一套不依赖 ELK 的布局结果类型
- 渲染层可直接消费的几何表达

### 第 3 步：建立文档规范化层，把原始元件和网络转换成布局友好的语义实体

目标：把后端传来的电路文档整理成布局器真正可用的中间结构，为后续主路径识别、器件分组、朝向决策提供基础。

实施点：

- 根据 `scope_path` 对组件和网络做作用域分组
- 根据 `symbol_kind`、`pin_roles`、`render_hints`、`port_side_hints` 对元件做语义分类
- 为每个组件构建布局实体，补齐宽高、引脚语义、候选朝向、可连接侧等信息
- 为每个网络统计连接组件数量、网络名、是否为电源/地/时钟/偏置/普通信号等基础类别
- 识别孤立组件、单端网络、极小连通分量，避免它们干扰主干布局
- 把需要在一起考虑的组件聚成布局 group，例如同一子电路、同一偏置支路、同一供电链路

开发提示：

- 这一步不是在画图，而是在建立“布局理解层”
- 规范化做得越干净，后面的策略越容易稳定

输出：

- 语义化组件集合
- 语义化网络集合
- 布局分组与连通分量信息

### 第 4 步：识别主方向、主路径和主干网络，建立整体骨架

目标：先让整张图有“阅读方向”，再决定局部摆放，否则只会得到摊开的乱图。

实施点：

- 默认把主阅读方向设为从左到右
- 对每个连通分量分析连接密度、方向性器件分布、输入输出角色，识别候选主路径
- 对命名明确的网络优先识别特殊语义，如 `gnd`、`0`、`vcc`、`vdd`、`vin`、`vout` 等
- 让供电网络优先占据上方或下方辅助通道，不与主信号流混在同一主干线上
- 对连接数高、跨层级强、承担汇流作用的网络提升优先级，作为主干候选
- 对每个连通分量生成粗粒度骨架：主路径组件顺序、辅助支路挂接位置、供电/地回路的相对位置

开发提示：

- 这一步解决的是“图为什么看起来像电路图”，不是“每个坐标精确是多少”
- 如果骨架阶段就失败，后面再精细路由也只是把混乱画得更精致

输出：

- 每个连通分量的主方向
- 主路径组件序列
- 主干网络与支路网络的初步划分

### 第 5 步：做组件粗放置，把图先摆成正确的大形态

目标：在不进入细节路由之前，先把组件放到大致正确的位置关系上。

实施点：

- 沿主路径依次摆放核心组件，保持均匀水平节距
- 把电源相关组件优先放在上方通道，把地相关组件优先放在下方通道
- 两端器件优先内联到其主要连接路径上，而不是随意散落
- 运放、子电路 block、受控源等 block 型器件优先位于信号主链中心区域
- 偏置网络、采样网络、去耦支路优先短距离挂接在对应主路径节点附近
- 对同一 `scope_path` 内组件保持视觉连续，避免作用域内器件被跨组打散
- 生成初版组件边界框并检测明显重叠，必要时进行局部排斥和间距扩张

开发提示：

- 粗放置阶段不要求最终美观，但必须先保证全图层次关系正确
- 这一步尽量避免开始就算细路由，否则很容易不断推翻坐标

输出：

- 初版组件坐标
- 初版组边界与整体分区关系

### 第 6 步：引入器件朝向决策，解决“元件不能旋转”这一根本缺陷

目标：把方向敏感器件从“固定朝向符号”升级为“可根据连接语义自动选朝向”的符号系统。

实施点：

- 在 `symbolRegistry.tsx` 中为支持的元件引入明确朝向模型
- 为电阻、电容、电感、二极管等两端器件支持横向/纵向两种主朝向
- 为运放、受控源、subckt block 支持朝左/朝右的输入输出导向
- 为 BJT、MOS 支持至少一套符合常见阅读习惯的朝向切换，确保基极/栅极和主要驱动侧对齐
- 朝向决策应结合主路径方向、相邻关键网络位置、引脚角色共同决定，而不是只靠元件类型静态写死
- 一旦组件朝向确定，引脚锚点必须同步由同一权威模型重新计算

开发提示：

- 这一阶段是本次布局升级观感提升最大的环节之一
- 如果旋转只做了视觉图标旋转，而没有同步更新引脚锚点和连线出口，问题会更严重

输出：

- 支持朝向决策的符号系统
- 组件最终朝向
- 与朝向一致的引脚锚点

### 第 7 步：实现新的正交路由器，让主干导线更直、支路更短、锚点更准

目标：替换 ELK 的通用正交边输出，改为更贴合电路图阅读习惯的自有导线生成逻辑。

实施点：

- 按已确定的组件坐标和引脚绝对位置生成导线
- 优先为主干网络生成直线或单次转折的骨干段
- 对多连接网络优先构造“主干线 + 接入支路”而不是多条平权折线
- 为上下供电网络保留独立通道，减少和主信号线交错
- 让支路从离目标最近的主干段接入，尽量减少多余折返
- 增加基础避障规则，避免导线横穿组件主体
- 对高风险重叠区域进行轨道偏移或通道分层，减少平行线完全重叠
- 路由结果必须严格吸附到引脚锚点，消除“图标和导线没连上”的视觉错误

开发提示：

- 不需要在第一版就做成通用 VLSI 路由器，但必须明显优于当前 ELK 通用折线结果
- “更少拐点”比“数学最短路径”更重要

输出：

- 新的权威网络线段结果
- 更规整的主干与支路结构

### 第 8 步：重做标签布局，让网络名和元件标签与新版导线/朝向协同工作

目标：让标签系统跟新布局一起工作，而不是继续基于旧几何补丁式漂浮。

实施点：

- 网络标签只从最终导线段中选位，不再基于旧路由残余结构选位
- 优先把标签放在主干段附近、靠近关键节点、且不遮挡组件的位置
- 组件实例名和值标签根据组件朝向自动选择上侧、下侧、左侧或右侧槽位
- 对 block 型器件和竖向器件分别设置不同的标签优先槽位策略
- 标签避让必须统一考虑组件体、导线段、已有标签框
- 保留当前“节点名称要靠近节点”的视觉目标，但改为在新路由语义下实现，而不是只调单个偏移常量

开发提示：

- 标签看似是细节，但它直接影响“用户能否一眼看懂图”
- 标签策略必须建立在最终导线几何之上，不能先算标签再强行拼路由

输出：

- 新的网络标签落点
- 与组件朝向一致的实例名和值标签位置

### 第 9 步：对齐 `SchematicCanvasSurface.tsx`，把所有几何消费统一收口到新布局结果

目标：确保渲染层完全服从新布局结果，不再在本地补几何、猜方向、补标签逻辑。

实施点：

- 更新画布对组件旋转或朝向字段的消费方式
- 更新画布对引脚绝对位置和导线段的消费方式
- 确保当前 SVG 符号绘制与新朝向模型一致
- 删除渲染层中任何仍在自行推导 pin label、引脚侧、局部连线几何的逻辑
- 检查组件选中框、hover 区域、点击命中区域是否仍与最终几何一致
- 同步修正布局等待态和错误文案，使其不再出现 ELK 相关描述

开发提示：

- 这一步的关键不是“让它先跑起来”，而是彻底消灭双重几何来源
- 一旦渲染层继续自行推坐标，后面维护会再次失控

输出：

- 完全对齐新布局结果的画布渲染层
- 删除旧布局残余消费逻辑

### 第 10 步：删除旧设计与依赖，确保代码库中只剩新权威路径

目标：把被替换掉的旧设计从代码库中真正移除，而不是挂着备用。

实施点：

- 删除 `schematicLayout.ts` 中所有 ELK import 与 ELK graph builder 逻辑
- 删除 `package.json` 和 `package-lock.json` 中的 `elkjs`
- 删除已不再使用的旧 helper、旧常量、旧 edge blueprint、旧 port graph 构造逻辑
- 评估并移除 `SchematicCanvas.tsx` 中已经无价值的旧布局/旧渲染实现
- 全局搜索并清理 ELK 相关文案、类型和死代码引用
- 确保对外只存在一条 `computeSchematicLayout` 权威路径

开发提示：

- 这一步不能心软保留 fallback，否则后续问题会不断绕回旧设计
- 真正完成重构的标志之一，就是旧的核心设计已经不再存在

输出：

- 无 ELK 依赖代码库
- 无旧布局 fallback
- 单一权威布局实现

### 第 11 步：做针对性验证与构建，确认效果改进和无回归

目标：在提交前确认这次重构不仅“能运行”，还确实提升了图面质量并保持已有能力稳定。

实施点：

- 用包含电阻、电容、电感、二极管、源、运放、BJT、MOS、子电路 block 的样例检查布局效果
- 重点检查：
  - 组件是否沿主信号方向合理摆放
  - 三极管和 MOS 的引脚是否视觉上连得上
  - 主干导线是否明显更直
  - 不必要转折是否减少
  - 节点标签是否贴近连接点
  - 组件标签是否压线
- 检查选择、缩放、平移、Fit 是否仍正确
- 在 `frontend/simulation-panel` 下重新执行构建
- 修复构建错误、类型错误和明显渲染回归
- 完成后准备英文 git commit 名称

开发提示：

- 本次验收标准是“相对当前实现有明显专业度提升”，不是“首版自动布局已经等同人工 schematic”
- 如果验证阶段发现某类器件朝向系统性错误，应优先修正规则而不是局部补坐标

输出：

- 通过构建的前端产物
- 一套更稳定的新布局效果
- 可用于提交的英文 commit name

---

## 第二阶段：约束求解驱动的布局引擎

第一阶段（第 1-11 步）产出了一条**单一权威**的布局流水线，但 `schematicCoarsePlacement.ts` 内部仍然是**枚举模板 + 手工车道**的思路，在复合电路、差分对、镜像结构、多域电源、级联放大等场景下均会失败（表现为组件摆位错乱、引脚视觉上不连接、电源/地线条带无概念）。第二阶段的目标是把 `schematicCoarsePlacement` **整体替换**为约束求解驱动的实现，并在单一电路惯例规则下让任意拓扑都能得到"专业度合格"的自动布局。

核心设计原则："**无模板，只有可组合的约束**" —— 每条电路语义事实（电源网、地网、I/O 端口、scope 子电路、信号流方向）都翻译成约束喂给求解器，由求解器统一权衡。

### 第 12 步：引入 WebCoLa 约束求解库

目标：为第二阶段提供底层约束布局内核，确保类型、打包、运行时都能稳定工作。

实施点：

- 在 `frontend/simulation-panel` 安装 `webcola` 作为 runtime dependency
- 同步更新 `package.json` 与 `package-lock.json`，版本锁定
- 验证 `Layout`、`Node`、`Link`、`Group`、`Constraint` 相关类型 / 构造器在本工程的 vite + TS 环境下可 import 与可用
- 若 `@types` 不完整，就近补本地类型声明
- 进行一次空构建，确认 webcola 打包没有额外问题（如 Node API 依赖、动态 eval 等）

开发提示：

- webcola 的主 API 可以在不引入 D3 的情况下独立使用，通过 `import * as cola from 'webcola'` 或 `import { Layout } from 'webcola'` 获得
- 非 D3 用法下使用 `.start(iter1, iter2, iter3, 0, false)` 最后一个参数设为 `false` 以同步完成迭代
- 不要引入 `webcola` 的 D3 adaptor 部分，避免连带拉入 d3 依赖

输出：

- 安装并锁定的 webcola 依赖
- 通过类型检查与构建的最小集成

### 第 13 步：以 `schematicConstraintPlacement.ts` 完全取代 `schematicCoarsePlacement.ts`

目标：用约束求解替换手工车道方案，成为**唯一的**放置权威；旧模块从代码库中根除。

对外契约：新模块保留原来的 `SchematicCoarsePlacement` 输出 shape（`componentPositions` / `componentsById` / `scopeGroupBounds` / `scopeGroupBoundsById` / `clusterBounds` / `overallBounds`），这样 `schematicLayout.ts` 下游（路由器、标签规划器、画布）完全零改动。

实施点：

- 新建 `schematicConstraintPlacement.ts`，提供 `computeSchematicCoarsePlacement(semantic, skeleton, orientations): SchematicCoarsePlacement` 权威入口
- 模块内部职责分段（同文件或拆为辅助模块皆可）：
  - **节点构造**：为每个 `SemanticComponent` 构造 WebCoLa 节点，宽高取 `orientation` 旋转后的符号尺寸 + 内边距
  - **链路构造**：为每个 `SemanticNet` 构造 WebCoLa 链路；链路长度按 `SemanticNetCategory`（power/ground/bias/signal）差异化取值；dangling 网跳过
  - **约束构造**：
    - 电源网所连组件 → `alignment(y)` 硬约束（顶部轨道）
    - 地网所连组件 → `alignment(y)` 硬约束（底部轨道）
    - 顶部轨道 `y` < 底部轨道 `y` 的 separation 硬约束
    - I/O 端口（通过 `SemanticPinRole` 识别）→ 左/右边缘的 separation 约束
  - **分组构造**：`SemanticScopeGroup` 按深度优先映射为 WebCoLa `groups`，含嵌套包含关系
  - **求解**：使用 `avoidOverlaps(true)` + `handleDisconnected(true)` + 三段迭代 `.start(iter1, iter2, iter3)` 同步完成
  - **结果封送**：WebCoLa 节点中心坐标 → `box`（左上坐标） + `symbolBox`（符号在内边距中央）；重算 `scopeGroupBounds`、`clusterBounds`、`overallBounds`（不依赖 WebCoLa group 包围盒的精确度）
  - **兜底收敛**：求解结果后做一次局部重叠消解 pass，保证任意情况下无矩形叠加
- 删除 `schematicCoarsePlacement.ts` 整个文件
- `schematicLayout.ts` 改为从新模块 import `computeSchematicCoarsePlacement` 与 `SchematicCoarsePlacement` 类型，别处引用一律更新
- 全局 `grep` 核查 `schematicCoarsePlacement` 无残留

开发提示：

- **禁止**保留旧 coarse placement 作为 fallback。求解器若不收敛要通过调约束/迭代数解决，不要用旧算法兜底
- 电源/地轨道可能对"同时接 power 与 ground"的组件（如电源器件本身）造成冲突 —— 此类组件不加入任一 alignment，由求解器自由定位；电源组件本身通常是 supply 角色，依靠连接到其上的其他组件的轨道约束自然落位
- 孤立子图（`handleDisconnected`）会被 WebCoLa 打包到非重叠区域，无需额外处理
- 求解器产出的坐标单位与旧方案一致（像素），下游路由器的 stub 长度 / grid 常量不需要跟着变
- 若对称镜像/差分对的识别成本过高，v1 可以不做；`avoidOverlaps + flowLayout` 已经能把绝大多数日常电路收束到合理布局

输出：

- 权威的 `schematicConstraintPlacement.ts`，以 WebCoLa 为内核
- `schematicCoarsePlacement.ts` 彻底删除
- `computeSchematicLayout` 流水线唯一放置路径

### 第 14 步：验证、回归与构建

目标：在真实电路样例上确认第二阶段产出确实比第一阶段有质的提升，且下游路由器/标签/画布无回归。

实施点：

- 在 RLC 低通、BJT 共射放大器、CMOS 反相器、运放反相放大（含反馈）、差分对五种拓扑上目视检查布局
- 重点验证：
  - 电源组件是否自然落到顶部轨道，地组件落到底部轨道
  - 主信号器件是否沿水平方向展开
  - Scope 子电路是否有可辨识的包围盒（嵌套时不相互切断）
  - 引脚视觉上与导线是否对齐（router 本身未变，故主要看 placement 产出的坐标是否合理）
  - 组件包围盒之间无物理重叠
  - `Fit` / 平移 / 缩放 / 选中依然正常
- 在 `frontend/simulation-panel` 下执行 `npm run build`，确认 0 错误 0 警告退出
- 如果某类拓扑出现明显放置异常，**优先调整约束规则与权重**，**不要**通过 hack 单点坐标解决
- 完成后给出英文 git commit 名称

开发提示：

- WebCoLa 的收敛结果受迭代数与初始位置影响。若某些拓扑效果不稳定，优先排查顺序：约束集完整性 → 链路长度差异化 → 迭代数 → 初始位置种子
- 本阶段的验收标准是"相对第一阶段有明显提升 + 结构化可读"，而非"已达人工布局水平"；进一步对齐/对称/多域轨道属于后续演进

输出：

- 通过构建的前端产物
- 一套对任意拓扑都更稳定的新布局效果
- 可用于提交的英文 commit name

---

## 第三阶段：正交可视性图驱动的权威路由

第二阶段只保证了**器件包围盒**的合理摆放，但 `schematicOrthogonalRouter.ts` 仍然是**模式匹配式**的 2-pin L 型连线 + 单一 trunk 躲障碍，本质上不是寻路算法。一旦出现"两组件之间隔着第三个器件""多个障碍堆叠""高密度电源网"这类情况，导线必然**斜穿器件本体**（差分对、运放反馈、级联滤波等结构是该问题的重灾区）。第三阶段把路由器也**整体替换**为学术界公认的 SOTA —— Wybrow, Marriott, Stuckey 2009 的 "Orthogonal Connector Routing"（即 libavoid / yEd / Inkscape 背后的算法），以**正交可视性图 + 端口约束 A\* + Nudging** 三件套为核心，成为唯一的导线路由权威。

核心设计原则："**任何导线都必须是可视性图上的正交最短路**"——斜穿器件、叠加平行线、引脚反向出线等症状在算法层面就不可能发生。

### 第 15 步：以 `schematicOrthogonalConnectorRouter.ts` 完全取代 `schematicOrthogonalRouter.ts`

目标：把路由器从**模板匹配**升级为**正交可视性图 + A\* + Nudging** 的权威寻路引擎；旧模块从代码库中根除，不保留任何 fallback。

对外契约：新模块保留现有路由器的返回 shape —— `Map<netId, SchematicLayoutNetSegment[]>`，下游 `schematicLabelPlanner` 与 `SchematicCanvasSurface` 零改动。

算法基础：Wybrow, Marriott, Stuckey, *"Orthogonal Connector Routing"*, Computer Graphics Forum 28(3), 2009。即 `libavoid` 的理论根基。该算法已被业界反复验证为 diagram routing 的 SOTA，在性能（O(n² log n) per edge，500 组件电路 <200ms）、视觉质量（不斜穿 + 自动 nudging）、泛用性（支持端口约束、分组、Steiner 树）三项同时优于均匀网格 A\*、libavoid-wasm、WebCoLa GridRouter。

实施点：

- 新建 `schematicOrthogonalConnectorRouter.ts`，提供 `routeSchematicNets(semantic, skeleton, pinsByNetId, components, scopeGroupBounds): Map<string, SchematicLayoutNetSegment[]>` 权威入口
- 模块内部按算法五层结构组织（同文件或拆分均可）：

**Layer 1 — 障碍模型（`buildObstacleWorld`）**

  - 每个 `SchematicLayoutComponent.symbolBounds` + `OBSTACLE_CLEARANCE` → 一个 `ObstacleRect`
  - `scope_group` 包围盒 → "软障碍"：内部 wire 自由通过，跨境 wire 必须经由**指定 gate 点**进入/离开
  - 障碍按 `ownerComponentId` 打标，pin 所属组件的障碍对该 pin 免疫（否则 pin 本身在障碍内无法出线）

**Layer 2 — 正交可视性图（`buildOrthogonalVisibilityGraph`）**

  - 对每个 `ObstacleRect` 的 4 个角，向上下左右 4 个方向投射"可视扫描线"，遇到另一个障碍就停
  - 所有扫描线之间的水平/垂直交点 → OVG 顶点
  - 相邻可视顶点（中间没有障碍且连线为水平或垂直）→ OVG 边
  - 数据结构：
    - `vertices: OVGVertex[]`（`{ x, y, neighbors: OVGEdge[] }`）
    - `edges: OVGEdge[]`（`{ from, to, axis, length, crossingsBaseline }`）
  - **一次构建，全部 wire 共用**；不按 wire 重建图

**Layer 3 — 端口插入（`attachPinPorts`）**

  - 每个 pin 按 `pin.side` 向对应方向延伸 `STUB_LENGTH`，得到 pin 的"corridor 入口点"
  - 入口点作为虚拟 OVG 顶点插入图中，只连向**同方向**的邻居（实现端口方向约束）
  - 保证 wire 必定从器件正确一侧出来，视觉上"连得上"
  - 对 pin 所在组件的障碍临时移除遮蔽（corridor 穿过自身符号矩形的 clearance 区）

**Layer 4 — 单对 A\* 与 Steiner 搜索（`findOrthogonalPath` / `findOrthogonalSteinerTree`）**

  - 2-pin 网：
    - A\* on OVG，启发式 = Manhattan 距离
    - 边权 = `length + BEND_PENALTY · isBendWith(prevEdge) + CROSSING_PENALTY · alreadyUsedCells`
    - 优先队列 = binary heap（`O((V+E) log V)`）
  - 多 pin 网（`pinCount >= 3`）：
    - 在 OVG 上做 Steiner 树近似（Kou-Markowsky：完全图最短路 + MST 再回代）
    - 输出一棵以 OVG 边构成的树，自然产生分叉点（T/十字接合）
  - dangling 网（1 pin）：直接输出 `STUB_LENGTH` 方向性短线，不入 A\*

**Layer 5 — Nudging（`nudgeParallelSegments`）**

  - 扫描所有已布 wire，按轴归类
    - 水平段按 y 桶归类
    - 垂直段按 x 桶归类
  - 同桶内重叠的平行段视为"冲突组"
  - 对每个冲突组在允许 y 区间（两侧障碍之间的空隙）内用一维 VPSC 求解分散：
    - 约束：`y_{i+1} - y_i ≥ WIRE_MIN_GAP`
    - 约束：`y_i ∈ [corridor_low, corridor_high]`
  - 解算后回写 wire 路径
  - **关键视觉质量提升**：平行总线不再堆叠、叠码，差分对自动分成两条平行轨道

**Layer 6 — 路径输出与 shape 转换（`marshalSegments`）**

  - OVG 路径 → `SchematicLayoutNetSegment[]`
  - 合并共线相邻段为单个 segment，减少渲染成本
  - 为多 pin 网的分叉点生成 `junction` kind 段（用于下游标记 T 点 / 连接点的视觉 dot）
  - grid snap 到 4px，与 Phase 2 的 placement 网格对齐

其他实施要点：

- 删除 `schematicOrthogonalRouter.ts` 整个文件
- `schematicLayout.ts` 改为从新模块 import `routeSchematicNets`，传参新增 `scopeGroupBounds`
- 全局 `grep` 核查 `schematicOrthogonalRouter` 无残留
- 新增常量集中到模块头部：`OBSTACLE_CLEARANCE` / `STUB_LENGTH` / `BEND_PENALTY` / `CROSSING_PENALTY` / `WIRE_MIN_GAP` / `GRID_SNAP`

开发提示：

- **禁止**保留旧模板路由器作为 fallback。A\* 找不到路（理论上对连通 OVG 不会发生）则抛错，表明障碍/端口约束矛盾，需要调算法，不准回退到直线连
- OVG 构建用"从每个障碍角向四方向扫描到第一个障碍"的经典 O(n²) 做法即可；schematic 场景 n 典型 10-300，无需线段树
- 为保证 A\* 的 Manhattan 启发式 admissible，边权中只有 `length` 进入 g-cost 的"距离"部分，`BEND_PENALTY` 和 `CROSSING_PENALTY` 作为附加整数 cost 不影响 admissibility
- Steiner 树的 Kou-Markowsky 近似比率 2-approx，对 schematic 视觉够用；想更优可换 Zelikovsky 1.55-approx，但 CPU 预算差不大时不必
- Nudging 的 VPSC 可以用 `webcola` 内的 `vpsc.js`（已经打包进 bundle，不增成本）
- 对 scope 分组：每个分组沿包围盒打 1-2 个 gate 顶点，跨分组 wire 必须经由 gate；内部 wire 不受影响
- 与 label placement 解耦：路由器只负责导线几何，标签碰撞检测在第 16 步独立做

性能预算（500 组件典型电路）：

- OVG 构建：一次，~40ms
- 单 wire A\*：~0.1-0.5ms
- Nudging 全量：~20ms
- 总体：**<200ms**，满足交互式重布局

输出：

- 权威的 `schematicOrthogonalConnectorRouter.ts`，以 OVG + A\* + Nudging 为内核
- `schematicOrthogonalRouter.ts` 彻底删除
- `computeSchematicLayout` 流水线唯一路由路径
- 任意电路上**不再**出现导线穿过器件本体的情况

### 第 16 步：验证、回归与构建

目标：在真实电路样例上确认第三阶段产出确实消除了导线穿体问题，且**不引入新的视觉缺陷**（标签错位可暂不在本步修复，留第四阶段）。

实施点：

- 在以下 6 类拓扑上目视检查导线：
  - RLC 低通、RC 级联带负载
  - BJT 共射放大器、CMOS 反相器
  - 运放反相放大（含反馈环）
  - **BJT 差分对**（第一阶段最差 case）
- 重点验证：
  - **任意一条导线都不穿过任何器件的 `symbolBounds`**
  - 引脚出线方向与 `pin.side` 一致（电阻左脚必向左出、上脚必向上出，以此类推）
  - 多 pin 网在视觉上形成清晰的 T/十字分叉
  - 平行 wire（电源总线、地总线、反馈线）彼此错开，不堆叠
  - scope 分组内部 wire 不穿越分组边界去抄近路
  - `Fit` / 平移 / 缩放 / 选中依然正常
- 执行 `npm run build`，0 错误 0 警告退出
- 如果某类拓扑仍出现穿越，优先排查顺序：OVG 构建完整性 → 端口 corridor 是否被阻塞 → Nudging 区间是否崩塌到 0；**不允许**用"补一条后置清理规则"的方式掩盖算法问题
- 完成后给出英文 git commit 名称

开发提示：

- Nudging 的常见退化：两条 wire 的可用区间完全相同且极窄 → VPSC 解不出差异 → 仍然重叠。对策：扩大 corridor 搜索范围、或允许其中一条换轨
- A\* 的常见退化：OVG 局部不连通 → A\* 返回失败。对策：确保每个障碍之间至少有一条"过道"（clearance 不能设得比 `WIRE_MIN_GAP` 还小）
- 验证时如发现"导线在器件 stub 范围内贴着器件边走"，这是符合预期的（stub 长度 = 28px 默认），不属于穿越

输出：

- 通过构建的前端产物
- 一套导线不穿体、平行线分散、分叉清晰的新路由效果
- 可用于提交的英文 commit name
