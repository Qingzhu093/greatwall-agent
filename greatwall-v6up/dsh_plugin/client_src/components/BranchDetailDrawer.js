/** GreatWall v0.3 轻量谱系树状图（子题 -> 学派 -> 分支代次）与 45% 人工接管面板（裁决四）。 */
function formatElapsedLabel(startedAt) {
  if (!startedAt) return "";
  const ms = Date.now() - Date.parse(startedAt);
  if (!Number.isFinite(ms) || ms < 0) return "";
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `已跑 ${sec}s`;
  const min = Math.floor(sec / 60);
  return `已跑 ${min}m${sec % 60}s`;
}

function readableBranchKind(kind) {
  const k = String(kind || "PURE").toUpperCase();
  if (k === "HUMAN_SEEDED") return "人类种子";
  if (k === "SYNTHESIS") return "双供体合体";
  if (k === "PROTECTED") return "保护支线";
  return "纯血主线";
}

function readableNodeStatus(st) {
  const s = String(st || "").toUpperCase();
  if (s === "EXPLORING") return "攻关中";
  if (s === "ACTIVE_REVISING") return "盲审返工中";
  if (s === "AWAITING_TRIAGE") return "待分诊";
  if (s === "PENDING_REVIEW") return "盲审验真中";
  if (s === "BLOCKED_L4B") return "缺引理挂起";
  if (s === "SEALED") return "已封存";
  if (s === "CLOSED") return "已关闭";
  return s || "未知";
}

function BranchDetailDrawer({ data, busy, onControl, getUiWorkspace }) {
  const [expandedNodes, setExpandedNodes] = React.useState({});
  const [showHistorical, setShowHistorical] = React.useState(false);
  const [feedback, setFeedback] = React.useState("");
  const [confirmEarlyNodeId, setConfirmEarlyNodeId] = React.useState("");

  const poolState = String(data?.status?.poolState || "idle").toLowerCase();
  const isPoolRunning = poolState === "running";
  const insp = data?.inspector || {};
  const knownSessions = data?.telemetryState?.sessions || null;
  const nodes = insp.lineage_nodes || [];
  const families = insp.method_families || [];
  const activeSessions = data?.status?.activeSessions || [];
  const runningExplorers = data?.status?.runningExplorers || [];
  const liveByNode = {};
  for (const r of runningExplorers) {
    if (r?.nodeId) liveByNode[r.nodeId] = { nodeId: r.nodeId, sessionId: r.sessionId, startedAt: r.startedAt || null };
  }
  for (const s of activeSessions) {
    if (s?.nodeId && (s.role === "explorer" || s.role === "lineage_companion")) {
      liveByNode[s.nodeId] = { ...(liveByNode[s.nodeId] || {}), ...s };
    }
  }

  const familyNameMap = {};
  for (const f of families) {
    if (f?.family_id) {
      familyNameMap[f.family_id] = String(f.mechanism_signature || f.family_id).slice(0, 42);
    }
  }

  const ACTIVE_SET = new Set(["EXPLORING", "ACTIVE_REVISING", "AWAITING_TRIAGE", "PENDING_REVIEW", "BLOCKED_L4B"]);
  const visibleNodes = showHistorical ? nodes : nodes.filter((n) => ACTIVE_SET.has(n.node_status));

  // 按 子题 -> 学派 -> 代次 组织谱系树
  const byQuestion = {};
  for (const n of visibleNodes) {
    const qid = String(n.question_id || "Q1");
    const fid = String(n.family_id || "未归类学派");
    if (!byQuestion[qid]) byQuestion[qid] = {};
    if (!byQuestion[qid][fid]) byQuestion[qid][fid] = [];
    byQuestion[qid][fid].push(n);
  }
  const qKeys = Object.keys(byQuestion).sort();

  const toggleExpand = (nid) => {
    setExpandedNodes((prev) => ({ ...prev, [nid]: !prev[nid] }));
  };

  return jsxs("div", {
    style: { display: "flex", flexDirection: "column", gap: "9px" },
    children: [
      feedback ? jsx("div", { className: "gw-item", style: { borderColor: "rgba(217,119,6,.45)" }, children: feedback }) : null,
      jsxs("div", {
        className: "gw-card",
        children: [
          jsxs("div", {
            className: "gw-card-hd",
            children: [
              jsx("span", { children: `谱系树状图 (${visibleNodes.length} / 总计 ${nodes.length} 代)` }),
              jsx("button", {
                className: "gw-btn",
                onClick: () => setShowHistorical((v) => !v),
                children: showHistorical ? "仅看活跃分支" : "展开历史封存代"
              })
            ]
          }),
          qKeys.length === 0
            ? jsx("div", { className: "gw-muted", children: "当前无在研或待处置分支节点。" })
            : qKeys.map((qid) => {
                const famMap = byQuestion[qid];
                const famKeys = Object.keys(famMap).sort();
                return jsxs("div", {
                  className: "gw-tree-q",
                  children: [
                    jsxs("div", {
                      className: "gw-row",
                      children: [
                        jsx("strong", { children: `子题 ${qid}` }),
                        jsx("span", { className: "gw-muted", children: `${famKeys.length} 个方法学派` })
                      ]
                    }),
                    famKeys.map((fid) => {
                      const fNodes = [...famMap[fid]].sort((a, b) => Number(a.generation || 1) - Number(b.generation || 1));
                      const famLabel = familyNameMap[fid] || fid;
                      return jsxs("div", {
                        className: "gw-tree-fam",
                        children: [
                          jsxs("div", {
                            className: "gw-row",
                            children: [
                              jsx("span", { style: { fontWeight: 600 }, children: `├─ ${famLabel}` }),
                              jsx("span", { className: "gw-muted gw-mono", children: fid })
                            ]
                          }),
                          fNodes.map((n) => {
                            const win = Math.max(1, Number(n.effective_context_window || 500000));
                            const pct = Math.min(100, Math.round((Number(n.pressure_tokens || 0) / win) * 100));
                            const ctrlSt = String(n.control_state || "AUTO_RUNNING");
                            const canIntervene = n.node_status === "EXPLORING" || n.node_status === "ACTIVE_REVISING";
                            const expSid = `gw-exp-${n.node_id}`;
                            const compSid = n.companion_session_id || `gw-comp-${n.node_id}`;
                            const liveInfo = liveByNode[n.node_id] || null;
                            const isTrulyRunning = Boolean(liveInfo && ctrlSt === "AUTO_RUNNING" && poolState === "running");
                            const elapsed = isTrulyRunning ? formatElapsedLabel(liveInfo.startedAt) : "";
                            const summary = String(n.mechanism_summary || "").trim();
                            const isExpanded = Boolean(expandedNodes[n.node_id]);
                            const needsToggle = summary.length > 90;
                            const displaySummary = needsToggle && !isExpanded ? `${summary.slice(0, 90)}…` : summary;
                            const isPausedForHuman = ctrlSt === "PAUSE_DRAINING" || ctrlSt === "HUMAN_ACTIVE";

                            const expExists = !knownSessions || Boolean(knownSessions[expSid]) || Boolean(liveInfo);
                            const compExists = !knownSessions || Boolean(knownSessions[compSid]);
                            const badgeStatusKey = isTrulyRunning
                              ? "RUNNING"
                              : (!isPoolRunning && canIntervene && ctrlSt === "AUTO_RUNNING"
                                  ? (poolState === "paused" ? "PAUSED" : "INFO")
                                  : n.node_status);
                            const badgeLabel = isTrulyRunning
                              ? "运行中"
                              : (canIntervene && ctrlSt === "AUTO_RUNNING"
                                  ? (isPoolRunning
                                      ? "排队等槽位"
                                      : (poolState === "paused" ? "总池已暂停" : "已停机待续"))
                                  : readableNodeStatus(n.node_status));

                            let obsCount = 0;
                            try {
                              const arr = Array.isArray(n.bound_obs_ids) ? n.bound_obs_ids : JSON.parse(n.bound_obs_ids_json || "[]");
                              obsCount = Array.isArray(arr) ? arr.length : 0;
                            } catch {}

                            return jsxs("div", {
                              className: "gw-tree-node",
                              children: [
                                jsxs("div", {
                                  className: "gw-row",
                                  children: [
                                    jsxs("span", {
                                      style: { fontWeight: 600 },
                                      title: `节点 ID: ${n.node_id}`,
                                      children: [
                                        isTrulyRunning ? jsx("span", { className: "gw-pulse", title: "实时运行中" }) : null,
                                        `第 ${n.generation || 1} 代 · ${readableBranchKind(n.branch_kind)}`,
                                        elapsed ? ` · ${elapsed}` : ""
                                      ]
                                    }),
                                    jsxs("div", {
                                      className: "gw-actions",
                                      children: [
                                        jsx("span", {
                                          className: stateBadgeClass(badgeStatusKey),
                                          children: badgeLabel
                                        }),
                                        ctrlSt !== "AUTO_RUNNING"
                                          ? jsx("span", { className: stateBadgeClass(ctrlSt), title: ctrlSt, children: readableControlState(ctrlSt) })
                                          : null
                                      ]
                                    })
                                  ]
                                }),
                                jsx("div", {
                                  className: "gw-muted",
                                  title: `内部节点 ID: ${n.node_id}`,
                                  children: `水位 ${pct}% · 收据 ${obsCount} 份 · 保护期 ${n.protection_generations_left ?? 0} 代`
                                }),
                                jsx("div", {
                                  className: "gw-bar",
                                  children: jsx("div", { className: "gw-bar-fill", style: { width: `${pct}%` } })
                                }),
                                summary
                                  ? jsxs("div", {
                                      children: [
                                        jsx("div", { className: "gw-summary", children: displaySummary }),
                                        needsToggle
                                          ? jsx("button", {
                                              className: "gw-link-btn",
                                              onClick: () => toggleExpand(n.node_id),
                                              children: isExpanded ? "收起完整思路" : "展开完整思路"
                                            })
                                          : null
                                      ]
                                    })
                                  : null,
                                jsxs("div", {
                                  className: "gw-actions",
                                  children: [
                                    jsx("button", {
                                      className: "gw-btn",
                                      disabled: !expExists,
                                      title: expExists ? `打开 ${expSid}` : "该探索会话尚未创建",
                                      onClick: () => {
                                        setFeedback("");
                                        openNativeSession(getUiWorkspace, expSid, setFeedback);
                                      },
                                      children: "打开探索对话"
                                    }),
                                    jsx("button", {
                                      className: "gw-btn",
                                      disabled: !compExists,
                                      title: compExists ? `打开 ${compSid}` : "该伴随会话尚未创建",
                                      onClick: () => {
                                        setFeedback("");
                                        openNativeSession(getUiWorkspace, compSid, setFeedback);
                                      },
                                      children: "打开伴随对话"
                                    }),
                                    isPoolRunning && canIntervene && ctrlSt === "AUTO_RUNNING"
                                      ? jsx("button", {
                                          className: "gw-btn gw-btn-pri",
                                          disabled: busy,
                                          onClick: () => onControl("pause_node", { node_id: n.node_id, reason: "HUMAN_TAKEOVER_45PCT" }),
                                          children: "暂停接管"
                                        })
                                      : null,
                                    canIntervene && isPausedForHuman
                                      ? jsx("button", {
                                          className: "gw-btn gw-btn-ok",
                                          disabled: busy,
                                          onClick: () => {
                                            setConfirmEarlyNodeId("");
                                            void onControl("resume_node", { node_id: n.node_id });
                                          },
                                          children: "交还托管(SHA对账)"
                                        })
                                      : null,
                                    canIntervene && isPausedForHuman
                                      ? jsx("button", {
                                          className: "gw-btn",
                                          disabled: busy,
                                          onClick: () => setConfirmEarlyNodeId((cur) => (cur === n.node_id ? "" : n.node_id)),
                                          children: "授权提前交班"
                                        })
                                      : null
                                  ]
                                }),
                                confirmEarlyNodeId === n.node_id && canIntervene && isPausedForHuman
                                  ? jsxs("div", {
                                      className: "gw-confirm-bar",
                                      style: { borderRadius: "6px", border: "1px solid rgba(220,38,38,.3)" },
                                      children: [
                                        jsx("span", { children: "确认提前结束本代探索并交由伴随封存遗嘱？" }),
                                        jsxs("div", {
                                          className: "gw-actions",
                                          children: [
                                            jsx("button", {
                                              className: "gw-btn gw-btn-danger",
                                              disabled: busy,
                                              onClick: () => {
                                                setConfirmEarlyNodeId("");
                                                void onControl("authorize_early_handoff", { node_id: n.node_id });
                                              },
                                              children: "确认提前交班"
                                            }),
                                            jsx("button", {
                                              className: "gw-btn",
                                              disabled: busy,
                                              onClick: () => setConfirmEarlyNodeId(""),
                                              children: "取消"
                                            })
                                          ]
                                        })
                                      ]
                                    })
                                  : null
                              ]
                            }, n.node_id);
                          })
                        ]
                      }, fid);
                    })
                  ]
                }, qid);
              })
        ]
      })
    ]
  });
}
