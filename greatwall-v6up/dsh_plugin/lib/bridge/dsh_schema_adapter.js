/**
 * DSH 0.2.2-rc.5 严格 JSON Schema 子集适配器（确定性无损映射 · Fail-Closed）。
 *
 * 精确覆盖 RC5 严格消费路径（`packages/core/tools/src/json-schema.ts`、PTC 类型生成与严格模型路由）：
 * 1. 支持可空单类型联合 `type: [T, "null"]`（顺序无关）→ `oneOf: [branchT, { type: "null" }]`；
 *    - 自动将同层 `enum`（移除 null 后）迁入标量分支（修正 `read_depth` / `support_scope` / `l3_entry_kind` / `goal_coverage`）；
 *    - 自动将同层 `items` 递归规范化后迁入 `array` 分支（修正 `fulfilled_request_ids` / `revision_requests`）；
 *    - 自动将同层 `properties` / `required` / `additionalProperties` 迁入 `object` 分支；
 * 2. 剥离 RC5 子集禁止的校验关键字（`minLength` / `maxLength` / `minimum` / `maximum` / `minItems` / `maxItems` / `pattern`）
 *    并将约束摘要无损拼入 `description`（由 Python 服务端 handler 强制执行对应校验）；
 * 3. Fail-Closed：遇到无法等价映射的联合类型（如 `["integer", "number"]` 重叠语义或多于一个非空类型）
 *    立即抛出含 `toolName` 与 `fieldPath` 的明确错误，绝不静默改写语义。
 * @module dsh-greatwall-v6up/bridge/dsh_schema_adapter
 */

export const STRIPPED_CONSTRAINT_KEYS = Object.freeze([
  'minLength',
  'maxLength',
  'minimum',
  'maximum',
  'minItems',
  'maxItems',
  'pattern',
])

const SCALAR_TYPES = new Set(['string', 'number', 'integer', 'boolean'])
const ALLOWED_PRIMITIVE_TYPES = new Set(['string', 'number', 'integer', 'boolean', 'array', 'object', 'null'])

function formatConstraintHints(node) {
  const hints = []
  if (node.minLength !== undefined) hints.push(`minLength=${node.minLength}`)
  if (node.maxLength !== undefined) hints.push(`maxLength=${node.maxLength}`)
  if (node.minimum !== undefined) hints.push(`minimum=${node.minimum}`)
  if (node.maximum !== undefined) hints.push(`maximum=${node.maximum}`)
  if (node.minItems !== undefined) hints.push(`minItems=${node.minItems}`)
  if (node.maxItems !== undefined) hints.push(`maxItems=${node.maxItems}`)
  if (node.pattern !== undefined) hints.push(`pattern=${node.pattern}`)
  return hints
}

function appendHintsToDescription(desc, hints) {
  const base = String(desc || '').trim()
  if (!hints.length) return base || undefined
  const suffix = `[constraints: ${hints.join(', ')}]`
  if (!base) return suffix
  return base.includes(suffix) ? base : `${base} ${suffix}`
}

function normalizeNode(raw, { toolName, path }) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error(`DSH Schema 适配失败 (${toolName || 'unknown'}:${path}): Schema 节点必须为对象`)
  }

  const node = { ...raw }
  const hints = formatConstraintHints(node)
  for (const k of STRIPPED_CONSTRAINT_KEYS) {
    delete node[k]
  }
  const mergedDesc = appendHintsToDescription(node.description, hints)
  if (mergedDesc !== undefined) {
    node.description = mergedDesc
  }

  // 1) 处理联合类型 `type: [...]`
  if (Array.isArray(node.type)) {
    const uniqueTypes = [...new Set(node.type.map((t) => String(t)))]
    for (const t of uniqueTypes) {
      if (!ALLOWED_PRIMITIVE_TYPES.has(t)) {
        throw new Error(`DSH Schema 适配失败 (${toolName}:${path}): 含未知 JSON Schema 类型 ${t}`)
      }
    }
    const hasNull = uniqueTypes.includes('null')
    const nonNullTypes = uniqueTypes.filter((t) => t !== 'null')

    if (!hasNull || nonNullTypes.length !== 1) {
      throw new Error(
        `DSH Schema 适配失败 (${toolName}:${path}): 仅支持单一非空类型与 null 的可空联合，无法无损映射 type=${JSON.stringify(uniqueTypes)}`,
      )
    }

    const primaryType = nonNullTypes[0]
    const primaryBranch = { type: primaryType }

    // 必须将类型专属关键字迁入主分支，严禁留在 oneOf 同层（否则被 RC5 ONE_OF_SIBLING_KEYWORDS 拒收）
    if (node.enum !== undefined) {
      if (!SCALAR_TYPES.has(primaryType)) {
        throw new Error(`DSH Schema 适配失败 (${toolName}:${path}): 非标量类型 ${primaryType} 不可携带 enum`)
      }
      const filteredEnum = Array.isArray(node.enum) ? node.enum.filter((v) => v !== null) : []
      if (filteredEnum.length > 0) {
        primaryBranch.enum = filteredEnum
      }
      delete node.enum
    }

    if (node.items !== undefined) {
      if (primaryType !== 'array') {
        throw new Error(`DSH Schema 适配失败 (${toolName}:${path}): 非 array 类型 ${primaryType} 不可携带 items`)
      }
      primaryBranch.items = normalizeNode(node.items, { toolName, path: `${path}.items` })
      delete node.items
    } else if (primaryType === 'array') {
      // Fail-Closed：array 必须显式声明 items，严禁悄悄补 { type: 'string' } 扭曲契约
      throw new Error(`DSH Schema 适配失败 (${toolName}:${path}): array 分支缺少必需的 items 声明`)
    }

    if (primaryType === 'object') {
      if (node.properties !== undefined) {
        const normProps = {}
        for (const [k, v] of Object.entries(node.properties)) {
          normProps[k] = normalizeNode(v, { toolName, path: `${path}.properties.${k}` })
        }
        primaryBranch.properties = normProps
        delete node.properties
      }
      if (node.required !== undefined) {
        primaryBranch.required = [...node.required]
        delete node.required
      }
      if (node.additionalProperties !== undefined) {
        primaryBranch.additionalProperties =
          typeof node.additionalProperties === 'boolean'
            ? node.additionalProperties
            : normalizeNode(node.additionalProperties, { toolName, path: `${path}.additionalProperties` })
        delete node.additionalProperties
      } else {
        primaryBranch.additionalProperties = true
      }
    }

    const out = {}
    if (node.description !== undefined) out.description = node.description
    if (node.default !== undefined) out.default = node.default
    out.oneOf = [primaryBranch, { type: 'null' }]
    return out
  }

  // 2) 非联合类型节点递归规整
  if (node.oneOf !== undefined) {
    if (!Array.isArray(node.oneOf) || node.oneOf.length === 0) {
      throw new Error(`DSH Schema 适配失败 (${toolName}:${path}): oneOf 必须为非空数组`)
    }
    // 禁止同层夹带 enum/items/properties/type 等与 oneOf 互斥的关键字
    for (const badSibling of ['type', 'enum', 'items', 'properties', 'required']) {
      if (node[badSibling] !== undefined) {
        throw new Error(`DSH Schema 适配失败 (${toolName}:${path}): oneOf 同层不可并存关键字 ${badSibling}`)
      }
    }
    node.oneOf = node.oneOf.map((branch, idx) =>
      normalizeNode(branch, { toolName, path: `${path}.oneOf[${idx}]` }),
    )
    return node
  }

  if (node.type === 'object') {
    if (node.properties && typeof node.properties === 'object') {
      const normProps = {}
      for (const [k, v] of Object.entries(node.properties)) {
        normProps[k] = normalizeNode(v, { toolName, path: `${path}.properties.${k}` })
      }
      node.properties = normProps
    } else if (node.additionalProperties === undefined) {
      node.additionalProperties = true
    }
    if (node.additionalProperties && typeof node.additionalProperties === 'object') {
      node.additionalProperties = normalizeNode(node.additionalProperties, {
        toolName,
        path: `${path}.additionalProperties`,
      })
    }
  } else if (node.type === 'array') {
    if (node.items !== undefined) {
      node.items = normalizeNode(node.items, { toolName, path: `${path}.items` })
    } else {
      throw new Error(`DSH Schema 适配失败 (${toolName}:${path}): array 节点缺少必需的 items 声明`)
    }
  }

  return node
}

/**
 * 将原始工具 JSON Schema 规范化为 DSH 0.2.2-rc.5 严格子集。
 * @param {object} rawSchema
 * @param {{ toolName?: string }} [opts]
 */
export function normalizeSchemaForDsh(rawSchema, { toolName = '' } = {}) {
  if (!rawSchema || typeof rawSchema !== 'object') {
    return { type: 'object', properties: {} }
  }
  return normalizeNode(rawSchema, { toolName: toolName || 'unknown', path: '$' })
}
