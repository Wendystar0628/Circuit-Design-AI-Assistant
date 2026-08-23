import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const desktopRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = join(desktopRoot, '..', '..')
const settingsRoot = join(
  desktopRoot,
  'src',
  'renderer',
  'src',
  'features',
  'settings',
)

function settingsSource(fileName) {
  return readFile(join(settingsRoot, fileName), 'utf8')
}

function sourceBetween(source, start, end) {
  const startIndex = source.indexOf(start)
  const endIndex = source.indexOf(end, startIndex + start.length)
  assert.notEqual(startIndex, -1, `missing source marker: ${start}`)
  assert.notEqual(endIndex, -1, `missing source marker: ${end}`)
  return source.slice(startIndex, endIndex)
}

async function executableSettingsTypes() {
  const source = await settingsSource('types.ts')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}

test('eight curated providers use the select path while aggregators use explicit model entry', async () => {
  const [panel, catalog] = await Promise.all([
    settingsSource('ModelSettingsPanel.tsx'),
    readFile(join(projectRoot, 'infrastructure', 'llm_adapters', 'provider_catalog.py'), 'utf8'),
  ])
  const providerSection = sourceBetween(catalog, 'PROVIDERS:', '_OPENAI_MODELS')
  const providerFlags = [...providerSection.matchAll(
    /ProviderCatalogEntry\(\s*id="([^"]+)",[\s\S]*?allow_custom_model=(True|False),/g,
  )].map((match) => ({ id: match[1], custom: match[2] === 'True' }))

  assert.equal(providerFlags.length, 10)
  assert.equal(providerFlags.filter((provider) => !provider.custom).length, 8)
  assert.deepEqual(
    providerFlags.filter((provider) => provider.custom).map((provider) => provider.id),
    ['opencode', 'siliconflow'],
  )

  assert.match(panel, /const customChatModel = Boolean\(chatProvider\?\.allow_custom_model\)/)
  assert.match(panel, /\{customChatModel \? \(\s*<input[\s\S]{0,300}updateChat\(\{ model: event\.target\.value \}\)/)
  assert.match(panel, /\) : \(\s*<select value=\{draft\.chat\.model\}[\s\S]{0,180}selectChatModel\(event\.target\.value\)/)

  const openCode = sourceBetween(providerSection, 'id="opencode"', 'id="siliconflow"')
  const siliconFlow = providerSection.slice(providerSection.indexOf('id="siliconflow"'))
  assert.match(openCode, /allow_custom_model=True/)
  assert.match(openCode, /protocol_options=PROTOCOL_NAMES/)
  assert.match(siliconFlow, /allow_custom_model=True/)
  assert.match(siliconFlow, /protocol_options=\("openai_chat",\)/)
})

test('OpenCode exposes protocol selection and SiliconFlow keeps its single protocol fixed', async () => {
  const [panel, types] = await Promise.all([
    settingsSource('ModelSettingsPanel.tsx'),
    settingsSource('types.ts'),
  ])

  assert.match(panel, /const showProtocolSelect = customChatModel && chatProtocolOptions\.length > 1/)
  assert.match(panel, /const fixedProtocol = customChatModel && chatProtocolOptions\.length === 1/)
  assert.match(panel, /\{chatProtocolOptions\.map\(\(protocol\) => \(/)
  assert.match(panel, /onChange=\{\(event\) => updateChat\(\{ api_protocol: event\.target\.value \}\)\}/)
  assert.match(panel, /text\.fixedProtocol\.replace\('\{protocol\}', fixedProtocol\.label\)/)
  assert.match(panel, /chatProvider\?\.id === 'opencode'[\s\S]{0,100}text\.openCodeModelHint[\s\S]{0,100}text\.customModelHint/)
  assert.match(panel, /Enter the API model ID without the opencode\/ prefix\./)
  assert.match(panel, /请输入 API 模型 ID，不要带 opencode\/ 前缀。/)
  assert.match(
    types,
    /chatProvider\.protocol_options\.length === 1[\s\S]{0,120}chatProvider\.protocol_options\[0\]\.id/,
  )
})

test('a fresh or invalid provider configuration resolves to the first usable curated provider', async () => {
  const { createModelDraft } = await executableSettingsTypes()
  const config = {
    providers: {
      chat: [
        {
          id: 'openai',
          label: 'OpenAI',
          default_model: 'gpt-current',
          default_base_url: 'https://api.openai.test/v1',
          allow_custom_model: false,
          protocol_options: [{ id: 'openai_responses', label: 'Responses' }],
          has_api_key: true,
          models: [
            {
              id: 'gpt-current',
              label: 'GPT Current',
              role: 'current_performance',
              generation: 'current',
              status: 'stable',
              protocol: 'openai_responses',
              capabilities: {
                tools: true,
                vision: true,
                thinking: true,
                streaming: true,
              },
              description: '',
            },
          ],
        },
      ],
      embedding: [
        {
          id: 'zhipu',
          label: 'Zhipu',
          default_model: 'embedding-3',
          default_base_url: 'https://embedding.test',
          requires_api_key: true,
          has_api_key: false,
          models: [{ id: 'embedding-3', label: 'Embedding 3' }],
        },
      ],
    },
    chat: {
      provider: '',
      model: '',
      api_protocol: '',
      base_url: 'https://stale.test',
      effective_base_url: 'https://stale.test',
      timeout: 60,
      enable_thinking: true,
      has_api_key: false,
    },
    embedding: {
      provider: '',
      model: '',
      base_url: 'https://stale-embedding.test',
      timeout: 30,
      batch_size: 16,
      has_api_key: false,
    },
  }

  for (const missingProvider of ['', 'retired-provider']) {
    const draft = createModelDraft({
      ...config,
      chat: { ...config.chat, provider: missingProvider },
    })
    assert.equal(draft.chat.provider, 'openai')
    assert.equal(draft.chat.model, 'gpt-current')
    assert.equal(draft.chat.api_protocol, 'openai_responses')
    assert.equal(draft.chat.base_url, '')
    assert.equal(draft.chat.effective_base_url, 'https://api.openai.test/v1')
    assert.equal(draft.chat.enable_thinking, false)
    assert.equal(draft.chat.has_api_key, true)
    assert.equal(draft.chat.api_key, '')
    assert.equal(draft.chat.api_key_action, 'keep')
  }
})

test('chat and embedding use independent save and test endpoints with section-local state', async () => {
  const panel = await settingsSource('ModelSettingsPanel.tsx')

  assert.match(panel, /`\$\{API_ROOT\}\/model-config\/\$\{target\}\/test`/)
  assert.match(panel, /api\.put<unknown>\(`\$\{API_ROOT\}\/model-config\/\$\{target\}`, payload\)/)
  assert.match(panel, /Partial<Record<ModelSection, ModelTestResult>>/)
  assert.match(panel, /Record<ModelSection, string>>\(\{ chat: '', embedding: '' \}\)/)
  assert.match(panel, /setTestResults\(\(current\) => \(\{ \.\.\.current, \[target\]: undefined \}\)\)/)
  assert.doesNotMatch(panel, /`\$\{API_ROOT\}\/model-config\/test`/)
  assert.doesNotMatch(panel, /api\.put[^\n]*\(`\$\{API_ROOT\}\/model-config`,/)
})

test('API keys preserve omission, replacement, deletion, and provider-scoped credential state', async () => {
  const [panel, types] = await Promise.all([
    settingsSource('ModelSettingsPanel.tsx'),
    settingsSource('types.ts'),
  ])
  const chatRequest = sourceBetween(panel, 'function chatRequest', 'function embeddingRequest')
  const embeddingRequest = sourceBetween(panel, 'function embeddingRequest', 'function Toggle')
  const providerSwitch = sourceBetween(panel, 'const selectChatProvider', 'const selectEmbeddingProvider')

  assert.match(types, /export type ApiKeyAction = 'keep' \| 'replace' \| 'delete'/)
  for (const requestSource of [chatRequest, embeddingRequest]) {
    const requestInitializer = sourceBetween(requestSource, 'const request:', 'const apiKey')
    assert.doesNotMatch(requestInitializer, /api_key/)
    assert.match(requestSource, /draft\.api_key_action === 'delete'\) request\.api_key = null/)
    assert.match(requestSource, /draft\.api_key_action === 'replace' && apiKey\) request\.api_key = apiKey/)
  }
  assert.match(
    providerSwitch,
    /has_api_key: provider\.has_api_key,[\s\S]{0,100}api_key: '',[\s\S]{0,100}api_key_action: 'keep'/,
  )
})

test('connection edits invalidate verification and obsolete model controls stay deleted', async () => {
  const [panel, feature, types, styles] = await Promise.all([
    settingsSource('ModelSettingsPanel.tsx'),
    settingsSource('SettingsFeature.tsx'),
    settingsSource('types.ts'),
    settingsSource('settings.css'),
  ])
  const updateChat = sourceBetween(panel, 'const updateChat', 'const updateEmbedding')
  const updateEmbedding = sourceBetween(panel, 'const updateEmbedding', 'const selectChatProvider')
  const chatConfig = sourceBetween(types, 'export interface ChatModelConfig', 'export interface EmbeddingModelConfig')
  const chatRequest = sourceBetween(panel, 'function chatRequest', 'function embeddingRequest')
  const settingsSources = `${feature}\n${panel}\n${types}`

  assert.match(updateChat, /invalidate\('chat'\)/)
  assert.match(updateEmbedding, /invalidate\('embedding'\)/)
  assert.doesNotMatch(settingsSources, /thinking_timeout|clear_api_key/)
  assert.doesNotMatch(chatConfig, /streaming:\s*boolean/)
  assert.doesNotMatch(chatRequest, /\bstreaming:/)
  assert.doesNotMatch(panel, /<Toggle[\s\S]{0,160}label=\{text\.streaming\}/)
  assert.match(styles, /\.settings-model-message\s*\{[\s\S]*?white-space:\s*pre-wrap/)
  assert.match(styles, /\.settings-verification\s*\{[\s\S]*?white-space:\s*pre-wrap/)
})

test('model metadata uses readable labels in both supported languages', async () => {
  const panel = await settingsSource('ModelSettingsPanel.tsx')
  const metadata = sourceBetween(panel, 'const modelMetadata =', 'const chatValid =')

  for (const label of [
    'Current performance flagship',
    'Current speed flagship',
    'Previous-generation performance flagship',
    'Previous-generation speed flagship',
    '当代性能旗舰',
    '当代速度旗舰',
    '上代性能旗舰',
    '上代速度旗舰',
  ]) {
    assert.match(panel, new RegExp(label))
  }
  assert.match(metadata, /text\.modelMeta\[value as keyof typeof text\.modelMeta\]/)
  assert.match(panel, /\{modelMetadata\.join\(' · '\)\}/)
  assert.doesNotMatch(
    panel,
    /\[chatModel\.role, chatModel\.generation, chatModel\.status\]\.filter\(Boolean\)\.join/,
  )
})

test('an in-flight model action locks the editable form and cannot race draft edits', async () => {
  const [panel, styles] = await Promise.all([
    settingsSource('ModelSettingsPanel.tsx'),
    settingsSource('settings.css'),
  ])
  const lockedForm = sourceBetween(
    panel,
    '<fieldset className="settings-model-form" disabled={busy} aria-busy={busy}>',
    '</fieldset>',
  )

  assert.match(lockedForm, /id="settings-chat-panel"/)
  assert.match(lockedForm, /id="settings-embedding-panel"/)
  assert.match(panel, /const busy = Boolean\(testing \|\| saving\)/)
  assert.equal((panel.match(/disabled=\{busy\}/g) ?? []).length, 3)
  assert.match(styles, /\.settings-model-form\s*\{[\s\S]*?border:\s*0/)
})

test('chat effective URL follows the current override or provider default only', async () => {
  const panel = await settingsSource('ModelSettingsPanel.tsx')
  const resolution = sourceBetween(panel, 'const chatEffectiveBaseUrl', 'const chatValid')

  assert.match(resolution, /draft\.chat\.base_url\.trim\(\)/)
  assert.match(resolution, /chatProvider\?\.default_base_url/)
  assert.doesNotMatch(resolution, /effective_base_url/)
  assert.match(panel, /text\.effectiveBaseUrl\.replace\('\{url\}', chatEffectiveBaseUrl\)/)
})

test('About loads and fails independently from the model settings mainline', async () => {
  const feature = await settingsSource('SettingsFeature.tsx')
  const loadAbout = sourceBetween(feature, 'const loadAbout =', 'const load =')
  const load = sourceBetween(feature, 'const load =', 'useEffect')

  assert.match(loadAbout, /api\.get<AboutInfo>\(`\$\{API_ROOT\}\/about`\)/)
  assert.match(loadAbout, /setAboutError\(errorMessage\(loadAboutError\)\)/)
  assert.match(load, /void loadAbout\(\)/)
  assert.match(load, /const \[nextPreferences, nextModelConfig\] = await Promise\.all/)
  assert.doesNotMatch(load, /api\.get<AboutInfo>/)
  assert.match(feature, /aboutError[\s\S]{0,180}<ErrorState[\s\S]{0,180}loadAbout\(\)/)
})
