/** GreatWall v0.3 前端 API 适配器与工作区会话直达助手。 */
const WS_STORAGE_KEY = "dsh-greatwall-v6up:selectedWs";

function readPersistedWs() {
  try {
    return typeof window !== "undefined" && window.sessionStorage
      ? String(window.sessionStorage.getItem(WS_STORAGE_KEY) || "")
      : "";
  } catch {
    return "";
  }
}

function persistSelectedWs(ws) {
  try {
    if (typeof window !== "undefined" && window.sessionStorage && ws) {
      window.sessionStorage.setItem(WS_STORAGE_KEY, String(ws));
    }
  } catch {}
}

async function fetchGreatwallStatus({ workspaceRoot = "", sessionId = "", selectedNodeId = "" } = {}) {
  const qs = new URLSearchParams();
  if (workspaceRoot) qs.set("workspaceRoot", workspaceRoot);
  if (sessionId) qs.set("sessionId", sessionId);
  if (selectedNodeId) qs.set("selectedNodeId", selectedNodeId);
  const res = await fetch(`${STATUS_API}?${qs.toString()}`, { cache: "no-store" });
  return res.json();
}

async function postGreatwallControl(action, payload = {}) {
  const res = await fetch(CONTROL_API, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action, ...payload })
  });
  return res.json();
}

function openNativeSession(getUiWorkspace, sessionId, onFeedback = null) {
  if (!sessionId) {
    if (typeof onFeedback === "function") onFeedback("未找到目标会话 ID，无法打开对话。");
    return false;
  }
  try {
    const uiWs = typeof getUiWorkspace === "function" ? getUiWorkspace() : null;
    if (uiWs && typeof uiWs.openSession === "function") {
      const ret = uiWs.openSession(sessionId);
      if (ret && typeof ret.catch === "function") {
        ret.catch((err) => {
          if (typeof onFeedback === "function") {
            onFeedback(`打开会话 ${sessionId} 失败：${String(err?.message || err)}（请检查左侧归档区或刷新面板）`);
          }
        });
      }
      return true;
    }
    if (typeof onFeedback === "function") {
      onFeedback(`当前宿主未暴露 uiWorkspace.openSession，无法直接跳转会话 ${sessionId}。`);
    }
  } catch (err) {
    if (typeof onFeedback === "function") {
      onFeedback(`打开会话 ${sessionId} 异常：${String(err?.message || err)}`);
    }
  }
  return false;
}
