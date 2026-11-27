/** GreatWall v0.3 领域总览视图：一屏直答「正在做什么 / 卡在哪里与待拍板卡 / 已证实基线」。 */
function ThreeQuestionsView({ data, busy, onControl, getUiWorkspace }) {
  const status = data?.status || {};
  const insp = data?.inspector || {};
  const poolState = String(status.poolState || "idle").toLowerCase();
  const isPoolRunning = poolState === "running";
  const isClosed = String(status.stage || "").toUpperCase() === "CLOSED_VERIFIED" || String(status.closureStatus || "").toUpperCase() === "CLOSED_VERIFIED";
  const humanStopActive = Boolean(status.humanStopActive);
  const rawSubs = insp.subproblem_runtime_state || status.subproblemStates || insp.subproblem_states || [];
  const subproblems = Array.isArray(rawSubs) ? rawSubs : Object.values(rawSubs || {});
  const proposals = insp.pending_proposals || [];
  const l3List = (insp.internal_ledger || []).filter((x) => x.ledger_type === "L3_VERIFIED" && Number(x.is_active ?? 1) === 1);
  const autonomyMode = status.autonomyMode || insp.snapshot?.autonomy_mode || "WAVE_CONFIRM";

  const emptyProposalHint = isClosed
    ? "课题已验收结题，全部成果已冻结交付。"
    : (humanStopActive
        ? "已触发人类收工，正在推进 Stage 3 终稿打包与核验。"
        : (isPoolRunning
            ? "当前无待拍板提案，系统正按授权全面托管推进中。"
            : (poolState === "paused"
                ? "当前无待拍板提案；系统处于「等待人类接管」态，点击顶部「全面托管」恢复推进。"
                : `当前无待拍板提案；编排器当前未运行（${typeof readablePoolState === "function" ? readablePoolState(poolState) : poolState}），点击顶部「恢复托管」即可继续推进。`)));

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
                        jsxs("strong", { children: [`${s.question_id} · 口径 v${s.active_spec_revision || 0}`] }),
                        jsx("span", {
                          className: !isPoolRunning && s.dispatch_state === "DISPATCHING"
                            ? (poolState === "paused" ? "gw-badge gw-b-warn" : "gw-badge gw-b-info")
                            : stateBadgeClass(s.dispatch_state),
                          title: `${s.dispatch_state} (pool=${poolState})`,
                          children: !isPoolRunning && s.dispatch_state === "DISPATCHING"
                            ? (poolState === "paused" ? "总池已暂停" : "待恢复(未运行)")
                            : (typeof readableDispatchState === "function" ? readableDispatchState(s.dispatch_state) : s.dispatch_state)
                        })
                      ]
                    }),
                    jsxs("div", {
                      className: "gw-row gw-muted",
                      children: [
                        jsx("span", { children: `波次 W${s.completed_waves || 0} · 基线 ${s.baseline_entry_id || "暂无"} · 通关 ${s.solved_entry_id || "未通关"}` }),
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
            ? jsx("div", { className: "gw-muted", children: emptyProposalHint })
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
                        jsx("span", {
                          className: stateBadgeClass(item.goal_coverage === "FULL_GOAL" ? "STOPPED_SOLVED" : "INFO"),
                          children: `${item.goal_coverage || item.l3_entry_kind}${item.publish_tier === "VERIFIED_INCREMENTAL" ? " · 归档" : " · 基线"}`
                        })
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
