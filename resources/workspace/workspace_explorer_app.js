(function () {
  const titleEl = document.getElementById('title');
  const collapseAllBtn = document.getElementById('collapse-all');
  const refreshBtn = document.getElementById('refresh-tree');
  const openFilesSection = document.getElementById('open-files-section');
  const openFilesTitleEl = document.getElementById('open-files-title');
  const openFilesListEl = document.getElementById('open-files-list');
  const treeRootEl = document.getElementById('tree-root');
  const emptyStateEl = document.getElementById('empty-state');

  const state = {
    title: 'EXPLORER',
    emptyMessage: '',
    openFilesTitle: 'OPEN FILES',
    collapseTooltip: 'Collapse All',
    refreshTooltip: 'Refresh',
    openFiles: [],
    tree: [],
  };

  const expandedPaths = new Set();
  let bridge = null;

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function invokeBridge(methodName, ...args) {
    if (!bridge || typeof bridge[methodName] !== 'function') {
      return;
    }
    bridge[methodName](...args);
  }

  function syncExpandedPaths(nodes) {
    function visit(node) {
      if (!node || typeof node !== 'object') {
        return false;
      }
      const children = asArray(node.children);
      const hasActiveDescendant = children.some((child) => visit(child));
      const shouldExpand = Boolean(node.defaultExpanded || node.isActive || hasActiveDescendant);
      if (node.isDirectory && shouldExpand && node.path) {
        expandedPaths.add(String(node.path));
      }
      return Boolean(node.isActive || hasActiveDescendant);
    }

    asArray(nodes).forEach((node) => visit(node));
  }

  function createStateIndicators(node) {
    const indicatorsEl = document.createElement('div');
    indicatorsEl.className = 'tree-indicators';

    if (node.isOpen) {
      const openDot = document.createElement('span');
      openDot.className = `state-dot${node.isActive ? ' active' : ''}`;
      indicatorsEl.appendChild(openDot);
    }

    if (node.isDirty) {
      const dirtyDot = document.createElement('span');
      dirtyDot.className = 'state-dot dirty';
      indicatorsEl.appendChild(dirtyDot);
    }

    return indicatorsEl;
  }

  function renderOpenFiles() {
    openFilesTitleEl.textContent = state.openFilesTitle || 'OPEN FILES';
    openFilesListEl.innerHTML = '';

    const items = asArray(state.openFiles);
    if (!items.length) {
      openFilesSection.style.display = 'none';
      return;
    }

    openFilesSection.style.display = 'flex';
    for (const item of items) {
      const row = document.createElement('div');
      row.className = `open-file-item${item && item.isActive ? ' active' : ''}`;
      row.title = item && item.path ? String(item.path) : '';
      row.addEventListener('click', () => {
        if (item && item.path) {
          invokeBridge('openFile', String(item.path));
        }
      });

      const nameEl = document.createElement('div');
      nameEl.className = 'open-file-name';
      nameEl.textContent = item && item.name ? String(item.name) : '';
      row.appendChild(nameEl);

      const badgesEl = document.createElement('div');
      badgesEl.className = 'state-badges';
      if (item && item.isOpen) {
        const openDot = document.createElement('span');
        openDot.className = `state-dot${item.isActive ? ' active' : ''}`;
        badgesEl.appendChild(openDot);
      }
      if (item && item.isDirty) {
        const dirtyDot = document.createElement('span');
        dirtyDot.className = 'state-dot dirty';
        badgesEl.appendChild(dirtyDot);
      }
      row.appendChild(badgesEl);

      openFilesListEl.appendChild(row);
    }
  }

  function buildTreeNode(node, depth) {
    const wrapper = document.createElement('div');
    wrapper.className = 'tree-node';

    const row = document.createElement('div');
    row.className = `tree-row${node.isDirectory ? ' directory' : ''}${node.isActive ? ' active' : ''}`;
    row.style.paddingLeft = `${8 + depth * 16}px`;
    row.title = node.path ? String(node.path) : '';

    const disclosure = document.createElement('div');
    disclosure.className = `disclosure${node.isDirectory ? '' : ' placeholder'}`;
    const isExpanded = node.isDirectory && expandedPaths.has(String(node.path || ''));
    disclosure.textContent = node.isDirectory ? (isExpanded ? '▾' : '▸') : '•';
    row.appendChild(disclosure);

    const label = document.createElement('div');
    label.className = 'tree-label';
    label.textContent = node.name ? String(node.name) : '';
    row.appendChild(label);

    row.appendChild(createStateIndicators(node));

    row.addEventListener('click', () => {
      if (node.isDirectory) {
        const path = String(node.path || '');
        if (!path) {
          return;
        }
        if (expandedPaths.has(path)) {
          expandedPaths.delete(path);
        } else {
          expandedPaths.add(path);
        }
        renderTree();
        return;
      }
      if (node.path) {
        invokeBridge('openFile', String(node.path));
      }
    });

    wrapper.appendChild(row);

    if (node.isDirectory && isExpanded) {
      const childrenEl = document.createElement('div');
      childrenEl.className = 'tree-children';
      for (const child of asArray(node.children)) {
        childrenEl.appendChild(buildTreeNode(child, depth + 1));
      }
      wrapper.appendChild(childrenEl);
    }

    return wrapper;
  }

  function renderTree() {
    treeRootEl.innerHTML = '';
    const nodes = asArray(state.tree);
    if (!nodes.length) {
      emptyStateEl.style.display = 'flex';
      emptyStateEl.textContent = state.emptyMessage || '';
      return;
    }

    emptyStateEl.style.display = 'none';
    for (const node of nodes) {
      treeRootEl.appendChild(buildTreeNode(node, 0));
    }
  }

  function render() {
    titleEl.textContent = state.title || 'EXPLORER';
    collapseAllBtn.title = state.collapseTooltip || 'Collapse All';
    refreshBtn.title = state.refreshTooltip || 'Refresh';
    renderOpenFiles();
    renderTree();
  }

  collapseAllBtn.addEventListener('click', () => {
    expandedPaths.clear();
    renderTree();
  });

  refreshBtn.addEventListener('click', () => {
    invokeBridge('requestRefresh');
  });

  window.workspaceExplorerApp = {
    setState(nextState) {
      const incoming = nextState && typeof nextState === 'object' ? nextState : {};
      state.title = incoming.title || 'EXPLORER';
      state.emptyMessage = incoming.emptyMessage || '';
      state.openFilesTitle = incoming.openFilesTitle || 'OPEN FILES';
      state.collapseTooltip = incoming.collapseTooltip || 'Collapse All';
      state.refreshTooltip = incoming.refreshTooltip || 'Refresh';
      state.openFiles = asArray(incoming.openFiles);
      state.tree = asArray(incoming.tree);
      syncExpandedPaths(state.tree);
      render();
    },
  };

  if (window.QWebChannel && window.qt && window.qt.webChannelTransport) {
    new QWebChannel(window.qt.webChannelTransport, function (channel) {
      bridge = channel.objects.workspaceExplorerBridge || null;
      if (bridge && typeof bridge.markReady === 'function') {
        bridge.markReady();
      }
      render();
    });
  } else {
    render();
  }
})();
