(function () {
  const rootEl = document.getElementById('simulation-root')
  let bridge = null
  let historyPreviewResultPath = ''
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
    },
    waveform_view: {
      signal_count: 0,
    },
    history_results_view: {
      items: [],
      selected_result_path: '',
    },
    op_result_view: {
      is_available: false,
      file_name: '',
      analysis_command: '',
      row_count: 0,
      section_count: 0,
      sections: [],
      can_add_to_conversation: false,
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

  function renderTabs() {
    const surfaceTabs = safeObject(state.surface_tabs)
    const availableTabs = safeArray(surfaceTabs.available_tabs)
    const activeTab = surfaceTabs.active_tab || 'metrics'
    return availableTabs.map((tabId) => {
      const activeClass = tabId === activeTab ? ' active' : ''
      const label = TAB_LABELS[tabId] || tabId
      return '<button class="tab-chip' + activeClass + '" data-tab-id="' + escapeHtml(tabId) + '">' + escapeHtml(label) + '</button>'
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
        '  <div class="card__value">局部动作暂时可能不可用，但当前 tab-first 壳仍会持续接收状态。</div>',
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
        '  <div class="card__value">' + escapeHtml(runtime.has_project ? '运行一次仿真后，当前 tab 会显示对应结果。' : '请先打开项目并运行仿真。') + '</div>',
        surfaceTabs.has_history ? '  <div class="state-actions"><button class="action-btn" data-tab-id="history">转到历史结果</button></div>' : '',
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

  function renderMetricsTab() {
    const runtime = safeObject(state.simulation_runtime)
    const currentResult = safeObject(runtime.current_result)
    const metricsView = safeObject(state.metrics_view)
    const items = safeArray(metricsView.items)
    const summaryCards = [
      ['综合评分', metricsView.has_goals ? Number(metricsView.overall_score || 0).toFixed(1) : '无目标模式'],
      ['结果文件', currentResult.file_name || '暂无结果'],
      ['分析类型', currentResult.analysis_label || '未加载'],
    ].map((item) => '<div class="metric-card"><div class="metric-card__title">' + escapeHtml(item[0]) + '</div><div class="metric-card__value">' + escapeHtml(item[1]) + '</div></div>').join('')
    const metricsCards = items.length ? items.map((item) => [
      '<div class="metric-card">',
      '  <div class="metric-card__header"><span class="metric-card__title">' + escapeHtml(item.display_name || item.name || 'metric') + '</span><span class="muted-text">' + escapeHtml(item.category || 'metric') + '</span></div>',
      '  <div class="metric-card__value">' + escapeHtml(item.value || '--') + '</div>',
      '  <div class="muted-text">目标：' + escapeHtml(item.target || '未定义') + '</div>',
      '</div>',
    ].join('')) : '<div class="metric-card"><div class="metric-card__title">暂无指标</div><div class="muted-text">指标区已切到 tab-local 布局。</div></div>'
    return [
      renderToolbar('指标', '局部动作区 + 指标卡区域 + 分组指标区', '<button class="action-btn action-btn--primary" data-add-target="metrics"' + (metricsView.can_add_to_conversation ? '' : ' disabled') + '>添加至对话</button>'),
      '<div class="content-card scrollable">',
      '  <div class="summary-grid">' + summaryCards + '</div>',
      '  <div class="metrics-grid">' + metricsCards + '</div>',
      '</div>',
    ].join('')
  }

  function renderSimpleTab(title, description, bodyHtml, actionsHtml) {
    return [
      renderToolbar(title, description, actionsHtml),
      '<div class="content-card">' + bodyHtml + '</div>',
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
        '<button class="history-item history-item--button' + activeClass + '" data-history-preview="' + escapeHtml(resultPath) + '">',
        '  <div class="history-item__meta">',
        '    <div class="history-item__title">' + escapeHtml(item.file_name || '未命名结果') + '</div>',
        '    <div class="history-item__sub">' + escapeHtml((item.analysis_type || '') + (item.timestamp ? ' · ' + item.timestamp : '')) + '</div>',
        '  </div>',
        item.is_current ? '  <span class="muted-text">当前</span>' : '  <span class="muted-text">预览</span>',
        '</button>',
      ].join('')
    }).join('') : '<div class="history-item"><div class="history-item__title">暂无历史结果</div></div>'
    return [
      renderToolbar('历史结果', '筛选/排序区 + 列表区 + 当前选中项预览/加载区；作为 peer tab 存在。'),
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
      '      <button class="action-btn action-btn--primary" data-load-history="' + escapeHtml(selectedItem && selectedItem.result_path || '') + '"' + (selectedItem && selectedItem.can_load ? '' : ' disabled') + '>加载选中结果</button>',
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
      renderToolbar('工作点结果', '局部动作区 + 结构化结果表；条件性 peer tab。', '<button class="action-btn action-btn--primary" data-add-target="op_result"' + (opView.can_add_to_conversation ? '' : ' disabled') + '>添加至对话</button>'),
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

  function renderActiveTab() {
    const activeTab = safeObject(state.surface_tabs).active_tab || 'metrics'
    const waveformView = safeObject(state.waveform_view)
    const rawDataView = safeObject(state.raw_data_view)
    const outputLogView = safeObject(state.output_log_view)
    const analysisInfoView = safeObject(state.analysis_info_view)
    const exportView = safeObject(state.export_view)
    switch (activeTab) {
      case 'history':
        return renderHistoryTab()
      case 'op_result':
        return renderOpResultTab()
      case 'waveform':
        return renderSimpleTab('波形', '低高度工具栏 + 信号浏览区 / 画布区 + 低高度测量栏', '<div class="stage"><div class="card__label">波形画布区</div><div class="card__value">已发现信号：' + escapeHtml(String(waveformView.signal_count || 0)) + '</div></div>', '<button class="action-btn" data-bridge-action="fit">Fit</button><button class="action-btn" data-bridge-action="clear-signals">清空信号</button><button class="action-btn action-btn--primary" data-add-target="waveform"' + (waveformView.can_add_to_conversation ? '' : ' disabled') + '>添加至对话</button>')
      case 'analysis_info':
        return renderSimpleTab('分析信息', '分析类型 / 参数 / X 轴信息', '<div class="info-grid"><div class="info-row"><div class="card__label">分析类型</div><div class="card__value">' + escapeHtml(analysisInfoView.analysis_type || '') + '</div></div><div class="info-row"><div class="card__label">命令</div><div class="card__value">' + escapeHtml(analysisInfoView.analysis_command || '') + '</div></div><div class="info-row"><div class="card__label">X 轴标签</div><div class="card__value">' + escapeHtml(analysisInfoView.x_axis_label || '') + '</div></div><div class="info-row"><div class="card__label">X 轴刻度</div><div class="card__value">' + escapeHtml(analysisInfoView.x_axis_scale || '') + '</div></div></div>')
      case 'raw_data':
        return renderSimpleTab('原始数据', '局部工具栏 + 大表格区，并保持独立滚动。', '<div class="stage stage--scrollable"><div class="card__label">大表格区</div><div class="card__value">总行数：' + escapeHtml(String(rawDataView.row_count || 0)) + '</div><div class="muted-text">X 轴标签：' + escapeHtml(rawDataView.x_axis_label || '未定义') + '，信号列数：' + escapeHtml(String(rawDataView.signal_count || 0)) + '</div></div>', '<button class="action-btn" data-bridge-action="raw-first-row">跳到首行</button><button class="action-btn" data-bridge-action="raw-jump-x">按 X 跳转</button><button class="action-btn" data-bridge-action="raw-search">按值搜索</button>')
      case 'output_log':
        return renderSimpleTab('输出日志', '搜索/过滤/跳错工具栏 + 日志区，并保持独立滚动。', '<div class="info-grid"><div class="info-row"><div class="card__label">日志行数</div><div class="card__value">' + escapeHtml(String(outputLogView.line_count || 0)) + '</div></div><div class="info-row"><div class="card__label">允许局部刷新</div><div class="card__value">' + escapeHtml(outputLogView.can_refresh ? '是' : '否') + '</div></div></div><div class="stage stage--scrollable"><div class="card__label">日志区</div><div class="muted-text">局部刷新保留在输出日志 tab 内。</div></div>', '<button class="action-btn" data-bridge-action="log-search-error">搜索 error</button><button class="action-btn" data-bridge-action="log-filter-error">过滤 error</button><button class="action-btn" data-bridge-action="log-jump-error">跳到错误</button><button class="action-btn" data-bridge-action="log-refresh"' + (outputLogView.can_refresh ? '' : ' disabled') + '>局部刷新</button><button class="action-btn action-btn--primary" data-add-target="output_log"' + (outputLogView.can_add_to_conversation ? '' : ' disabled') + '>添加至对话</button>')
      case 'export':
        return renderSimpleTab('导出', '局部导出动作区', '<div class="info-grid"><div class="info-row"><div class="card__label">最新项目导出目录</div><div class="card__value">' + escapeHtml(exportView.latest_project_export_root || '无') + '</div></div><div class="info-row"><div class="card__label">可导出类型</div><div class="card__value">' + escapeHtml(safeArray(exportView.available_types).join(', ') || '无') + '</div></div></div>', '<button class="action-btn action-btn--primary" data-bridge-action="export-all"' + (safeArray(exportView.available_types).length ? '' : ' disabled') + '>导出选中项</button>')
      case 'chart':
        return renderSimpleTab('图表', '图表 tab-first peer surface', '<div class="stage"><div class="card__label">图表画布区</div><div class="muted-text">当前保留为权威图表 surface 占位。</div></div>', '<button class="action-btn" data-bridge-action="export-charts">导出图表</button><button class="action-btn action-btn--primary" data-add-target="chart">添加至对话</button>')
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

    rootEl.querySelectorAll('[data-tab-id]').forEach((element) => {
      element.addEventListener('click', function () {
        const tabId = this.getAttribute('data-tab-id')
        if (bridge && tabId && typeof bridge.activateTab === 'function') {
          bridge.activateTab(tabId)
        }
      })
    })

    rootEl.querySelectorAll('[data-history-preview]').forEach((element) => {
      element.addEventListener('click', function () {
        historyPreviewResultPath = this.getAttribute('data-history-preview') || ''
        render()
      })
    })

    rootEl.querySelectorAll('[data-load-history]').forEach((element) => {
      element.addEventListener('click', function () {
        const resultPath = this.getAttribute('data-load-history')
        if (bridge && resultPath && typeof bridge.loadHistoryResult === 'function') {
          bridge.loadHistoryResult(resultPath)
        }
      })
    })

    rootEl.querySelectorAll('[data-add-target]').forEach((element) => {
      element.addEventListener('click', function () {
        const target = this.getAttribute('data-add-target')
        if (bridge && target && typeof bridge.addToConversation === 'function') {
          bridge.addToConversation(target)
        }
      })
    })

    rootEl.querySelectorAll('[data-bridge-action]').forEach((element) => {
      element.addEventListener('click', function () {
        const action = this.getAttribute('data-bridge-action')
        if (!bridge || !action) {
          return
        }
        if (action === 'fit' && typeof bridge.requestFit === 'function') {
          bridge.requestFit()
        }
        if (action === 'clear-signals' && typeof bridge.clearAllSignals === 'function') {
          bridge.clearAllSignals()
        }
        if (action === 'raw-first-row' && typeof bridge.jumpRawDataToRow === 'function') {
          bridge.jumpRawDataToRow(0)
        }
        if (action === 'raw-jump-x' && typeof bridge.jumpRawDataToX === 'function') {
          bridge.jumpRawDataToX(0)
        }
        if (action === 'raw-search' && typeof bridge.searchRawDataValue === 'function') {
          bridge.searchRawDataValue(0, 0, 0)
        }
        if (action === 'log-search-error' && typeof bridge.searchOutputLog === 'function') {
          bridge.searchOutputLog('error')
        }
        if (action === 'log-filter-error' && typeof bridge.filterOutputLog === 'function') {
          bridge.filterOutputLog('error')
        }
        if (action === 'log-jump-error' && typeof bridge.jumpToOutputLogError === 'function') {
          bridge.jumpToOutputLogError()
        }
        if (action === 'log-refresh' && typeof bridge.refreshOutputLog === 'function') {
          bridge.refreshOutputLog()
        }
        if (action === 'export-charts' && typeof bridge.requestExport === 'function') {
          bridge.requestExport(['charts'])
        }
        if (action === 'export-all' && typeof bridge.requestExport === 'function') {
          bridge.requestExport(safeArray(safeObject(state.export_view).available_types))
        }
      })
    })
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
