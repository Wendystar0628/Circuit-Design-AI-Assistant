(function () {
  const titleEl = document.getElementById('title');
  const collapseAllBtn = document.getElementById('collapse-all');
  const refreshBtn = document.getElementById('refresh-tree');
  const treeRootEl = document.getElementById('tree-root');
  const emptyStateEl = document.getElementById('empty-state');

  const state = {
    title: 'EXPLORER',
    emptyMessage: '',
    collapseTooltip: 'Collapse All',
    refreshTooltip: 'Refresh',
    iconSpriteUrl: '',
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

  function createTreePrefix(ancestorLines, hasNextSibling) {
    const prefix = document.createElement('div');
    prefix.className = 'tree-prefix';

    for (const continueLine of ancestorLines) {
      const slot = document.createElement('div');
      slot.className = `guide-slot${continueLine ? ' line' : ''}`;
      prefix.appendChild(slot);
    }

    const currentSlot = document.createElement('div');
    currentSlot.className = `guide-slot ${hasNextSibling ? 'branch' : 'tail'}`;
    prefix.appendChild(currentSlot);
    return prefix;
  }

  function createTreeIcon(node, isExpanded) {
    const iconEl = document.createElement('div');
    const iconName = node && node.isDirectory
      ? (isExpanded
        ? String(node.openIconName || node.iconName || 'folder-open')
        : String(node.iconName || 'folder'))
      : String((isExpanded ? node.openIconName : node.iconName) || node.iconName || 'file');
    iconEl.className = 'tree-icon';

    const iconSvgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    iconSvgEl.setAttribute('viewBox', '0 0 24 24');
    iconSvgEl.setAttribute('aria-hidden', 'true');
    const useEl = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    const spriteUrl = String(state.iconSpriteUrl || '');
    useEl.setAttribute('href', `${spriteUrl}#${iconName}`);
    useEl.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', `${spriteUrl}#${iconName}`);
    iconSvgEl.appendChild(useEl);
    iconEl.appendChild(iconSvgEl);
    return iconEl;
  }

  function buildTreeNode(node, depth, ancestorLines, hasNextSibling) {
    const wrapper = document.createElement('div');
    wrapper.className = 'tree-node';

    const row = document.createElement('div');
    row.className = `tree-row${node.isDirectory ? ' directory' : ''}${node.isActive ? ' active' : ''}`;
    const titleParts = [];
    if (node.typeLabel) {
      titleParts.push(String(node.typeLabel));
    }
    if (node.path) {
      titleParts.push(String(node.path));
    }
    row.title = titleParts.join('\n');

    const disclosure = document.createElement('div');
    disclosure.className = `disclosure${node.isDirectory ? '' : ' placeholder'}`;
    const isExpanded = node.isDirectory && expandedPaths.has(String(node.path || ''));
    disclosure.textContent = node.isDirectory ? (isExpanded ? '▾' : '▸') : '';

    if (depth > 0) {
      row.appendChild(createTreePrefix(ancestorLines, hasNextSibling));
    }
    row.appendChild(disclosure);
    row.appendChild(createTreeIcon(node, isExpanded));

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
      const children = asArray(node.children);
      const nextAncestorLines = depth > 0 ? ancestorLines.concat(hasNextSibling) : ancestorLines;
      for (let index = 0; index < children.length; index += 1) {
        childrenEl.appendChild(
          buildTreeNode(
            children[index],
            depth + 1,
            nextAncestorLines,
            index < children.length - 1
          )
        );
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
    for (let index = 0; index < nodes.length; index += 1) {
      treeRootEl.appendChild(buildTreeNode(nodes[index], 0, [], index < nodes.length - 1));
    }
  }

  function render() {
    titleEl.textContent = state.title || 'EXPLORER';
    collapseAllBtn.title = state.collapseTooltip || 'Collapse All';
    refreshBtn.title = state.refreshTooltip || 'Refresh';
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
      state.collapseTooltip = incoming.collapseTooltip || 'Collapse All';
      state.refreshTooltip = incoming.refreshTooltip || 'Refresh';
      state.iconSpriteUrl = incoming.iconSpriteUrl || '';
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
