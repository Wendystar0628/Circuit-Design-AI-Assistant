(function () {
  const rootEl = document.getElementById('simulation-root')
  let bridge = null
  let historyPreviewResultPath = ''
  let eventsBound = false
  let state = {
    simulation_runtime: {
      status: 'idle',
      status_message: '',
      error_message: '',
      project_root: '',
      has_project: false,
      current_result_path: '',
      is_empty: true,
      has_result: false,
      has_error: false,
      awaiting_confirmation: false,
      current_result: {
        file_name: '',
        analysis_label: '',
      },
    },
    surface_tabs: {
      active_tab: 'metrics',
      available_tabs: ['metrics', 'chart', 'waveform', 'analysis_info', 'raw_data', 'output_log', 'export'],
    },
    metrics_view: {
      total: 0,
      overall_score: 0,
      items: [],
    },
    analysis_chart_view: {
      has_chart: false,
      visible_series: [],
      available_series: [],
    },
    waveform_view: {
      has_waveform: false,
      visible_series: [],
      signal_catalog: [],
    },
    raw_data_view: {
      has_data: false,
      columns: [],
      rows: [],
    },
    output_log_view: {
      has_log: false,
      lines: [],
      summary: {},
    },
    history_results_view: {
      items: [],
      selected_result_path: '',
    },
    op_result_view: {
      is_available: false,
      sections: [],
    },
  }

  const TAB_LABELS = {
    metrics: '指标',
    chart: '图表',
    waveform: '波形',
    analysis_info: '分析信息',
    raw_data: '原始数据',
    output_log: '输出日志',
    export: '导出',
    history: '历史结果',
    op_result: '工作点结果',
  }

  function ensureRuntimeStyles() {
    if (document.getElementById('simulation-runtime-styles')) {
      return
    }
    const styleEl = document.createElement('style')
    styleEl.id = 'simulation-runtime-styles'
    styleEl.textContent = `
      .runtime-stack,
      .plot-stack,
      .signal-list,
      .legend-list,
      .table-meta,
      .log-list,
      .parameter-list {
        display: grid;
        gap: 8px;
      }
      .runtime-stack {
        min-height: 0;
      }
      .plot-pane,
      .legend-item,
      .signal-item,
      .table-window-card,
      .log-line,
      .key-value,
      .parameter-row,
      .series-overview,
      .empty-panel,
      .summary-chip {
        border: 1px solid #d8e1ec;
        border-radius: 8px;
        background: #ffffff;
      }
      .plot-pane,
      .empty-panel {
        padding: 8px;
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .plot-svg-wrap,
      .table-scroll,
      .log-scroll {
        min-height: 0;
        overflow: auto;
        border: 1px solid #d8e1ec;
        border-radius: 8px;
        background: #ffffff;
      }
      .plot-svg {
        width: 100%;
        height: 260px;
        display: block;
        background: #ffffff;
      }
      .legend-item,
      .signal-item,
      .summary-chip,
      .parameter-row,
      .series-overview {
        padding: 6px 8px;
      }
      .signal-item {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .signal-item input {
        margin: 0;
      }
      .legend-item,
      .series-overview {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }
      .series-overview__meta,
      .log-line__content,
      .parameter-row__value {
        min-width: 0;
      }
      .series-overview__meta,
      .log-line__content {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .plot-pane__title,
      .key-value__label,
      .series-overview__title,
      .log-line__number,
      .parameter-row__key {
        font-size: 11px;
        color: #64748b;
      }
      .plot-pane__subtitle,
      .key-value__value,
      .series-overview__value,
      .parameter-row__value,
      .log-line__text {
        font-size: 12px;
        color: #0f172a;
      }
      .plot-pane__title,
      .series-overview__value,
      .key-value__value {
        font-weight: 600;
      }
      .plot-legend-row,
      .pill-row,
      .form-row,
      .action-row {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        align-items: center;
      }
      .summary-chip,
      .plot-legend-tag {
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }
      .plot-legend-swatch {
        width: 10px;
        height: 10px;
        border-radius: 999px;
        flex: 0 0 auto;
      }
      .field-input,
      .field-select {
        height: 28px;
        min-width: 0;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        padding: 0 8px;
        background: #ffffff;
        color: #0f172a;
        font-size: 12px;
      }
      .field-input--short {
        width: 88px;
      }
      .field-input--medium,
      .field-select--medium {
        width: 132px;
      }
      .field-input--wide {
        width: 220px;
        max-width: 100%;
      }
      .data-table {
        width: 100%;
        border-collapse: collapse;
        font-family: Consolas, monospace;
        font-size: 11px;
      }
      .data-table thead th {
        position: sticky;
        top: 0;
        z-index: 1;
        background: #f8fafc;
      }
      .data-table th,
      .data-table td {
        padding: 6px 8px;
        border-bottom: 1px solid #eef2f7;
        text-align: left;
        white-space: nowrap;
      }
      .data-table tbody tr.is-selected {
        background: #eef4ff;
      }
      .log-list {
        padding: 8px;
      }
      .log-line {
        display: grid;
        grid-template-columns: 68px minmax(0, 1fr);
        gap: 8px;
        padding: 8px;
        font-family: Consolas, monospace;
      }
      .log-line--error {
        border-color: #f3c1c1;
        background: #fff1f2;
      }
      .log-line--warning {
        border-color: #f5d28d;
        background: #fff7e6;
      }
      .log-line--selected {
        box-shadow: inset 0 0 0 1px #2563eb;
      }
      .log-line__number {
        font-weight: 600;
      }
      .log-line mark {
        background: #fff59d;
        color: inherit;
        padding: 0;
      }
      .measurement-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
      }
      .key-value {
        padding: 8px;
        display: flex;
        flex-direction: column;
        gap: 3px;
      }
      .empty-panel {
        min-height: 160px;
        justify-content: center;
      }
      .empty-panel .card__value {
        font-size: 12px;
      }
      .mono-text {
        font-family: Consolas, monospace;
      }
      @media (max-width: 960px) {
        .measurement-grid {
          grid-template-columns: 1fr;
        }
      }
    `
    document.head.appendChild(styleEl)
  }

  function safeObject(value) {
    return value && typeof value === 'object' ? value : {}
  }

  function safeArray(value) {
    return Array.isArray(value) ? value : []
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
  }

  function escapeRegExp(value) {
    return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  }

  function asNumber(value) {
    const numeric = Number(value)
    return Number.isFinite(numeric) ? numeric : null
  }

  function formatNumber(value) {
    const numeric = asNumber(value)
    if (numeric === null) {
      return '--'
    }
    const absolute = Math.abs(numeric)
    if ((absolute > 0 && absolute < 1e-3) || absolute >= 1e6) {
      return numeric.toExponential(4)
    }
    return String(Number(numeric.toPrecision(6)))
  }

  function formatWindow(start, end, total) {
    if (!start || !end || !total) {
      return '空窗口'
    }
    return String(start) + ' - ' + String(end) + ' / ' + String(total)
  }

  function currentResult() {
    return safeObject(safeObject(state.simulation_runtime).current_result)
  }

  function requestBridgeCall(methodName, args) {
    if (!bridge || typeof bridge[methodName] !== 'function') {
      return false
    }
    bridge[methodName].apply(bridge, safeArray(args))
    return true
  }

  function activateTab(tabId) {
    if (!tabId) {
      return
    }
    if (window.simulationApp && typeof window.simulationApp.activateTab === 'function') {
      window.simulationApp.activateTab(tabId)
    }
    requestBridgeCall('activateTab', [tabId])
  }

  function renderTabs() {
    const surfaceTabs = safeObject(state.surface_tabs)
    const availableTabs = safeArray(surfaceTabs.available_tabs)
    const activeTab = surfaceTabs.active_tab || 'metrics'
    return availableTabs.map((tabId) => {
      const activeClass = tabId === activeTab ? ' active' : ''
      const label = TAB_LABELS[tabId] || tabId
      return '<button type="button" class="tab-chip' + activeClass + '" data-tab-id="' + escapeHtml(tabId) + '">' + escapeHtml(label) + '</button>'
    }).join('')
  }

  function syncHistoryPreview() {
    const historyView = safeObject(state.history_results_view)
    const items = safeArray(historyView.items)
    const selectedPath = historyView.selected_result_path ? String(historyView.selected_result_path) : ''
    const hasPreview = items.some((item) => item && String(item.result_path || '') === historyPreviewResultPath)
    if (hasPreview) {
      return
    }
    if (selectedPath && items.some((item) => item && String(item.result_path || '') === selectedPath)) {
      historyPreviewResultPath = selectedPath
      return
    }
    historyPreviewResultPath = items.length && items[0] && items[0].result_path ? String(items[0].result_path) : ''
  }

  function renderStateCards() {
    const runtime = safeObject(state.simulation_runtime)
    const surfaceTabs = safeObject(state.surface_tabs)
    const cards = []
    if (!bridge) {
      cards.push([
        '<div class="state-card state-card--warning">',
        '  <div class="card__label">前端桥接未连接</div>',
        '  <div class="card__value">当前界面仍会接收后端状态，但局部动作可能暂时不可用。</div>',
        '</div>',
      ].join(''))
    }
    if (runtime.error_message) {
      cards.push([
        '<div class="state-card state-card--error">',
        '  <div class="card__label">仿真错误</div>',
        '  <div class="card__value">' + escapeHtml(runtime.error_message) + '</div>',
        '</div>',
      ].join(''))
    } else if (runtime.status_message) {
      const tone = runtime.awaiting_confirmation ? 'warning' : 'info'
      cards.push([
        '<div class="state-card state-card--' + tone + '">',
        '  <div class="card__label">运行状态</div>',
        '  <div class="card__value">' + escapeHtml(runtime.status_message) + '</div>',
        '</div>',
      ].join(''))
    }
    if (runtime.is_empty && surfaceTabs.active_tab !== 'history') {
      cards.push([
        '<div class="state-card state-card--empty">',
        '  <div class="card__label">暂无仿真结果</div>',
        '  <div class="card__value">' + escapeHtml(runtime.has_project ? '运行一次仿真后，对应 tab 会显示真实结果。' : '请先打开项目并运行仿真。') + '</div>',
        surfaceTabs.has_history ? '  <div class="state-actions"><button type="button" class="action-btn" data-tab-id="history">转到历史结果</button></div>' : '',
        '</div>',
      ].join(''))
    }
    return cards.length ? '<div class="state-stack">' + cards.join('') + '</div>' : ''
  }

  function renderToolbar(title, description, actionsHtml) {
    return [
      '<div class="toolbar">',
      '  <div class="toolbar__meta">',
      '    <div class="toolbar__title">' + escapeHtml(title) + '</div>',
      '    <div class="toolbar__desc">' + escapeHtml(description) + '</div>',
      '  </div>',
      '  <div class="toolbar__actions">' + (actionsHtml || '') + '</div>',
      '</div>',
    ].join('')
  }

  function renderEmptyPanel(title, description) {
    return [
      '<div class="empty-panel">',
      '  <div class="card__label">' + escapeHtml(title) + '</div>',
      '  <div class="card__value">' + escapeHtml(description) + '</div>',
      '</div>',
    ].join('')
  }

  function renderMetricsTab() {
    const runtime = safeObject(state.simulation_runtime)
    const result = currentResult()
    const metricsView = safeObject(state.metrics_view)
    const items = safeArray(metricsView.items)
    const summaryCards = [
      ['综合评分', metricsView.has_goals ? Number(metricsView.overall_score || 0).toFixed(1) : '无目标模式'],
      ['结果文件', result.file_name || '暂无结果'],
      ['分析类型', result.analysis_label || '未加载'],
    ].map((item) => '<div class="metric-card"><div class="metric-card__title">' + escapeHtml(item[0]) + '</div><div class="metric-card__value">' + escapeHtml(item[1]) + '</div></div>').join('')
    const metricCards = items.length ? items.map((item) => [
      '<div class="metric-card">',
      '  <div class="metric-card__header"><span class="metric-card__title">' + escapeHtml(item.display_name || item.name || 'metric') + '</span><span class="muted-text">' + escapeHtml(item.category || 'metric') + '</span></div>',
      '  <div class="metric-card__value">' + escapeHtml(item.value || '--') + '</div>',
      '  <div class="muted-text">目标：' + escapeHtml(item.target || '未定义') + '</div>',
      '</div>',
    ].join('')).join('') : '<div class="metric-card"><div class="metric-card__title">暂无指标</div><div class="muted-text">当前结果没有结构化指标。</div></div>'
    return [
      renderToolbar('指标', '局部动作区 + 指标概览 + 结构化指标区', '<button type="button" class="action-btn action-btn--primary" data-add-target="metrics"' + (metricsView.can_add_to_conversation ? '' : ' disabled') + '>添加至对话</button>'),
      '<div class="content-card scrollable">',
      '  <div class="summary-grid">' + summaryCards + '</div>',
      '  <div class="metrics-grid">' + metricCards + '</div>',
      '</div>',
    ].join('')
  }

  function renderHistoryTab() {
    const historyView = safeObject(state.history_results_view)
    const items = safeArray(historyView.items)
    syncHistoryPreview()
    const selectedItem = items.find((item) => item && String(item.result_path || '') === historyPreviewResultPath) || items[0] || null
    const listHtml = items.length ? items.map((item) => {
      const resultPath = item && item.result_path ? String(item.result_path) : ''
      const activeClass = resultPath === (selectedItem && selectedItem.result_path ? String(selectedItem.result_path) : '') ? ' history-item--active' : ''
      return [
        '<button type="button" class="history-item history-item--button' + activeClass + '" data-history-preview="' + escapeHtml(resultPath) + '">',
        '  <div class="history-item__meta">',
        '    <div class="history-item__title">' + escapeHtml(item.file_name || '未命名结果') + '</div>',
        '    <div class="history-item__sub">' + escapeHtml((item.analysis_type || '') + (item.timestamp ? ' · ' + item.timestamp : '')) + '</div>',
        '  </div>',
        item.is_current ? '  <span class="muted-text">当前</span>' : '  <span class="muted-text">预览</span>',
        '</button>',
      ].join('')
    }).join('') : '<div class="history-item"><div class="history-item__title">暂无历史结果</div></div>'
    return [
      renderToolbar('历史结果', '筛选/排序区 + 列表区 + 当前选中项预览/加载区'),
      '<div class="responsive-pane">',
      '  <div class="content-card scrollable">',
      '    <div class="filter-row"><div class="filter-chip">最近结果</div><div class="filter-chip">按时间排序</div></div>',
      '    <div class="history-list">' + listHtml + '</div>',
      '  </div>',
      '  <div class="content-card">',
      '    <div class="info-grid">',
      '      <div class="info-row"><div class="card__label">文件</div><div class="card__value">' + escapeHtml(selectedItem && selectedItem.file_name || '未选择结果') + '</div></div>',
      '      <div class="info-row"><div class="card__label">分析类型</div><div class="card__value">' + escapeHtml(selectedItem && selectedItem.analysis_type || '未定义') + '</div></div>',
      '      <div class="info-row"><div class="card__label">时间戳</div><div class="card__value">' + escapeHtml(selectedItem && selectedItem.timestamp || '无') + '</div></div>',
      '      <div class="info-row"><div class="card__label">状态</div><div class="card__value">' + escapeHtml(selectedItem ? (selectedItem.success ? '成功' : '失败') : '无') + '</div></div>',
      '    </div>',
      '    <div class="stage">',
      '      <div class="card__label">当前选中项预览</div>',
      '      <div class="card__value">结果路径：' + escapeHtml(selectedItem && selectedItem.result_path || '未选择结果') + '</div>',
      '    </div>',
      '    <div class="footer-row">',
      '      <div><div class="card__label">加载历史结果</div><div class="muted-text">加载后会替换当前权威结果。</div></div>',
      '      <button type="button" class="action-btn action-btn--primary" data-load-history="' + escapeHtml(selectedItem && selectedItem.result_path || '') + '"' + (selectedItem && selectedItem.can_load ? '' : ' disabled') + '>加载选中结果</button>',
      '    </div>',
      '  </div>',
      '</div>',
    ].join('')
  }

  function renderOpResultTab() {
    const opView = safeObject(state.op_result_view)
    const sections = safeArray(opView.sections)
    const sectionsHtml = sections.length ? sections.map((section) => {
      const rows = safeArray(section.rows)
      const rowsHtml = rows.length ? rows.map((row) => [
        '<div class="op-row">',
        '  <div class="op-row__name">' + escapeHtml(row.name || '') + '</div>',
        '  <div class="op-row__value">' + escapeHtml(row.formatted_value || '无效值') + '</div>',
        '</div>',
      ].join('')).join('') : '<div class="muted-text">当前分组暂无可展示结果。</div>'
      return [
        '<section class="op-section">',
        '  <div class="op-section__header"><div class="card__label">' + escapeHtml(section.title || '') + '</div><div class="muted-text">' + escapeHtml(String(section.row_count || 0)) + ' 项</div></div>',
        '  <div class="op-row-list">' + rowsHtml + '</div>',
        '</section>',
      ].join('')
    }).join('') : '<div class="muted-text">当前结果不包含工作点结构化数据。</div>'
    return [
      renderToolbar('工作点结果', '局部动作区 + 结构化结果表', '<button type="button" class="action-btn action-btn--primary" data-add-target="op_result"' + (opView.can_add_to_conversation ? '' : ' disabled') + '>添加至对话</button>'),
      '<div class="responsive-pane">',
      '  <div class="content-card scrollable">',
      '    <div class="info-grid">',
      '      <div class="info-row"><div class="card__label">结果文件</div><div class="card__value">' + escapeHtml(opView.file_name || '未命名结果') + '</div></div>',
      '      <div class="info-row"><div class="card__label">分析命令</div><div class="card__value">' + escapeHtml(opView.analysis_command || '.op') + '</div></div>',
      '      <div class="info-row"><div class="card__label">结果行数</div><div class="card__value">' + escapeHtml(String(opView.row_count || 0)) + '</div></div>',
      '      <div class="info-row"><div class="card__label">分组数量</div><div class="card__value">' + escapeHtml(String(opView.section_count || 0)) + '</div></div>',
      '    </div>',
      '  </div>',
      '  <div class="content-card scrollable">',
      '    <div class="stage stage--scrollable">' + sectionsHtml + '</div>',
      '  </div>',
      '</div>',
    ].join('')
  }

  function renderAnalysisInfoTab() {
    const info = safeObject(state.analysis_info_view)
    const parameterEntries = Object.entries(safeObject(info.parameters))
    const parameterHtml = parameterEntries.length ? parameterEntries.map(([key, value]) => [
      '<div class="parameter-row">',
      '  <div class="parameter-row__key">' + escapeHtml(key) + '</div>',
      '  <div class="parameter-row__value">' + escapeHtml(String(value == null ? '' : value)) + '</div>',
      '</div>',
    ].join('')).join('') : '<div class="muted-text">暂无结构化参数。</div>'
    return [
      renderToolbar('分析信息', '结构化分析参数、执行上下文与 X 轴定义'),
      '<div class="content-card scrollable runtime-stack">',
      '  <div class="info-grid">',
      '    <div class="info-row"><div class="card__label">分析类型</div><div class="card__value">' + escapeHtml(info.analysis_type || '未加载') + '</div></div>',
      '    <div class="info-row"><div class="card__label">命令</div><div class="card__value">' + escapeHtml(info.analysis_command || '未加载') + '</div></div>',
      '    <div class="info-row"><div class="card__label">执行器</div><div class="card__value">' + escapeHtml(info.executor || '未加载') + '</div></div>',
      '    <div class="info-row"><div class="card__label">文件</div><div class="card__value">' + escapeHtml(info.file_name || '未加载') + '</div></div>',
      '    <div class="info-row"><div class="card__label">X 轴标签</div><div class="card__value">' + escapeHtml(info.x_axis_label || '未定义') + '</div></div>',
      '    <div class="info-row"><div class="card__label">X 轴刻度</div><div class="card__value">' + escapeHtml(info.x_axis_scale || '未定义') + '</div></div>',
      '  </div>',
      '  <div class="stage stage--scrollable">',
      '    <div class="card__label">参数</div>',
      '    <div class="parameter-list">' + parameterHtml + '</div>',
      '  </div>',
      '</div>',
    ].join('')
  }

  function renderExportTab() {
    const exportView = safeObject(state.export_view)
    const availableTypes = safeArray(exportView.available_types)
    const itemsHtml = availableTypes.length ? availableTypes.map((item) => [
      '<div class="series-overview">',
      '  <div class="series-overview__meta">',
      '    <div class="series-overview__title">导出项</div>',
      '    <div class="series-overview__value">' + escapeHtml(item) + '</div>',
      '  </div>',
      '</div>',
    ].join('')).join('') : '<div class="empty-panel"><div class="card__label">暂无可导出项</div><div class="card__value">当前结果没有可导出的结构化内容。</div></div>'
    return [
      renderToolbar('导出', '局部导出动作区', '<button type="button" class="action-btn action-btn--primary" data-bridge-action="export-all"' + (exportView.has_result && availableTypes.length ? '' : ' disabled') + '>导出选中项</button>'),
      '<div class="content-card scrollable runtime-stack">',
      '  <div class="info-grid">',
      '    <div class="info-row"><div class="card__label">最近项目导出目录</div><div class="card__value">' + escapeHtml(exportView.latest_project_export_root || '无') + '</div></div>',
      '    <div class="info-row"><div class="card__label">可导出类型</div><div class="card__value">' + escapeHtml(availableTypes.join(', ') || '无') + '</div></div>',
      '  </div>',
      '  <div class="runtime-stack">' + itemsHtml + '</div>',
      '</div>',
    ].join('')
  }

  function splitSeriesByAxis(seriesList) {
    const buckets = { left: [], right: [] }
    safeArray(seriesList).forEach((series) => {
      const axisKey = String(series.axis_key || series.axis || 'left')
      if (axisKey === 'right') {
        buckets.right.push(series)
      } else {
        buckets.left.push(series)
      }
    })
    return buckets
  }

  function toPlotValue(value, logEnabled) {
    const numeric = asNumber(value)
    if (numeric === null) {
      return null
    }
    if (logEnabled) {
      if (numeric <= 0) {
        return null
      }
      return Math.log10(numeric)
    }
    return numeric
  }

  function buildDomain(seriesList, logX, logY) {
    let xMin = Infinity
    let xMax = -Infinity
    let yMin = Infinity
    let yMax = -Infinity
    safeArray(seriesList).forEach((series) => {
      const xs = safeArray(series.x)
      const ys = safeArray(series.y)
      const pointCount = Math.min(xs.length, ys.length)
      for (let index = 0; index < pointCount; index += 1) {
        const scaledX = toPlotValue(xs[index], !!logX)
        const scaledY = toPlotValue(ys[index], !!logY)
        if (scaledX === null || scaledY === null) {
          continue
        }
        if (scaledX < xMin) xMin = scaledX
        if (scaledX > xMax) xMax = scaledX
        if (scaledY < yMin) yMin = scaledY
        if (scaledY > yMax) yMax = scaledY
      }
    })
    if (!Number.isFinite(xMin) || !Number.isFinite(xMax) || !Number.isFinite(yMin) || !Number.isFinite(yMax)) {
      return null
    }
    if (xMin === xMax) {
      const pad = Math.abs(xMin || 1) * 0.1 || 1
      xMin -= pad
      xMax += pad
    }
    if (yMin === yMax) {
      const pad = Math.abs(yMin || 1) * 0.1 || 1
      yMin -= pad
      yMax += pad
    }
    return { xMin, xMax, yMin, yMax }
  }

  function buildSeriesPath(series, domain, options) {
    const xs = safeArray(series.x)
    const ys = safeArray(series.y)
    const pointCount = Math.min(xs.length, ys.length)
    const width = options.width
    const height = options.height
    const padding = options.padding
    const innerWidth = width - padding.left - padding.right
    const innerHeight = height - padding.top - padding.bottom
    let commands = []
    let pendingMove = true
    for (let index = 0; index < pointCount; index += 1) {
      const scaledX = toPlotValue(xs[index], !!options.logX)
      const scaledY = toPlotValue(ys[index], !!options.logY)
      if (scaledX === null || scaledY === null) {
        pendingMove = true
        continue
      }
      const xRatio = (scaledX - domain.xMin) / (domain.xMax - domain.xMin)
      const yRatio = (scaledY - domain.yMin) / (domain.yMax - domain.yMin)
      const svgX = padding.left + innerWidth * xRatio
      const svgY = padding.top + innerHeight * (1 - yRatio)
      const command = (pendingMove ? 'M' : 'L') + svgX.toFixed(2) + ' ' + svgY.toFixed(2)
      commands.push(command)
      pendingMove = false
    }
    return commands.join(' ')
  }

  function renderPlotSvg(seriesList, options) {
    const width = 900
    const height = options.height || 260
    const padding = { top: 16, right: 14, bottom: 28, left: 44 }
    const domain = buildDomain(seriesList, options.logX, options.logY)
    if (!domain) {
      return renderEmptyPanel('暂无可视曲线', '当前没有可绘制的有效数据点。')
    }
    const innerWidth = width - padding.left - padding.right
    const innerHeight = height - padding.top - padding.bottom
    const gridLines = []
    for (let step = 0; step <= 4; step += 1) {
      const y = padding.top + innerHeight * (step / 4)
      const x = padding.left + innerWidth * (step / 4)
      gridLines.push('<line x1="' + padding.left + '" y1="' + y.toFixed(2) + '" x2="' + (padding.left + innerWidth) + '" y2="' + y.toFixed(2) + '" stroke="#e2e8f0" stroke-width="1" />')
      gridLines.push('<line x1="' + x.toFixed(2) + '" y1="' + padding.top + '" x2="' + x.toFixed(2) + '" y2="' + (padding.top + innerHeight) + '" stroke="#eff3f8" stroke-width="1" />')
    }
    const axisLabels = [
      '<text x="' + padding.left + '" y="' + (height - 8) + '" fill="#64748b" font-size="11">' + escapeHtml(options.xLabel || 'X') + '</text>',
      '<text x="12" y="14" fill="#64748b" font-size="11">' + escapeHtml(options.yLabel || 'Y') + '</text>',
      '<text x="' + padding.left + '" y="' + (padding.top - 2) + '" fill="#94a3b8" font-size="10">[' + escapeHtml(formatNumber(options.logX ? Math.pow(10, domain.xMin) : domain.xMin)) + ', ' + escapeHtml(formatNumber(options.logX ? Math.pow(10, domain.xMax) : domain.xMax)) + ']</text>',
      '<text x="' + (width - padding.right - 120) + '" y="' + (padding.top - 2) + '" fill="#94a3b8" font-size="10">[' + escapeHtml(formatNumber(options.logY ? Math.pow(10, domain.yMin) : domain.yMin)) + ', ' + escapeHtml(formatNumber(options.logY ? Math.pow(10, domain.yMax) : domain.yMax)) + ']</text>',
    ]
    const paths = safeArray(seriesList).map((series) => {
      const pathData = buildSeriesPath(series, domain, {
        width,
        height,
        padding,
        logX: !!options.logX,
        logY: !!options.logY,
      })
      if (!pathData) {
        return ''
      }
      const dash = String(series.line_style || '') === 'dash' ? ' stroke-dasharray="6 4"' : ''
      return '<path d="' + pathData + '" fill="none" stroke="' + escapeHtml(series.color || '#2563eb') + '" stroke-width="1.6"' + dash + ' />'
    }).join('')
    return [
      '<div class="plot-svg-wrap">',
      '  <svg class="plot-svg" viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none">',
      '    ' + gridLines.join(''),
      '    <rect x="' + padding.left + '" y="' + padding.top + '" width="' + innerWidth + '" height="' + innerHeight + '" fill="transparent" stroke="#cbd5e1" stroke-width="1" />',
      '    ' + paths,
      '    ' + axisLabels.join(''),
      '  </svg>',
      '</div>',
    ].join('')
  }

  function renderLegendTags(seriesList) {
    return safeArray(seriesList).map((series) => [
      '<div class="plot-legend-tag summary-chip">',
      '  <span class="plot-legend-swatch" style="background:' + escapeHtml(series.color || '#2563eb') + '"></span>',
      '  <span>' + escapeHtml(series.name || 'series') + '</span>',
      '</div>',
    ].join('')).join('')
  }

  function renderPlotPane(title, subtitle, seriesList, options) {
    return [
      '<div class="plot-pane">',
      '  <div class="plot-pane__title">' + escapeHtml(title) + '</div>',
      subtitle ? '  <div class="plot-pane__subtitle">' + escapeHtml(subtitle) + '</div>' : '',
      safeArray(seriesList).length ? '  <div class="plot-legend-row">' + renderLegendTags(seriesList) + '</div>' : '',
      renderPlotSvg(seriesList, options),
      '</div>',
    ].join('')
  }

  function renderMeasurementBlock(measurement, xLabel) {
    const info = safeObject(measurement)
    const valuesA = safeObject(info.values_a)
    const valuesB = safeObject(info.values_b)
    const keys = Array.from(new Set(Object.keys(valuesA).concat(Object.keys(valuesB))))
    const hasSummary = info.cursor_a_x != null || info.cursor_b_x != null || info.delta_x != null || info.frequency != null || info.delta_y != null || info.slope != null
    if (!hasSummary && !keys.length) {
      return ''
    }
    const summaryItems = [
      ['A', info.cursor_a_x != null ? formatNumber(info.cursor_a_x) : '--'],
      ['B', info.cursor_b_x != null ? formatNumber(info.cursor_b_x) : '--'],
      ['ΔX', info.delta_x != null ? formatNumber(info.delta_x) : '--'],
      ['频率', info.frequency != null ? formatNumber(info.frequency) + ' Hz' : '--'],
      ['ΔY', info.delta_y != null ? formatNumber(info.delta_y) : '--'],
      ['斜率', info.slope != null ? formatNumber(info.slope) : '--'],
    ].map((item) => [
      '<div class="key-value">',
      '  <div class="key-value__label">' + escapeHtml(item[0] + (item[0] === 'A' || item[0] === 'B' || item[0] === 'ΔX' ? ' (' + (xLabel || 'X') + ')' : '')) + '</div>',
      '  <div class="key-value__value mono-text">' + escapeHtml(item[1]) + '</div>',
      '</div>',
    ].join('')).join('')
    const valuesHtml = keys.length ? keys.map((name) => [
      '<div class="parameter-row">',
      '  <div class="parameter-row__key">' + escapeHtml(name) + '</div>',
      '  <div class="parameter-row__value mono-text">A=' + escapeHtml(valuesA[name] != null ? formatNumber(valuesA[name]) : '--') + '  B=' + escapeHtml(valuesB[name] != null ? formatNumber(valuesB[name]) : '--') + '</div>',
      '</div>',
    ].join('')).join('') : '<div class="muted-text">当前未启用测量光标。</div>'
    return [
      '<div class="stage stage--scrollable">',
      '  <div class="card__label">测量结果</div>',
      '  <div class="measurement-grid">' + summaryItems + '</div>',
      '  <div class="parameter-list">' + valuesHtml + '</div>',
      '</div>',
    ].join('')
  }

  function renderWaveformTab() {
    const waveformView = safeObject(state.waveform_view)
    const signalCatalog = safeArray(waveformView.signal_catalog)
    const visibleSeries = safeArray(waveformView.visible_series)
    const splitSeries = splitSeriesByAxis(visibleSeries)
    const signalHtml = signalCatalog.length ? signalCatalog.map((item) => [
      '<label class="signal-item">',
      '  <input type="checkbox" data-signal-toggle="' + escapeHtml(item.name || '') + '"' + (item.visible ? ' checked' : '') + ' />',
      '  <span>' + escapeHtml(item.name || '') + '</span>',
      '  <span class="muted-text">' + escapeHtml(item.signal_type || 'signal') + '</span>',
      '</label>',
    ].join('')).join('') : renderEmptyPanel('暂无信号目录', '当前结果不包含可显示的波形信号。')
    const actions = [
      '<button type="button" class="action-btn" data-bridge-action="fit"' + (visibleSeries.length ? '' : ' disabled') + '>Fit</button>',
      '<button type="button" class="action-btn" data-bridge-action="clear-signals"' + (visibleSeries.length ? '' : ' disabled') + '>清空信号</button>',
      '<button type="button" class="action-btn" data-bridge-action="cursor-a-toggle">Cursor A ' + (waveformView.cursor_a_visible ? '关' : '开') + '</button>',
      '<button type="button" class="action-btn" data-bridge-action="cursor-b-toggle">Cursor B ' + (waveformView.cursor_b_visible ? '关' : '开') + '</button>',
      '<button type="button" class="action-btn action-btn--primary" data-add-target="waveform"' + (waveformView.can_add_to_conversation ? '' : ' disabled') + '>添加至对话</button>',
    ].join('')
    const plotStack = [
      splitSeries.left.length ? renderPlotPane('主波形', 'X 轴：' + (waveformView.x_axis_label || 'X'), splitSeries.left, { xLabel: waveformView.x_axis_label || 'X', yLabel: 'Value', logX: waveformView.log_x }) : '',
      splitSeries.right.length ? renderPlotPane('右轴信号', '右轴信号（通常为电流）', splitSeries.right, { xLabel: waveformView.x_axis_label || 'X', yLabel: 'Current', logX: waveformView.log_x }) : '',
      !splitSeries.left.length && !splitSeries.right.length ? renderEmptyPanel('暂无显示中的波形', '请在左侧勾选信号以显示真实曲线。') : '',
      renderMeasurementBlock(waveformView.measurement, waveformView.x_axis_label || 'X'),
    ].join('')
    return [
      renderToolbar('波形', '真实信号目录 + 当前显示曲线 + 测量结果', actions),
      '<div class="responsive-pane">',
      '  <div class="content-card scrollable runtime-stack">',
      '    <div class="pill-row">',
      '      <div class="summary-chip">总信号：' + escapeHtml(String(waveformView.signal_count || 0)) + '</div>',
      '      <div class="summary-chip">已显示：' + escapeHtml(String(safeArray(waveformView.displayed_signal_names).length)) + '</div>',
      '      <div class="summary-chip">X 轴：' + escapeHtml(waveformView.x_axis_label || 'X') + '</div>',
      '    </div>',
      '    <div class="signal-list">' + signalHtml + '</div>',
      '  </div>',
      '  <div class="content-card runtime-stack">' + plotStack + '</div>',
      '</div>',
    ].join('')
  }

  function renderChartSeriesList(seriesList) {
    return safeArray(seriesList).length ? safeArray(seriesList).map((series) => [
      '<div class="series-overview">',
      '  <div class="series-overview__meta">',
      '    <div class="series-overview__title">' + escapeHtml(series.group_key || series.name || 'series') + '</div>',
      '    <div class="series-overview__value">' + escapeHtml(series.name || '') + '</div>',
      '  </div>',
      '  <div class="plot-legend-tag">',
      '    <span class="plot-legend-swatch" style="background:' + escapeHtml(series.color || '#2563eb') + '"></span>',
      '    <span class="muted-text">' + escapeHtml(series.visible ? '显示中' : '未显示') + '</span>',
      '  </div>',
      '</div>',
    ].join('')).join('') : renderEmptyPanel('暂无图表序列', '当前结果没有可绘制的图表序列。')
  }

  function renderChartTab() {
    const chartView = safeObject(state.analysis_chart_view)
    const visibleSeries = safeArray(chartView.visible_series)
    const splitSeries = splitSeriesByAxis(visibleSeries)
    const actions = [
      '<button type="button" class="action-btn" data-bridge-action="export-charts"' + (chartView.can_export ? '' : ' disabled') + '>导出图表</button>',
      '<button type="button" class="action-btn action-btn--primary" data-add-target="chart"' + (chartView.can_add_to_conversation ? '' : ' disabled') + '>添加至对话</button>',
    ].join('')
    const plotContent = chartView.has_chart ? [
      splitSeries.left.length ? renderPlotPane(chartView.title || '图表', chartView.y_label || '', splitSeries.left, { xLabel: chartView.x_label || 'X', yLabel: chartView.y_label || 'Y', logX: chartView.log_x, logY: chartView.log_y }) : '',
      splitSeries.right.length ? renderPlotPane('右轴序列', chartView.secondary_y_label || '', splitSeries.right, { xLabel: chartView.x_label || 'X', yLabel: chartView.secondary_y_label || 'Y', logX: chartView.log_x, logY: false }) : '',
      renderMeasurementBlock(chartView.measurement, chartView.x_label || 'X'),
    ].join('') : renderEmptyPanel('暂无图表', '当前结果没有可用的图表数据。')
    return [
      renderToolbar('图表', '真实图表序列与当前可见曲线', actions),
      '<div class="responsive-pane">',
      '  <div class="content-card scrollable runtime-stack">',
      '    <div class="pill-row">',
      '      <div class="summary-chip">标题：' + escapeHtml(chartView.title || '无') + '</div>',
      '      <div class="summary-chip">类型：' + escapeHtml(chartView.chart_type || '无') + '</div>',
      '      <div class="summary-chip">可见序列：' + escapeHtml(String(visibleSeries.length)) + '</div>',
      '    </div>',
      '    <div class="legend-list">' + renderChartSeriesList(chartView.available_series) + '</div>',
      '  </div>',
      '  <div class="content-card runtime-stack">' + plotContent + '</div>',
      '</div>',
    ].join('')
  }

  function renderRawDataTable(view) {
    const columns = safeArray(view.columns)
    const rows = safeArray(view.rows)
    if (!columns.length || !rows.length) {
      return renderEmptyPanel('暂无原始数据', '当前结果没有可显示的数据表。')
    }
    const headHtml = ['<th>#</th>'].concat(columns.map((column) => '<th>' + escapeHtml(column) + '</th>')).join('')
    const rowHtml = rows.map((row) => {
      const values = safeArray(row.values)
      return '<tr class="' + (row.selected ? 'is-selected' : '') + '"><td>' + escapeHtml(String(row.row_number || '')) + '</td>' + values.map((value) => '<td>' + escapeHtml(value) + '</td>').join('') + '</tr>'
    }).join('')
    return [
      '<div class="table-scroll">',
      '  <table class="data-table">',
      '    <thead><tr>' + headHtml + '</tr></thead>',
      '    <tbody>' + rowHtml + '</tbody>',
      '  </table>',
      '</div>',
    ].join('')
  }

  function renderRawDataTab() {
    const rawDataView = safeObject(state.raw_data_view)
    const columns = safeArray(rawDataView.columns)
    const selectedRows = safeArray(rawDataView.selected_row_numbers)
    const selectedRow = selectedRows.length ? String(selectedRows[0]) : '1'
    return [
      renderToolbar('原始数据', '真实表格窗口、跳转与搜索动作'),
      '<div class="content-card runtime-stack">',
      '  <div class="pill-row">',
      '    <div class="summary-chip">总行数：' + escapeHtml(String(rawDataView.row_count || 0)) + '</div>',
      '    <div class="summary-chip">信号列：' + escapeHtml(String(rawDataView.signal_count || 0)) + '</div>',
      '    <div class="summary-chip">当前窗口：' + escapeHtml(formatWindow(rawDataView.window_start, rawDataView.window_end, rawDataView.row_count)) + '</div>',
      '    <div class="summary-chip">已选：' + escapeHtml(String(rawDataView.selection_count || 0)) + '</div>',
      '  </div>',
      '  <div class="form-row">',
      '    <input class="field-input field-input--short" data-raw-row-input type="number" min="1" value="' + escapeHtml(selectedRow) + '" />',
      '    <button type="button" class="action-btn" data-raw-go-row' + (rawDataView.has_data ? '' : ' disabled') + '>跳转行</button>',
      '    <input class="field-input field-input--medium" data-raw-x-input type="number" step="any" placeholder="X 值" />',
      '    <button type="button" class="action-btn" data-raw-go-x' + (rawDataView.has_data ? '' : ' disabled') + '>按 X 跳转</button>',
      '    <select class="field-select field-select--medium" data-raw-column-select>' + columns.map((column, index) => '<option value="' + escapeHtml(String(index)) + '">' + escapeHtml(column) + '</option>').join('') + '</select>',
      '    <input class="field-input field-input--medium" data-raw-search-value type="number" step="any" placeholder="搜索值" />',
      '    <input class="field-input field-input--short" data-raw-search-tolerance type="number" step="any" value="1e-9" />',
      '    <button type="button" class="action-btn" data-raw-search-button' + (rawDataView.has_data ? '' : ' disabled') + '>按值搜索</button>',
      '  </div>',
      renderRawDataTable(rawDataView),
      '</div>',
    ].join('')
  }

  function highlightText(content, keyword) {
    const text = String(content || '')
    const query = String(keyword || '').trim()
    if (!query) {
      return escapeHtml(text)
    }
    const expression = new RegExp('(' + escapeRegExp(query) + ')', 'ig')
    return escapeHtml(text).replace(expression, '<mark>$1</mark>')
  }

  function renderOutputLogTab() {
    const outputLogView = safeObject(state.output_log_view)
    const summary = safeObject(outputLogView.summary)
    const lines = safeArray(outputLogView.lines)
    const keyword = outputLogView.search_keyword || ''
    const linesHtml = lines.length ? lines.map((line) => {
      const level = String(line.level || 'info').toLowerCase()
      const selectedClass = Number(line.line_number) === Number(outputLogView.selected_line_number) ? ' log-line--selected' : ''
      return [
        '<div class="log-line log-line--' + escapeHtml(level) + selectedClass + '">',
        '  <div class="log-line__number">#' + escapeHtml(String(line.line_number || '')) + '</div>',
        '  <div class="log-line__content"><div class="log-line__text">' + highlightText(line.content || '', keyword) + '</div><div class="muted-text">' + escapeHtml(level) + '</div></div>',
        '</div>',
      ].join('')
    }).join('') : renderEmptyPanel('暂无日志输出', '当前结果没有可显示的输出日志。')
    return [
      renderToolbar('输出日志', '真实日志行、搜索、过滤与跳错', '<button type="button" class="action-btn action-btn--primary" data-add-target="output_log"' + (outputLogView.can_add_to_conversation ? '' : ' disabled') + '>添加至对话</button>'),
      '<div class="content-card runtime-stack">',
      '  <div class="pill-row">',
      '    <div class="summary-chip">总行数：' + escapeHtml(String(outputLogView.line_count || 0)) + '</div>',
      '    <div class="summary-chip">过滤后：' + escapeHtml(String(outputLogView.filtered_line_count || 0)) + '</div>',
      '    <div class="summary-chip">错误：' + escapeHtml(String(summary.error_count || 0)) + '</div>',
      '    <div class="summary-chip">警告：' + escapeHtml(String(summary.warning_count || 0)) + '</div>',
      '    <div class="summary-chip">过滤器：' + escapeHtml(outputLogView.current_filter || 'all') + '</div>',
      '  </div>',
      '  <div class="form-row">',
      '    <input class="field-input field-input--wide" data-log-search-input type="text" value="' + escapeHtml(keyword) + '" placeholder="输入关键词搜索" />',
      '    <button type="button" class="action-btn" data-log-search-button' + (outputLogView.has_log ? '' : ' disabled') + '>搜索</button>',
      '    <select class="field-select field-select--medium" data-log-filter-select' + (outputLogView.has_log ? '' : ' disabled') + '>',
      '      <option value="all"' + (String(outputLogView.current_filter || 'all') === 'all' ? ' selected' : '') + '>全部</option>',
      '      <option value="error"' + (String(outputLogView.current_filter || '') === 'error' ? ' selected' : '') + '>错误</option>',
      '      <option value="warning"' + (String(outputLogView.current_filter || '') === 'warning' ? ' selected' : '') + '>警告</option>',
      '      <option value="info"' + (String(outputLogView.current_filter || '') === 'info' ? ' selected' : '') + '>信息</option>',
      '    </select>',
      '    <button type="button" class="action-btn" data-bridge-action="log-jump-error"' + (summary.error_count ? '' : ' disabled') + '>跳到错误</button>',
      '    <button type="button" class="action-btn" data-bridge-action="log-refresh"' + (outputLogView.can_refresh ? '' : ' disabled') + '>刷新</button>',
      '  </div>',
      '  <div class="table-window-card">',
      '    <div class="pill-row">',
      '      <div class="summary-chip">窗口：' + escapeHtml(formatWindow(outputLogView.window_start, outputLogView.window_end, outputLogView.filtered_line_count || outputLogView.line_count || 0)) + '</div>',
      '      <div class="summary-chip">首个错误：' + escapeHtml(summary.first_error || '无') + '</div>',
      '    </div>',
      '  </div>',
      '  <div class="log-scroll"><div class="log-list">' + linesHtml + '</div></div>',
      '</div>',
    ].join('')
  }

  function renderActiveTab() {
    const activeTab = safeObject(state.surface_tabs).active_tab || 'metrics'
    switch (activeTab) {
      case 'history':
        return renderHistoryTab()
      case 'op_result':
        return renderOpResultTab()
      case 'chart':
        return renderChartTab()
      case 'waveform':
        return renderWaveformTab()
      case 'analysis_info':
        return renderAnalysisInfoTab()
      case 'raw_data':
        return renderRawDataTab()
      case 'output_log':
        return renderOutputLogTab()
      case 'export':
        return renderExportTab()
      case 'metrics':
      default:
        return renderMetricsTab()
    }
  }

  function render() {
    if (!rootEl) {
      return
    }
    rootEl.innerHTML = [
      '<div class="shell">',
      '  <div class="tab-row">' + renderTabs() + '</div>',
      '  <div class="surface-frame">',
      renderStateCards(),
      renderActiveTab(),
      '  </div>',
      '</div>',
    ].join('')
  }

  function handleRootClick(event) {
    const target = event.target
    if (!(target instanceof Element)) {
      return
    }
    const tabButton = target.closest('[data-tab-id]')
    if (tabButton) {
      const tabId = tabButton.getAttribute('data-tab-id')
      activateTab(tabId)
      return
    }
    const historyPreviewButton = target.closest('[data-history-preview]')
    if (historyPreviewButton) {
      historyPreviewResultPath = historyPreviewButton.getAttribute('data-history-preview') || ''
      render()
      return
    }
    const loadHistoryButton = target.closest('[data-load-history]')
    if (loadHistoryButton) {
      const resultPath = loadHistoryButton.getAttribute('data-load-history')
      requestBridgeCall('loadHistoryResult', [resultPath])
      return
    }
    const addButton = target.closest('[data-add-target]')
    if (addButton) {
      const attachTarget = addButton.getAttribute('data-add-target')
      requestBridgeCall('addToConversation', [attachTarget])
      return
    }
    const bridgeActionButton = target.closest('[data-bridge-action]')
    if (bridgeActionButton) {
      const action = bridgeActionButton.getAttribute('data-bridge-action')
      const waveformView = safeObject(state.waveform_view)
      if (action === 'fit') {
        requestBridgeCall('requestFit', [])
      }
      if (action === 'clear-signals') {
        requestBridgeCall('clearAllSignals', [])
      }
      if (action === 'cursor-a-toggle') {
        requestBridgeCall('setCursorVisible', ['a', !waveformView.cursor_a_visible])
      }
      if (action === 'cursor-b-toggle') {
        requestBridgeCall('setCursorVisible', ['b', !waveformView.cursor_b_visible])
      }
      if (action === 'log-jump-error') {
        requestBridgeCall('jumpToOutputLogError', [])
      }
      if (action === 'log-refresh') {
        requestBridgeCall('refreshOutputLog', [])
      }
      if (action === 'export-charts') {
        requestBridgeCall('requestExport', [['charts']])
      }
      if (action === 'export-all') {
        requestBridgeCall('requestExport', [safeArray(safeObject(state.export_view).available_types)])
      }
      return
    }
    const rawRowButton = target.closest('[data-raw-go-row]')
    if (rawRowButton) {
      const input = rootEl.querySelector('[data-raw-row-input]')
      const rowNumber = input ? asNumber(input.value) : null
      if (rowNumber !== null) {
        requestBridgeCall('jumpRawDataToRow', [Math.max(0, Math.round(rowNumber) - 1)])
      }
      return
    }
    const rawXButton = target.closest('[data-raw-go-x]')
    if (rawXButton) {
      const input = rootEl.querySelector('[data-raw-x-input]')
      const xValue = input ? asNumber(input.value) : null
      if (xValue !== null) {
        requestBridgeCall('jumpRawDataToX', [xValue])
      }
      return
    }
    const rawSearchButton = target.closest('[data-raw-search-button]')
    if (rawSearchButton) {
      const columnSelect = rootEl.querySelector('[data-raw-column-select]')
      const valueInput = rootEl.querySelector('[data-raw-search-value]')
      const toleranceInput = rootEl.querySelector('[data-raw-search-tolerance]')
      const column = columnSelect ? Number(columnSelect.value || 0) : 0
      const value = valueInput ? asNumber(valueInput.value) : null
      const tolerance = toleranceInput ? asNumber(toleranceInput.value) : null
      if (value !== null) {
        requestBridgeCall('searchRawDataValue', [Math.max(0, column), value, tolerance === null ? 0 : Math.max(0, tolerance)])
      }
      return
    }
    const logSearchButton = target.closest('[data-log-search-button]')
    if (logSearchButton) {
      const input = rootEl.querySelector('[data-log-search-input]')
      requestBridgeCall('searchOutputLog', [input ? input.value : ''])
    }
  }

  function handleRootChange(event) {
    const target = event.target
    if (!(target instanceof Element)) {
      return
    }
    if (target.matches('[data-signal-toggle]')) {
      requestBridgeCall('setSignalVisible', [target.getAttribute('data-signal-toggle') || '', !!target.checked])
      return
    }
    if (target.matches('[data-log-filter-select]')) {
      requestBridgeCall('filterOutputLog', [target.value || 'all'])
    }
  }

  function bindRootEvents() {
    if (eventsBound || !rootEl) {
      return
    }
    eventsBound = true
    rootEl.addEventListener('click', handleRootClick)
    rootEl.addEventListener('change', handleRootChange)
  }

  window.simulationApp = {
    setState(nextState) {
      state = safeObject(nextState)
      syncHistoryPreview()
      render()
    },
    activateTab(tabId) {
      state = Object.assign({}, state, {
        surface_tabs: Object.assign({}, safeObject(state.surface_tabs), {
          active_tab: tabId,
        }),
      })
      if (tabId === 'history') {
        syncHistoryPreview()
      }
      render()
    },
  }

  function initializeBridge() {
    ensureRuntimeStyles()
    bindRootEvents()
    if (!window.qt || !window.qt.webChannelTransport || !window.QWebChannel) {
      render()
      return
    }
    new window.QWebChannel(window.qt.webChannelTransport, function (channel) {
      bridge = channel.objects && channel.objects.simulationBridge ? channel.objects.simulationBridge : null
      if (bridge && typeof bridge.markReady === 'function') {
        bridge.markReady()
      }
      render()
    })
  }

  initializeBridge()
})()
