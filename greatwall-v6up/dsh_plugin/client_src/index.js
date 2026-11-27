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
  const [banner, setBanner] = React.useState(null);
  const [confirmHumanStop, setConfirmHumanStop] = React.useState(false);
  const reqSeqRef = React.useRef(0);
  const bannerTimerRef = React.useRef(null);

  const showBanner = React.useCallback((kind, text, autoHideMs = 6000) => {
    if (bannerTimerRef.current) {
      clearTimeout(bannerTimerRef.current);
      bannerTimerRef.current = null;
    }
    if (!text) {
      setBanner(null);
      return;
    }
    setBanner({ kind, text });
    if (kind !== "err" && autoHideMs > 0) {
      bannerTimerRef.current = setTimeout(() => {
        setBanner(null);
        bannerTimerRef.current = null;
      }, autoHideMs);
    }
  }, []);

  React.useEffect(() => () => {
    if (bannerTimerRef.current) clearTimeout(bannerTimerRef.current);
  }, []);

  const refresh = React.useCallback(async (wsOverride) => {
    const seq = ++reqSeqRef.current;
    try {
      const ws = wsOverride !== undefined ? wsOverride : selectedWs;
      const uiWs = typeof getUiWorkspace === "function" ? getUiWorkspace() : null;
      const activeSid = String(uiWs?.activeSessionId || uiWs?.currentSessionId || "");
      const res = await fetchGreatwallStatus({ workspaceRoot: ws, sessionId: activeSid });
      if (seq !== reqSeqRef.current) return;
      if (res && res.ok) {
        setData(res);
        if (!ws && res.workspaceRoot) {
          setSelectedWs(res.workspaceRoot);
          persistSelectedWs(res.workspaceRoot);
        }
      }
    } catch (err) {
      if (seq !== reqSeqRef.current) return;
      showBanner("err", `刷新失败: ${String(err?.message || err)}`);
    }
  }, [selectedWs, getUiWorkspace, showBanner]);

  React.useEffect(() => {
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 4000);
    return () => clearInterval(timer);
  }, [refresh]);

  const handleControl = async (action, payload = {}) => {
    setBusy(true);
    showBanner("info", "", 0);
    try {
      const ws = data?.workspaceRoot || selectedWs;
      const res = await postGreatwallControl(action, { workspaceRoot: ws, ...payload });
      const label = readableActionLabel(action);
      if (res?.ok === false) {
        showBanner("err", `${label}失败: ${res.error || "未知错误"}`);
      } else if (action === "open_chief" && res?.sessionId) {
        const opened = openNativeSession(getUiWorkspace, res.sessionId, (msg) => showBanner("err", msg));
        if (opened) showBanner("ok", `已唤醒科研总控会话`);
      } else if (action === "pause") {
        const cnt = Array.isArray(res?.pausedNodeIds) ? res.pausedNodeIds.length : 0;
        showBanner("ok", cnt > 0 ? `已全局暂停，${cnt} 条在跑分支已切入等待人类接管` : "已全局暂停，系统进入等待人类接管态");
      } else if (action === "resume") {
        const cnt = Array.isArray(res?.resumedNodeIds) ? res.resumedNodeIds.length : 0;
        showBanner("ok", cnt > 0 ? `已对 ${cnt} 条接管分支完成 SHA 对账并恢复全面托管` : "已恢复全面托管运行");
      } else {
        showBanner("ok", `已完成：${label}`);
      }
      await refresh(ws);
    } catch (err) {
      showBanner("err", `请求异常: ${String(err?.message || err)}`);
    } finally {
      setBusy(false);
    }
  };

  const poolState = data?.status?.poolState || "idle";
  const stage = data?.status?.stage || "";
  const isClosed = stage === "CLOSED_VERIFIED" || data?.status?.closureStatus === "CLOSED_VERIFIED";
  const humanStopActive = Boolean(data?.status?.humanStopActive);
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
              jsx("span", { className: stateBadgeClass(poolState), title: poolState, children: readablePoolState(poolState) }),
              stage ? jsx("span", { className: "gw-badge gw-b-info", title: stage, children: readableStage(stage) }) : null
            ]
          }),
          jsxs("div", {
            className: "gw-actions",
            children: [
              !isClosed
                ? (poolState === "running"
                    ? jsx("button", { className: "gw-btn", disabled: busy, onClick: () => handleControl("pause"), children: "暂停接管" })
                    : jsx("button", {
                        className: "gw-btn gw-btn-pri",
                        disabled: busy || poolState === "starting",
                        onClick: () => handleControl("resume"),
                        children: poolState === "paused" ? "全面托管" : "恢复托管"
                      }))
                : null,
              jsx("button", {
                className: "gw-btn gw-btn-danger",
                disabled: busy || isClosed || humanStopActive,
                onClick: () => setConfirmHumanStop((v) => !v),
                children: humanStopActive ? "已收工" : "人类收工"
              }),
              jsx("button", { className: "gw-btn", disabled: busy, onClick: () => void refresh(), children: "刷新" })
            ]
          })
        ]
      }),
      confirmHumanStop && !isClosed && !humanStopActive
        ? jsxs("div", {
            className: "gw-confirm-bar",
            children: [
              jsx("span", { children: "确认全局收工并强制进入 Stage 3 部分结题？（不可撤销）" }),
              jsxs("div", {
                className: "gw-actions",
                children: [
                  jsx("button", {
                    className: "gw-btn gw-btn-danger",
                    disabled: busy,
                    onClick: () => {
                      setConfirmHumanStop(false);
                      void handleControl("human_stop", { note: "UI_HUMAN_STOP" });
                    },
                    children: "确认收工"
                  }),
                  jsx("button", {
                    className: "gw-btn",
                    disabled: busy,
                    onClick: () => setConfirmHumanStop(false),
                    children: "取消"
                  })
                ]
              })
            ]
          })
        : null,
      knownWorkspaces.length > 1
        ? jsx("div", {
            style: { padding: "6px 10px", borderBottom: "1px solid var(--dsw-alias-border-l4)" },
            children: jsx("select", {
              className: "gw-select",
              value: data?.workspaceRoot || selectedWs,
              onChange: (e) => {
                const next = e.target.value;
                setConfirmHumanStop(false);
                setSelectedWs(next);
                persistSelectedWs(next);
                void refresh(next);
              },
              children: knownWorkspaces.map((w) => jsx("option", { value: w, children: w }, w))
            })
          })
        : null,
      banner
        ? jsxs("div", {
            className: `gw-banner gw-banner-${banner.kind || "info"}`,
            children: [
              jsx("span", { children: banner.text }),
              jsx("button", { className: "gw-link-btn", onClick: () => setBanner(null), children: "关闭" })
            ]
          })
        : null,
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
