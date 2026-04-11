(function () {
  const rootEl = document.getElementById('simulation-root')
  let bridge = null
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
    },
    op_result_view: {
      is_available: false,
      row_count: 0,
    },
  }

  function safeObject(value) {
    return value && typeof value === 'object' ? value : {}
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
    const availableTabs = Array.isArray(surfaceTabs.available_tabs) ? surfaceTabs.available_tabs : []
    const activeTab = surfaceTabs.active_tab || 'metrics'
    return availableTabs.map((tabId) => {
      const activeClass = tabId === activeTab ? ' active' : ''
      return '<button class="tab-chip' + activeClass + '" data-tab-id="' + escapeHtml(tabId) + '">' + escapeHtml(tabId) + '</button>'
    }).join('')
  }

  function renderHistory() {
    const historyView = safeObject(state.history_results_view)
    const items = Array.isArray(historyView.items) ? historyView.items : []
    if (!items.length) {
      return '<div class="history-item"><div class="history-item__title">暂无历史结果</div></div>'
    }
    return items.map((item) => {
      const resultPath = item && item.result_path ? String(item.result_path) : ''
      return [
        '<div class="history-item">',
        '  <div class="history-item__meta">',
        '    <div class="history-item__title">' + escapeHtml(item.file_name || '未命名结果') + '</div>',
        '    <div class="history-item__sub">' + escapeHtml((item.analysis_type || '') + (item.timestamp ? ' · ' + item.timestamp : '')) + '</div>',
        '  </div>',
        '  <button class="history-item__action" data-result-path="' + escapeHtml(resultPath) + '">加载</button>',
        '</div>',
      ].join('')
    }).join('')
  }

  function render() {
    if (!rootEl) {
      return
    }
    const runtime = safeObject(state.simulation_runtime)
    const metricsView = safeObject(state.metrics_view)
    const waveformView = safeObject(state.waveform_view)
    const currentResult = safeObject(runtime.current_result)

    rootEl.innerHTML = [
      '<div class="shell">',
      '  <div class="tab-row">' + renderTabs() + '</div>',
      '  <div class="status-row">',
      '    <div class="card"><div class="card__label">状态</div><div class="card__value">' + escapeHtml(runtime.status_message || runtime.status || 'idle') + '</div></div>',
      '    <div class="card"><div class="card__label">结果</div><div class="card__value">' + escapeHtml(currentResult.file_name || '暂无结果') + '</div></div>',
      '    <div class="card"><div class="card__label">分析</div><div class="card__value">' + escapeHtml(currentResult.analysis_label || '未加载') + '</div></div>',
      '  </div>',
      '  <div class="content">',
      '    <div class="panel">',
      '      <div class="panel__header"><div class="panel__title">Phase 1 React/Fallback Host</div></div>',
      '      <div class="panel__body"><pre>' + escapeHtml('metrics=' + String(metricsView.total || 0) + '\nwaveformSignals=' + String(waveformView.signal_count || 0)) + '</pre></div>',
      '    </div>',
      '    <div class="panel">',
      '      <div class="panel__header"><div class="panel__title">历史结果</div></div>',
      '      <div class="panel__body"><div class="history-list">' + renderHistory() + '</div></div>',
      '    </div>',
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

    rootEl.querySelectorAll('[data-result-path]').forEach((element) => {
      element.addEventListener('click', function () {
        const resultPath = this.getAttribute('data-result-path')
        if (bridge && resultPath && typeof bridge.loadHistoryResult === 'function') {
          bridge.loadHistoryResult(resultPath)
        }
      })
    })
  }

  window.simulationApp = {
    setState(nextState) {
      state = safeObject(nextState)
      render()
    },
    activateTab(tabId) {
      state = Object.assign({}, state, {
        surface_tabs: Object.assign({}, safeObject(state.surface_tabs), {
          active_tab: tabId,
        }),
      })
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
