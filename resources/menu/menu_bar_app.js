(() => {
  const root = document.getElementById('root');

  let bridge = null;
  let state = {
    brandLabel: '',
    menus: [],
    openMenuId: '',
  };

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function normalizeState(nextState) {
    return {
      brandLabel: String((nextState && nextState.brandLabel) || ''),
      menus: asArray(nextState && nextState.menus),
      openMenuId: String((nextState && nextState.openMenuId) || ''),
    };
  }

  function invokeBridge(methodName, ...args) {
    if (!bridge || typeof bridge[methodName] !== 'function') {
      return;
    }
    bridge[methodName](...args);
  }

  function toggleMenu(menuId, button) {
    const rect = button && typeof button.getBoundingClientRect === 'function'
      ? button.getBoundingClientRect()
      : { left: 0, width: 0 };
    invokeBridge('toggleMenu', String(menuId || ''), Math.round(rect.left || 0), Math.round(rect.width || 0));
  }

  function hoverMenu(menuId, button) {
    const rect = button && typeof button.getBoundingClientRect === 'function'
      ? button.getBoundingClientRect()
      : { left: 0, width: 0 };
    invokeBridge('hoverMenu', String(menuId || ''), Math.round(rect.left || 0), Math.round(rect.width || 0));
  }

  function render() {
    if (!root) {
      return;
    }

    root.innerHTML = '';

    const host = document.createElement('div');
    host.className = 'menu-host';

    const bar = document.createElement('div');
    bar.className = 'menu-bar';

    const brand = document.createElement('div');
    brand.className = 'brand-pill';
    brand.textContent = state.brandLabel || '';
    bar.appendChild(brand);

    const buttonGroup = document.createElement('div');
    buttonGroup.className = 'menu-buttons';

    state.menus.forEach((menu) => {
      if (!menu || typeof menu !== 'object') {
        return;
      }
      const menuId = String(menu.id || '');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'menu-button';
      button.textContent = String(menu.label || '');
      if (menuId && menuId === state.openMenuId) {
        button.classList.add('active');
      }
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        toggleMenu(menuId, button);
      });
      button.addEventListener('mouseenter', () => {
        if (state.openMenuId && state.openMenuId !== menuId) {
          hoverMenu(menuId, button);
        }
      });
      buttonGroup.appendChild(button);
    });

    bar.appendChild(buttonGroup);
    host.appendChild(bar);
    root.appendChild(host);
  }

  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      invokeBridge('dismissMenus');
    }
  });

  window.menuBarApp = {
    setState(nextState) {
      state = normalizeState(nextState || {});
      render();
    },
    closeMenus() {
      invokeBridge('dismissMenus');
    },
  };

  if (window.QWebChannel && window.qt && window.qt.webChannelTransport) {
    new QWebChannel(window.qt.webChannelTransport, (channel) => {
      bridge = channel.objects.menuBarBridge || null;
      invokeBridge('notifyReady');
      render();
    });
  } else {
    render();
  }
})();
