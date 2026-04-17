import type { ReactNode } from 'react'

import type { SchematicComponentState, SchematicPinState } from '../../types/state'
import type { SchematicLayoutOrientation, SchematicPinSide } from './schematicLayoutTypes'

export type { SchematicPinSide } from './schematicLayoutTypes'

export interface SchematicSymbolAnchor {
  x: number
  y: number
  side: SchematicPinSide
}

export interface SchematicSymbolAppearance {
  stroke: string
  fill: string
  accent: string
  text: string
  pinFill: string
  readonly: boolean
}

export interface RenderSchematicSymbolProps {
  component: SchematicComponentState
  width: number
  height: number
  appearance: SchematicSymbolAppearance
}

export interface SchematicSymbolDefinition {
  width: number
  height: number
  getPinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor
  render(props: RenderSchematicSymbolProps): ReactNode
}

const SIDE_ROTATION_CW: Record<SchematicPinSide, SchematicPinSide> = {
  left: 'top',
  top: 'right',
  right: 'bottom',
  bottom: 'left',
}

const SIDE_ROTATION_CCW: Record<SchematicPinSide, SchematicPinSide> = {
  left: 'bottom',
  bottom: 'right',
  right: 'top',
  top: 'left',
}

const SIDE_MIRROR_X: Record<SchematicPinSide, SchematicPinSide> = {
  left: 'right',
  right: 'left',
  top: 'top',
  bottom: 'bottom',
}

export function transformSchematicSymbolAnchor(
  baseAnchor: SchematicSymbolAnchor,
  orientation: SchematicLayoutOrientation,
  baseWidth: number,
  baseHeight: number,
): SchematicSymbolAnchor {
  switch (orientation) {
    case 'right':
      return { x: baseAnchor.x, y: baseAnchor.y, side: baseAnchor.side }
    case 'left':
      return { x: baseWidth - baseAnchor.x, y: baseAnchor.y, side: SIDE_MIRROR_X[baseAnchor.side] }
    case 'down':
      return { x: baseHeight - baseAnchor.y, y: baseAnchor.x, side: SIDE_ROTATION_CW[baseAnchor.side] }
    case 'up':
      return { x: baseAnchor.y, y: baseWidth - baseAnchor.x, side: SIDE_ROTATION_CCW[baseAnchor.side] }
  }
}

export function getSchematicSymbolRenderTransform(
  orientation: SchematicLayoutOrientation,
  baseWidth: number,
  baseHeight: number,
): string {
  switch (orientation) {
    case 'right':
      return ''
    case 'left':
      return `translate(${baseWidth} 0) scale(-1 1)`
    case 'down':
      return `translate(${baseHeight} 0) rotate(90)`
    case 'up':
      return `translate(0 ${baseWidth}) rotate(-90)`
  }
}

const PASSIVE_WIDTH = 108
const PASSIVE_HEIGHT = 60
const BLOCK_WIDTH = 132
const BLOCK_HEIGHT = 82
const SOURCE_SIZE = 76
const TRIANGLE_WIDTH = 110
const TRIANGLE_HEIGHT = 82
const TRANSISTOR_WIDTH = 94
const TRANSISTOR_HEIGHT = 90

function isSide(value: string): value is SchematicPinSide {
  return value === 'left' || value === 'right' || value === 'top' || value === 'bottom'
}

export function isSchematicComponentReadonly(component: SchematicComponentState): boolean {
  if (!component.editable_fields.length) {
    return true
  }
  return component.editable_fields.every((field) => !field.editable)
}

const schematicComponentTypeLabels: Record<string, string> = {
  r: '电阻',
  resistor: '电阻',
  c: '电容',
  capacitor: '电容',
  l: '电感',
  inductor: '电感',
  d: '二极管',
  diode: '二极管',
  v: '电压源',
  voltage_source: '电压源',
  i: '电流源',
  current_source: '电流源',
  gnd: '接地',
  ground: '接地',
  x: '子电路',
  subckt: '子电路',
  subckt_block: '子电路',
  controlled_source: '受控源',
  e: '受控源',
  f: '受控源',
  g: '受控源',
  h: '受控源',
  u: '运算放大器',
  opamp: '运算放大器',
  q: '三极管',
  bjt: '三极管',
  m: 'MOS 管',
  mos: 'MOS 管',
  unknown: '未知元件',
}

function normalizeSchematicComponentTypeKey(value: string): string {
  return value.trim().toLowerCase()
}

export function getSchematicComponentTypeLabel(component: SchematicComponentState): string {
  const candidates = [component.symbol_kind, component.kind, component.display_name].filter((value) => Boolean(value))
  for (const candidate of candidates) {
    const label = schematicComponentTypeLabels[normalizeSchematicComponentTypeKey(candidate)]
    if (label) {
      return label
    }
  }
  return component.display_name || component.kind || component.symbol_kind || '--'
}

function renderLeadLine(x1: number, y1: number, x2: number, y2: number, stroke: string): ReactNode {
  return <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={stroke} strokeWidth={2.2} strokeLinecap="round" />
}

function resolvePinSide(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicPinSide {
  const hintedSide = component.port_side_hints[pin.name]
  if (isSide(hintedSide)) {
    return hintedSide
  }
  if (pin.role === 'ground') {
    return 'bottom'
  }
  if (pin.role === 'power') {
    return 'top'
  }
  if (pin.role === 'output') {
    return 'right'
  }
  if (pin.role === 'input') {
    return 'left'
  }
  if (component.pins.length <= 1) {
    return 'top'
  }
  if (component.pins.length === 2) {
    return index === 0 ? 'left' : 'right'
  }
  return index % 2 === 0 ? 'left' : 'right'
}

function resolveSideOrder(component: SchematicComponentState, side: SchematicPinSide, index: number): { order: number; total: number } {
  const sameSideIndices = component.pins
    .map((pin, pinIndex) => ({ pinIndex, side: resolvePinSide(component, pin, pinIndex) }))
    .filter((item) => item.side === side)
    .map((item) => item.pinIndex)
  return {
    order: Math.max(0, sameSideIndices.indexOf(index)),
    total: Math.max(1, sameSideIndices.length),
  }
}

function distributeAlongSide(side: SchematicPinSide, order: number, total: number, width: number, height: number): SchematicSymbolAnchor {
  if (side === 'left') {
    return { x: 0, y: height * (order + 1) / (total + 1), side }
  }
  if (side === 'right') {
    return { x: width, y: height * (order + 1) / (total + 1), side }
  }
  if (side === 'top') {
    return { x: width * (order + 1) / (total + 1), y: 0, side }
  }
  return { x: width * (order + 1) / (total + 1), y: height, side }
}

function resolveRectPinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number, width: number, height: number): SchematicSymbolAnchor {
  const side = resolvePinSide(component, pin, index)
  const placement = resolveSideOrder(component, side, index)
  return distributeAlongSide(side, placement.order, placement.total, width, height)
}

function resolvePassivePinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor {
  if (component.pins.length <= 1) {
    return { x: PASSIVE_WIDTH / 2, y: 0, side: 'top' }
  }
  if (index === 0) {
    return { x: 0, y: PASSIVE_HEIGHT / 2, side: 'left' }
  }
  if (index === 1) {
    return { x: PASSIVE_WIDTH, y: PASSIVE_HEIGHT / 2, side: 'right' }
  }
  return resolveRectPinAnchor(component, pin, index, PASSIVE_WIDTH, PASSIVE_HEIGHT)
}

function renderResistor({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const y = PASSIVE_HEIGHT / 2
  return (
    <g>
      {renderLeadLine(0, y, 18, y, appearance.stroke)}
      <polyline
        points={`18,${y} 28,${y - 10} 38,${y + 10} 48,${y - 10} 58,${y + 10} 68,${y - 10} 78,${y + 10} 90,${y}`}
        fill="none"
        stroke={appearance.stroke}
        strokeWidth={2.2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {renderLeadLine(90, y, PASSIVE_WIDTH, y, appearance.stroke)}
    </g>
  )
}

function renderCapacitor({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const y = PASSIVE_HEIGHT / 2
  return (
    <g>
      {renderLeadLine(0, y, 34, y, appearance.stroke)}
      <line x1={38} y1={12} x2={38} y2={PASSIVE_HEIGHT - 12} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={70} y1={12} x2={70} y2={PASSIVE_HEIGHT - 12} stroke={appearance.stroke} strokeWidth={2.2} />
      {renderLeadLine(74, y, PASSIVE_WIDTH, y, appearance.stroke)}
    </g>
  )
}

function renderInductor({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const y = PASSIVE_HEIGHT / 2
  return (
    <g>
      {renderLeadLine(0, y, 20, y, appearance.stroke)}
      <path
        d={`M20 ${y} C26 ${y - 15}, 34 ${y - 15}, 40 ${y} C46 ${y - 15}, 54 ${y - 15}, 60 ${y} C66 ${y - 15}, 74 ${y - 15}, 80 ${y} C86 ${y - 15}, 94 ${y - 15}, 100 ${y}`}
        fill="none"
        stroke={appearance.stroke}
        strokeWidth={2.2}
        strokeLinecap="round"
      />
      {renderLeadLine(100, y, PASSIVE_WIDTH, y, appearance.stroke)}
    </g>
  )
}

function renderDiode({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const y = PASSIVE_HEIGHT / 2
  return (
    <g>
      {renderLeadLine(0, y, 24, y, appearance.stroke)}
      <polygon points={`24,12 24,${PASSIVE_HEIGHT - 12} 66,${y}`} fill={appearance.fill} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={72} y1={10} x2={72} y2={PASSIVE_HEIGHT - 10} stroke={appearance.stroke} strokeWidth={2.2} />
      {renderLeadLine(72, y, PASSIVE_WIDTH, y, appearance.stroke)}
    </g>
  )
}

function renderVoltageSource({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const center = SOURCE_SIZE / 2
  return (
    <g>
      {renderLeadLine(center, 0, center, 14, appearance.stroke)}
      <circle cx={center} cy={center} r={24} fill={appearance.fill} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={center - 7} y1={center - 8} x2={center + 7} y2={center - 8} stroke={appearance.stroke} strokeWidth={2} />
      <line x1={center} y1={center - 14} x2={center} y2={center - 2} stroke={appearance.stroke} strokeWidth={2} />
      <line x1={center - 7} y1={center + 10} x2={center + 7} y2={center + 10} stroke={appearance.stroke} strokeWidth={2} />
      {renderLeadLine(center, SOURCE_SIZE - 14, center, SOURCE_SIZE, appearance.stroke)}
    </g>
  )
}

function renderCurrentSource({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const center = SOURCE_SIZE / 2
  return (
    <g>
      {renderLeadLine(center, 0, center, 14, appearance.stroke)}
      <circle cx={center} cy={center} r={24} fill={appearance.fill} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={center} y1={center + 12} x2={center} y2={center - 8} stroke={appearance.stroke} strokeWidth={2} />
      <polyline
        points={`${center - 6},${center - 2} ${center},${center - 10} ${center + 6},${center - 2}`}
        fill="none"
        stroke={appearance.stroke}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {renderLeadLine(center, SOURCE_SIZE - 14, center, SOURCE_SIZE, appearance.stroke)}
    </g>
  )
}

function renderGround({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const center = SOURCE_SIZE / 2
  return (
    <g>
      {renderLeadLine(center, 0, center, 22, appearance.stroke)}
      <line x1={center - 16} y1={26} x2={center + 16} y2={26} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={center - 10} y1={34} x2={center + 10} y2={34} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={center - 4} y1={42} x2={center + 4} y2={42} stroke={appearance.stroke} strokeWidth={2.2} />
    </g>
  )
}

function renderBlock({ width, height, appearance }: RenderSchematicSymbolProps): ReactNode {
  return <rect x={10} y={10} width={width - 20} height={height - 20} rx={12} fill={appearance.fill} stroke={appearance.stroke} strokeWidth={2.2} />
}

function renderControlledSource({ width, height, appearance }: RenderSchematicSymbolProps): ReactNode {
  const centerX = width / 2
  const centerY = height / 2
  return (
    <g>
      <polygon
        points={`${centerX},8 ${width - 8},${centerY} ${centerX},${height - 8} 8,${centerY}`}
        fill={appearance.fill}
        stroke={appearance.stroke}
        strokeWidth={2.2}
      />
    </g>
  )
}

function renderOpamp({ appearance }: RenderSchematicSymbolProps): ReactNode {
  return (
    <g>
      <polygon
        points={`14,8 ${TRIANGLE_WIDTH - 12},${TRIANGLE_HEIGHT / 2} 14,${TRIANGLE_HEIGHT - 8}`}
        fill={appearance.fill}
        stroke={appearance.stroke}
        strokeWidth={2.2}
      />
      <line x1={22} y1={TRIANGLE_HEIGHT * 0.34} x2={34} y2={TRIANGLE_HEIGHT * 0.34} stroke={appearance.stroke} strokeWidth={2} />
      <line x1={28} y1={TRIANGLE_HEIGHT * 0.28} x2={28} y2={TRIANGLE_HEIGHT * 0.4} stroke={appearance.stroke} strokeWidth={2} />
      <line x1={22} y1={TRIANGLE_HEIGHT * 0.66} x2={34} y2={TRIANGLE_HEIGHT * 0.66} stroke={appearance.stroke} strokeWidth={2} />
    </g>
  )
}

function renderBjt({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const cx = TRANSISTOR_WIDTH * 0.56
  const cy = TRANSISTOR_HEIGHT / 2
  return (
    <g>
      <circle cx={cx} cy={cy} r={22} fill={appearance.fill} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={12} y1={cy} x2={cx - 12} y2={cy} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={cx - 4} y1={cy - 12} x2={cx + 14} y2={18} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={cx - 4} y1={cy + 12} x2={cx + 14} y2={TRANSISTOR_HEIGHT - 18} stroke={appearance.stroke} strokeWidth={2.2} />
      <polyline
        points={`${cx + 4},${TRANSISTOR_HEIGHT - 28} ${cx + 14},${TRANSISTOR_HEIGHT - 18} ${cx + 1},${TRANSISTOR_HEIGHT - 14}`}
        fill="none"
        stroke={appearance.stroke}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
  )
}

function renderMos({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const channelX = TRANSISTOR_WIDTH * 0.58
  return (
    <g>
      <line x1={16} y1={TRANSISTOR_HEIGHT / 2} x2={34} y2={TRANSISTOR_HEIGHT / 2} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={42} y1={18} x2={42} y2={TRANSISTOR_HEIGHT - 18} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={channelX} y1={16} x2={channelX} y2={TRANSISTOR_HEIGHT - 16} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={channelX} y1={20} x2={channelX + 18} y2={20} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={channelX} y1={TRANSISTOR_HEIGHT - 20} x2={channelX + 18} y2={TRANSISTOR_HEIGHT - 20} stroke={appearance.stroke} strokeWidth={2.2} />
      <polyline
        points={`${channelX + 8},${TRANSISTOR_HEIGHT - 30} ${channelX + 18},${TRANSISTOR_HEIGHT - 20} ${channelX + 5},${TRANSISTOR_HEIGHT - 16}`}
        fill="none"
        stroke={appearance.stroke}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
  )
}

function renderUnknown({ width, height, appearance }: RenderSchematicSymbolProps): ReactNode {
  return (
    <g>
      <rect
        x={10}
        y={10}
        width={width - 20}
        height={height - 20}
        rx={12}
        fill={appearance.fill}
        stroke={appearance.stroke}
        strokeWidth={2.2}
        strokeDasharray="6 4"
      />
      <text x={width / 2} y={height / 2 + 6} textAnchor="middle" fontSize={24} fontWeight={700} fill={appearance.accent}>
        ?
      </text>
    </g>
  )
}

function resolveOpampPinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor {
  const sideHint = component.port_side_hints[pin.name]
  if (isSide(sideHint)) {
    const placement = resolveSideOrder(component, sideHint, index)
    return distributeAlongSide(sideHint, placement.order, placement.total, TRIANGLE_WIDTH, TRIANGLE_HEIGHT)
  }
  if (pin.role === 'output' || index === component.pins.length - 1) {
    return { x: TRIANGLE_WIDTH, y: TRIANGLE_HEIGHT / 2, side: 'right' }
  }
  if (index === 0) {
    return { x: 0, y: TRIANGLE_HEIGHT * 0.34, side: 'left' }
  }
  if (index === 1) {
    return { x: 0, y: TRIANGLE_HEIGHT * 0.66, side: 'left' }
  }
  return resolveRectPinAnchor(component, pin, index, TRIANGLE_WIDTH, TRIANGLE_HEIGHT)
}

function resolveBjtPinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor {
  const sideHint = component.port_side_hints[pin.name]
  if (isSide(sideHint)) {
    const placement = resolveSideOrder(component, sideHint, index)
    return distributeAlongSide(sideHint, placement.order, placement.total, TRANSISTOR_WIDTH, TRANSISTOR_HEIGHT)
  }
  if (pin.role === 'input' || index === 0) {
    return { x: 0, y: TRANSISTOR_HEIGHT / 2, side: 'left' }
  }
  if (index === 1) {
    return { x: TRANSISTOR_WIDTH, y: 12, side: 'right' }
  }
  return { x: TRANSISTOR_WIDTH, y: TRANSISTOR_HEIGHT - 12, side: 'right' }
}

function resolveMosPinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor {
  const sideHint = component.port_side_hints[pin.name]
  if (isSide(sideHint)) {
    const placement = resolveSideOrder(component, sideHint, index)
    return distributeAlongSide(sideHint, placement.order, placement.total, TRANSISTOR_WIDTH, TRANSISTOR_HEIGHT)
  }
  if (pin.role === 'input' || index === 0) {
    return { x: 0, y: TRANSISTOR_HEIGHT / 2, side: 'left' }
  }
  if (index === 1) {
    return { x: TRANSISTOR_WIDTH, y: 12, side: 'right' }
  }
  if (index === 2) {
    return { x: TRANSISTOR_WIDTH, y: TRANSISTOR_HEIGHT - 12, side: 'right' }
  }
  return { x: TRANSISTOR_WIDTH / 2, y: TRANSISTOR_HEIGHT, side: 'bottom' }
}

const passiveDefinition: SchematicSymbolDefinition = {
  width: PASSIVE_WIDTH,
  height: PASSIVE_HEIGHT,
  getPinAnchor(component, pin, index) {
    return resolvePassivePinAnchor(component, pin, index)
  },
  render: renderResistor,
}

const symbolDefinitions: Record<string, SchematicSymbolDefinition> = {
  resistor: {
    ...passiveDefinition,
    render: renderResistor,
  },
  capacitor: {
    ...passiveDefinition,
    render: renderCapacitor,
  },
  inductor: {
    ...passiveDefinition,
    render: renderInductor,
  },
  diode: {
    ...passiveDefinition,
    render: renderDiode,
  },
  voltage_source: {
    width: SOURCE_SIZE,
    height: SOURCE_SIZE,
    getPinAnchor(component, pin, index) {
      if (index === 0) {
        return { x: SOURCE_SIZE / 2, y: 0, side: 'top' }
      }
      if (index === 1) {
        return { x: SOURCE_SIZE / 2, y: SOURCE_SIZE, side: 'bottom' }
      }
      return resolveRectPinAnchor(component, pin, index, SOURCE_SIZE, SOURCE_SIZE)
    },
    render: renderVoltageSource,
  },
  current_source: {
    width: SOURCE_SIZE,
    height: SOURCE_SIZE,
    getPinAnchor(component, pin, index) {
      if (index === 0) {
        return { x: SOURCE_SIZE / 2, y: 0, side: 'top' }
      }
      if (index === 1) {
        return { x: SOURCE_SIZE / 2, y: SOURCE_SIZE, side: 'bottom' }
      }
      return resolveRectPinAnchor(component, pin, index, SOURCE_SIZE, SOURCE_SIZE)
    },
    render: renderCurrentSource,
  },
  ground: {
    width: SOURCE_SIZE,
    height: SOURCE_SIZE,
    getPinAnchor() {
      return { x: SOURCE_SIZE / 2, y: 0, side: 'top' }
    },
    render: renderGround,
  },
  subckt_block: {
    width: BLOCK_WIDTH,
    height: BLOCK_HEIGHT,
    getPinAnchor(component, pin, index) {
      return resolveRectPinAnchor(component, pin, index, BLOCK_WIDTH, BLOCK_HEIGHT)
    },
    render: renderBlock,
  },
  controlled_source: {
    width: BLOCK_WIDTH,
    height: BLOCK_HEIGHT,
    getPinAnchor(component, pin, index) {
      return resolveRectPinAnchor(component, pin, index, BLOCK_WIDTH, BLOCK_HEIGHT)
    },
    render: renderControlledSource,
  },
  opamp: {
    width: TRIANGLE_WIDTH,
    height: TRIANGLE_HEIGHT,
    getPinAnchor(component, pin, index) {
      return resolveOpampPinAnchor(component, pin, index)
    },
    render: renderOpamp,
  },
  bjt: {
    width: TRANSISTOR_WIDTH,
    height: TRANSISTOR_HEIGHT,
    getPinAnchor(component, pin, index) {
      return resolveBjtPinAnchor(component, pin, index)
    },
    render: renderBjt,
  },
  mos: {
    width: TRANSISTOR_WIDTH,
    height: TRANSISTOR_HEIGHT,
    getPinAnchor(component, pin, index) {
      return resolveMosPinAnchor(component, pin, index)
    },
    render: renderMos,
  },
  unknown: {
    width: BLOCK_WIDTH,
    height: BLOCK_HEIGHT,
    getPinAnchor(component, pin, index) {
      return resolveRectPinAnchor(component, pin, index, BLOCK_WIDTH, BLOCK_HEIGHT)
    },
    render: renderUnknown,
  },
}

export function getSchematicSymbolDefinition(kind: string): SchematicSymbolDefinition {
  return symbolDefinitions[kind] ?? symbolDefinitions.unknown
}
