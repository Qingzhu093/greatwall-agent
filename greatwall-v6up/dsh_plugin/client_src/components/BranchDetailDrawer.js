/** GreatWall v0.3 分支详情与 45% 人工接管抽屉（暂停让权 / 交还托管 / 提前交班 / 一键直达会话）。 */
function BranchDetailDrawer({ data, busy, onControl, getUiWorkspace }) {
  const insp = data?.inspector || {};
  const nodes = insp.lineage_nodes || [];
  const activeNodes = nodes.filter((n) => ["EXPLORING", "ACTIVE_REVISING", "AWAITING_TRIAGE", "PENDING_REVIEW", "BLOCKED_L4B"].includes(n.node_status));

  return jsxs("div", {
    style: { display: "flex", flexDirection: "column", gap: "9px" },
    children: [
      jsxs("div", {
        className: "gw-card",
        children: [
          jsx("div", { className: "gw-card-hd", children: `活跃与待处置分支 (${activeNodes.length} / 总计 ${nodes.length} 代)` }),
          activeNodes.length === 0
            ? jsx("div", { className: "gw-muted", children: "当前无在研或待处置分支节点。" })
            : activeNodes.map((n) => {
                const win = Math.max(1, Number(n.effective_context_window || 500000));
                const pct = Math.min(100, Math.round((Number(n.pressure_tokens || 0) / win) * 100));
                const ctrlSt = String(n.control_state || "AUTO_RUNNING");
                const canIntervene = n.node_status === "EXPLORING" || n.node_status === "ACTIVE_REVISING";
                const expSid = `gw-exp-${n.node_id}`;
                const compSid = n.companion_session_id || `gw-comp-${n.node_id}`;

                return jsxs("div", {
                  className: "gw-item",
                  children: [
                    jsxs("div", {
                      className: "gw-row",
                      children: [
                        jsx("strong", { className: "gw-mono", children: `${n.question_id} · ${n.node_id} (G${n.generation || 1})` }),
                        jsxs("div", {
                          className: "gw-actions",
                          children: [
                            jsx("span", { className: stateBadgeClass(n.node_status), children: n.node_status }),
                            ctrlSt !== "AUTO_RUNNING" ? jsx("span", { className: "gw-badge gw-b-warn", children: ctrlSt }) : null
                          ]
                        })
                      ]
                    }),
                    jsx("div", { className: "gw-muted", children: `${n.family_id || "未归类"} · ${n.branch_kind || "PURE"} · 保护期 ${n.protection_generations_left ?? 0} 代 · 水位 ${pct}%` }),
                    jsx("div", {
                      className: "gw-bar",
                      children: jsx("div", { className: "gw-bar-fill", style: { width: `${pct}%` } })
                    }),
                    n.mechanism_summary ? jsx("div", { children: n.mechanism_summary }) : null,
                    jsxs("div", {
                      className: "gw-actions",
                      children: [
                        jsx("button", {
                          className: "gw-btn",
                          onClick: () => openNativeSession(getUiWorkspace, expSid),
                          children: "打开探索对话"
                        }),
                        jsx("button", {
                          className: "gw-btn",
                          onClick: () => openNativeSession(getUiWorkspace, compSid),
                          children: "打开伴随对话"
                        }),
                        canIntervene && ctrlSt === "AUTO_RUNNING"
                          ? jsx("button", {
                              className: "gw-btn gw-btn-pri",
                              disabled: busy,
                              onClick: () => onControl("pause_node", { node_id: n.node_id, reason: "HUMAN_TAKEOVER_45PCT" }),
                              children: "暂停接管"
                            })
                          : null,
                        canIntervene && (ctrlSt === "PAUSE_DRAINING" || ctrlSt === "HUMAN_ACTIVE")
                          ? jsx("button", {
                              className: "gw-btn gw-btn-ok",
                              disabled: busy,
                              onClick: () => onControl("resume_node", { node_id: n.node_id }),
                              children: "交还托管(SHA对账)"
                            })
                          : null,
                        canIntervene
                          ? jsx("button", {
                              className: "gw-btn",
                              disabled: busy,
                              onClick: () => onControl("authorize_early_handoff", { node_id: n.node_id }),
                              children: "授权提前交班"
                            })
                          : null
                      ]
                    })
                  ]
                }, n.node_id);
              })
        ]
      })
    ]
  });
}
