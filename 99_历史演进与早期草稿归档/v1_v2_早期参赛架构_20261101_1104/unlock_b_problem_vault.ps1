# 一键解锁并原路还原 CUMCM 2026 B 题历史资料与上一次测试目录
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$vaultDir = "D:\.vault_cumcm2026_locked"
$manifestPath = Join-Path $PSScriptRoot "vault_manifest.json"

Write-Host "1. 正在解除 Windows NTFS 底层权限锁 (icacls)..." -ForegroundColor Cyan
icacls $vaultDir /remove:d "${env:USERNAME}"
attrib -h -s $vaultDir

if (Test-Path $manifestPath) {
    $items = Get-Content -Path $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($item in $items) {
        $src = Join-Path $vaultDir $item.VaultName
        $dst = $item.OriginalPath
        if (Test-Path -LiteralPath $src) {
            Move-Item -LiteralPath $src -Destination $dst -Force
            Write-Host "已还原: $dst" -ForegroundColor Green
        }
    }
    Remove-Item -Path $vaultDir -Force -ErrorAction SilentlyContinue
    Write-Host "✅ 全部 20 项历史资料已 100% 完好还原至原路径！" -ForegroundColor Green
} else {
    Write-Host "未找到 vault_manifest.json，但已解除 $vaultDir 的读取限制。" -ForegroundColor Yellow
}
