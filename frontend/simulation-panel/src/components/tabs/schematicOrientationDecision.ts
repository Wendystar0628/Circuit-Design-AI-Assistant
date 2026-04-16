import type { SchematicLayoutOrientation } from './schematicLayoutTypes'
import type { SchematicSemanticModel, SemanticComponent } from './schematicSemanticModel'
import type { SchematicSkeleton } from './schematicSkeletonModel'
import { getSchematicSymbolDefinition } from './symbolRegistry'

export function decideSchematicComponentOrientations(
  semantic: SchematicSemanticModel,
  skeleton: SchematicSkeleton,
): Map<string, SchematicLayoutOrientation> {
  const result = new Map<string, SchematicLayoutOrientation>()
  for (const semanticComponent of semantic.components) {
    result.set(
      semanticComponent.component.id,
      decideOrientationForComponent(semanticComponent, semantic, skeleton),
    )
  }
  return result
}

function decideOrientationForComponent(
  semanticComponent: SemanticComponent,
  semantic: SchematicSemanticModel,
  skeleton: SchematicSkeleton,
): SchematicLayoutOrientation {
  const definition = getSchematicSymbolDefinition(semanticComponent.component.symbol_kind)
  const supported = definition.supportedOrientations
  const preferred = definition.preferredOrientations

  if (supported.length === 1) {
    return supported[0]
  }

  switch (semanticComponent.role) {
    case 'passive':
      return decideForPassive(semanticComponent, semantic, skeleton, supported, preferred)
    case 'amplifier':
    case 'controlled_source':
    case 'block':
      return decideForDirectionalBlock(semanticComponent, supported, preferred)
    case 'active':
      return decideForActiveDevice(semanticComponent, supported, preferred)
    case 'supply':
    case 'ground':
    case 'unknown':
      return preferred[0] ?? supported[0]
  }
}

function decideForPassive(
  semanticComponent: SemanticComponent,
  semantic: SchematicSemanticModel,
  skeleton: SchematicSkeleton,
  supported: readonly SchematicLayoutOrientation[],
  preferred: readonly SchematicLayoutOrientation[],
): SchematicLayoutOrientation {
  const skeletonComponent = skeleton.componentsById.get(semanticComponent.component.id)
  if (skeletonComponent?.role === 'main_path') {
    if (supported.includes('right')) {
      return 'right'
    }
  }
  if (passiveBridgesRailAndSignal(semanticComponent, semantic, skeleton)) {
    if (supported.includes('down')) {
      return 'down'
    }
  }
  return preferred[0] ?? supported[0]
}

function passiveBridgesRailAndSignal(
  semanticComponent: SemanticComponent,
  semantic: SchematicSemanticModel,
  skeleton: SchematicSkeleton,
): boolean {
  const componentId = semanticComponent.component.id
  let railHits = 0
  let signalHits = 0
  for (const semanticNet of semantic.nets) {
    if (!semanticNet.componentIds.includes(componentId)) {
      continue
    }
    const skeletonNet = skeleton.netsById.get(semanticNet.net.id)
    if (!skeletonNet) {
      continue
    }
    if (skeletonNet.role === 'ground_rail' || skeletonNet.role === 'power_rail') {
      railHits += 1
    } else if (skeletonNet.role !== 'dangling') {
      signalHits += 1
    }
  }
  return railHits >= 1 && signalHits >= 1
}

function decideForDirectionalBlock(
  semanticComponent: SemanticComponent,
  supported: readonly SchematicLayoutOrientation[],
  preferred: readonly SchematicLayoutOrientation[],
): SchematicLayoutOrientation {
  let rightwardVotes = 0
  let leftwardVotes = 0
  for (const pin of semanticComponent.pins) {
    if (pin.role === 'input' && pin.hintedSide === 'right') {
      leftwardVotes += 1
    } else if (pin.role === 'output' && pin.hintedSide === 'left') {
      leftwardVotes += 1
    } else if (pin.role === 'input' && pin.hintedSide === 'left') {
      rightwardVotes += 1
    } else if (pin.role === 'output' && pin.hintedSide === 'right') {
      rightwardVotes += 1
    }
  }
  if (leftwardVotes > rightwardVotes && supported.includes('left')) {
    return 'left'
  }
  return preferred[0] ?? supported[0]
}

function decideForActiveDevice(
  semanticComponent: SemanticComponent,
  supported: readonly SchematicLayoutOrientation[],
  preferred: readonly SchematicLayoutOrientation[],
): SchematicLayoutOrientation {
  const firstPin = semanticComponent.pins[0]
  if (firstPin && firstPin.hintedSide === 'right' && supported.includes('left')) {
    return 'left'
  }
  return preferred[0] ?? supported[0]
}
