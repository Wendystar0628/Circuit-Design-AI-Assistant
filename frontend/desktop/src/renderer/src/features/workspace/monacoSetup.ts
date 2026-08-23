import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import 'monaco-editor/esm/vs/basic-languages/css/css.contribution'
import 'monaco-editor/esm/vs/basic-languages/html/html.contribution'
import 'monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution'
import 'monaco-editor/esm/vs/basic-languages/markdown/markdown.contribution'
import 'monaco-editor/esm/vs/basic-languages/powershell/powershell.contribution'
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution'
import 'monaco-editor/esm/vs/basic-languages/shell/shell.contribution'
import 'monaco-editor/esm/vs/basic-languages/typescript/typescript.contribution'
import 'monaco-editor/esm/vs/basic-languages/xml/xml.contribution'
import 'monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution'

interface MonacoWorkerEnvironment {
  getWorker: (_moduleId: string, label: string) => Worker
}

const workerEnvironment: MonacoWorkerEnvironment = {
  getWorker() {
    return new EditorWorker()
  },
}

;(globalThis as typeof globalThis & { MonacoEnvironment?: MonacoWorkerEnvironment }).MonacoEnvironment = workerEnvironment

// Monaco's JSON language service ships with a separate worker. The workspace only
// needs editing and highlighting, so keep JSON lightweight instead of loading a
// validation stack that is unrelated to the circuit-design mainline.
monaco.languages.register({ id: 'json', extensions: ['.json'], aliases: ['JSON', 'json'] })
monaco.languages.setMonarchTokensProvider('json', {
  tokenizer: {
    root: [
      [/\"(?:[^\"\\]|\\.)*\"(?=\s*:)/, 'key'],
      [/\"(?:[^\"\\]|\\.)*\"/, 'string'],
      [/-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/, 'number'],
      [/\b(?:true|false|null)\b/, 'constant'],
      [/[{}\[\],:]/, 'delimiter'],
    ],
  },
})

monaco.languages.register({ id: 'spice', extensions: ['.cir', '.sp', '.spice', '.net'] })
monaco.languages.setMonarchTokensProvider('spice', {
  ignoreCase: true,
  tokenizer: {
    root: [
      [/^\s*\*.*/, 'comment'],
      [/;.*/, 'comment'],
      [/^\s*\.[a-z]+/, 'keyword'],
      [/^\s*[rclvidqmxebfgstuwkoz](?=\S*)/, 'type.identifier'],
      [/[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?(?:meg|[tgkmunpf])?\b/, 'number'],
      [/\{[^}]*\}/, 'variable'],
      [/\b(?:true|false)\b/, 'constant'],
    ],
  },
})

loader.config({ monaco: monaco as typeof import('monaco-editor') })

export { monaco }
