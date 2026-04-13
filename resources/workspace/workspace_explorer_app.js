(function () {
  const titleEl = document.getElementById('title');
  const collapseAllBtn = document.getElementById('collapse-all');
  const refreshBtn = document.getElementById('refresh-tree');
  const treeScrollEl = document.getElementById('tree-scroll');
  const treeRootEl = document.getElementById('tree-root');
  const emptyStateEl = document.getElementById('empty-state');
  const contextMenuEl = document.getElementById('context-menu');
  const contextMenuItemEls = Array.from(document.querySelectorAll('.context-menu-item'));

  const state = {
    title: 'EXPLORER',
    emptyMessage: '',
    collapseTooltip: 'Collapse All',
    refreshTooltip: 'Refresh',
    contextMenu: {
      addToConversation: 'Add to Conversation',
      copyPath: 'Copy Path',
      rename: 'Rename',
      delete: 'Delete',
    },
    iconSpriteUrl: '',
    tree: [],
  };

  const contextMenuState = {
    visible: false,
    path: '',
    x: 0,
    y: 0,
  };
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

  function hideContextMenu() {
    contextMenuState.visible = false;
    contextMenuState.path = '';
    if (!contextMenuEl) {
      return;
    }
    contextMenuEl.classList.remove('open');
    contextMenuEl.style.left = '0px';
    contextMenuEl.style.top = '0px';
  }

  function updateContextMenuLabels() {
    if (!contextMenuItemEls.length) {
      return;
    }
    const labels = state.contextMenu || {};
    for (const itemEl of contextMenuItemEls) {
      const action = String(itemEl.dataset.action || '');
      if (action === 'add_to_conversation') {
        itemEl.textContent = labels.addToConversation || 'Add to Conversation';
      } else if (action === 'copy_path') {
        itemEl.textContent = labels.copyPath || 'Copy Path';
      } else if (action === 'rename') {
        itemEl.textContent = labels.rename || 'Rename';
      } else if (action === 'delete_file') {
        itemEl.textContent = labels.delete || 'Delete';
      }
    }
  }

  function positionContextMenu() {
    if (!contextMenuEl || !contextMenuState.visible) {
      return;
    }
    const menuWidth = contextMenuEl.offsetWidth || 180;
    const menuHeight = contextMenuEl.offsetHeight || 140;
    const left = Math.min(contextMenuState.x, Math.max(8, window.innerWidth - menuWidth - 8));
    const top = Math.min(contextMenuState.y, Math.max(8, window.innerHeight - menuHeight - 8));
    contextMenuEl.style.left = `${Math.max(8, left)}px`;
    contextMenuEl.style.top = `${Math.max(8, top)}px`;
  }

  function showContextMenu(node, x, y) {
    if (!contextMenuEl || !node || node.isDirectory || !node.path) {
      hideContextMenu();
      return;
    }
    contextMenuState.visible = true;
    contextMenuState.path = String(node.path || '');
    contextMenuState.x = Number(x || 0);
    contextMenuState.y = Number(y || 0);
    updateContextMenuLabels();
    contextMenuEl.classList.add('open');
    requestAnimationFrame(positionContextMenu);
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
    const isExpanded = Boolean(node.isDirectory && node.isExpanded);
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
      hideContextMenu();
      if (node.isDirectory) {
        const path = String(node.path || '');
        if (!path) {
          return;
        }
        invokeBridge('setDirectoryExpanded', path, !isExpanded);
        return;
      }
      if (node.path) {
        invokeBridge('openFile', String(node.path));
      }
    });

    row.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!node.isDirectory && node.path) {
        showContextMenu(node, event.clientX, event.clientY);
        return;
      }
      hideContextMenu();
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
    hideContextMenu();
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
    updateContextMenuLabels();
    renderTree();
  }

  collapseAllBtn.addEventListener('click', () => {
    hideContextMenu();
    invokeBridge('collapseAllDirectories');
  });

  refreshBtn.addEventListener('click', () => {
    hideContextMenu();
    invokeBridge('requestRefresh');
  });

  if (treeScrollEl) {
    treeScrollEl.addEventListener('scroll', hideContextMenu, { passive: true });
  }

  if (contextMenuEl) {
    contextMenuEl.addEventListener('contextmenu', (event) => {
      event.preventDefault();
    });
  }

  for (const itemEl of contextMenuItemEls) {
    itemEl.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      const action = String(itemEl.dataset.action || '');
      const path = contextMenuState.path;
      hideContextMenu();
      if (action && path) {
        invokeBridge('triggerContextAction', action, path);
      }
    });
  }

  document.addEventListener('pointerdown', (event) => {
    if (!contextMenuState.visible) {
      return;
    }
    if (contextMenuEl && contextMenuEl.contains(event.target)) {
      return;
    }
    hideContextMenu();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      hideContextMenu();
    }
  });

  window.addEventListener('blur', hideContextMenu);
  window.addEventListener('resize', hideContextMenu);

  window.workspaceExplorerApp = {
    setState(nextState) {
      const incoming = nextState && typeof nextState === 'object' ? nextState : {};
      state.title = incoming.title || 'EXPLORER';
      state.emptyMessage = incoming.emptyMessage || '';
      state.collapseTooltip = incoming.collapseTooltip || 'Collapse All';
      state.refreshTooltip = incoming.refreshTooltip || 'Refresh';
      state.contextMenu = incoming.contextMenu && typeof incoming.contextMenu === 'object'
        ? {
            addToConversation: incoming.contextMenu.addToConversation || 'Add to Conversation',
            copyPath: incoming.contextMenu.copyPath || 'Copy Path',
            rename: incoming.contextMenu.rename || 'Rename',
            delete: incoming.contextMenu.delete || 'Delete',
          }
        : {
            addToConversation: 'Add to Conversation',
            copyPath: 'Copy Path',
            rename: 'Rename',
            delete: 'Delete',
          };
      state.iconSpriteUrl = incoming.iconSpriteUrl || '';
      state.tree = asArray(incoming.tree);
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
