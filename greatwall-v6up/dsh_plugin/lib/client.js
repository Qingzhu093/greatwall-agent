window.__ModuleLoader__.load({
	id: "dsh-greatwall-v6up",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

		const jsxRuntime = require("react/jsx-runtime");
		const jsx = jsxRuntime.jsx;
		const jsxs = jsxRuntime.jsxs;
		const Fragment = jsxRuntime.Fragment;
		const React = require("react");

		const TAB_ID = "dsh-greatwall-v6up";
		const TAB_KIND = "greatwall";
		const STATUS_API = "/api/greatwall.status";
		const CONTROL_API = "/api/greatwall.control";

		const CSS_TEXT = [
			".gw-console-root{box-sizing:border-box;display:flex;flex-direction:column;height:100%;overflow:hidden;color:var(--dsw-alias-label-primary);font-size:12px;line-height:1.45}",
			".gw-console-header{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 12px;border-bottom:1px solid var(--dsw-alias-border-l4);flex:none}",
			".gw-console-title-wrap{display:flex;align-items:center;gap:6px;min-width:0}",
			".gw-console-badge{display:inline-flex;align-items:center;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:600;border:1px solid var(--dsw-alias-border-l3);background:var(--dsw-alias-bg-layer-2)}",
			".gw-badge-run{color:#16a34a;border-color:rgba(22,163,74,.35);background:rgba(22,163,74,.1)}",
			".gw-badge-pause{color:#d97706;border-color:rgba(217,119,6,.35);background:rgba(217,119,6,.1)}",
			".gw-badge-err{color:#dc2626;border-color:rgba(220,38,38,.35);background:rgba(220,38,38,.1)}",
			".gw-console-actions{display:flex;flex-wrap:wrap;gap:5px}",
			".gw-btn{cursor:pointer;border:1px solid var(--dsw-alias-border-l3);background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);border-radius:7px;padding:3px 9px;font-size:11px;font-weight:500}",
			".gw-btn:hover{background:var(--dsw-alias-interactive-bg-hover)}",
			".gw-btn:disabled{opacity:.45;cursor:not-allowed}",
			".gw-btn-danger{color:#dc2626;border-color:rgba(220,38,38,.35)}",
			".gw-btn-primary{color:#2563eb;border-color:rgba(37,99,235,.4);background:rgba(37,99,235,.08)}",
			".gw-scroll{flex:1;overflow-y:auto;padding:10px 12px;display:flex;flex-direction:column;gap:12px}",
			".gw-card{border:1px solid var(--dsw-alias-border-l4);background:var(--dsw-alias-bg-layer-1);border-radius:10px;padding:9px 10px;display:flex;flex-direction:column;gap:7px}",
			".gw-card-title{font-size:11px;font-weight:600;color:var(--dsw-alias-label-secondary);display:flex;justify-content:space-between;align-items:center}",
			".gw-q-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(125px,1fr));gap:6px}",
			".gw-q-item{border:1px solid var(--dsw-alias-border-l4);border-radius:8px;padding:6px 8px;background:var(--dsw-alias-bg-layer-2);display:flex;flex-direction:column;gap:3px}",
			".gw-row{display:flex;align-items:center;justify-content:space-between;gap:6px}",
			".gw-mono{font-family:var(--dsw-font-mono,ui-monospace,monospace);font-size:11px;word-break:break-all}",
			".gw-muted{color:var(--dsw-alias-label-tertiary);font-size:11px}",
			".gw-bar-bg{height:5px;border-radius:999px;background:var(--dsw-alias-fill-l2,rgba(128,128,128,.2));overflow:hidden}",
			".gw-bar-fill{height:100%;border-radius:999px;background:#2563eb;transition:width .25s ease}",
			".gw-bar-warn{background:#d97706}",
			".gw-bar-hot{background:#dc2626}",
			".gw-form-row{display:flex;gap:6px;align-items:center}",
			".gw-input,.gw-select,.gw-textarea{box-sizing:border-box;width:100%;border:1px solid var(--dsw-alias-border-l3);background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary);border-radius:7px;padding:4px 7px;font-size:11px;font-family:inherit}",
			".gw-textarea{min-height:52px;resize:vertical}",
			".gw-log-line{font-size:11px;padding:4px 6px;border-radius:6px;background:var(--dsw-alias-bg-layer-2);border:1px solid var(--dsw-alias-border-l4)}"
		].join("");

		if (typeof document !== "undefined" && !document.querySelector('style[data-plugin-css="dsh-greatwall-v6up/console"]')) {
			const tag = document.createElement("style");
			tag.dataset.plugin = TAB_ID;
			tag.dataset.pluginCss = "dsh-greatwall-v6up/console";
			tag.textContent = CSS_TEXT;
			document.head.appendChild(tag);
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
					jsx("path", {
						d: "M2 13V6h2v2h2V5h4v3h2V6h2v7H2Z",
						stroke: "currentColor",
						strokeWidth: "1.35",
						strokeLinejoin: "round"
					}),
					jsx("path", {
						d: "M6 13v-3h4v3",
						stroke: "currentColor",
						strokeWidth: "1.35",
						strokeLinejoin: "round"
					})
				]
			});
		}

		function GreatwallTitle({ useTabInfo }) {
			const info = useTabInfo ? useTabInfo() : { tab: { title: "长城控制台" } };
			return jsxs(Fragment, {
				children: [
					jsx(GreatwallGlyph, { size: 15 }),
					jsx("span", { style: { marginLeft: 5 }, children: info?.tab?.title || "长城控制台" })
				]
			});
		}

		function stateBadgeClass(st) {
			if (st === "running") return "gw-console-badge gw-badge-run";
			if (st === "paused") return "gw-console-badge gw-badge-pause";
			if (st === "stopped" || st === "error" || st === "interrupted_unclaimed") return "gw-console-badge gw-badge-err";
			return "gw-console-badge";
		}

		function GreatwallConsoleBody({ sessionId }) {
			const [payload, setPayload] = React.useState(null);
			const [loading, setLoading] = React.useState(true);
			const [selectedWs, setSelectedWs] = React.useState("");
			const [busy, setBusy] = React.useState(false);
			const [notice, setNotice] = React.useState("");

			const [abortNodeId, setAbortNodeId] = React.useState("");
			const [abortReason, setAbortReason] = React.useState("");

			const fetchStatus = React.useCallback(async (wsOverride) => {
				try {
					const qs = new URLSearchParams();
					const wsVal = wsOverride !== undefined ? wsOverride : selectedWs;
					if (wsVal) qs.set("workspaceRoot", wsVal);
					if (sessionId) qs.set("sessionId", sessionId);
					const res = await fetch(`${STATUS_API}?${qs.toString()}`, { cache: "no-store" });
					const data = await res.json();
					if (data && data.ok) {
						setPayload(data);
						if (!wsVal && data.workspaceRoot) setSelectedWs(data.workspaceRoot);
					}
				} catch (err) {
					setNotice("刷新状态失败：" + String(err?.message || err));
				} finally {
					setLoading(false);
				}
			}, [selectedWs, sessionId]);

			React.useEffect(() => {
				let alive = true;
				const run = () => { if (alive) void fetchStatus(); };
				run();
				const timer = setInterval(run, 3000);
				return () => { alive = false; clearInterval(timer); };
			}, [fetchStatus]);

			const sendControl = async (action, extra = {}) => {
				setBusy(true);
				setNotice("");
				try {
					const res = await fetch(CONTROL_API, {
						method: "POST",
						headers: { "content-type": "application/json" },
						body: JSON.stringify({
							action,
							workspaceRoot: selectedWs || payload?.workspaceRoot || "",
							sessionId: sessionId || "",
							...extra
						})
					});
					const json = await res.json();
					if (!json.ok) {
						setNotice("⚠️ " + (json.error || "操作未成功"));
					} else {
						setNotice("✅ 已执行：" + action);
						if (action === "abort_node") { setAbortNodeId(""); setAbortReason(""); }
						await fetchStatus();
					}
				} catch (err) {
					setNotice("⚠️ 请求异常：" + String(err?.message || err));
				} finally {
					setBusy(false);
				}
			};

			const st = payload?.status || {};
			const snap = st.snapshot || {};
			const tState = payload?.telemetryState || {};
			const sessionsMap = tState.sessions || {};
			const allSessions = Object.values(sessionsMap).sort((a, b) => String(b.startedAt || "").localeCompare(String(a.startedAt || "")));
			const runningExplorers = st.runningExplorers || [];
			const orderStatus = snap.question_order_status || {};
			const qIds = Array.isArray(snap.required_questions) && snap.required_questions.length
				? snap.required_questions
				: Object.keys(orderStatus).length ? Object.keys(orderStatus) : ["Q1"];
			const ambiguousAlerts = snap.ambiguous_spec_alerts || st.ambiguousSpecAlerts || [];
			const brokenItems = st.circuitBrokenItems || [];
			const effWindow = Math.max(1, Number(st.effectiveContextWindow || 500000));
			const effWindowK = Math.round(effWindow / 1000);
			const modelLabel = st.modelBinding?.provider && st.modelBinding?.model
				? `${st.modelBinding.provider}/${st.modelBinding.model}`
				: "";
			const specRev = Number(st.latestSpecRevision ?? snap.latest_spec_revision ?? 0);
			const closureStatus = snap.closure_state?.status || st.closureStatus || "OPEN";
			const poolState = st.poolState || st.state || "idle";
			const kernelAlive = st.kernelAlive === true;
			const lastError = st.lastError || "";
			const knownWorkspaces = payload?.knownWorkspaces || [];

			return jsxs("div", {
				className: "gw-console-root",
				children: [
					jsxs("div", {
						className: "gw-console-header",
						children: [
							jsxs("div", {
								className: "gw-console-title-wrap",
								children: [
									jsx("strong", { children: "长城 V6-Up v3.0" }),
									jsx("span", { className: stateBadgeClass(poolState), children: poolState }),
									jsx("span", {
										className: kernelAlive ? "gw-console-badge gw-badge-run" : "gw-console-badge gw-badge-err",
										title: kernelAlive ? "Python 控制面内核在线" : (lastError || "Python 控制面内核不可达"),
										children: kernelAlive ? "内核在线" : "内核离线"
									}),
									jsx("span", { className: "gw-muted", children: `${st.stage || "STAGE1_PARSE0"} · ${closureStatus}` })
								]
							}),
							jsxs("div", {
								className: "gw-console-actions",
								children: [
									jsx("button", { type: "button", className: "gw-btn", disabled: busy, onClick: () => void fetchStatus(), children: "刷新" }),
									poolState === "running"
										? jsx("button", { type: "button", className: "gw-btn", disabled: busy, onClick: () => void sendControl("pause"), children: "暂停" })
										: jsx("button", { type: "button", className: "gw-btn gw-btn-primary", disabled: busy || poolState !== "paused", onClick: () => void sendControl("resume"), children: "恢复" }),
									jsx("button", { type: "button", className: "gw-btn gw-btn-danger", disabled: busy || poolState === "idle" || poolState === "stopped", onClick: () => void sendControl("human_stop", { note: "UI_HUMAN_STOP" }), title: "写入不可伪造的人类叫停真源，触发 PARTIAL_ON_HUMAN_STOP 收口汇总", children: "叫停结项" }),
									jsx("button", { type: "button", className: "gw-btn gw-btn-danger", disabled: busy || poolState === "idle" || poolState === "stopped", onClick: () => void sendControl("stop"), children: "强停" })
								]
							})
						]
					}),
					jsxs("div", {
						className: "gw-scroll",
						children: [
							notice && jsx("div", { className: "gw-log-line", children: notice }),
							(!kernelAlive || lastError) && jsx("div", {
								className: "gw-log-line",
								style: { borderColor: "rgba(220,38,38,.45)", color: "#dc2626" },
								children: `🔴 内核异常：${lastError || "Python 控制面未响应"}`
							}),
							ambiguousAlerts.length > 0 && jsx("div", {
								className: "gw-log-line",
								style: { borderColor: "rgba(220,38,38,.45)", color: "#dc2626" },
								children: `🔴 ALERT_AMBIGUOUS_SPEC (${ambiguousAlerts.length})：${ambiguousAlerts[0]?.notes || "存在口径歧义告警（系统按原口径继续不停机）"}`
							}),
							brokenItems.length > 0 && jsx("div", {
								className: "gw-log-line",
								style: { borderColor: "rgba(217,119,6,.45)", color: "#d97706" },
								children: `🟠 单项治理熔断 (${brokenItems.length})：${brokenItems.map((b) => b.key).join(", ")}（不连坐其他健康项，resume 可复位）`
							}),
							(modelLabel || specRev > 0) && jsx("div", {
								className: "gw-log-line gw-muted",
								children: `模型绑定：${modelLabel || "待绑定"} · 有效窗口：${effWindowK}k · 裁决版本：v${specRev}`
							}),
							knownWorkspaces.length > 0 && jsxs("div", {
								className: "gw-form-row",
								children: [
									jsx("span", { className: "gw-muted", style: { flex: "none" }, children: "工作区：" }),
									jsx("select", {
										className: "gw-select",
										value: selectedWs || payload?.workspaceRoot || "",
										onChange: (e) => { setSelectedWs(e.target.value); void fetchStatus(e.target.value); },
										children: knownWorkspaces.map((w) => jsx("option", { value: w, children: w }, w))
									})
								]
							}),
							loading && !payload && jsx("div", { className: "gw-muted", children: "正在读取控制面状态…" }),
							jsxs("div", {
								className: "gw-card",
								children: [
									jsxs("div", {
										className: "gw-card-title",
										children: [
											jsx("span", { children: "子题进展 & 两步终核状态" }),
											jsx("span", { className: "gw-muted", children: `待盲审:${(snap.pending_reviews || []).length} | 待分诊:${(snap.awaiting_triage || []).length}` })
										]
									}),
									jsxs("div", {
										className: "gw-q-grid",
										children: qIds.map((qid) => {
											const info = orderStatus[qid] || {};
											const l3c = Number(info.full_goal_l3_count ?? info.l3_count ?? 0);
											const needsBranch = (snap.questions_needing_branch || []).includes(qid);
											const blocked = info.unlocked === false;
											return jsxs("div", {
												className: "gw-q-item",
												children: [
													jsxs("div", {
														className: "gw-row",
														children: [
															jsx("strong", { children: qid }),
															jsx("span", {
																className: blocked ? "gw-badge-pause gw-console-badge" : (l3c > 0 ? "gw-badge-run gw-console-badge" : "gw-console-badge"),
																children: blocked ? "顺序待解锁" : (l3c > 0 ? `L3×${l3c}` : (needsBranch ? "待派枝" : "探索中"))
															})
														]
													})
												]
											}, qid);
										})
									})
								]
							}),
							jsxs("div", {
								className: "gw-card",
								children: [
									jsxs("div", {
										className: "gw-card-title",
										children: [
											jsx("span", { children: `节点会话与自适应窗口 (${effWindowK}k) 压力监视` }),
											jsx("span", { className: "gw-muted", children: `运行中探索者: ${runningExplorers.length} | 待交接恢复: ${(st.pendingHandoffNodes || []).length}` })
										]
									}),
									allSessions.length === 0
										? jsx("div", { className: "gw-muted", children: "暂无节点记录（主控 start 后将在此实时显示各探索枝与门控会话）" })
										: allSessions.slice(0, 12).map((s) => {
											const tok = Number(s.pressureTokens || 0);
											const pct = Math.min(100, Math.round((tok / effWindow) * 100));
											const fillCls = pct >= 70 ? "gw-bar-fill gw-bar-hot" : (pct >= 37 ? "gw-bar-fill gw-bar-warn" : "gw-bar-fill");
											return jsxs("div", {
												className: "gw-log-line",
												style: { cursor: s.nodeId ? "pointer" : "default" },
												onClick: () => { if (s.nodeId) setAbortNodeId(s.nodeId); },
												title: s.nodeId ? "点击填入下方节点 ID 以便确定性中止" : "",
												children: [
													jsxs("div", {
														className: "gw-row",
														children: [
															jsx("span", { style: { fontWeight: 600 }, children: s.title || s.role }),
															jsx("span", { className: stateBadgeClass(s.status), children: s.status })
														]
													}),
													jsxs("div", {
														className: "gw-row gw-muted",
														children: [
															jsx("span", { className: "gw-mono", children: `${s.questionId || "-"} ${s.nodeId || s.sessionId.slice(0, 12)}` }),
															jsx("span", { children: `${Math.round(tok / 1000)}k / ${effWindowK}k (${pct}%)` })
														]
													}),
													s.role === "explorer" && jsx("div", {
														className: "gw-bar-bg",
														style: { marginTop: 3 },
														children: jsx("div", { className: fillCls, style: { width: `${pct}%` } })
													})
												]
											}, s.sessionId);
										})
								]
							}),
							jsxs("div", {
								className: "gw-card",
								children: [
									jsx("div", { className: "gw-card-title", children: "确定性单节点中止 (abort_node)" }),
									jsx("div", { className: "gw-muted", children: "如需补充题意澄清，请先暂停、将文档放入工作区 rulings/ 目录后点击「恢复」自动升级 spec_revision；如需中止旧口径或失控节点，直接执行下方确定性中止。" }),
									jsxs("div", {
										className: "gw-form-row",
										children: [
											jsx("input", {
												className: "gw-input",
												style: { flex: 1 },
												value: abortNodeId,
												onChange: (e) => setAbortNodeId(e.target.value),
												placeholder: "节点 ID (点击上方节点自动填入)"
											}),
											jsx("input", {
												className: "gw-input",
												style: { flex: 1 },
												value: abortReason,
												onChange: (e) => setAbortReason(e.target.value),
												placeholder: "中止原因 (可选)"
											})
										]
									}),
									jsx("button", {
										type: "button",
										className: "gw-btn gw-btn-danger",
										disabled: busy || !abortNodeId.trim(),
										onClick: () => void sendControl("abort_node", { nodeId: abortNodeId.trim(), reason: abortReason.trim() || "UI_ABORT_NODE" }),
										children: "确定性中止该节点并释槽"
									})
								]
							}),
							jsxs("div", {
								className: "gw-card",
								children: [
									jsx("div", { className: "gw-card-title", children: "最近调度事件日志" }),
									(tState.recentEvents || []).slice(-6).reverse().map((ev, i) => jsxs("div", {
										className: "gw-log-line gw-mono",
										children: [
											`[${String(ev.at || "").slice(11, 19)}] ${ev.kind || "event"} `,
											ev.nodeId || ev.itemKey || ev.questionId || ""
										]
									}, `${ev.at || ""}_${i}`)),
									(tState.recentEvents || []).length === 0 && jsx("div", { className: "gw-muted", children: "暂无调度事件" })
								]
							})
						]
					})
				]
			});
		}

		const inject = ["slots", "sidebarRightTabs"];

		function apply(ctx) {
			ctx.effect(() => ctx.sidebarRightTabs.register({
				id: TAB_ID,
				kind: TAB_KIND,
				priority: "extension",
				title: () => "长城控制台",
				guide: [{
					order: 15,
					title: () => "长城控制台",
					description: () => "总控进展・子题依赖锁・500k 压力・人工定向纠偏",
					icon: GreatwallGlyph
				}]
			}), "greatwall-console: register tab type");

			ctx.effect(() => ctx.slots.inject("sidebar.right.pane.tab", () => ctx.slots.register({
				name: "sidebar.right.pane.tab",
				key: TAB_ID
			}, GreatwallConsoleBody)), "greatwall-console: tab body");

			ctx.effect(() => ctx.slots.inject("sidebar.right.pane.tab.title", () => ctx.slots.register({
				name: "sidebar.right.pane.tab.title",
				key: TAB_ID
			}, GreatwallTitle)), "greatwall-console: tab title");
		}

		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
