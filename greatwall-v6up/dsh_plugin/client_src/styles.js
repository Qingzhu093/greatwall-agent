/** GreatWall v0.3 右侧科研指挥舱纯 --dsw-alias-* 主题样式（零外部 UI 依赖，适配 390px 窄屏）。 */
const TAB_ID = "dsh-greatwall-v6up";
const TAB_KIND = "greatwall";
const STATUS_API = "/api/greatwall.status";
const CONTROL_API = "/api/greatwall.control";

const CSS_TEXT = [
  ".gw-operator { padding: 10px; }",
  ".gw-operator fieldset { display: grid; gap: 6px; margin-bottom: 10px; }",
  ".gw-operator label { display: grid; grid-template-columns: minmax(85px, 1fr) minmax(125px, 1.5fr); align-items: center; gap: 8px; }",
  ".gw-operator input:not([type=checkbox]) { min-width: 0; max-width: 100%; }",
  ".gw-operator li { overflow-wrap: anywhere; margin: 4px 0; }",
  ".gw-root{box-sizing:border-box;display:flex;flex-direction:column;height:100%;overflow:hidden;color:var(--dsw-alias-label-primary);font-size:12px;line-height:1.45}",
  ".gw-hdr{display:flex;align-items:center;justify-content:space-between;gap:6px;padding:8px 10px;border-bottom:1px solid var(--dsw-alias-border-l4);flex:none;flex-wrap:wrap}",
  ".gw-title-wrap{display:flex;align-items:center;flex-wrap:wrap;gap:5px;min-width:0}",
  ".gw-badge{display:inline-flex;align-items:center;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:600;border:1px solid var(--dsw-alias-border-l3);background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary)}",
  ".gw-b-run{color:#16a34a;border-color:rgba(22,163,74,.38);background:rgba(22,163,74,.1)}",
  ".gw-b-warn{color:#d97706;border-color:rgba(217,119,6,.38);background:rgba(217,119,6,.1)}",
  ".gw-b-err{color:#dc2626;border-color:rgba(220,38,38,.38);background:rgba(220,38,38,.1)}",
  ".gw-b-info{color:#2563eb;border-color:rgba(37,99,235,.38);background:rgba(37,99,235,.1)}",
  ".gw-actions{display:flex;flex-wrap:wrap;gap:4px}",
  ".gw-btn{cursor:pointer;border:1px solid var(--dsw-alias-border-l3);background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);border-radius:7px;padding:3px 8px;font-size:11px;font-weight:500}",
  ".gw-btn:hover{background:var(--dsw-alias-interactive-bg-hover)}",
  ".gw-btn:disabled{opacity:.45;cursor:not-allowed}",
  ".gw-btn-pri{color:#2563eb;border-color:rgba(37,99,235,.4);background:rgba(37,99,235,.08)}",
  ".gw-btn-ok{color:#16a34a;border-color:rgba(22,163,74,.4);background:rgba(22,163,74,.08)}",
  ".gw-btn-danger{color:#dc2626;border-color:rgba(220,38,38,.4)}",
  ".gw-tabs{display:flex;gap:4px;padding:6px 10px;border-bottom:1px solid var(--dsw-alias-border-l4);background:var(--dsw-alias-bg-layer-1);flex:none;overflow-x:auto}",
  ".gw-tab{cursor:pointer;border:1px solid transparent;border-radius:6px;padding:3px 9px;font-size:11px;font-weight:600;color:var(--dsw-alias-label-secondary);background:transparent;white-space:nowrap}",
  ".gw-tab-on{color:#2563eb;border-color:rgba(37,99,235,.35);background:rgba(37,99,235,.08)}",
  ".gw-scroll{flex:1;overflow-y:auto;padding:9px 10px;display:flex;flex-direction:column;gap:9px}",
  ".gw-card{border:1px solid var(--dsw-alias-border-l4);background:var(--dsw-alias-bg-layer-1);border-radius:9px;padding:8px 10px;display:flex;flex-direction:column;gap:6px}",
  ".gw-card-hd{font-size:11px;font-weight:600;color:var(--dsw-alias-label-secondary);display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap}",
  ".gw-row{display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap}",
  ".gw-item{border:1px solid var(--dsw-alias-border-l4);border-radius:8px;padding:7px 8px;background:var(--dsw-alias-bg-layer-2);display:flex;flex-direction:column;gap:4px}",
  ".gw-mono{font-family:var(--dsw-font-mono,ui-monospace,monospace);font-size:11px;word-break:break-all}",
  ".gw-muted{color:var(--dsw-alias-label-tertiary);font-size:11px}",
  ".gw-pre{margin:0;padding:7px 8px;border-radius:7px;background:var(--dsw-alias-bg-layer-2);border:1px solid var(--dsw-alias-border-l4);font-family:var(--dsw-font-mono,ui-monospace,monospace);font-size:11px;white-space:pre-wrap;word-break:break-word;max-height:240px;overflow-y:auto}",
  ".gw-select{box-sizing:border-box;width:100%;border:1px solid var(--dsw-alias-border-l3);background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary);border-radius:7px;padding:4px 7px;font-size:11px}",
  ".gw-bar{position:relative;height:6px;border-radius:999px;background:var(--dsw-alias-fill-l2,rgba(128,128,128,.2));overflow:hidden}",
  ".gw-bar-fill{height:100%;border-radius:999px;background:#2563eb;transition:width .2s ease}",
  ".gw-tree-q{border:1px solid var(--dsw-alias-border-l4);border-radius:8px;padding:7px 8px;background:var(--dsw-alias-bg-layer-1);display:flex;flex-direction:column;gap:6px}",
  ".gw-tree-fam{border-left:2px solid var(--dsw-alias-border-l3);padding-left:8px;margin-left:3px;display:flex;flex-direction:column;gap:5px}",
  ".gw-tree-node{border:1px solid var(--dsw-alias-border-l4);border-radius:7px;padding:6px 8px;background:var(--dsw-alias-bg-layer-2);display:flex;flex-direction:column;gap:4px}",
  ".gw-pulse{display:inline-block;width:7px;height:7px;border-radius:50%;background:#16a34a;margin-right:4px}",
  ".gw-summary{font-size:12px;color:var(--dsw-alias-label-primary);white-space:pre-wrap;word-break:break-word}",
  ".gw-link-btn{cursor:pointer;border:none;background:transparent;color:#2563eb;padding:0;font-size:11px;text-align:left}",
  ".gw-banner{display:flex;align-items:center;justify-content:space-between;gap:6px;padding:5px 10px;font-size:11px;border-bottom:1px solid var(--dsw-alias-border-l4)}",
  ".gw-banner-ok{color:#15803d;background:rgba(22,163,74,.08)}",
  ".gw-banner-err{color:#dc2626;background:rgba(220,38,38,.08)}",
  ".gw-banner-info{color:#2563eb;background:rgba(37,99,235,.06)}",
  ".gw-confirm-bar{display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap;padding:6px 10px;font-size:11px;color:#b91c1c;background:rgba(220,38,38,.08);border-bottom:1px solid rgba(220,38,38,.3)}"
].join("");

function mountConsoleStyles() {
  if (typeof document === "undefined") return () => {};
  const existing = document.querySelector('style[data-plugin-css="dsh-greatwall-v6up/console"]');
  if (existing) {
    existing.textContent = CSS_TEXT;
    return () => { try { existing.remove(); } catch {} };
  }
  const tag = document.createElement("style");
  tag.dataset.plugin = TAB_ID;
  tag.dataset.pluginCss = "dsh-greatwall-v6up/console";
  tag.textContent = CSS_TEXT;
  document.head.appendChild(tag);
  return () => { try { tag.remove(); } catch {} };
}

function stateBadgeClass(st) {
  const s = String(st || "").toUpperCase();
  if (s.includes("RUN") || s === "DISPATCHING" || s === "STOPPED_SOLVED" || s === "CLOSED_VERIFIED" || s === "APPROVED_EXECUTED") return "gw-badge gw-b-run";
  if (s.includes("PAUSE") || s.includes("DRAIN") || s.includes("HUMAN") || s.includes("PENDING") || s.includes("BLOCKED") || s === "EARLY_HANDOFF_READY") return "gw-badge gw-b-warn";
  if (s.includes("ERR") || s.includes("FAIL") || s.includes("REFUTED") || s === "UNHEALTHY") return "gw-badge gw-b-err";
  return "gw-badge gw-b-info";
}

function readablePoolState(st) {
  const s = String(st || "").toLowerCase();
  if (s === "running") return "全面托管中";
  if (s === "paused") return "等待人类接管";
  if (s === "starting") return "启动中";
  if (s === "idle") return "空闲待命";
  if (s === "stopped") return "已停止";
  if (s === "archived") return "历史归档";
  if (s === "error") return "异常停摆";
  return s || "未知";
}

function readableStage(st) {
  const s = String(st || "").toUpperCase();
  if (s === "STAGE1_PARSE0") return "Stage 1 · 立项准备";
  if (s === "STAGE2_EVOLVE") return "Stage 2 · 攻坚演化";
  if (s === "STAGE3_CONSOLIDATE" || s === "STAGE3_DELIVER") return "Stage 3 · 终稿核验";
  if (s === "CLOSED_VERIFIED") return "已验收结题";
  return s || "";
}

function readableControlState(st) {
  const s = String(st || "").toUpperCase();
  if (s === "AUTO_RUNNING") return "自动托管";
  if (s === "PAUSE_DRAINING") return "让权收尾中";
  if (s === "DRAIN_AFTER_TURN") return "当前回合收尾中";
  if (s === "DRAIN_AFTER_HANDOFF") return "本班交班收尾中";
  if (s === "HUMAN_ACTIVE") return "人工接管 · 0 槽";
  if (s === "HIBERNATED") return "已休眠 · 0 槽";
  if (s === "EARLY_HANDOFF_READY") return "已授权提前交班";
  return s || "";
}

function readableDispatchState(st) {
  const s = String(st || "").toUpperCase();
  if (s === "DISPATCHING") return "攻关中";
  if (s === "PAUSED_HUMAN" || s === "PAUSED") return "人工暂停";
  if (s === "PAUSED_SATURATED") return "语义饱和待拍板";
  if (s === "PAUSED_BLOCKED") return "阻塞/预算挂起";
  if (s === "WAITING_HUMAN") return "待人类拍板";
  if (s === "STOPPED_SOLVED") return "已通关";
  if (s === "CLOSED") return "已结题";
  return s || "未知";
}

function readableReceiptStatus(status) {
  return { SETTLED: "已生效", DRAINING: "收尾中", PARTIAL_FAILED: "有失败项", SUPERSEDED: "已被覆盖" }[status] || status;
}

function readableActionLabel(act) {
  const map = {
    pause: "全局暂停（全部等待人类接管）",
    resume: "恢复全面托管",
    human_stop: "人类收工",
    pause_node: "暂停接管该分支",
    resume_node: "交还托管(SHA对账)",
    authorize_early_handoff: "授权提前交班",
    set_subproblem_state: "切换子题启停",
    set_autonomy_mode: "切换自主档位",
    approve_proposal: "审批提案",
    open_chief: "唤起科研总控"
  };
  return map[act] || act;
}

function GreatwallGlyph({ size = 16, className }) {
  return jsxs("svg", {
    width: size,
    height: size,
    viewBox: "0 0 16 16",
    fill: "none",
    "aria-hidden": "true",
    className,
    children: [
      jsx("path", { d: "M2 13V6h2v2h2V5h4v3h2V6h2v7H2Z", stroke: "currentColor", strokeWidth: "1.35", strokeLinejoin: "round" }),
      jsx("path", { d: "M6 13v-3h4v3", stroke: "currentColor", strokeWidth: "1.35", strokeLinejoin: "round" })
    ]
  });
}
