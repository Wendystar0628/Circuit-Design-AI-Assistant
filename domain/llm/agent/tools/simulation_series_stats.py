# Simulation Series Stats - 信号 CSV 单扫流式统计 + 锚点采样
"""跨 read 工具共用的"时间序列数值特征"单一权威实现。

``read_signals``（raw_data / chart 源通吃）要对一列列的数值时间
序列给 LLM 同一套紧凑摘要：每条信号的
``samples / min / max / mean / initial / final / zero_crossings /
peak_to_peak``，再加一张等距锚点小表 ``(x, y1, y2, ...)``。把这套
统计抽到这里是**禁止两份实现**的刚性要求——任何 read 工具
的 `.py` 绝不允许再自己算一次 min/max 或自行拉锚点索引。

流式契约：

    result = read_series_csv(
        csv_path=path,
        anchor_count=14,
        anchor_scale=AnchorScale.LINEAR,
    )

- 对 CSV 做**两遍扫描**，每次只在内存里持有 O(S) 的信号级标量累加器
  + O(K) 的锚点缓冲（S=信号数、K=锚点数）；绝不把完整 CSV 一次性
  读入——测 10 万+ 采样点也不会爆。
- 文件顶部的"自证 header"（``# artifact_type: ...`` 等 6 行 + 一行
  空行）被解析成 ``(key, value)`` 列表透传回来，调用方需要的话可以
  在自己的 markdown 里原样 echo 出来。
- 只做**描述性**统计——peak-to-peak = max - min；zero_crossings
  严格按"前后两非空采样符号相反且都非零"计数；不做任何派生量
  计算（``bandwidth`` / ``gain_margin`` / ``phase_margin`` 之类的
  .ac 派生量有自己的权威来源——``metrics.json``，本模块**绝不**代劳）。

锚点采样语义：

- ``LINEAR``: 在 ``[0, N-1]`` 行索引等距取 ``K`` 个点（``.tran`` /
  ``.dc`` 默认）。
- ``LOG``: 在 ``[x_min, x_max]`` 对 x 值取对数等距 K 个目标，再在
  第二遍扫描中挑**最接近**每个目标的数据行（``.ac`` 分支默认）。
  若 x_min <= 0（数据里含零或负值），自动降级为 LINEAR—— 不抛异常，
  因为那是上游 exporter 的数据形态问题，read 工具能退也能工作；
  降级事实会被写到 ``anchor_scale_effective``，调用方可在文案里
  如实呈现给 LLM。

模块边界：

- **只**读 CSV + 计算统计；**不**读 PNG、**不**读 JSON、**不**碰
  metrics.json——这些职责由调用 tool 自己掌握。
- 任何 ``OSError`` / 解析失败一律抛成 ``ValueError`` / ``OSError``，
  让调用 tool 把它包装成 is_error，不在这里猜 content 文案。
"""

from __future__ import annotations

import csv
import enum
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================
# 公共数据类 / 枚举
# ============================================================


class AnchorScale(enum.Enum):
    """锚点采样的 x 轴分布方式。"""

    LINEAR = "linear"
    """行索引上等距——``.tran`` / ``.dc`` 默认。"""

    LOG = "log"
    """x 值对数等距——``.ac`` 默认；若 x_min <= 0 自动退到 LINEAR。"""


@dataclass(frozen=True)
class SeriesStats:
    """单条信号的一行摘要统计。

    所有字段都是确定性、可被 LLM 直接读的标量；**不**回传原始向量。
    """

    name: str
    """信号列名（CSV header 中的字符串，例如 ``V(out)``）。"""

    samples: int
    """该列的非空采样点数。CSV 里某列尾部比 primary 短时那些空单元
    不计入——和任一 exporter 的 ``primary_x`` 对齐策略一致。"""

    min_value: float
    max_value: float
    mean_value: float

    initial_value: float
    """第一条非空采样点的 y 值。"""

    final_value: float
    """最后一条非空采样点的 y 值。"""

    zero_crossings: int
    """严格正负号翻转次数；两端都为 0 的过渡**不**计数。"""

    peak_to_peak: float
    """``max - min``。仅作展示，不参与派生量计算。"""


@dataclass(frozen=True)
class AnchorRow:
    """一次等距采样点。

    Attributes:
        x: 采样点的 x 值（时间 / 频率 / 扫描值）。
        values: 与 ``column_names`` 对齐的信号值列表；空单元为
            ``None``，LLM 文案里会渲染成 ``—`` 而不是 0。
    """

    x: float
    values: Tuple[Optional[float], ...]


@dataclass(frozen=True)
class SeriesReadResult:
    """``read_series_csv`` 的聚合返回值。"""

    header_entries: Tuple[Tuple[str, str], ...]
    """CSV 顶部 ``# key: value`` 自证 header 条目（顺序保留）。"""

    x_column_name: str
    """x 轴列名（csv header 的第 0 列；例如 ``time`` / ``frequency``）。"""

    signal_column_names: Tuple[str, ...]
    """信号列名顺序；与 ``stats`` 和 ``anchors.values`` 一致对齐。"""

    total_rows: int
    """数据行数（不含 header 与 csv 列行）。"""

    x_range: Tuple[float, float]
    """数据里 x 值的 ``(min, max)``；无有效数据时为 ``(nan, nan)``。"""

    stats: Tuple[SeriesStats, ...]
    """与 ``signal_column_names`` 同顺序的每列统计摘要。"""

    anchors: Tuple[AnchorRow, ...]
    """等距锚点样本（已按 x 升序排列）。"""

    anchor_scale_requested: AnchorScale
    """调用方传入的锚点分布偏好。"""

    anchor_scale_effective: AnchorScale
    """实际使用的分布；``LOG`` 在 x_min <= 0 时会退化为 ``LINEAR``。"""


# ============================================================
# 入口
# ============================================================


def read_series_csv(
    csv_path: Path,
    *,
    anchor_count: int = 14,
    anchor_scale: AnchorScale = AnchorScale.LINEAR,
) -> SeriesReadResult:
    """扫描一份 ``{raw_data,chart}.csv`` 并返回紧凑统计 + 锚点。

    Args:
        csv_path: 绝对路径。调用方已自己校验过文件存在。
        anchor_count: 锚点目标数量；函数内部 clamp 到 ``[4, 32]``。
        anchor_scale: 锚点在 x 上的分布（线性 / 对数）。

    Returns:
        :class:`SeriesReadResult` ——所有字段都是不可变 dataclass，
        调用方可以直接拿去 join markdown。

    Raises:
        OSError: 文件打开 / 读取失败。
        ValueError: CSV 格式不符合 exporter 产出约定（缺 header 块、
            缺列行、列行至少要有一列 x 轴等）。
    """
    anchor_count = max(4, min(32, int(anchor_count)))

    # -------- 第一遍：解析 header、列名、累加统计 --------
    pass1 = _scan_pass1(csv_path)

    if pass1.total_rows == 0:
        return SeriesReadResult(
            header_entries=pass1.header_entries,
            x_column_name=pass1.x_column_name,
            signal_column_names=pass1.signal_column_names,
            total_rows=0,
            x_range=(float("nan"), float("nan")),
            stats=tuple(
                _stats_from_aggregator(agg) for agg in pass1.aggregators
            ),
            anchors=(),
            anchor_scale_requested=anchor_scale,
            anchor_scale_effective=anchor_scale,
        )

    # -------- 选锚点索引 / 目标 x --------
    effective_scale = anchor_scale
    if anchor_scale == AnchorScale.LOG:
        if not (pass1.x_min > 0 and math.isfinite(pass1.x_min)
                and math.isfinite(pass1.x_max) and pass1.x_max > pass1.x_min):
            # 数据里有 <=0 或 x 轴退化 —— 对数采样不可行，退到线性。
            effective_scale = AnchorScale.LINEAR

    if effective_scale == AnchorScale.LINEAR:
        target_indices = _linear_anchor_indices(pass1.total_rows, anchor_count)
        target_xs: Optional[List[float]] = None
    else:
        target_indices = None
        target_xs = _log_anchor_targets(
            pass1.x_min, pass1.x_max, anchor_count
        )

    # -------- 第二遍：挑锚点 --------
    anchors = _scan_pass2(
        csv_path=csv_path,
        column_count=1 + len(pass1.signal_column_names),
        target_indices=target_indices,
        target_xs=target_xs,
    )

    return SeriesReadResult(
        header_entries=pass1.header_entries,
        x_column_name=pass1.x_column_name,
        signal_column_names=pass1.signal_column_names,
        total_rows=pass1.total_rows,
        x_range=(pass1.x_min, pass1.x_max),
        stats=tuple(
            _stats_from_aggregator(agg) for agg in pass1.aggregators
        ),
        anchors=anchors,
        anchor_scale_requested=anchor_scale,
        anchor_scale_effective=effective_scale,
    )


# ============================================================
# 第一遍：header + 列名 + 累加统计
# ============================================================


@dataclass
class _SignalAggregator:
    """流式累加器。"""

    name: str
    samples: int = 0
    min_value: float = float("inf")
    max_value: float = float("-inf")
    sum_value: float = 0.0
    initial_value: Optional[float] = None
    final_value: Optional[float] = None
    last_value: Optional[float] = None
    zero_crossings: int = 0


@dataclass
class _Pass1Result:
    header_entries: Tuple[Tuple[str, str], ...]
    x_column_name: str
    signal_column_names: Tuple[str, ...]
    total_rows: int
    x_min: float
    x_max: float
    aggregators: Tuple[_SignalAggregator, ...]


def _scan_pass1(csv_path: Path) -> _Pass1Result:
    header_entries: List[Tuple[str, str]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        # 1) 解析 ``# key: value`` 块 + 空行。
        while True:
            raw = handle.readline()
            if raw == "":
                raise ValueError(
                    "series csv ended before reaching the column header"
                )
            stripped = raw.rstrip("\r\n")
            if stripped.startswith("#"):
                key, _, value = stripped[1:].partition(":")
                header_entries.append((key.strip(), value.strip()))
                continue
            if stripped == "":
                break
            # 没有 header 块的 CSV 退化为"直接是列行"。exporter 目前
            # 永远写 header，但把这条兼容路径保留给将来从外部接入
            # 的 CSV（或手写测试 fixture）；仍走同一条解析链。
            column_line = stripped
            columns = _parse_csv_line(column_line)
            return _bootstrap_pass1(handle, header_entries, columns)

        # 2) header 后第一条非空行是 csv 列名。
        while True:
            raw = handle.readline()
            if raw == "":
                raise ValueError(
                    "series csv has a header block but no column row"
                )
            stripped = raw.rstrip("\r\n")
            if stripped:
                columns = _parse_csv_line(stripped)
                return _bootstrap_pass1(handle, header_entries, columns)


def _bootstrap_pass1(
    handle,
    header_entries: List[Tuple[str, str]],
    columns: List[str],
) -> _Pass1Result:
    if len(columns) < 1:
        raise ValueError("series csv column header is empty")
    x_column = columns[0]
    signal_columns = columns[1:]
    aggregators = tuple(
        _SignalAggregator(name=name) for name in signal_columns
    )

    x_min = float("inf")
    x_max = float("-inf")
    total_rows = 0

    reader = csv.reader(handle)
    for row in reader:
        if not row:
            continue
        # csv.reader 永远保证 row 是 List[str]；row 长度可能短于列数
        # （exporter 的 ``writer.writerow([row.get(col, "") for col ...])``
        # 实际上会对齐，但测试 fixture 可能手写成缺列；我们能容错）。
        x_value = _try_parse_float(row[0] if row else "")
        if x_value is None:
            # x 轴解析失败的数据行丢弃；exporter 产出不会触发，但
            # 手写 fixture 或外部 CSV 可能会遇到。不抛——仿真结果
            # 的质量问题不应让 read 工具完全放弃整个文件。
            continue
        total_rows += 1
        if x_value < x_min:
            x_min = x_value
        if x_value > x_max:
            x_max = x_value

        for i, agg in enumerate(aggregators):
            cell_index = i + 1
            if cell_index >= len(row):
                continue
            cell = row[cell_index]
            y_value = _try_parse_float(cell)
            if y_value is None:
                continue
            agg.samples += 1
            agg.sum_value += y_value
            if y_value < agg.min_value:
                agg.min_value = y_value
            if y_value > agg.max_value:
                agg.max_value = y_value
            if agg.initial_value is None:
                agg.initial_value = y_value
            agg.final_value = y_value
            if agg.last_value is not None:
                # 严格正负号翻转：两端都非零 + 乘积 < 0。
                if agg.last_value * y_value < 0.0:
                    agg.zero_crossings += 1
            agg.last_value = y_value

    if total_rows == 0:
        # x_min / x_max 仍是 inf/-inf——用 nan 对外呈现，让调用方
        # 清楚"有文件但没有有效数据"。
        return _Pass1Result(
            header_entries=tuple(header_entries),
            x_column_name=x_column,
            signal_column_names=tuple(signal_columns),
            total_rows=0,
            x_min=float("nan"),
            x_max=float("nan"),
            aggregators=aggregators,
        )

    return _Pass1Result(
        header_entries=tuple(header_entries),
        x_column_name=x_column,
        signal_column_names=tuple(signal_columns),
        total_rows=total_rows,
        x_min=x_min,
        x_max=x_max,
        aggregators=aggregators,
    )


# ============================================================
# 第二遍：锚点挑行
# ============================================================


def _scan_pass2(
    *,
    csv_path: Path,
    column_count: int,
    target_indices: Optional[List[int]],
    target_xs: Optional[List[float]],
) -> Tuple[AnchorRow, ...]:
    """按目标索引（线性）或目标 x（对数最近邻）挑采样行。

    只会一遍扫描；对数路径维护 ``best_delta[k]`` 就地替换最近邻行。
    """
    if target_indices is not None:
        needed = set(target_indices)
        picked: Dict[int, AnchorRow] = {}
    else:
        assert target_xs is not None
        best_delta: List[float] = [float("inf")] * len(target_xs)
        picked_xs: List[Optional[AnchorRow]] = [None] * len(target_xs)

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        # 跳过 header 块 + 空行 + 列名行。
        saw_blank = False
        saw_columns = False
        while True:
            raw = handle.readline()
            if raw == "":
                return ()
            stripped = raw.rstrip("\r\n")
            if stripped.startswith("#"):
                continue
            if stripped == "":
                saw_blank = True
                continue
            if saw_blank or not stripped.startswith("#"):
                # 第一条非 # 非空行即列名行。
                saw_columns = True
                break
        # 若 CSV 没有 header 块 + 空行，上面循环也能把列名行消耗掉。
        if not saw_columns:
            return ()

        reader = csv.reader(handle)
        data_index = 0
        for row in reader:
            if not row:
                continue
            x_value = _try_parse_float(row[0] if row else "")
            if x_value is None:
                continue

            values: List[Optional[float]] = []
            for i in range(1, column_count):
                if i >= len(row):
                    values.append(None)
                else:
                    values.append(_try_parse_float(row[i]))

            if target_indices is not None:
                if data_index in needed:
                    picked[data_index] = AnchorRow(
                        x=x_value, values=tuple(values)
                    )
                    needed.discard(data_index)
                    if not needed:
                        data_index += 1
                        break
            else:
                # 对数最近邻：对每个目标 x 看看当前行是否更近。
                for k, target in enumerate(target_xs):  # type: ignore[arg-type]
                    delta = abs(math.log10(x_value) - math.log10(target))
                    if delta < best_delta[k]:
                        best_delta[k] = delta
                        picked_xs[k] = AnchorRow(
                            x=x_value, values=tuple(values)
                        )

            data_index += 1

    if target_indices is not None:
        rows = [picked[idx] for idx in target_indices if idx in picked]
    else:
        # 对数路径：去重相邻被吸到同一行的目标。
        seen_xs: set = set()
        rows = []
        for entry in picked_xs:
            if entry is None:
                continue
            if entry.x in seen_xs:
                continue
            seen_xs.add(entry.x)
            rows.append(entry)

    rows.sort(key=lambda r: r.x)
    return tuple(rows)


# ============================================================
# 锚点目标计算
# ============================================================


def _linear_anchor_indices(total_rows: int, anchor_count: int) -> List[int]:
    if total_rows <= 0:
        return []
    if total_rows <= anchor_count:
        return list(range(total_rows))
    # 等距采样，首尾一定命中。
    step = (total_rows - 1) / (anchor_count - 1)
    indices = sorted({int(round(i * step)) for i in range(anchor_count)})
    # 防止 round 带来重复（极小 total_rows 时会发生），再裁一次范围。
    return [i for i in indices if 0 <= i < total_rows]


def _log_anchor_targets(
    x_min: float, x_max: float, anchor_count: int
) -> List[float]:
    log_min = math.log10(x_min)
    log_max = math.log10(x_max)
    if anchor_count == 1 or log_max == log_min:
        return [x_min]
    step = (log_max - log_min) / (anchor_count - 1)
    return [10 ** (log_min + i * step) for i in range(anchor_count)]


# ============================================================
# 工具
# ============================================================


def _stats_from_aggregator(agg: _SignalAggregator) -> SeriesStats:
    if agg.samples == 0:
        nan = float("nan")
        return SeriesStats(
            name=agg.name,
            samples=0,
            min_value=nan,
            max_value=nan,
            mean_value=nan,
            initial_value=nan,
            final_value=nan,
            zero_crossings=0,
            peak_to_peak=nan,
        )
    mean = agg.sum_value / agg.samples
    return SeriesStats(
        name=agg.name,
        samples=agg.samples,
        min_value=agg.min_value,
        max_value=agg.max_value,
        mean_value=mean,
        initial_value=agg.initial_value if agg.initial_value is not None else float("nan"),
        final_value=agg.final_value if agg.final_value is not None else float("nan"),
        zero_crossings=agg.zero_crossings,
        peak_to_peak=agg.max_value - agg.min_value,
    )


def _try_parse_float(text: str) -> Optional[float]:
    if text is None:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = float(stripped)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _parse_csv_line(line: str) -> List[str]:
    """解析单行 csv，剔除首尾空白。"""
    row_iter = csv.reader([line])
    for row in row_iter:
        return [cell.strip() for cell in row]
    return []


# ============================================================
# 模块导出
# ============================================================


__all__ = [
    "AnchorScale",
    "SeriesStats",
    "AnchorRow",
    "SeriesReadResult",
    "read_series_csv",
]
