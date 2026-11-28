/**
 * GreatWall v0.3 DSH 插件配置解析与动态 Config Schema（裁决 6）。
 *
 * - 优先动态探测宿主 `@deepseek-ai/schemastery`，原生支持 DSH Plugin Manager 自动表单渲染；
 * - 独立单测或无宿主环境时自动平滑回退至零依赖 Standard Schema v1 (`~standard.validate`)。
 * @module dsh-greatwall-v6up/config
 */
import path from 'node:path'

export const DEFAULT_PLUGIN_CONFIG = Object.freeze({
  corePythonRoot: '',
  pythonBin: '',
  dataDir: '',
  requestTimeoutMs: 60_000,
  longToolTimeoutMs: 300_000,
  chiefAnchorHardCapChars: 2400,
  maxEffectiveContextWindow: 360_000,
  contextHolidayPct: 0.52,
  defaultAgentOptions: Object.freeze({}),
})

export const CONFIG_SCHEMA_DESCRIPTOR = Object.freeze({
  type: 'object',
  properties: {
    corePythonRoot: {
      type: 'string',
      default: '',
      description: '可选：覆盖内置 core_python 内核根目录路径。',
    },
    pythonBin: {
      type: 'string',
      default: '',
      description: '可选：指定运行 Python MCP 内核的可执行文件路径（留空默认使用系统 python）。',
    },
    dataDir: {
      type: 'string',
      default: '',
      description: '可选：覆写长城持久化数据目录（默认 ~/.dsh/greatwall-v6up）。',
    },
    requestTimeoutMs: {
      type: 'number',
      default: 60_000,
      description: '常规只读/短事务 MCP 调用超时（毫秒，默认 60000）。',
    },
    longToolTimeoutMs: {
      type: 'number',
      default: 300_000,
      description: '长耗时仪器评测、校准集回归与 Stage 3 导出超时（毫秒，默认 300000）。',
    },
    chiefAnchorHardCapChars: {
      type: 'number',
      default: DEFAULT_PLUGIN_CONFIG.chiefAnchorHardCapChars,
      description: 'gw-chief 现况锚点卡字数上限，按子题数在上限内伸缩。',
    },
    maxEffectiveContextWindow: {
      type: 'number', default: DEFAULT_PLUGIN_CONFIG.maxEffectiveContextWindow,
      description: '单班岗上下文窗口上限（tokens），仍受模型物理窗口约束。',
    },
    contextHolidayPct: {
      type: 'number', default: DEFAULT_PLUGIN_CONFIG.contextHolidayPct,
      description: '夜科学停码水位，允许 0.42–0.62。',
    },
    defaultAgentOptions: {
      type: 'object',
      default: {},
      description: '可选：子会话默认模型参数（provider / model / reasoningEffort）。',
    },
  },
})

function sanitizePositiveInt(val, fallback) {
  const n = Number(val)
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : fallback
}

function sanitizeAgentOptions(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}
  const out = {}
  if (typeof raw.provider === 'string' && raw.provider.trim()) out.provider = raw.provider.trim()
  if (typeof raw.model === 'string' && raw.model.trim()) out.model = raw.model.trim()
  if (typeof raw.reasoningEffort === 'string' && raw.reasoningEffort.trim()) {
    out.reasoningEffort = raw.reasoningEffort.trim()
  }
  return out
}

function validateFallbackStandardSchema(input) {
  const raw = input === undefined || input === null ? {} : input
  if (typeof raw !== 'object' || Array.isArray(raw)) {
    return { issues: [{ message: 'dsh-greatwall-v6up 配置必须为对象', path: [] }] }
  }
  const issues = []
  for (const strKey of ['corePythonRoot', 'pythonBin', 'dataDir']) {
    const val = raw[strKey]
    if (val !== undefined && typeof val !== 'string') {
      issues.push({ message: `${strKey} 必须为字符串`, path: [strKey] })
    }
  }
  for (const numKey of ['requestTimeoutMs', 'longToolTimeoutMs', 'chiefAnchorHardCapChars', 'maxEffectiveContextWindow']) {
    const val = raw[numKey]
    if (val !== undefined && (typeof val !== 'number' || !Number.isFinite(val) || val <= 0)) {
      issues.push({ message: `${numKey} 必须为正有限数字`, path: [numKey] })
    }
  }
  if (raw.contextHolidayPct !== undefined && (
    typeof raw.contextHolidayPct !== 'number' || !(raw.contextHolidayPct >= 0.42 && raw.contextHolidayPct <= 0.62)
  )) issues.push({ message: 'contextHolidayPct 须在 0.42–0.62', path: ['contextHolidayPct'] })
  if (raw.defaultAgentOptions !== undefined) {
    if (!raw.defaultAgentOptions || typeof raw.defaultAgentOptions !== 'object' || Array.isArray(raw.defaultAgentOptions)) {
      issues.push({ message: 'defaultAgentOptions 必须为对象', path: ['defaultAgentOptions'] })
    } else {
      for (const subKey of ['provider', 'model', 'reasoningEffort']) {
        const sv = raw.defaultAgentOptions[subKey]
        if (sv !== undefined && typeof sv !== 'string') {
          issues.push({ message: `defaultAgentOptions.${subKey} 必须为字符串`, path: ['defaultAgentOptions', subKey] })
        }
      }
    }
  }
  if (issues.length > 0) return { issues }

  const requestTimeoutMs = raw.requestTimeoutMs !== undefined
    ? Math.floor(raw.requestTimeoutMs)
    : DEFAULT_PLUGIN_CONFIG.requestTimeoutMs
  const longToolTimeoutMs = Math.max(
    requestTimeoutMs,
    raw.longToolTimeoutMs !== undefined ? Math.floor(raw.longToolTimeoutMs) : DEFAULT_PLUGIN_CONFIG.longToolTimeoutMs,
  )
  const chiefAnchorHardCapChars = Math.max(
    400,
    raw.chiefAnchorHardCapChars !== undefined
      ? Math.floor(raw.chiefAnchorHardCapChars)
      : DEFAULT_PLUGIN_CONFIG.chiefAnchorHardCapChars,
  )
  return {
    value: {
      corePythonRoot: typeof raw.corePythonRoot === 'string' ? raw.corePythonRoot.trim() : '',
      pythonBin: typeof raw.pythonBin === 'string' ? raw.pythonBin.trim() : '',
      dataDir: typeof raw.dataDir === 'string' ? raw.dataDir.trim() : '',
      requestTimeoutMs,
      longToolTimeoutMs,
      chiefAnchorHardCapChars,
      maxEffectiveContextWindow: Math.floor(raw.maxEffectiveContextWindow ?? DEFAULT_PLUGIN_CONFIG.maxEffectiveContextWindow),
      contextHolidayPct: raw.contextHolidayPct ?? DEFAULT_PLUGIN_CONFIG.contextHolidayPct,
      defaultAgentOptions: sanitizeAgentOptions(raw.defaultAgentOptions),
    },
  }
}

const FALLBACK_STANDARD_CONFIG = Object.freeze({
  ...CONFIG_SCHEMA_DESCRIPTOR,
  '~standard': Object.freeze({
    version: 1,
    vendor: 'dsh-greatwall-v6up',
    validate: validateFallbackStandardSchema,
  }),
})

let _resolvedConfig = FALLBACK_STANDARD_CONFIG
let _configBackend = 'standard-schema-v1'

try {
  const mod = await import('@deepseek-ai/schemastery')
  const Schema = mod?.default || mod?.Schema || mod
  if (Schema && typeof Schema.object === 'function') {
    _resolvedConfig = Schema.object({
      corePythonRoot: Schema.string().default('').description(CONFIG_SCHEMA_DESCRIPTOR.properties.corePythonRoot.description),
      pythonBin: Schema.string().default('').description(CONFIG_SCHEMA_DESCRIPTOR.properties.pythonBin.description),
      dataDir: Schema.string().default('').description(CONFIG_SCHEMA_DESCRIPTOR.properties.dataDir.description),
      requestTimeoutMs: Schema.number().min(1000).default(60_000).description(CONFIG_SCHEMA_DESCRIPTOR.properties.requestTimeoutMs.description),
      longToolTimeoutMs: Schema.number().min(1000).default(300_000).description(CONFIG_SCHEMA_DESCRIPTOR.properties.longToolTimeoutMs.description),
      chiefAnchorHardCapChars: Schema.number().min(400).max(4000).default(DEFAULT_PLUGIN_CONFIG.chiefAnchorHardCapChars)
        .description(CONFIG_SCHEMA_DESCRIPTOR.properties.chiefAnchorHardCapChars.description),
      maxEffectiveContextWindow: Schema.number().min(1).default(DEFAULT_PLUGIN_CONFIG.maxEffectiveContextWindow)
        .description(CONFIG_SCHEMA_DESCRIPTOR.properties.maxEffectiveContextWindow.description),
      contextHolidayPct: Schema.number().min(0.42).max(0.62).default(DEFAULT_PLUGIN_CONFIG.contextHolidayPct)
        .description(CONFIG_SCHEMA_DESCRIPTOR.properties.contextHolidayPct.description),
      defaultAgentOptions: Schema.object({
        provider: Schema.string().description('默认模型提供方'),
        model: Schema.string().description('默认模型 ID'),
        reasoningEffort: Schema.string().description('默认思考强度 (low / medium / high)'),
      }).default({}).description(CONFIG_SCHEMA_DESCRIPTOR.properties.defaultAgentOptions.description),
    })
    _configBackend = 'schemastery'
  }
} catch {
  // 独立测试环境无宿主 @deepseek-ai/schemastery，自动使用零依赖 Standard Schema v1 回退
}

export const CONFIG_SCHEMA_BACKEND = _configBackend
export const Config = _resolvedConfig

export function resolvePluginConfig(rawConfig = {}, defaultCorePythonRoot = '') {
  const src = rawConfig && typeof rawConfig === 'object' ? rawConfig : {}
  const coreRootRaw = typeof src.corePythonRoot === 'string' ? src.corePythonRoot.trim() : ''
  const corePythonRoot = coreRootRaw ? path.resolve(coreRootRaw) : path.resolve(defaultCorePythonRoot || '.')
  const pythonBin = typeof src.pythonBin === 'string' ? src.pythonBin.trim() : ''
  const dataDir = typeof src.dataDir === 'string' ? src.dataDir.trim() : ''
  const requestTimeoutMs = sanitizePositiveInt(src.requestTimeoutMs, DEFAULT_PLUGIN_CONFIG.requestTimeoutMs)
  const longToolTimeoutMs = Math.max(
    requestTimeoutMs,
    sanitizePositiveInt(src.longToolTimeoutMs, DEFAULT_PLUGIN_CONFIG.longToolTimeoutMs),
  )
  const chiefAnchorHardCapChars = Math.max(
    400,
    sanitizePositiveInt(src.chiefAnchorHardCapChars, DEFAULT_PLUGIN_CONFIG.chiefAnchorHardCapChars),
  )
  const defaultAgentOptions = sanitizeAgentOptions(src.defaultAgentOptions)

  return {
    corePythonRoot,
    pythonBin,
    dataDir,
    requestTimeoutMs,
    longToolTimeoutMs,
    chiefAnchorHardCapChars,
    maxEffectiveContextWindow: sanitizePositiveInt(src.maxEffectiveContextWindow, DEFAULT_PLUGIN_CONFIG.maxEffectiveContextWindow),
    contextHolidayPct: src.contextHolidayPct ?? DEFAULT_PLUGIN_CONFIG.contextHolidayPct,
    defaultAgentOptions,
  }
}
