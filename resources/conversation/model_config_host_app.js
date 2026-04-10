(function () {
  const root = document.getElementById('model-config-root');
  if (!root) {
    return;
  }

  const shell = document.createElement('div');
  shell.className = 'shell';
  const card = document.createElement('div');
  card.className = 'card';
  const title = document.createElement('div');
  title.className = 'title';
  title.textContent = 'Model Configuration';
  const payload = document.createElement('pre');
  payload.className = 'payload';
  payload.textContent = 'Waiting for state...';

  card.appendChild(title);
  card.appendChild(payload);
  shell.appendChild(card);
  root.appendChild(shell);

  function applyState(state) {
    const dialog = state && typeof state === 'object' ? state.dialog || {} : {};
    title.textContent = dialog.title || 'Model Configuration';
    try {
      payload.textContent = JSON.stringify(state || {}, null, 2);
    } catch (error) {
      payload.textContent = String(error || 'Failed to render state');
    }
  }

  window.modelConfigApp = {
    setState: applyState,
  };

  function bindBridge() {
    if (!window.QWebChannel || !window.qt || !window.qt.webChannelTransport) {
      return;
    }
    new window.QWebChannel(window.qt.webChannelTransport, function (channel) {
      const bridge = channel.objects && channel.objects.modelConfigBridge;
      if (bridge && typeof bridge.markReady === 'function') {
        bridge.markReady();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindBridge, { once: true });
  } else {
    bindBridge();
  }
})();
