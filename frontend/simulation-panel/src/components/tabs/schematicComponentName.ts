import type { SchematicComponentState } from '../../types/state'

export function getSchematicComponentDisplayName(
  component: Pick<SchematicComponentState, 'display_name' | 'instance_name' | 'id'> | null | undefined,
): string {
  if (!component) {
    return ''
  }
  return component.display_name || component.instance_name || component.id || ''
}
