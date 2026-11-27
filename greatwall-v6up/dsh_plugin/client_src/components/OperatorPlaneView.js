/** GreatWall v0.3.1 运行安排状态大盘（轻量只读态势为主，高级直控表单按需折叠）。 */
function safeParseIsoTimestamp(raw) {
  const text = String(raw || "").trim();
  if (!text) return { ok: true, value: null };
  const ms = Date.parse(text);
  if (Number.isNaN(ms)) return { ok: false, value: null };
  return { ok: true, value: new Date(ms).toISOString() };
}

function safeFormatLocalTime(raw) {
  const ms = Date.parse(String(raw || ""));
  if (Number.isNaN(ms)) return String(raw || "");
  return new Date(ms).toLocaleString();
}

function OperatorPlaneView({ data, busy, onControl }) {
  const [form, setForm] = React.useState({ scope: "PROJECT", target: "ALL", policy: "", priority: "", cap: "", workers: "", drain: "", expires: "", untilBatch: false });
  const [dateErr, setDateErr] = React.useState("");
  const [nodeIds, setNodeIds] = React.useState([]);
  const [nodeMode, setNodeMode] = React.useState("");
  const [archive, setArchive] = React.useState(false);
  const [alsoApply, setAlsoApply] = React.useState(false);
  const [inheritLit, setInheritLit] = React.useState(false);
  const [inheritInstruments, setInheritInstruments] = React.useState(false);
  const snap = data?.inspector?.snapshot || data?.status?.snapshot || {};
  if (!snap.operator_plane) return jsx("div", { className: "gw-card gw-muted", children: "签署课题后可查看与调整运行安排。" });

  const states = snap.subproblem_runtime_state || [];
  const nodes = (data?.inspector?.lineage_nodes || []).filter((n) =>
    ["EXPLORING", "ACTIVE_REVISING", "BLOCKED_L4B", "RETIRED"].includes(n.node_status));
  const ledger = snap.operator_slot_ledger || {};
  const arrangements = snap.active_arrangements || [];
  const receipts = snap.operation_receipts || [];
  const assign = (key) => (e) => {
    if (key === "expires") setDateErr("");
    setForm({ ...form, [key]: e.target.value });
  };
  const cmd = (operation, payload) => onControl("operator_command", { operation, ...payload });
  const hasPatch = Boolean(form.policy || form.cap || form.priority || (form.scope === "PROJECT" && form.workers) || form.drain);
  const field = (label, input) => jsxs("label", { children: [jsx("span", { children: label }), input] });
  const select = (items, props) => jsx("select", {
    className: "gw-select", ...props, children: items.map(([value, label]) => jsx("option", { value, children: label }, value)),
  });
  const number = (key, min, max) => jsx("input", { type: "number", min, max, value: form[key], onChange: assign(key) });
  const button = (label, onClick, disabled = busy) => jsx("button", { type: "button", className: "gw-btn", onClick, disabled, children: label });

  const submitArrangement = (event) => {
    event.preventDefault();
    if (!hasPatch || busy) return;
    const parsedExp = safeParseIsoTimestamp(form.expires);
    if (!parsedExp.ok) {
      setDateErr("到期时间格式无效，请重新选择或留空。");
      return;
    }
    const arrangement = {
      scope_type: form.scope,
      target_id: form.target,
      ...(form.policy ? { dispatch_policy: form.policy } : {}),
      ...(form.cap ? { max_active_branches: Number(form.cap) } : {}),
      ...(form.priority ? { priority_weight: Number(form.priority) } : {}),
      ...(form.scope === "PROJECT" && form.workers ? { max_concurrent_workers: Number(form.workers) } : {}),
      ...(form.drain ? { inflight_drain_mode: form.drain } : {}),
      ...(parsedExp.value ? { ends_on_kind: "AT_TIME", expires_at: parsedExp.value }
        : form.untilBatch ? { ends_on_kind: "AFTER_INFLIGHT_BATCH" } : {}),
    };
    const payload = { arrangement };
    if (alsoApply && nodeIds.length && nodeMode) {
      payload.node_action = { node_ids: nodeIds, mode: nodeMode, archive_family: archive };
    }
    void cmd("apply_arrangement", payload);
  };

  return jsxs("section", {
    className: "gw-operator",
    style: { display: "flex", flexDirection: "column", gap: "9px" },
    children: [
      // 1. 纪元与占槽态势总览 + 快捷唤起 gw-chief
      jsxs("div", {
        className: "gw-card",
        children: [
          jsxs("div", {
            className: "gw-card-hd",
            children: [
              jsx("span", { children: `运行安排 · 纪元 ${snap.epoch_id ?? 1}` }),
              jsx("button", {
                type: "button",
                className: "gw-btn gw-btn-pri",
                disabled: busy,
                onClick: () => onControl("open_chief", {}),
                children: "在 gw-chief 下令",
              }),
            ],
          }),
          jsx("div", {
            className: "gw-muted",
            children: `执行中 ${ledger.working?.length || 0} · 收尾占槽 ${ledger.draining?.length || 0} · 挂起/人工接管 ${ledger.hibernated_or_human?.length || 0}`,
          }),
          states.length === 0
            ? jsx("div", { className: "gw-muted", children: "暂无子题运行态。" })
            : jsx("ul", {
                children: states.map((q) => jsx("li", {
                  children: `${q.question_id} · ${q.dispatch_state} · ${q.dispatch_policy} · 优先级 ${q.priority_weight} · 分支上限 ${q.max_active_branches}`,
                }, q.question_id)),
              }),
        ],
      }),

      // 2. 当前生效中的临时安排（支持一键撤销）
      jsxs("div", {
        className: "gw-card",
        children: [
          jsxs("div", {
            className: "gw-card-hd",
            children: [
              jsx("span", { children: `生效中的运行安排 (${arrangements.length})` }),
            ],
          }),
          arrangements.length === 0
            ? jsx("div", { className: "gw-muted", children: "当前按默认策略推进；可直接在 gw-chief 对话下令调整优先级、停新派或到期恢复。" })
            : jsx("ul", {
                children: arrangements.map((a) => jsxs("li", {
                  children: [
                    `${a.target_id} · v${a.arrangement_version} · ${a.summary_md || Object.entries(a.patch || {}).map(([k, v]) => `${k}=${v}`).join("，")}`,
                    a.expires_at ? ` · ${safeFormatLocalTime(a.expires_at)} 到期` : "",
                    a.ends_on_kind === "AFTER_INFLIGHT_BATCH" ? ` · 等待本批次 ${(a.watch_node_ids || []).length} 条` : "",
                    " ",
                    button("撤销", () => cmd("revoke_arrangement", { details: { arrangement_id: a.arrangement_id } })),
                  ],
                }, a.arrangement_id)),
              }),
        ],
      }),

      // 3. 最近操作回执
      jsxs("div", {
        className: "gw-card",
        children: [
          jsx("div", { className: "gw-card-hd", children: jsx("span", { children: `近期操作回执 (${receipts.length})` }) }),
          receipts.length === 0
            ? jsx("div", { className: "gw-muted", children: "尚无运行操作回执。" })
            : jsx("ul", {
                children: receipts.slice(0, 8).map((op) => jsxs("li", {
                  children: [
                    `${readableReceiptStatus(op.status)} · ${op.summary_md}`,
                    op.pending_targets?.length ? jsx("div", { className: "gw-muted", children: `仍在收尾：${op.pending_targets.join("，")}` }) : null,
                    ...(op.failed_items || []).map((item) => jsx("div", {
                      className: "gw-muted",
                      children: `${item.target_id} · ${item.error}${item.retry_hint ? ` · ${item.retry_hint}` : ""}`,
                    }, item.target_id)),
                  ],
                }, op.op_id)),
              }),
        ],
      }),

      // 4. 折叠式高级直控区（默认收起，保持窄侧栏简洁）
      jsxs("details", {
        className: "gw-card",
        children: [
          jsx("summary", { style: { cursor: "pointer", fontWeight: 600 }, children: "高级直控表单（调整安排 / 点名分支 / 推进纪元）" }),
          jsxs("div", {
            style: { display: "flex", flexDirection: "column", gap: "8px", marginTop: "8px" },
            children: [
              jsx("form", {
                onSubmit: submitArrangement,
                children: jsxs("fieldset", {
                  disabled: busy,
                  children: [
                    jsx("legend", { children: "调整运行安排" }),
                    field("范围", select([["ALL", "全院"], ...states.map((q) => [q.question_id, q.question_id])], {
                      value: form.target, onChange: (e) => setForm({ ...form, target: e.target.value, scope: e.target.value === "ALL" ? "PROJECT" : "QUESTION" }),
                    })),
                    field("派工", select([["", "沿用"], ["NORMAL", "正常派发"], ["NO_NEW_DISPATCH", "停止新派"], ["PAUSED_ALL", "全面暂停"]], { value: form.policy, onChange: assign("policy") })),
                    field("优先级", number("priority", -10000, 10000)),
                    field("每题分支上限", number("cap", 1, 100)),
                    form.scope === "PROJECT" && field("普通执行槽", number("workers", 1, snap.max_worker_slots || 10)),
                    field("在途收尾", select([["", "按策略默认"], ["FINISH_CURRENT_TURN", "本回合后挂起"], ["FINISH_CURRENT_HANDOFF", "本班交班后停驻"], ["IMMEDIATE_YIELD", "尽快让出执行槽"]], { value: form.drain, onChange: assign("drain") })),
                    field("到期时间", jsx("input", { type: "datetime-local", value: form.expires, onChange: assign("expires") })),
                    dateErr ? jsx("div", { className: "gw-banner gw-banner-err", children: dateErr }) : null,
                    field("本批退出后到期", jsx("input", { type: "checkbox", checked: form.untilBatch, disabled: Boolean(form.expires), onChange: (e) => setForm({ ...form, untilBatch: e.target.checked }) })),
                    field("同时执行下方分支操作", jsx("input", { type: "checkbox", checked: alsoApply, onChange: (e) => setAlsoApply(e.target.checked) })),
                    jsx("button", { type: "submit", className: "gw-btn gw-btn-pri", disabled: !hasPatch || (alsoApply && (!nodeIds.length || !nodeMode)), children: "应用运行安排" }),
                  ],
                }),
              }),
              jsxs("fieldset", {
                disabled: busy,
                children: [
                  jsx("legend", { children: "点名操作分支" }),
                  field("目标分支", jsx("select", {
                    className: "gw-select", multiple: true, value: nodeIds,
                    onChange: (e) => setNodeIds(Array.from(e.target.selectedOptions).map((o) => o.value)),
                    children: nodes.map((n) => jsx("option", { value: n.node_id, children: `${n.question_id} · ${n.node_id} · ${n.node_status} / ${n.control_state}` }, n.node_id)),
                  })),
                  field("动作", select([["", "请选择"], ["retire", "撤编"], ["hibernate", "挂起"], ["pause_takeover", "人工接管"], ["resume", "恢复托管"], ["early_handoff", "提前交班"], ["reactivate", "重新激活"]], { value: nodeMode, onChange: (e) => setNodeMode(e.target.value) })),
                  nodeMode === "retire" && field("同时归档无保留分支的学派", jsx("input", { type: "checkbox", checked: archive, onChange: (e) => setArchive(e.target.checked) })),
                  button("执行分支操作", () => cmd("node_intervene", { node_action: { node_ids: nodeIds, mode: nodeMode, archive_family: archive } }), busy || !nodeIds.length || !nodeMode),
                ],
              }),
              jsxs("fieldset", {
                disabled: busy,
                children: [
                  jsx("legend", { children: "推进新纪元（归档旧库）" }),
                  field("继承外藏文献", jsx("input", { type: "checkbox", checked: inheritLit, onChange: (e) => setInheritLit(e.target.checked) })),
                  field("继承健康仪器", jsx("input", { type: "checkbox", checked: inheritInstruments, onChange: (e) => setInheritInstruments(e.target.checked) })),
                  button("生成纪元确认单", () => onControl("propose_epoch", {
                    inherit_external_literature: inheritLit, inherit_instruments: inheritInstruments,
                  })),
                ],
              }),
            ],
          }),
        ],
      }),
    ],
  });
}
