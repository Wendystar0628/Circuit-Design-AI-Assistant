import type {
  SchematicComponentDto,
  SchematicDocumentDto,
  SchematicPinDto,
} from './types'

export interface LayoutPoint {
  x: number
  y: number
}

export interface LayoutPin extends LayoutPoint {
  pin: SchematicPinDto
  side: 'left' | 'right' | 'top' | 'bottom'
}

export interface LayoutComponent {
  component: SchematicComponentDto
  x: number
  y: number
  width: number
  height: number
  pins: LayoutPin[]
}

export interface LayoutNet {
  id: string
  name: string
  hub: LayoutPoint
  paths: string[]
}

export interface SchematicLayout {
  components: LayoutComponent[]
  nets: LayoutNet[]
  viewBox: { x: number; y: number; width: number; height: number }
}

const COMPONENT_WIDTH = 120
const COLUMN_GAP = 230
const ROW_GAP = 145
const ORIGIN_X = 110
const ORIGIN_Y = 90

function componentOrder(left: SchematicComponentDto, right: SchematicComponentDto): number {
  const leftScope = left.scope_path.join('/')
  const rightScope = right.scope_path.join('/')
  return leftScope.localeCompare(rightScope) || left.instance_name.localeCompare(right.instance_name)
}

function preferredRoot(component: SchematicComponentDto): boolean {
  const prefix = component.instance_name[0]?.toUpperCase()
  return prefix === 'V' || prefix === 'I' || component.kind.includes('source')
}

function buildLayers(document: SchematicDocumentDto): Map<string, number> {
  const components = [...document.components].sort(componentOrder)
  const adjacency = new Map(components.map((component) => [component.id, new Set<string>()]))
  for (const net of document.nets) {
    const ids = [...new Set(net.connections.map((connection) => connection.component_id))]
      .filter((id) => adjacency.has(id))
    for (let left = 0; left < ids.length; left += 1) {
      for (let right = left + 1; right < ids.length; right += 1) {
        adjacency.get(ids[left])?.add(ids[right])
        adjacency.get(ids[right])?.add(ids[left])
      }
    }
  }
  const layers = new Map<string, number>()
  const roots = components.filter(preferredRoot)
  const queue: Array<{ id: string; layer: number }> = (roots.length ? roots : components.slice(0, 1))
    .map((component) => ({ id: component.id, layer: 0 }))
  const visitQueue = () => {
    while (queue.length) {
      const item = queue.shift() as { id: string; layer: number }
      if (layers.has(item.id)) continue
      layers.set(item.id, item.layer)
      const neighbours = [...(adjacency.get(item.id) ?? [])].sort()
      neighbours.forEach((id) => {
        if (!layers.has(id)) queue.push({ id, layer: item.layer + 1 })
      })
    }
  }
  visitQueue()
  for (const component of components) {
    if (layers.has(component.id)) continue
    const nextLayer = layers.size ? Math.max(...layers.values()) + 1 : 0
    queue.push({ id: component.id, layer: nextLayer })
    visitQueue()
  }
  return layers
}

function resolveSide(component: SchematicComponentDto, pin: SchematicPinDto, index: number): LayoutPin['side'] {
  const hint = component.port_side_hints[pin.name]
  if (hint === 'left' || hint === 'right' || hint === 'top' || hint === 'bottom') return hint
  if (component.pins.length === 1) return 'left'
  return index < Math.ceil(component.pins.length / 2) ? 'left' : 'right'
}

function pinPositions(component: SchematicComponentDto, x: number, y: number, width: number, height: number): LayoutPin[] {
  const groups: Record<LayoutPin['side'], Array<{ pin: SchematicPinDto; index: number }>> = {
    left: [],
    right: [],
    top: [],
    bottom: [],
  }
  component.pins.forEach((pin, index) => groups[resolveSide(component, pin, index)].push({ pin, index }))
  return (Object.entries(groups) as Array<[LayoutPin['side'], Array<{ pin: SchematicPinDto; index: number }>]>)
    .flatMap(([side, pins]) => pins.map(({ pin }, index) => {
      const ratio = (index + 1) / (pins.length + 1)
      if (side === 'left') return { pin, side, x: x - width / 2, y: y - height / 2 + height * ratio }
      if (side === 'right') return { pin, side, x: x + width / 2, y: y - height / 2 + height * ratio }
      if (side === 'top') return { pin, side, x: x - width / 2 + width * ratio, y: y - height / 2 }
      return { pin, side, x: x - width / 2 + width * ratio, y: y + height / 2 }
    }))
}

function layoutComponents(document: SchematicDocumentDto): LayoutComponent[] {
  const layers = buildLayers(document)
  const grouped = new Map<number, SchematicComponentDto[]>()
  for (const component of document.components) {
    const layer = layers.get(component.id) ?? 0
    const group = grouped.get(layer) ?? []
    group.push(component)
    grouped.set(layer, group)
  }
  const laidOut: LayoutComponent[] = []
  for (const [layer, rawComponents] of [...grouped.entries()].sort(([left], [right]) => left - right)) {
    const components = rawComponents.sort(componentOrder)
    components.forEach((component, row) => {
      const leftRightCount = component.pins.filter((pin, index) => {
        const side = resolveSide(component, pin, index)
        return side === 'left' || side === 'right'
      }).length
      const height = Math.max(72, leftRightCount * 18 + 34)
      const x = ORIGIN_X + layer * COLUMN_GAP
      const y = ORIGIN_Y + row * ROW_GAP
      laidOut.push({
        component,
        x,
        y,
        width: COMPONENT_WIDTH,
        height,
        pins: pinPositions(component, x, y, COMPONENT_WIDTH, height),
      })
    })
  }
  return laidOut
}

function layoutNets(document: SchematicDocumentDto, components: LayoutComponent[]): LayoutNet[] {
  const pinIndex = new Map<string, LayoutPin>()
  for (const component of components) {
    for (const pin of component.pins) {
      pinIndex.set(`${component.component.id}\u0000${pin.pin.name}`, pin)
    }
  }
  return [...document.nets]
    .sort((left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id))
    .map((net) => {
      const pins = net.connections
        .map((connection) => pinIndex.get(`${connection.component_id}\u0000${connection.pin_name}`))
        .filter((pin): pin is LayoutPin => Boolean(pin))
      if (!pins.length) return null
      const hub = {
        x: pins.reduce((sum, pin) => sum + pin.x, 0) / pins.length,
        y: pins.reduce((sum, pin) => sum + pin.y, 0) / pins.length,
      }
      return {
        id: net.id,
        name: net.name,
        hub,
        paths: pins.map((pin) => `M ${pin.x} ${pin.y} H ${hub.x} V ${hub.y}`),
      }
    })
    .filter((net): net is LayoutNet => Boolean(net))
}

export function buildSchematicLayout(document: SchematicDocumentDto): SchematicLayout {
  const components = layoutComponents(document)
  const nets = layoutNets(document, components)
  if (!components.length) {
    return { components, nets, viewBox: { x: 0, y: 0, width: 640, height: 400 } }
  }
  const minX = Math.min(...components.map((component) => component.x - component.width / 2)) - 80
  const maxX = Math.max(...components.map((component) => component.x + component.width / 2)) + 80
  const minY = Math.min(...components.map((component) => component.y - component.height / 2)) - 70
  const maxY = Math.max(...components.map((component) => component.y + component.height / 2)) + 80
  return {
    components,
    nets,
    viewBox: {
      x: minX,
      y: minY,
      width: Math.max(640, maxX - minX),
      height: Math.max(400, maxY - minY),
    },
  }
}
