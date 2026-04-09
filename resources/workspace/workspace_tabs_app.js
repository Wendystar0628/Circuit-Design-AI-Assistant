(function () {
  const rootEl = document.getElementById('tabs-root');
  const emptyStateEl = document.getElementById('empty-state');

  const state = {
    items: [],
    emptyMessage: '',
  };

  let bridge = null;

  function invokeBridge(methodName, ...args) {
    if (!bridge || typeof bridge[methodName] !== 'function') {
      return;
    }
    bridge[methodName](...args);
  }

  function render() {
    rootEl.querySelectorAll('.tab-chip').forEach((item) => item.remove());
    const items = Array.isArray(state.items) ? state.items : [];
    if (!items.length) {
      emptyStateEl.style.display = 'flex';
      emptyStateEl.textContent = state.emptyMessage || '';
      return;
    }

    emptyStateEl.style.display = 'none';
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

      const indicatorsEl = document.createElement('div');
      indicatorsEl.className = 'tab-indicators';

      const openDot = document.createElement('span');
      openDot.className = `state-dot${item && item.isActive ? ' active' : ''}`;
      indicatorsEl.appendChild(openDot);

      if (item && item.isDirty) {
        const dirtyDot = document.createElement('span');
        dirtyDot.className = 'state-dot dirty';
        indicatorsEl.appendChild(dirtyDot);
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
      indicatorsEl.appendChild(closeBtn);

      chip.appendChild(indicatorsEl);
      rootEl.appendChild(chip);
    }
  }

  window.workspaceTabsApp = {
    setState(nextState) {
      const incoming = nextState && typeof nextState === 'object' ? nextState : {};
      state.items = Array.isArray(incoming.items) ? incoming.items : [];
      state.emptyMessage = incoming.emptyMessage || '';
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
