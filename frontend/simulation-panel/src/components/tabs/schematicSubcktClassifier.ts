import type { SchematicSubcircuitState } from '../../types/state'

/**
 * Primitive subckt classifier.
 *
 * SPICE `.subckt` definitions are sometimes just a hand-rolled macro for a
 * well-known analog primitive (typically an op-amp). The circuit author
 * does not want to see the macro's guts (a single VCVS `E1` inside a dashed
 * scope box); they want the industry-standard symbol.
 *
 * This module identifies such primitive subckts purely from the `.subckt`
 * name and its published port arity. The downstream normalizer uses the
 * result to black-box primitive instances: internal components / nets /
 * scope groups are dropped from the semantic model, and each `X` call site
 * is rewritten to render as the canonical symbol (the op-amp triangle).
 *
 * Classification is name-pattern driven. The matching rules intentionally
 * err on the side of being generous with names (any `*opamp*`, any
 * `lm###`/`ne###`/`tl###`/`uA###` family) because these names carry strong
 * industry convention and miss-classifying a passive RC network as an op-amp
 * requires a truly hostile naming scheme.
 */

export interface SchematicPrimitiveSubcktInfo {
  name: string
  scopePathKey: string
  portNames: readonly string[]
  componentIds: readonly string[]
  /**
   * Mapping from subckt port name → normalized pin role hint for the
   * synthesized primitive instance. The normalizer uses this to assign
   * semantic roles so symbol renderers pick the right anchor layout.
   */
  portRoleHints: Readonly<Record<string, 'input_plus' | 'input_minus' | 'output' | 'ground'>>
}

export type SchematicPrimitiveSubcktMap = ReadonlyMap<string, SchematicPrimitiveSubcktInfo>

const OPAMP_NAME_PATTERNS: readonly RegExp[] = [
  /^ideal[_-]?op[_-]?amp$/i,
  /^op[_-]?amp$/i,
  /^opamp\d*$/i,
  /^lm\d{2,4}[a-z]?$/i, // LM741, LM358, LM324, ...
  /^ne\d{3,4}[a-z]?$/i, // NE5532, NE5534, ...
  /^ua\d{3,4}[a-z]?$/i, // uA741, uA776, ...
  /^tl\d{2,4}[a-z]?$/i, // TL071, TL082, TL084, ...
  /^ad\d{3,4}[a-z]?$/i, // AD820, AD8066, ...
  /^opa\d{3,4}[a-z]?$/i, // OPA2134, OPA134, ...
  /^mcp\d{3,4}[a-z]?$/i, // MCP6001, ...
]

function scopePathKey(path: readonly string[]): string {
  return path.join(' / ')
}

function matchAny(name: string, patterns: readonly RegExp[]): boolean {
  return patterns.some((pattern) => pattern.test(name))
}

/**
 * Infer the external port roles of a primitive op-amp given its advertised
 * port names. The heuristic checks positional conventions first (SPICE
 * convention for op-amp subckts is `(inp, inn, out, ...)`), then falls back
 * to lexical hints on the port names themselves.
 */
function inferOpampPortRoles(
  portNames: readonly string[],
): SchematicPrimitiveSubcktInfo['portRoleHints'] {
  const roles: Record<string, 'input_plus' | 'input_minus' | 'output' | 'ground'> = {}
  for (let index = 0; index < portNames.length; index += 1) {
    const raw = portNames[index]
    const normalized = raw.trim().toLowerCase()
    if (/(^|[^a-z])(inp|in_p|in\+|vp|v\+|noninv|ninv|plus)($|[^a-z])/i.test(`-${normalized}-`) || normalized === 'inp' || normalized === 'plus') {
      roles[raw] = 'input_plus'
      continue
    }
    if (/(^|[^a-z])(inn|in_n|in-|vn|v-|inv|minus)($|[^a-z])/i.test(`-${normalized}-`) || normalized === 'inn' || normalized === 'minus') {
      roles[raw] = 'input_minus'
      continue
    }
    if (normalized === 'out' || normalized === 'output' || normalized === 'vo') {
      roles[raw] = 'output'
      continue
    }
    if (normalized === 'gnd' || normalized === 'ground' || normalized === '0') {
      roles[raw] = 'ground'
      continue
    }
    // Positional fallback: the SPICE canonical op-amp order is +, -, out.
    if (index === 0) {
      roles[raw] = 'input_plus'
    } else if (index === 1) {
      roles[raw] = 'input_minus'
    } else if (index === 2) {
      roles[raw] = 'output'
    }
  }
  return roles
}

/**
 * Decide whether a subckt definition is a recognized analog primitive.
 *
 * Returns `null` if no primitive pattern matches or if the port arity is
 * incompatible (e.g. an "opamp" with only 2 ports is almost certainly a
 * misnamed passive).
 */
function classifyOneSubckt(
  subckt: SchematicSubcircuitState,
): SchematicPrimitiveSubcktInfo | null {
  const rawName = subckt.name.trim()
  if (!rawName) {
    return null
  }
  if (matchAny(rawName, OPAMP_NAME_PATTERNS) && subckt.port_names.length >= 3) {
    return {
      name: rawName,
      scopePathKey: scopePathKey([...subckt.scope_path, subckt.name]),
      portNames: subckt.port_names,
      componentIds: subckt.component_ids,
      portRoleHints: inferOpampPortRoles(subckt.port_names),
    }
  }
  return null
}

export function classifySchematicPrimitiveSubckts(
  subcircuits: readonly SchematicSubcircuitState[],
): SchematicPrimitiveSubcktMap {
  const map = new Map<string, SchematicPrimitiveSubcktInfo>()
  for (const subckt of subcircuits) {
    const info = classifyOneSubckt(subckt)
    if (info) {
      map.set(info.scopePathKey, info)
    }
  }
  return map
}

/**
 * Renderer's canonical `symbol_kind` tag for every primitive subckt. Every
 * match currently maps to the op-amp triangle — the only primitive symbol
 * this build recognizes. Keeping this indirection isolated means adding a
 * new primitive (e.g. a real comparator glyph) happens in exactly one place.
 */
export const PRIMITIVE_SYMBOL_KIND = 'opamp'
