7 665554# SPICE 电路设计语法参考

本文档面向编写 SPICE 网表的 AI。目标仿真器是 **ngspice**（非 HSPICE / PSpice），下列所有规则已对齐 ngspice 的实际行为。按本文档生成的网表可直接交给 ngspice 执行。

---

## 一、文件骨架

```spice
.title <电路名称>

* 注释以 * 开头（整行）；行内注释以 $ 开头
* 元件行（R/C/L/D/Q/M/J/V/I/E/G/F/H/X）
* ...

* 恰好一条分析命令
.<analysis> ...

* 可选：.MEASURE
.MEASURE ...

.end
```

规则：

- 文件首行 `.title`，末行 `.end`
- **恰好一条** 分析命令（`.dc` / `.op` / `.tran` / `.ac` / `.noise`），禁止混用
- 所有电路节点名区分来源但不区分大小写；`0` 是全局地
- 所有元件名首字母决定类型（见第四节）

---

## 二、数值与单位后缀

数值后紧跟后缀（不带空格），大小写不敏感：

| 后缀 | 量级 | 示例 |
|---|---|---|
| `T`   | 10¹²  | `1T`   |
| `G`   | 10⁹   | `1G`   |
| `Meg` | 10⁶   | `1Meg` |
| `K`   | 10³   | `4.7K` |
| `M`   | 10⁻³  | `1M` = 1e-3 |
| `U`   | 10⁻⁶  | `10U` |
| `N`   | 10⁻⁹  | `5N`  |
| `P`   | 10⁻¹² | `1P`  |
| `F`   | 10⁻¹⁵ | `1F`  |

**陷阱**：`M` 是毫（10⁻³），**不是**兆；兆必须写 `Meg`。

---

## 三、分析命令

| 命令 | 语法 | 用途 |
|---|---|---|
| `.op`    | `.op` | DC 工作点 |
| `.dc`    | `.dc <src> <start> <stop> <step>` | 参数扫描 |
| `.tran`  | `.tran <tstep> <tstop> [UIC]`    | 瞬态 |
| `.ac`    | `.ac {dec\|oct\|lin} <N> <fstart> <fstop>` | 频响 |
| `.noise` | `.noise V(<out>) <src> {dec\|oct\|lin} <N> <fstart> <fstop>` | 噪声谱 |

---

## 四、元件行语法

节点数按元件类型固定，**模型名放在所有端口之后**。

### 无源

```spice
R<name> n+ n- <value>                         * 电阻
C<name> n+ n- <value> [IC=<v0>]               * 电容（可选初值）
L<name> n+ n- <value> [IC=<i0>]               * 电感（可选初值）
```

### 独立源

```spice
V<name> n+ n- DC <v> [AC <mag> [phase]]
V<name> n+ n- SIN(<vo> <va> <freq> [<td> <theta>])
V<name> n+ n- PULSE(<v1> <v2> <td> <tr> <tf> <pw> <per>)
V<name> n+ n- PWL(<t1> <v1> <t2> <v2> ...)
I<name> n+ n- DC <i>                           * 同结构，仅替换 V→I
```

### 受控源

```spice
E<name> n+ n- nc+ nc- <gain>                   * VCVS：输出电压 = gain × V(nc+,nc-)
G<name> n+ n- nc+ nc- <gm>                     * VCCS：输出电流 = gm × V(nc+,nc-)
F<name> n+ n- <Vsense> <gain>                  * CCCS：引用已定义电压源名 Vsense
H<name> n+ n- <Vsense> <transres>              * CCVS：同上
```

### 半导体

```spice
D<name> anode cathode <model>                  * 二极管
Q<name> collector base emitter <model>         * BJT（3 端）
M<name> drain gate source body <model>         * MOSFET（4 端；body 通常接源或衬底）
J<name> drain gate source <model>              * JFET（3 端）
```

### 子电路

```spice
.subckt <NAME> <port1> <port2> ...
  ...
.ends <NAME>

X<name> <port1> <port2> ... <NAME>             * 实例化
```

---

## 五、可用器件模型

**直接用名字引用即可**，运行器会自动注入 `.model` 卡，**不要**在网表中重复写 `.model`。

| 类型 | 可用模型 |
|---|---|
| BJT (NPN / PNP)      | `2N3904` / `2N3906` |
| MOSFET (NMOS / PMOS) | `BSS123` / `BSS84`  |
| JFET (NJF / PJF)     | `2N3819` / `2N5460` |
| Diode                | `1N4148`            |

示例：

```spice
Q1 c b e 2N3904
M1 d g s s BSS123
D1 a k 1N4148
```

---

## 六、初始条件与 UIC

`IC=` 只在 `.tran` 附带 `UIC` 时生效：

```spice
C1 cap 0 1u IC=5
.tran 10u 50m UIC
```

- 无 `UIC` → `IC=` 被忽略
- 有 `UIC` 但无 `IC=` → 所有节点初值为 0

---

## 七、输出变量与函数

在 `.MEASURE`、`.print`、`.plot`、`.noise` 中可用：

| 写法 | 含义 |
|---|---|
| `V(node)`         | 节点对地电压 |
| `V(n1, n2)`       | 两节点间电压差 |
| `I(Vname)`        | 流过名为 Vname 的电压源的电流 |
| `vdb(node)`       | `20·log10(|V(node)|)`（AC 用） |
| `vp(node)`        | 相位（度，AC 用） |
| `onoise` / `inoise` | 输出 / 输入参考噪声功率谱（`.noise` 用） |

---

## 八、`.MEASURE` 规则（按分析分类）

**核心**：`WHEN var = VAL` 的 `VAL` 必须是**数值字面量**（如 `4.5`）。不允许表达式（如 `(a-3)`）或 HSPICE 方言关键字（如 `MAXAC`）。

| 分析 | 允许 | 禁止 |
|---|---|---|
| `.dc`    | `FIND <var> AT=<v>` / `WHEN <var>=<数值> RISE=1/FALL=1` | 表达式 target |
| `.op`    | — | 任何 `.MEASURE` |
| `.tran`  | `MAX` / `MIN` / `PP` / `AVG` / `INTEG` / `FIND <var> AT=<t>` / `WHEN <var>=<数值>` / `TRIG … TARG …` | 表达式 target |
| `.ac`    | **仅** `FIND vdb(<node>) AT=<f>` | `MAX` / `MIN` / HSPICE 方言关键字 |
| `.noise` | **无**（直接用 `onoise` / `inoise` 输出频谱） | 任何 `.MEASURE NOISE`（ngspice 未实现） |

---

## 九、拓扑约束

- 每个节点必须有到地（`0`）的 **DC 路径**；悬空节点会触发奇异矩阵错误
- 浮地参考需用大电阻（如 `Rgnd node 0 1`）拉到地
- 避免纯电感回路、纯电压源回路

---

## 十、常见错误速查

| 错误写法 | 错误原因 |
|---|---|
| `.MEASURE AC f_peak WHEN vdb(out)=MAXAC`                    | `MAXAC` 非 ngspice 关键字 |
| `.MEASURE AC f_3db WHEN vdb(out)=(av_midband-3)`            | 括号表达式 target 不稳定 |
| `.MEASURE AC v_peak MAX vdb(out)`                           | ngspice 对 AC `MAX`/`MIN` 支持不稳定，会在 simulation 阶段崩溃 |
| `.MEASURE NOISE total INTEG onoise FROM=1 TO=10Meg`         | ngspice `.MEAS` 不支持 `NOISE` 分析类型 |
| `.tran 10u 5m UIC` 无任何 `IC=`                              | `UIC` 无效，等价于无 `UIC` |
| 自写 `.model 2N3904 NPN (…)`                                 | 与 bundled 库冲突 |
| 用 `M` 表示兆（`1M`）                                         | `M` 是毫（10⁻³），兆要写 `Meg` |

---

## 十一、完整示例

### `.op` — BJT 共射偏置

```spice
.title NPN Common-Emitter Bias

Vdd vdd 0 DC 12

Rb1 vdd base 68k
Rb2 base 0   12k
Rc  vdd col  4.7k
Re  emit 0   1k

Q1  col base emit 2N3904

.op
.end
```

### `.dc` — 二极管 I–V

```spice
.title Diode I-V Sweep

Vs a 0 DC 0
Rs a anode 100
D1 anode 0 1N4148

.dc Vs 0 1 0.01
.end
```

### `.tran` — RC 充电

```spice
.title RC Charging

Vin in 0 PULSE(0 5 0 1u 1u 20m 40m)
R1  in  cap 10k
C1  cap 0   1u

.tran 100u 50m
.MEASURE TRAN v_final FIND V(cap) AT=45m
.MEASURE TRAN t_90    WHEN V(cap)=4.5 RISE=1
.end
```

### `.ac` — RLC 带通

```spice
.title Series RLC Band-Pass

Vin in 0 AC 1
R1  in  out 10
L1  out n2  1m
C1  n2  0   1u

.ac dec 40 100 1Meg
.MEASURE AC v_at_resonance FIND vdb(out) AT=5k
.end
```

### `.noise` — 电阻热噪声

```spice
.title Resistor Thermal Noise

Vin in 0 AC 1
R1  in  out 10k
R2  out 0   10k

.noise V(out) Vin dec 20 1 10Meg
.end
```

