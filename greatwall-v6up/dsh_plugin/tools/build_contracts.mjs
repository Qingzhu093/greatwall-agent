import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const projectRoot = fileURLToPath(new URL('../../', import.meta.url))
const output = new URL('../lib/contracts.generated.json', import.meta.url)
const code = [
  'import json',
  'from core_python.mcp_server.tool_registry import export_contracts_snapshot',
  'print(json.dumps(export_contracts_snapshot(), indent=2))',
].join('\n')
const snapshot = execFileSync(process.env.GREATWALL_PYTHON || 'python', ['-c', code], {
  cwd: projectRoot,
  encoding: 'utf8',
}).replace(/\r\n/g, '\n')
fs.writeFileSync(output, snapshot)
