/** GreatWall v0.3 右侧科研指挥舱顶层容器与 DSH RC5 插件挂载入口。 */
function GreatwallTitle() {
  return jsxs("span", {
    style: { display: "inline-flex", alignItems: "center", gap: "5px" },
    children: [jsx(GreatwallGlyph, { size: 14 }), jsx("span", { children: "长城科研指挥舱" })]
  });
}

function GreatwallConsoleBody({ getUiWorkspace }) {
  const [tab, setTab] = React.useState("overview");
  const [selectedWs, setSelectedWs] = React.useState(() => readPersistedWs());
  const [data, setData] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [banner, setBanner] = React.useState("");

  const refresh = React.useCallback(async (wsOverride) => {
    try {
      const ws = wsOverride !== undefined ? wsOverride : selectedWs;
      const res = await fetchGreatwallStatus({ workspaceRoot: ws });
      if (res && res.ok) {
        setData(res);
        if (!ws && res.workspaceRoot) {
          setSelectedWs(res.workspaceRoot);
          persistSelectedWs(res.workspaceRoot);
        }
      }
    } catch (err) {
      setBanner(`刷新失败: ${String(err?.message || err)}`);
    }
  }, [selectedWs]);

  React.useEffect(() => {
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 4000);
    return () => clearInterval(timer);
  }, [refresh]);

  const handleControl = async (action, payload = {}) => {
    setBusy(true);
    setBanner("");
    try {
      const ws = data?.workspaceRoot || selectedWs;
      const res = await postGreatwallControl(action, { workspaceRoot: ws, ...payload });
      if (res?.ok === false) {
        setBanner(`操作失败 (${action}): ${res.error || "未知错误"}`);
      } else if (action === "open_chief" && res?.sessionId) {
        openNativeSession(getUiWorkspace, res.sessionId);
        setBanner(`已唤醒科研总控会话 ${res.sessionId}`);
      } else {
        setBanner(`已执行 ${action}`);
      }
      await refresh(ws);
    } catch (err) {
      setBanner(`请求异常: ${String(err?.message || err)}`);
    } finally {
      setBusy(false);
    }
  };

  const poolState = data?.status?.poolState || "idle";
  const knownWorkspaces = data?.knownWorkspaces || [];

  return jsxs("div", {
    className: "gw-root",
    children: [
      jsxs("div", {
        className: "gw-hdr",
        children: [
          jsxs("div", {
            className: "gw-title-wrap",
            children: [
              jsx("strong", { children: "GreatWall v0.3" }),
              jsx("span", { className: stateBadgeClass(poolState), children: poolState }),
              data?.status?.stage ? jsx("span", { className: "gw-badge gw-b-info", children: data.status.stage }) : null
            ]
          }),
          jsxs("div", {
            className: "gw-actions",
            children: [
              poolState === "running"
                ? jsx("button", { className: "gw-btn", disabled: busy, onClick: () => handleControl("pause"), children: "暂停" })
                : jsx("button", { className: "gw-btn gw-btn-pri", disabled: busy, onClick: () => handleControl("resume"), children: "继续" }),
              jsx("button", { className: "gw-btn gw-btn-danger", disabled: busy, onClick: () => handleControl("human_stop", { note: "UI_HUMAN_STOP" }), children: "人类收工" }),
              jsx("button", { className: "gw-btn", disabled: busy, onClick: () => void refresh(), children: "刷新" })
            ]
          })
        ]
      }),
      knownWorkspaces.length > 1
        ? jsx("div", {
            style: { padding: "6px 10px", borderBottom: "1px solid var(--dsw-alias-border-l4)" },
            children: jsx("select", {
              className: "gw-select",
              value: data?.workspaceRoot || selectedWs,
              onChange: (e) => {
                const next = e.target.value;
                setSelectedWs(next);
                persistSelectedWs(next);
                void refresh(next);
              },
              children: knownWorkspaces.map((w) => jsx("option", { value: w, children: w }, w))
            })
          })
        : null,
      banner ? jsx("div", { style: { padding: "4px 10px", fontSize: "11px", color: "#2563eb", borderBottom: "1px solid var(--dsw-alias-border-l4)" }, children: banner }) : null,
      jsxs("div", {
        className: "gw-tabs",
        children: [
          jsx("button", { className: tab === "overview" ? "gw-tab gw-tab-on" : "gw-tab", onClick: () => setTab("overview"), children: "三大问题总览" }),
          jsx("button", { className: tab === "survey" ? "gw-tab gw-tab-on" : "gw-tab", onClick: () => setTab("survey"), children: "全局总览与圆桌" }),
          jsx("button", { className: tab === "branches" ? "gw-tab gw-tab-on" : "gw-tab", onClick: () => setTab("branches"), children: "分支与人工接管" })
        ]
      }),
      jsx("div", {
        className: "gw-scroll",
        children: tab === "overview"
          ? jsx(ThreeQuestionsView, { data, busy, onControl: handleControl, getUiWorkspace })
          : (tab === "survey"
              ? jsx(LivingSurveyView, { data })
              : jsx(BranchDetailDrawer, { data, busy, onControl: handleControl, getUiWorkspace }))
      })
    ]
  });
}

const inject = ["slots", "sidebarRightTabs"];

function apply(ctx) {
  ctx.effect(() => mountConsoleStyles(), "greatwall-console: inject styles");
  const getUiWorkspace = () => {
    try {
      return (typeof ctx?.get === "function" ? ctx.get("uiWorkspace") : null)
        || (typeof ctx?.root?.get === "function" ? ctx.root.get("uiWorkspace") : null)
        || ctx?.uiWorkspace
        || null;
    } catch {
      return null;
    }
  };
  const BoundConsoleBody = (props) => jsx(GreatwallConsoleBody, { ...props, getUiWorkspace });

  ctx.effect(() => ctx.sidebarRightTabs.register({
    id: TAB_ID,
    kind: TAB_KIND,
    priority: "extension",
    title: () => "长城科研指挥舱",
    guide: [{
      order: 15,
      title: () => "长城科研指挥舱",
      description: () => "三大问题总览・人类待拍板提案卡・1500字活体综述・45%暂停接管与会话直达",
      icon: GreatwallGlyph
    }]
  }), "greatwall-console: register tab type");

  ctx.effect(() => ctx.slots.inject("sidebar.right.pane.tab", () => ctx.slots.register({
    name: "sidebar.right.pane.tab",
    key: TAB_ID
  }, BoundConsoleBody)), "greatwall-console: tab body");

  ctx.effect(() => ctx.slots.inject("sidebar.right.pane.tab.title", () => ctx.slots.register({
    name: "sidebar.right.pane.tab.title",
    key: TAB_ID
  }, GreatwallTitle)), "greatwall-console: tab title");
}
