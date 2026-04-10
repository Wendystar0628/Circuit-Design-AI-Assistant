(function () {
  const rootEl = document.getElementById('conversation-root');
  let bridge = null;
  let state = normalizeState({});

  function normalizeState(nextState) {
    const incoming = nextState && typeof nextState === 'object' ? nextState : {};
    const session = incoming.session && typeof incoming.session === 'object' ? incoming.session : {};
    const conversation = incoming.conversation && typeof incoming.conversation === 'object' ? incoming.conversation : {};
    const composer = incoming.composer && typeof incoming.composer === 'object' ? incoming.composer : {};
    const viewFlags = incoming.view_flags && typeof incoming.view_flags === 'object' ? incoming.view_flags : {};

    return {
      session,
      conversation: {
        messages: Array.isArray(conversation.messages) ? conversation.messages : [],
        runtime_steps: Array.isArray(conversation.runtime_steps) ? conversation.runtime_steps : [],
        message_count: Number.isFinite(conversation.message_count) ? conversation.message_count : 0,
        is_loading: Boolean(conversation.is_loading),
        can_send: conversation.can_send !== false,
      },
      composer,
      view_flags: viewFlags,
    };
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function render() {
    if (!rootEl) {
      return;
    }

    const sessionName = state.session.name || 'Conversation';
    const messageCount = state.conversation.message_count || state.conversation.messages.length || 0;
    const runtimeStepCount = state.conversation.runtime_steps.length;
    const busy = state.view_flags.is_busy ? 'busy' : 'idle';
    const bridgeStatus = bridge ? 'connected' : 'disconnected';

    rootEl.innerHTML = [
      '<div class="shell">',
      '  <div class="shell__header">',
      '    <div class="shell__title">' + escapeHtml(sessionName) + '</div>',
      '    <div class="shell__meta">',
      '      bridge: ' + escapeHtml(bridgeStatus) + ' · ',
      '      state: ' + escapeHtml(busy) + ' · ',
      '      messages: ' + escapeHtml(messageCount) + ' · ',
      '      runtime steps: ' + escapeHtml(runtimeStepCount),
      '    </div>',
      '  </div>',
      '  <pre class="shell__payload">' + escapeHtml(JSON.stringify(state, null, 2)) + '</pre>',
      '</div>',
    ].join('');
  }

  window.conversationApp = {
    setState(nextState) {
      state = normalizeState(nextState);
      render();
    },
  };

  if (window.QWebChannel && window.qt && window.qt.webChannelTransport) {
    new QWebChannel(window.qt.webChannelTransport, function (channel) {
      bridge = channel.objects.conversationBridge || null;
      if (bridge && typeof bridge.markReady === 'function') {
        bridge.markReady();
      }
      render();
    });
  } else {
    render();
  }
})();
