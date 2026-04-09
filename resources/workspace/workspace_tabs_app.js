(function () {
  const rootEl = document.getElementById('tabs-root');
  const emptyStateEl = document.getElementById('empty-state');
  const actionsEl = document.getElementById('tabs-actions');

  const state = {
    items: [],
    emptyMessage: '',
    runIconUrl: '',
    stopIconUrl: '',
    simulationControl: {
      isRunning: false,
      isStopRequested: false,
      canRun: false,
      canStop: false,
      primaryAction: 'run',
      primaryEnabled: false,
      primaryTooltip: '',
    },
  };

  let bridge = null;

  function invokeBridge(methodName, ...args) {
    if (!bridge || typeof bridge[methodName] !== 'function') {
      return;
    }
    bridge[methodName](...args);
  }

  function scrollActiveTabIntoView() {
    const activeChip = rootEl.querySelector('.tab-chip.active');
    if (!activeChip) {
      return;
    }
    activeChip.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  function render() {
    rootEl.querySelectorAll('.tab-chip').forEach((item) => item.remove());
    actionsEl.replaceChildren();
    const items = Array.isArray(state.items) ? state.items : [];
    if (!items.length) {
      emptyStateEl.style.display = 'flex';
      emptyStateEl.textContent = state.emptyMessage || '';
    } else {
      emptyStateEl.style.display = 'none';
    }

    for (const item of items) {
      const chip = document.createElement('div');
      chip.className = `tab-chip${item && item.isActive ? ' active' : ''}`;
      chip.title = item && item.path ? String(item.path) : '';
      chip.addEventListener('click', () => {
        if (item && item.path) {
          invokeBridge('activateFile', String(item.path));
        }
      });

      const nameEl = document.createElement('div');
      nameEl.className = 'tab-name';
      nameEl.textContent = item && item.name ? String(item.name) : '';
      chip.appendChild(nameEl);

      const metaEl = document.createElement('div');
      metaEl.className = 'tab-meta';

      if (item && item.isDirty) {
        const dirtyDot = document.createElement('span');
        dirtyDot.className = 'dirty-dot';
        metaEl.appendChild(dirtyDot);
      }

      const closeBtn = document.createElement('button');
      closeBtn.className = 'close-btn';
      closeBtn.type = 'button';
      closeBtn.textContent = '×';
      closeBtn.title = 'Close';
      closeBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        if (item && item.path) {
          invokeBridge('closeFile', String(item.path));
        }
      });
      metaEl.appendChild(closeBtn);

      chip.appendChild(metaEl);
      rootEl.appendChild(chip);
    }

    const simulationControl = state.simulationControl && typeof state.simulationControl === 'object'
      ? state.simulationControl
      : {};
    const primaryAction = simulationControl.primaryAction === 'stop' ? 'stop' : 'run';
    const primaryBtn = document.createElement('button');
    primaryBtn.className = 'simulation-btn';
    primaryBtn.type = 'button';
    primaryBtn.disabled = !simulationControl.primaryEnabled;
    primaryBtn.title = simulationControl.primaryTooltip || '';
    primaryBtn.setAttribute('aria-label', simulationControl.primaryTooltip || primaryAction);
    primaryBtn.addEventListener('click', () => {
      if (primaryBtn.disabled) {
        return;
      }
      invokeBridge(primaryAction === 'stop' ? 'stopSimulation' : 'runSimulation');
    });

    const iconEl = document.createElement('img');
    iconEl.alt = '';
    iconEl.src = primaryAction === 'stop' ? state.stopIconUrl : state.runIconUrl;
    primaryBtn.appendChild(iconEl);
    actionsEl.appendChild(primaryBtn);

    requestAnimationFrame(scrollActiveTabIntoView);
  }

  rootEl.addEventListener('wheel', (event) => {
    const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
    if (!delta || rootEl.scrollWidth <= rootEl.clientWidth) {
      return;
    }
    event.preventDefault();
    rootEl.scrollLeft += delta;
  }, { passive: false });

  window.workspaceTabsApp = {
    setState(nextState) {
      const incoming = nextState && typeof nextState === 'object' ? nextState : {};
      state.items = Array.isArray(incoming.items) ? incoming.items : [];
      state.emptyMessage = incoming.emptyMessage || '';
      state.runIconUrl = incoming.runIconUrl || '';
      state.stopIconUrl = incoming.stopIconUrl || '';
      state.simulationControl = incoming.simulationControl && typeof incoming.simulationControl === 'object'
        ? incoming.simulationControl
        : {
            isRunning: false,
            isStopRequested: false,
            canRun: false,
            canStop: false,
            primaryAction: 'run',
            primaryEnabled: false,
            primaryTooltip: '',
          };
      render();
    },
  };

  if (window.QWebChannel && window.qt && window.qt.webChannelTransport) {
    new QWebChannel(window.qt.webChannelTransport, function (channel) {
      bridge = channel.objects.workspaceTabsBridge || null;
      if (bridge && typeof bridge.markReady === 'function') {
        bridge.markReady();
      }
      render();
    });
  } else {
    render();
  }
})();
