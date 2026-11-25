/**
 * 长城 V6-Up (v3.0) DSH 插件真接线配置解析与标准 Config 声明。
 *
 * 只暴露入口实际读取并生效的 6 项配置（彻底剔除未消费的假旋钮，避免配置面板误导用户）：
 * - `corePythonRoot`、`pythonBin`、`dataDir`
 * - `requestTimeoutMs`、`longToolTimeoutMs`
 * - `defaultAgentOptions`（provider / model / reasoningEffort）
 * @module dsh-greatwall-v6up/config
 */
import path from 'node:path'

export const DEFAULT_PLUGIN_CONFIG = Object.freeze({
  corePythonRoot: '',
  pythonBin: '',
  dataDir: '',
  requestTimeoutMs: 60_000,
  longToolTimeoutMs: 300_000,
  defaultAgentOptions: Object.freeze({}),
})

/**
 * 供 DSH Plugin Manager / Schema 工具参考的 JSON Schema 描述。
 */
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

/**
 * 符合 Standard Schema v1 (`~standard.validate`) 的零依赖插件 Config 校验器。
 * 直接对齐 DSH 0.2.2-rc.5 内置 Cordis 4.1.0 `resolveConfig` 的同步校验协议：
 * - 合法配置返回 `{ value }`（带完整默认值与规范化数值）；
 * - 非法类型返回 `{ issues: [{ message, path }] }`，避免装载阶段抛 `Cannot read properties of undefined (reading 'validate')`。
 */
export const Config = Object.freeze({
  ...CONFIG_SCHEMA_DESCRIPTOR,
  '~standard': Object.freeze({
    version: 1,
    vendor: 'dsh-greatwall-v6up',
    validate(input) {
      const raw = input === undefined || input === null ? {} : input
      if (typeof raw !== 'object' || Array.isArray(raw)) {
        return {
          issues: [{ message: 'dsh-greatwall-v6up 配置必须为对象', path: [] }],
        }
      }
      const issues = []
      for (const strKey of ['corePythonRoot', 'pythonBin', 'dataDir']) {
        const val = raw[strKey]
        if (val !== undefined && typeof val !== 'string') {
          issues.push({ message: `${strKey} 必须为字符串`, path: [strKey] })
        }
      }
      for (const numKey of ['requestTimeoutMs', 'longToolTimeoutMs']) {
        const val = raw[numKey]
        if (val !== undefined && (typeof val !== 'number' || !Number.isFinite(val) || val <= 0)) {
          issues.push({ message: `${numKey} 必须为正有限数字`, path: [numKey] })
        }
      }
      if (raw.defaultAgentOptions !== undefined) {
        if (!raw.defaultAgentOptions || typeof raw.defaultAgentOptions !== 'object' || Array.isArray(raw.defaultAgentOptions)) {
          issues.push({ message: 'defaultAgentOptions 必须为对象', path: ['defaultAgentOptions'] })
        } else {
          for (const subKey of ['provider', 'model', 'reasoningEffort']) {
            const sv = raw.defaultAgentOptions[subKey]
            if (sv !== undefined && typeof sv !== 'string') {
              issues.push({
                message: `defaultAgentOptions.${subKey} 必须为字符串`,
                path: ['defaultAgentOptions', subKey],
              })
            }
          }
        }
      }
      if (issues.length > 0) {
        return { issues }
      }
      const requestTimeoutMs =
        raw.requestTimeoutMs !== undefined
          ? Math.floor(raw.requestTimeoutMs)
          : DEFAULT_PLUGIN_CONFIG.requestTimeoutMs
      const longToolTimeoutMs = Math.max(
        requestTimeoutMs,
        raw.longToolTimeoutMs !== undefined
          ? Math.floor(raw.longToolTimeoutMs)
          : DEFAULT_PLUGIN_CONFIG.longToolTimeoutMs,
      )
      return {
        value: {
          corePythonRoot: typeof raw.corePythonRoot === 'string' ? raw.corePythonRoot.trim() : '',
          pythonBin: typeof raw.pythonBin === 'string' ? raw.pythonBin.trim() : '',
          dataDir: typeof raw.dataDir === 'string' ? raw.dataDir.trim() : '',
          requestTimeoutMs,
          longToolTimeoutMs,
          defaultAgentOptions: sanitizeAgentOptions(raw.defaultAgentOptions),
        },
      }
    },
  }),
})

/**
 * 解析并规范化插件运行时配置（只保留真接线字段）。
 * @param {Record<string, any>} [rawConfig]
 * @param {string} defaultCorePythonRoot
 */
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
  const defaultAgentOptions = sanitizeAgentOptions(src.defaultAgentOptions)

  return {
    corePythonRoot,
    pythonBin,
    dataDir,
    requestTimeoutMs,
    longToolTimeoutMs,
    defaultAgentOptions,
  }
}
