(() => {
  const root = document.getElementById('root');
  const PANEL_GAP = 8;
  const PANEL_WIDTH = 280;
  const EDGE_PADDING = 8;

  let bridge = null;
  let state = {
    menu: null,
    anchorLeft: 0,
    anchorWidth: 0,
    viewportWidth: 0,
    viewportHeight: 0,
  };
  let openSubmenuPath = [];

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function normalizeState(nextState) {
    return {
      menu: nextState && typeof nextState.menu === 'object' ? nextState.menu : null,
      anchorLeft: Math.max(0, Number.parseInt((nextState && nextState.anchorLeft) || 0, 10) || 0),
      anchorWidth: Math.max(0, Number.parseInt((nextState && nextState.anchorWidth) || 0, 10) || 0),
      viewportWidth: Math.max(0, Number.parseInt((nextState && nextState.viewportWidth) || 0, 10) || 0),
      viewportHeight: Math.max(0, Number.parseInt((nextState && nextState.viewportHeight) || 0, 10) || 0),
    };
  }

  function invokeBridge(methodName, ...args) {
    if (!bridge || typeof bridge[methodName] !== 'function') {
      return;
    }
    bridge[methodName](...args);
  }

  function pathKey(parts) {
    return asArray(parts).join('/');
  }

  function isSubmenuItem(item) {
    const children = item && item.children;
    return Array.isArray(children) && children.length > 0;
  }

  function menuContentItems(items) {
    return asArray(items).filter((item) => item && typeof item === 'object' && String(item.type || 'action') !== 'separator');
  }

  function computePanelLeft(preferredLeft, panelWidth, viewportWidth) {
    const safeViewportWidth = Math.max(viewportWidth || 0, panelWidth + EDGE_PADDING * 2);
    const maxLeft = Math.max(EDGE_PADDING, safeViewportWidth - panelWidth - EDGE_PADDING);
    return Math.max(EDGE_PADDING, Math.min(preferredLeft, maxLeft));
  }

  function computePrimaryLeft() {
    const preferredLeft = state.anchorLeft;
    return computePanelLeft(preferredLeft, PANEL_WIDTH, state.viewportWidth);
  }

  function makePanel(items, left, top) {
    const panel = document.createElement('div');
    panel.className = 'menu-panel';
    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
    panel.style.width = `${PANEL_WIDTH}px`;
    let interactiveIndex = 0;
    asArray(items).forEach((item, index) => {
      if (!item || typeof item !== 'object') {
        return;
      }
      if (String(item.type || 'action') === 'separator') {
        const separator = document.createElement('div');
        separator.className = 'menu-separator';
        panel.appendChild(separator);
        return;
      }

      const row = document.createElement('div');
      row.className = 'menu-item';
      const enabled = item.enabled !== false;
      const hasChildren = isSubmenuItem(item);
      const itemId = String(item.id || `row-${index}`);
      row.dataset.itemIndex = String(interactiveIndex);
      interactiveIndex += 1;
      if (!enabled) {
        row.classList.add('disabled');
      }

      const indicator = document.createElement('div');
      indicator.className = 'menu-indicator';
      indicator.textContent = item.checkable && item.checked ? '✓' : '';
      row.appendChild(indicator);

      const label = document.createElement('div');
      label.className = 'menu-label';
      label.textContent = String(item.label || '');
      row.appendChild(label);

      const shortcut = document.createElement('div');
      shortcut.className = 'menu-shortcut';
      shortcut.textContent = String(item.shortcut || '');
      row.appendChild(shortcut);

      const arrow = document.createElement('div');
      arrow.className = 'menu-arrow';
      arrow.textContent = hasChildren ? '›' : '';
      row.appendChild(arrow);

      if (hasChildren) {
        row.dataset.submenuId = itemId;
      }

      panel.appendChild(row);
    });
    return panel;
  }

  function menuItemsForPath(rootItems, panelPath) {
    if (!panelPath.length) {
      return asArray(rootItems);
    }
    let currentItems = asArray(rootItems);
    for (const part of panelPath) {
      const item = currentItems.find((candidate) => String((candidate && candidate.id) || '') === String(part || ''));
      currentItems = item && Array.isArray(item.children) ? item.children : [];
    }
    return asArray(currentItems);
  }

  function renderPanels(menu) {
    const primaryTop = PANEL_GAP;
    const primaryLeft = computePrimaryLeft();
    const primaryPanel = makePanel(menu.items, primaryLeft, primaryTop);
    root.appendChild(primaryPanel);

    let panels = [{ element: primaryPanel, path: [] }];
    let nextItems = asArray(menu.items);
    let parentPanel = primaryPanel;

    for (let depth = 0; depth < openSubmenuPath.length; depth += 1) {
      const targetId = String(openSubmenuPath[depth] || '');
      const targetItem = nextItems.find((item) => String((item && item.id) || '') === targetId && isSubmenuItem(item));
      if (!targetItem) {
        openSubmenuPath = openSubmenuPath.slice(0, depth);
        break;
      }
      const row = parentPanel.querySelector(`[data-submenu-id="${CSS.escape(targetId)}"]`);
      if (!row) {
        openSubmenuPath = openSubmenuPath.slice(0, depth);
        break;
      }
      row.classList.add('open');
      const parentLeft = parseFloat(parentPanel.style.left || '0');
      const parentTop = parseFloat(parentPanel.style.top || '0');
      const childPreferredLeft = parentLeft + PANEL_WIDTH + PANEL_GAP;
      const childLeft = childPreferredLeft + PANEL_WIDTH + EDGE_PADDING <= state.viewportWidth
        ? childPreferredLeft
        : computePanelLeft(parentLeft - PANEL_WIDTH - PANEL_GAP, PANEL_WIDTH, state.viewportWidth);
      const childTop = Math.max(PANEL_GAP, parentTop + row.offsetTop - 6);
      const childPanel = makePanel(targetItem.children, childLeft, childTop);
      root.appendChild(childPanel);
      panels.push({ element: childPanel, path: openSubmenuPath.slice(0, depth + 1) });
      parentPanel = childPanel;
      nextItems = asArray(targetItem.children);
    }

    panels.forEach((entry) => {
      const panelPath = asArray(entry.path);
      const items = menuItemsForPath(menu.items, panelPath);
      const interactiveItems = menuContentItems(items);
      const rows = Array.from(entry.element.querySelectorAll('.menu-item'));
      rows.forEach((row, index) => {
        const itemIndex = Number.parseInt(row.dataset.itemIndex || '', 10);
        const item = Number.isNaN(itemIndex) ? null : interactiveItems[itemIndex] || null;
        if (!item || typeof item !== 'object' || String(item.type || 'action') === 'separator') {
          return;
        }
        const enabled = item.enabled !== false;
        const hasChildren = isSubmenuItem(item);
        const nextPath = panelPath.concat(String(item.id || `item-${index}`));
        row.addEventListener('mouseenter', () => {
          if (hasChildren) {
            const changed = pathKey(openSubmenuPath.slice(0, nextPath.length)) !== pathKey(nextPath);
            if (changed) {
              openSubmenuPath = nextPath;
              render();
            }
            return;
          }
          if (pathKey(openSubmenuPath) !== pathKey(panelPath)) {
            openSubmenuPath = panelPath;
            render();
          }
        });
        row.addEventListener('click', (event) => {
          event.stopPropagation();
          if (!enabled) {
            return;
          }
          if (hasChildren) {
            openSubmenuPath = nextPath;
            render();
            return;
          }
          invokeBridge('triggerAction', String(item.id || ''));
        });
      });
    });
  }

  function render() {
    if (!root) {
      return;
    }
    root.innerHTML = '';
    if (!state.menu || typeof state.menu !== 'object') {
      return;
    }
    renderPanels(state.menu);
  }

  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      invokeBridge('dismiss');
    }
  });

  document.addEventListener('mousedown', (event) => {
    const target = event.target;
    if (target && typeof target.closest === 'function' && target.closest('.menu-panel')) {
      return;
    }
    invokeBridge('dismiss');
  });

  window.menuPopupApp = {
    setState(nextState) {
      const previousMenuId = String((state.menu && state.menu.id) || '');
      state = normalizeState(nextState || {});
      const nextMenuId = String((state.menu && state.menu.id) || '');
      if (previousMenuId !== nextMenuId) {
        openSubmenuPath = [];
      } else {
        const validPrefixes = [];
        let currentItems = asArray(state.menu && state.menu.items);
        for (const part of openSubmenuPath) {
          const item = currentItems.find((candidate) => String((candidate && candidate.id) || '') === String(part || ''));
          if (!item || !Array.isArray(item.children) || !item.children.length) {
            break;
          }
          validPrefixes.push(part);
          currentItems = item.children;
        }
        openSubmenuPath = validPrefixes;
      }
      render();
    },
    closeMenus() {
      openSubmenuPath = [];
      render();
    },
  };

  if (window.QWebChannel && window.qt && window.qt.webChannelTransport) {
    new QWebChannel(window.qt.webChannelTransport, (channel) => {
      bridge = channel.objects.menuPopupBridge || null;
      invokeBridge('notifyReady');
      render();
    });
  } else {
    render();
  }
})();
