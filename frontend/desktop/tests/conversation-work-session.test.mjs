import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const desktopRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = join(desktopRoot, '..', '..')

async function desktopSource(relativePath) {
  return readFile(join(desktopRoot, relativePath), 'utf8')
}

test('conversation UI and draft have one renderer work-session authority', async () => {
  const [feature, composer, tabs, actions, types, runtime] = await Promise.all([
    desktopSource('src/renderer/src/features/conversation/ConversationFeature.tsx'),
    desktopSource('src/renderer/src/features/conversation/components/ConversationComposer.tsx'),
    desktopSource('src/renderer/src/features/conversation/components/RightPanelTabs.tsx'),
    desktopSource('src/renderer/src/features/conversation/actions.ts'),
    desktopSource('src/renderer/src/features/conversation/types.ts'),
    readFile(join(projectRoot, 'application', 'runtime.py'), 'utf8'),
  ])

  assert.match(feature, /availability !== 'ready' \|\| !sessionId/)
  assert.match(feature, /sameProjectRoot\(persisted\.projectRoot, projectRoot\)/)
  assert.match(feature, /persisted\.conversation\.sessionId === sessionId/)
  assert.match(feature, /updateConversationSession\(projectRoot, \{[\s\S]{0,180}sessionId,[\s\S]{0,180}activeSurface:[\s\S]{0,180}draftText:/)
  assert.match(composer, /draftText: string/)
  assert.match(composer, /onDraftTextChange\(text: string\): void/)
  assert.match(composer, /draftSessionIdRef = useRef\(state\.session\.id\)/)
  assert.match(tabs, /onActivateSurface\(surface: 'conversation' \| 'rag'\): void/)

  for (const source of [actions, types, runtime]) {
    assert.doesNotMatch(source, /clear_draft_nonce/)
    assert.doesNotMatch(source, /active_surface/)
  }
  assert.doesNotMatch(actions, /activateSurface/)
})

test('composer clears accepted payload only after the backend validates its identity', async () => {
  const [composer, actions] = await Promise.all([
    desktopSource('src/renderer/src/features/conversation/components/ConversationComposer.tsx'),
    desktopSource('src/renderer/src/features/conversation/actions.ts'),
  ])

  assert.match(
    actions,
    /accepted\.context_id !== contextId[\s\S]{0,240}!isCurrentContext\(dependencies, contextId\)[\s\S]{0,160}onAccepted\(\)/,
  )
  assert.match(composer, /draftTextRef\.current === submittedDraftText/)
  assert.match(composer, /onDraftTextChange\(''\)/)
  assert.match(composer, /submittedAttachmentKeys/)
  assert.doesNotMatch(composer, /clearNonceRef|draftContextIdRef/)
})
