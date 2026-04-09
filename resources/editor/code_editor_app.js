(() => {
  const editorRoot = document.getElementById('editor-root');
  const fileActions = document.getElementById('file-actions');
  const startupError = document.getElementById('startup-error');
  let bridge = null;
  let monacoInstance = null;
  let plainEditor = null;
  let diffEditor = null;
  let plainModel = null;
  let originalModel = null;
  let modifiedModel = null;
  let suppressContentEvents = false;
  let currentState = {
    content: '',
    baselineContent: '',
    language: 'plaintext',
    readOnly: false,
    isModified: false,
    pendingFileState: null,
  };
  let hunkWidgets = [];
  const monacoRootUrl = new URL('./monaco/', window.location.href).href;
  const monacoVsUrl = new URL('./monaco/vs', window.location.href).href;
  const monacoBaseUrl = `${monacoVsUrl}/`;
  let monacoWorkerUrl = null;

  function showError(message) {
    startupError.textContent = message;
    startupError.classList.add('visible');
  }

  function hideError() {
    startupError.classList.remove('visible');
    startupError.textContent = '';
  }

  function ensureMonacoWorkerUrl() {
    if (monacoWorkerUrl) {
      return monacoWorkerUrl;
    }
    const workerMainUrl = `${monacoBaseUrl}base/worker/workerMain.js`;
    const workerBootstrap = [
      `self.MonacoEnvironment = { baseUrl: ${JSON.stringify(monacoRootUrl)} };`,
      `importScripts(${JSON.stringify(workerMainUrl)});`,
    ].join('\n');
    monacoWorkerUrl = URL.createObjectURL(
      new Blob([workerBootstrap], { type: 'text/javascript' })
    );
    return monacoWorkerUrl;
  }

  function normalizeState(raw) {
    const state = raw && typeof raw === 'object' ? raw : {};
    return {
      content: typeof state.content === 'string' ? state.content : '',
      baselineContent: typeof state.baselineContent === 'string' ? state.baselineContent : '',
      language: typeof state.language === 'string' && state.language ? state.language : 'plaintext',
      readOnly: !!state.readOnly,
      isModified: !!state.isModified,
      pendingFileState: state.pendingFileState && typeof state.pendingFileState === 'object' ? state.pendingFileState : null,
    };
  }

  function isDiffMode() {
    return !!currentState.pendingFileState;
  }

  function invokeBridge(method, ...args) {
    if (!bridge || typeof bridge[method] !== 'function') {
      return;
    }
    bridge[method](...args);
  }

  function ensureTheme() {
    if (!monacoInstance) {
      return;
    }
    monacoInstance.editor.defineTheme('circuit-editor-light', {
      base: 'vs',
      inherit: true,
      rules: [],
      colors: {
        'editor.background': '#ffffff',
        'editor.lineHighlightBackground': '#f8fafc',
        'editorGutter.background': '#ffffff',
        'diffEditor.insertedTextBackground': '#dcfce799',
        'diffEditor.removedTextBackground': '#fee2e299',
        'diffEditor.insertedLineBackground': '#ecfdf5',
        'diffEditor.removedLineBackground': '#fef2f2',
        'editorOverviewRuler.insertedForeground': '#22c55e',
        'editorOverviewRuler.removedForeground': '#ef4444',
      },
    });
    monacoInstance.editor.setTheme('circuit-editor-light');
  }

  function baseEditorOptions() {
    return {
      automaticLayout: true,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      renderWhitespace: 'selection',
      contextmenu: true,
      wordWrap: 'off',
      smoothScrolling: true,
      fontSize: 13,
      lineHeight: 20,
      glyphMargin: true,
      folding: false,
      stickyScroll: { enabled: false },
      readOnly: currentState.readOnly,
    };
  }

  function disposeHunkWidgets() {
    if (!diffEditor) {
      hunkWidgets = [];
      return;
    }
    const modifiedEditorRef = diffEditor.getModifiedEditor();
    for (const widget of hunkWidgets) {
      try {
        modifiedEditorRef.removeContentWidget(widget);
      } catch (error) {
      }
    }
    hunkWidgets = [];
  }

  function handleContentChanged(content) {
    if (suppressContentEvents) {
      return;
    }
    currentState = {
      ...currentState,
      content,
      isModified: true,
    };
    renderFileActions();
    renderHunkWidgets();
    invokeBridge('notifyContentChanged', content);
  }

  function bindEditorEvents(editor) {
    editor.onDidChangeModelContent(() => {
      const model = editor.getModel();
      handleContentChanged(model ? model.getValue() : '');
    });
    editor.onDidChangeCursorPosition((event) => {
      invokeBridge('notifyCursorChanged', event.position.lineNumber, event.position.column);
    });
  }

  function disposePlainEditor() {
    if (plainEditor) {
      plainEditor.dispose();
      plainEditor = null;
    }
    if (plainModel) {
      plainModel.dispose();
      plainModel = null;
    }
  }

  function disposeDiffEditor() {
    disposeHunkWidgets();
    if (diffEditor) {
      diffEditor.dispose();
      diffEditor = null;
    }
    if (originalModel) {
      originalModel.dispose();
      originalModel = null;
    }
    if (modifiedModel) {
      modifiedModel.dispose();
      modifiedModel = null;
    }
  }

  function ensurePlainEditor() {
    if (plainEditor) {
      return;
    }
    disposeDiffEditor();
    plainModel = monacoInstance.editor.createModel(currentState.content, currentState.language);
    plainEditor = monacoInstance.editor.create(editorRoot, {
      ...baseEditorOptions(),
      model: plainModel,
    });
    bindEditorEvents(plainEditor);
  }

  function ensureDiffEditor() {
    if (diffEditor) {
      return;
    }
    disposePlainEditor();
    originalModel = monacoInstance.editor.createModel(currentState.baselineContent, currentState.language);
    modifiedModel = monacoInstance.editor.createModel(currentState.content, currentState.language);
    diffEditor = monacoInstance.editor.createDiffEditor(editorRoot, {
      ...baseEditorOptions(),
      renderSideBySide: false,
      originalEditable: false,
      enableSplitViewResizing: false,
      renderOverviewRuler: false,
      diffCodeLens: false,
    });
    diffEditor.setModel({ original: originalModel, modified: modifiedModel });
    bindEditorEvents(diffEditor.getModifiedEditor());
  }

  function syncModels() {
    suppressContentEvents = true;
    if (isDiffMode()) {
      ensureDiffEditor();
      if (originalModel && originalModel.getValue() !== currentState.baselineContent) {
        originalModel.setValue(currentState.baselineContent);
      }
      if (modifiedModel && modifiedModel.getValue() !== currentState.content) {
        modifiedModel.setValue(currentState.content);
      }
      monacoInstance.editor.setModelLanguage(originalModel, currentState.language);
      monacoInstance.editor.setModelLanguage(modifiedModel, currentState.language);
      diffEditor.updateOptions({ readOnly: currentState.readOnly });
      diffEditor.getModifiedEditor().updateOptions({ readOnly: currentState.readOnly });
    } else {
      ensurePlainEditor();
      if (plainModel && plainModel.getValue() !== currentState.content) {
        plainModel.setValue(currentState.content);
      }
      monacoInstance.editor.setModelLanguage(plainModel, currentState.language);
      plainEditor.updateOptions({ readOnly: currentState.readOnly });
    }
    suppressContentEvents = false;
  }

  function createActionButton(label, kind, disabled, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `editor-action-btn ${kind}`;
    button.textContent = label;
    button.disabled = !!disabled;
    button.addEventListener('click', onClick);
    return button;
  }

  function renderFileActions() {
    fileActions.innerHTML = '';
    if (!isDiffMode()) {
      fileActions.classList.remove('visible');
      return;
    }
    fileActions.classList.add('visible');
    const disabled = currentState.readOnly || currentState.isModified;
    fileActions.appendChild(
      createActionButton('Accept File', 'accept', disabled, () => invokeBridge('acceptFile'))
    );
    fileActions.appendChild(
      createActionButton('Reject File', 'reject', disabled, () => invokeBridge('rejectFile'))
    );
  }

  function anchorLineForHunk(hunk) {
    if (!modifiedModel) {
      return 1;
    }
    const maxLine = Math.max(1, modifiedModel.getLineCount());
    const rawLine = Number(hunk && hunk.new_start ? hunk.new_start : 0) + 1;
    return Math.min(Math.max(1, rawLine), maxLine);
  }

  function renderHunkWidgets() {
    disposeHunkWidgets();
    if (!isDiffMode() || !diffEditor || !currentState.pendingFileState) {
      return;
    }
    const hunks = Array.isArray(currentState.pendingFileState.hunks)
      ? currentState.pendingFileState.hunks
      : [];
    const modifiedEditorRef = diffEditor.getModifiedEditor();
    const disabled = currentState.readOnly || currentState.isModified;
    for (const hunk of hunks) {
      if (!hunk || typeof hunk !== 'object' || !hunk.id) {
        continue;
      }
      const domNode = document.createElement('div');
      domNode.className = 'hunk-action-widget';
      domNode.appendChild(
        createActionButton('Accept', 'accept', disabled, () => invokeBridge('acceptHunk', String(hunk.id)))
      );
      domNode.appendChild(
        createActionButton('Reject', 'reject', disabled, () => invokeBridge('rejectHunk', String(hunk.id)))
      );
      const widget = {
        getId() {
          return `hunk-widget-${String(hunk.id)}`;
        },
        getDomNode() {
          return domNode;
        },
        getPosition() {
          return {
            position: {
              lineNumber: anchorLineForHunk(hunk),
              column: Number.MAX_SAFE_INTEGER,
            },
            preference: [monacoInstance.editor.ContentWidgetPositionPreference.EXACT],
          };
        },
      };
      modifiedEditorRef.addContentWidget(widget);
      hunkWidgets.push(widget);
    }
  }

  function activeEditor() {
    if (diffEditor) {
      return diffEditor.getModifiedEditor();
    }
    return plainEditor;
  }

  function goToLine(lineNumber, columnNumber) {
    const editor = activeEditor();
    if (!editor) {
      return;
    }
    const line = Math.max(1, Number(lineNumber || 1));
    const column = Math.max(1, Number(columnNumber || 1));
    editor.revealLineInCenter(line);
    editor.setPosition({ lineNumber: line, column });
    editor.focus();
  }

  function focusEditor() {
    const editor = activeEditor();
    if (editor) {
      editor.focus();
    }
  }

  function applyState(nextState) {
    currentState = normalizeState(nextState);
    syncModels();
    renderFileActions();
    renderHunkWidgets();
    hideError();
  }

  function loadMonaco() {
    return new Promise((resolve, reject) => {
      if (typeof require !== 'function') {
        reject(new Error('Monaco loader is unavailable'));
        return;
      }
      window.MonacoEnvironment = {
        baseUrl: monacoRootUrl,
        getWorkerUrl() {
          return ensureMonacoWorkerUrl();
        },
      };
      require.config({ paths: { vs: monacoVsUrl } });
      require(['vs/editor/editor.main'], () => {
        monacoInstance = window.monaco;
        ensureTheme();
        resolve();
      }, reject);
    });
  }

  function initBridge() {
    if (!window.qt || typeof window.QWebChannel !== 'function') {
      showError('Qt WebChannel is unavailable.');
      return;
    }
    new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
      bridge = channel.objects.editorBridge;
      loadMonaco()
        .then(() => {
          applyState(currentState);
          invokeBridge('notifyReady');
        })
        .catch((error) => {
          showError(error && error.message ? error.message : 'Failed to initialize Monaco editor.');
        });
    });
  }

  window.codeEditorApp = {
    setState(nextState) {
      if (!monacoInstance) {
        currentState = normalizeState(nextState);
        return;
      }
      applyState(nextState);
    },
    goToLine(lineNumber, columnNumber) {
      goToLine(lineNumber, columnNumber);
    },
    focus() {
      focusEditor();
    },
  };

  initBridge();
})();
