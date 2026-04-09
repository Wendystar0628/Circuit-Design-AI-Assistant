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
    tree: [],
  };

  const expandedPaths = new Set();
  let bridge = null;

  function fileBadgeSvg(label, fontSize) {
    return `
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M14 2v6h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        <rect x="6" y="13.5" width="12" height="5" rx="1.6" fill="currentColor" opacity="0.14"/>
        <text x="12" y="17.25" text-anchor="middle" font-size="${fontSize}" font-family="Segoe UI, Arial, sans-serif" font-weight="700" fill="currentColor">${label}</text>
      </svg>
    `;
  }

  function iconSvg(iconKey) {
    const icons = {
      folder: `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M3 6.5A2.5 2.5 0 0 1 5.5 4H10l2.1 2.3H18.5A2.5 2.5 0 0 1 21 8.8V17.5A2.5 2.5 0 0 1 18.5 20H5.5A2.5 2.5 0 0 1 3 17.5V6.5Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      `,
      folderOpen: `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M3 8.2A2.2 2.2 0 0 1 5.2 6h4.1l1.7 1.8H18a2.2 2.2 0 0 1 2.14 1.7l.03.12.85 5.27A2.5 2.5 0 0 1 18.55 18H6.2a2.5 2.5 0 0 1-2.46-2.05L3 11.2V8.2Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      `,
      circuit: `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <rect x="4" y="4" width="16" height="16" rx="2.2" stroke="currentColor" stroke-width="1.8"/>
          <circle cx="9" cy="9" r="1" fill="currentColor"/>
          <circle cx="15" cy="9" r="1" fill="currentColor"/>
          <circle cx="9" cy="15" r="1" fill="currentColor"/>
          <circle cx="15" cy="15" r="1" fill="currentColor"/>
          <path d="M9 10.4V13.6M15 10.4V13.6M10.4 9H13.6M10.4 15H13.6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
      `,
      image: `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <rect x="3.5" y="4" width="17" height="16" rx="2.2" stroke="currentColor" stroke-width="1.8"/>
          <circle cx="8.5" cy="9" r="1.6" fill="currentColor"/>
          <path d="M5.5 17 10.3 12.6a1 1 0 0 1 1.34 0L14.2 15l2.46-2.25a1 1 0 0 1 1.36.02L20.5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      `,
      file: `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M14 2v6h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      `,
      text: fileBadgeSvg('TXT', 5.6),
      code: `
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M14 2v6h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="m9.2 14.7-2.2-2.2 2.2-2.2M14.8 10.3l2.2 2.2-2.2 2.2M13.3 9.6l-2.6 5.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      `,
      python: fileBadgeSvg('PY', 6.1),
      json: fileBadgeSvg('JSN', 5.2),
      markdown: fileBadgeSvg('MD', 6.1),
      javascript: fileBadgeSvg('JS', 6.1),
      typescript: fileBadgeSvg('TS', 6.1),
      html: fileBadgeSvg('HT', 6.1),
      css: fileBadgeSvg('CSS', 5.2),
      xml: fileBadgeSvg('XML', 5.0),
      config: fileBadgeSvg('CFG', 5.0),
      word: fileBadgeSvg('DOC', 5.0),
      pdf: fileBadgeSvg('PDF', 5.2),
      table: fileBadgeSvg('CSV', 5.0),
      diff: fileBadgeSvg('DIF', 5.0),
    };
    return icons[iconKey] || icons.file;
  }

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
    const tone = node && node.iconTone ? String(node.iconTone) : 'file';
    const iconKey = node && node.isDirectory
      ? (isExpanded ? 'folderOpen' : 'folder')
      : (node && node.iconKey ? String(node.iconKey) : 'file');
    iconEl.className = `tree-icon tone-${tone}`;
    iconEl.innerHTML = iconSvg(iconKey);
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
