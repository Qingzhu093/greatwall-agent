/** GreatWall v0.3 领域总览视图：一屏直答「正在做什么 / 卡在哪里与待拍板卡 / 已证实基线」。 */
function ThreeQuestionsView({ data, busy, onControl, getUiWorkspace }) {
  const status = data?.status || {};
  const insp = data?.inspector || {};
  const subproblems = insp.subproblem_runtime_state || status.subproblemStates || [];
  const proposals = insp.pending_proposals || [];
  const l3List = (insp.internal_ledger || []).filter((x) => x.ledger_type === "L3_VERIFIED" && Number(x.is_active) === 1);
  const autonomyMode = status.autonomyMode || insp.snapshot?.autonomy_mode || "WAVE_CONFIRM";

  return jsxs("div", {
    style: { display: "flex", flexDirection: "column", gap: "9px" },
    children: [
      // 1. 正在做什么 + 自主档位与单子题启停
      jsxs("div", {
        className: "gw-card",
        children: [
          jsxs("div", {
            className: "gw-card-hd",
            children: [
              jsx("span", { children: "① 正在做什么（子题运行态）" }),
              jsxs("div", {
                className: "gw-actions",
                children: [
                  jsx("button", {
                    className: autonomyMode === "WAVE_CONFIRM" ? "gw-btn gw-btn-pri" : "gw-btn",
                    disabled: busy,
                    onClick: () => onControl("set_autonomy_mode", { autonomy_mode: autonomyMode === "WAVE_CONFIRM" ? "AUTOPILOT" : "WAVE_CONFIRM" }),
                    children: autonomyMode === "WAVE_CONFIRM" ? "档位: 逐波确认" : "档位: 自主续航"
                  }),
                  jsx("button", {
                    className: "gw-btn gw-btn-pri",
                    disabled: busy,
                    onClick: () => onControl("open_chief", {}),
                    children: "唤起 gw-chief"
                  })
                ]
              })
            ]
          }),
          subproblems.length === 0
            ? jsx("div", { className: "gw-muted", children: "尚未初始化 Parse 0 子题。" })
            : subproblems.map((s) =>
                jsxs("div", {
                  className: "gw-item",
                  children: [
                    jsxs("div", {
                      className: "gw-row",
                      children: [
                        jsxs("strong", { children: [`${s.question_id} · v${s.active_spec_revision || 0}`] }),
                        jsx("span", { className: stateBadgeClass(s.dispatch_state), children: s.dispatch_state })
                      ]
                    }),
                    jsxs("div", {
                      className: "gw-row gw-muted",
                      children: [
                        jsx("span", { children: `波次 W${s.completed_waves || 0} · 基线 ${s.solved_entry_id || "未通关"}` }),
                        s.dispatch_state !== "CLOSED" && s.dispatch_state !== "STOPPED_SOLVED"
                          ? jsx("button", {
                              className: "gw-btn",
                              disabled: busy,
                              onClick: () => onControl("set_subproblem_state", {
                                question_id: s.question_id,
                                desired_state: s.desired_state === "PAUSED" ? "ACTIVE" : "PAUSED"
                              }),
                              children: s.desired_state === "PAUSED" ? "恢复该题" : "暂停该题"
                            })
                          : null
                      ]
                    }),
                    s.block_reason_code ? jsx("div", { className: "gw-muted", children: `阻塞原因: ${s.block_reason_code}` }) : null
                  ]
                }, s.question_id)
              )
        ]
      }),

      // 2. 卡在哪里与人类待拍板提案卡（双端乐观锁幂等）
      jsxs("div", {
        className: "gw-card",
        children: [
          jsxs("div", {
            className: "gw-card-hd",
            children: [
              jsx("span", { children: `② 卡在哪里与待拍板提案 (${proposals.length})` }),
              proposals.length > 0 ? jsx("span", { className: "gw-badge gw-b-warn", children: "需人类签字" }) : null
            ]
          }),
          proposals.length === 0
            ? jsx("div", { className: "gw-muted", children: "当前无待拍板提案，系统正按授权自主推进。" })
            : proposals.map((p) =>
                jsxs("div", {
                  className: "gw-item",
                  children: [
                    jsxs("div", {
                      className: "gw-row",
                      children: [
                        jsx("strong", { className: "gw-mono", children: `${p.action_type} · ${p.target_id}` }),
                        jsx("span", { className: "gw-badge gw-b-warn", children: p.proposal_id })
                      ]
                    }),
                    jsx("div", { children: p.rationale_md || "(无说明)" }),
                    jsxs("div", {
                      className: "gw-actions",
                      children: [
                        jsx("button", {
                          className: "gw-btn gw-btn-ok",
                          disabled: busy,
                          onClick: () => onControl("approve_proposal", { proposal_id: p.proposal_id, decision: "APPROVE", approved_by_source: "human_ui" }),
                          children: "批准并执行"
                        }),
                        jsx("button", {
                          className: "gw-btn gw-btn-danger",
                          disabled: busy,
                          onClick: () => onControl("approve_proposal", { proposal_id: p.proposal_id, decision: "REJECT", approved_by_source: "human_ui" }),
                          children: "驳回"
                        })
                      ]
                    })
                  ]
                }, p.proposal_id)
              )
        ]
      }),

      // 3. 已证实基线 (L3_VERIFIED)
      jsxs("div", {
        className: "gw-card",
        children: [
          jsxs("div", {
            className: "gw-card-hd",
            children: [
              jsx("span", { children: `③ 已证实知识基线 L3 (${l3List.length})` }),
              jsx("span", { className: "gw-muted", children: `全局口径 v${status.latestSpecRevision || 0}` })
            ]
          }),
          l3List.length === 0
            ? jsx("div", { className: "gw-muted", children: "尚无通过两阶段独立盲审的 L3 条目。" })
            : l3List.slice(0, 8).map((item) =>
                jsxs("div", {
                  className: "gw-item",
                  children: [
                    jsxs("div", {
                      className: "gw-row",
                      children: [
                        jsx("strong", { className: "gw-mono", children: `${item.entry_id} (${item.question_id}/v${item.verified_spec_revision || 0})` }),
                        jsx("span", { className: stateBadgeClass(item.goal_coverage === "FULL_GOAL" ? "STOPPED_SOLVED" : "INFO"), children: item.goal_coverage || item.l3_entry_kind })
                      ]
                    }),
                    jsx("div", { children: item.title }),
                    jsx("div", { className: "gw-muted", children: String(item.exact_verified_scope_md || item.abstract_md || "").slice(0, 180) })
                  ]
                }, item.entry_id)
              )
        ]
      })
    ]
  });
}
