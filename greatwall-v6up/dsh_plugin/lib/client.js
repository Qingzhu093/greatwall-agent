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
			".gw-console-header{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 11px;border-bottom:1px solid var(--dsw-alias-border-l4);flex:none}",
			".gw-console-title-wrap{display:flex;align-items:center;flex-wrap:wrap;gap:5px;min-width:0}",
			".gw-console-badge{display:inline-flex;align-items:center;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:600;border:1px solid var(--dsw-alias-border-l3);background:var(--dsw-alias-bg-layer-2)}",
			".gw-badge-run{color:#16a34a;border-color:rgba(22,163,74,.35);background:rgba(22,163,74,.1)}",
			".gw-badge-pause{color:#d97706;border-color:rgba(217,119,6,.35);background:rgba(217,119,6,.1)}",
			".gw-badge-err{color:#dc2626;border-color:rgba(220,38,38,.35);background:rgba(220,38,38,.1)}",
			".gw-badge-info{color:#2563eb;border-color:rgba(37,99,235,.35);background:rgba(37,99,235,.1)}",
			".gw-badge-purple{color:#9333ea;border-color:rgba(147,51,234,.35);background:rgba(147,51,234,.1)}",
			".gw-console-actions{display:flex;flex-wrap:wrap;gap:4px}",
			".gw-btn{cursor:pointer;border:1px solid var(--dsw-alias-border-l3);background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);border-radius:7px;padding:3px 8px;font-size:11px;font-weight:500}",
			".gw-btn:hover{background:var(--dsw-alias-interactive-bg-hover)}",
			".gw-btn:disabled{opacity:.45;cursor:not-allowed}",
			".gw-btn-danger{color:#dc2626;border-color:rgba(220,38,38,.35)}",
			".gw-btn-primary{color:#2563eb;border-color:rgba(37,99,235,.4);background:rgba(37,99,235,.08)}",
			".gw-tabs{display:flex;gap:4px;padding:6px 11px;border-bottom:1px solid var(--dsw-alias-border-l4);background:var(--dsw-alias-bg-layer-1);flex:none;overflow-x:auto}",
			".gw-tab{cursor:pointer;border:1px solid transparent;border-radius:6px;padding:3px 9px;font-size:11px;font-weight:600;color:var(--dsw-alias-label-secondary);background:transparent;white-space:nowrap}",
			".gw-tab-active{color:#2563eb;border-color:rgba(37,99,235,.35);background:rgba(37,99,235,.08)}",
			".gw-scroll{flex:1;overflow-y:auto;padding:10px 11px;display:flex;flex-direction:column;gap:10px}",
			".gw-card{border:1px solid var(--dsw-alias-border-l4);background:var(--dsw-alias-bg-layer-1);border-radius:9px;padding:8px 10px;display:flex;flex-direction:column;gap:6px}",
			".gw-card-title{font-size:11px;font-weight:600;color:var(--dsw-alias-label-secondary);display:flex;justify-content:space-between;align-items:center;gap:6px}",
			".gw-kpi-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}",
			".gw-kpi-box{border:1px solid var(--dsw-alias-border-l4);border-radius:8px;padding:6px 8px;background:var(--dsw-alias-bg-layer-2);display:flex;flex-direction:column;gap:2px}",
			".gw-q-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(125px,1fr));gap:6px}",
			".gw-q-item{border:1px solid var(--dsw-alias-border-l4);border-radius:8px;padding:6px 8px;background:var(--dsw-alias-bg-layer-2);display:flex;flex-direction:column;gap:3px}",
			".gw-row{display:flex;align-items:center;justify-content:space-between;gap:6px}",
			".gw-mono{font-family:var(--dsw-font-mono,ui-monospace,monospace);font-size:11px;word-break:break-all}",
			".gw-muted{color:var(--dsw-alias-label-tertiary);font-size:11px}",
			".gw-bar-wrap{position:relative;height:7px;border-radius:999px;background:var(--dsw-alias-fill-l2,rgba(128,128,128,.2));overflow:hidden;margin-top:3px}",
			".gw-bar-fill{height:100%;border-radius:999px;background:#2563eb;transition:width .25s ease}",
			".gw-bar-warn{background:#d97706}",
			".gw-bar-hot{background:#16a34a}",
			".gw-bar-tick{position:absolute;top:0;bottom:0;width:1.5px;background:rgba(255,255,255,.75)}",
			".gw-node-card{border:1px solid var(--dsw-alias-border-l3);border-radius:8px;padding:7px 9px;background:var(--dsw-alias-bg-layer-2);cursor:pointer;display:flex;flex-direction:column;gap:4px;transition:border-color .15s}",
			".gw-node-card:hover{border-color:#2563eb}",
			".gw-node-selected{border-color:#2563eb;box-shadow:0 0 0 1px rgba(37,99,235,.35);background:rgba(37,99,235,.04)}",
			".gw-pre{margin:0;padding:7px 8px;border-radius:7px;background:var(--dsw-alias-bg-layer-2);border:1px solid var(--dsw-alias-border-l4);font-family:var(--dsw-font-mono,ui-monospace,monospace);font-size:11px;white-space:pre-wrap;word-break:break-word;max-height:320px;overflow-y:auto}",
			".gw-form-row{display:flex;gap:6px;align-items:center}",
			".gw-input,.gw-select,.gw-textarea{box-sizing:border-box;width:100%;border:1px solid var(--dsw-alias-border-l3);background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary);border-radius:7px;padding:4px 7px;font-size:11px;font-family:inherit}",
			".gw-log-line{font-size:11px;padding:5px 7px;border-radius:6px;background:var(--dsw-alias-bg-layer-2);border:1px solid var(--dsw-alias-border-l4)}"
		].join("");

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

		function mountConsoleStyles() {
			if (typeof document === "undefined") return () => {};
			const existing = document.querySelector('style[data-plugin-css="dsh-greatwall-v6up/console"]');
			if (existing) {
				existing.textContent = CSS_TEXT;
				return () => {
					try { existing.remove(); } catch {}
				};
			}
			const tag = document.createElement("style");
			tag.dataset.plugin = TAB_ID;
			tag.dataset.pluginCss = "dsh-greatwall-v6up/console";
			tag.textContent = CSS_TEXT;
			document.head.appendChild(tag);
			return () => {
				try { tag.remove(); } catch {}
			};
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
			const info = useTabInfo ? useTabInfo() : { tab: { title: "长城科研指挥舱" } };
			return jsxs(Fragment, {
				children: [
					jsx(GreatwallGlyph, { size: 15 }),
					jsx("span", { style: { marginLeft: 5 }, children: info?.tab?.title || "长城科研指挥舱" })
				]
			});
		}

		function stateBadgeClass(st) {
			const s = String(st || "").toLowerCase();
			if (s === "running" || s === "exploring" || s === "valid_pass" || s === "passed" || s === "accept") return "gw-console-badge gw-badge-run";
			if (s === "active_revising" || s === "pending_review" || s === "stage1_blind" || s === "stage2_unblind") return "gw-console-badge gw-badge-purple";
			if (s === "paused" || s === "archived" || s === "awaiting_triage" || s === "closed_revise" || s === "revise") return "gw-console-badge gw-badge-pause";
			if (s === "stopped" || s === "error" || s === "interrupted_unclaimed" || s === "instrument_error" || s === "alert") return "gw-console-badge gw-badge-err";
			return "gw-console-badge";
		}

		function GreatwallConsoleBody({ sessionId, getUiWorkspace }) {
			const [payload, setPayload] = React.useState(null);
			const [loading, setLoading] = React.useState(true);
			const [selectedWs, setSelectedWs] = React.useState(() => readPersistedWs());
			const [busy, setBusy] = React.useState(false);
			const [notice, setNotice] = React.useState("");

			const updateSelectedWs = React.useCallback((nextWs) => {
				const clean = String(nextWs || "").trim();
				setSelectedWs(clean);
				if (clean) persistSelectedWs(clean);
			}, []);

			const openNativeSession = React.useCallback(async (targetSid, { status = "", archived = false, archiveError = "", label = "", workspaceRoot = "" } = {}) => {
				const sid = String(targetSid || "").trim();
				if (!sid) {
					setNotice("⚠️ 该条目暂无可打开的会话 ID。");
					return;
				}
				const boundWs = workspaceRoot || selectedWs || payload?.workspaceRoot || "";
				if (boundWs) persistSelectedWs(boundWs);
				const uiWs = typeof getUiWorkspace === "function" ? getUiWorkspace() : null;
				if (!uiWs || typeof uiWs.openSession !== "function") {
					setNotice(`⚠️ 当前 DSH 宿主未提供 uiWorkspace.openSession，无法直接跳转会话 ${sid}。`);
					return;
				}
				try {
					await uiWs.openSession(sid);
					const isRunning = String(status || "").toLowerCase() === "running";
					if (isRunning) {
						setNotice(`💬 已打开运行中会话（实时增量）：${label || sid}`);
					} else if (archived) {
						setNotice(`📦 已打开已归档会话：${label || sid}`);
					} else if (archiveError) {
						setNotice(`📄 已打开已结束会话（未归档：${archiveError}）：${label || sid}`);
					} else {
						setNotice(`📄 已打开已结束会话：${label || sid}`);
					}
				} catch (err) {
					setNotice(`⚠️ 无法打开会话 ${sid}：${String(err?.message || err)}`);
				}
			}, [getUiWorkspace, selectedWs, payload?.workspaceRoot]);

			const [activeTab, setActiveTab] = React.useState("flow"); // "flow" | "docs" | "worktree" | "gov"
			const [docSubTab, setDocSubTab] = React.useState("briefing"); // "briefing" | "reflect37" | "handoff70" | "chat" | "obs"
			const [selectedNodeId, setSelectedNodeId] = React.useState("");
			const [selectedFileRel, setSelectedFileRel] = React.useState("");
			const [showGovSessions, setShowGovSessions] = React.useState(false);

			const [abortNodeId, setAbortNodeId] = React.useState("");
			const [abortReason, setAbortReason] = React.useState("");

			const fetchStatus = React.useCallback(async (wsOverride, nodeOverride, fileOverride) => {
				try {
					const qs = new URLSearchParams();
					const wsVal = wsOverride !== undefined ? wsOverride : selectedWs;
					const nidVal = nodeOverride !== undefined ? nodeOverride : selectedNodeId;
					const fileVal = fileOverride !== undefined ? fileOverride : selectedFileRel;
					if (wsVal) qs.set("workspaceRoot", wsVal);
					if (sessionId) qs.set("sessionId", sessionId);
					if (nidVal) qs.set("selectedNodeId", nidVal);
					if (fileVal) qs.set("selectedFile", fileVal);
					const res = await fetch(`${STATUS_API}?${qs.toString()}`, { cache: "no-store" });
					const data = await res.json();
					if (data && data.ok) {
						setPayload(data);
						if (!wsVal && data.workspaceRoot) updateSelectedWs(data.workspaceRoot);
						const detailNid = data.inspector?.selected_node_detail?.node_id || "";
						if (!nidVal && detailNid) setSelectedNodeId(detailNid);
					}
				} catch (err) {
					setNotice("刷新状态失败：" + String(err?.message || err));
				} finally {
					setLoading(false);
				}
			}, [selectedWs, sessionId, selectedNodeId, selectedFileRel]);

			React.useEffect(() => {
				let alive = true;
				const run = () => { if (alive) void fetchStatus(); };
				run();
				const timer = setInterval(run, 3500);
				return () => { alive = false; clearInterval(timer); };
			}, [fetchStatus]);

			const sendControl = async (action, extra = {}) => {
				if (action === "stop" || action === "human_stop") {
					const msg = action === "human_stop"
						? "确认触发「叫停结项 (PARTIAL_ON_HUMAN_STOP)」并进入 Stage 3 汇总导出？"
						: "确认强制停止当前后台编排循环？";
					if (typeof window !== "undefined" && typeof window.confirm === "function" && !window.confirm(msg)) {
						return;
					}
				}
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
			const insp = payload?.inspector || {};
			const snap = insp.snapshot || st.snapshot || {};
			const topo = insp.topology_health || {};
			const slotUtil = topo.slot_utilization || snap.slot_utilization || { active_branches_count: 0, slot_cap: 6, free_slots: 6 };
			const families = insp.method_families || [];
			const lineageNodes = insp.lineage_nodes || [];
			const obsList = insp.observations || [];
			const probesList = insp.probes || [];
			const reviewsList = insp.reviews || [];
			const ledgerList = insp.internal_ledger || [];
			const worksTickets = insp.works_tickets || [];
			const complianceLogs = insp.compliance_logs || [];
			const nodeDetail = insp.selected_node_detail || null;
			const nodeConversations = payload?.nodeConversations || [];

			const tState = payload?.telemetryState || {};
			const sessionsMap = tState.sessions || {};
			const allSessions = Object.values(sessionsMap).sort((a, b) => String(b.startedAt || "").localeCompare(String(a.startedAt || "")));
			const govSessions = Array.isArray(payload?.governanceSessions) && payload.governanceSessions.length > 0
				? payload.governanceSessions
				: allSessions.filter((s) => s.role !== "explorer");
			const latestNodeSessionByRole = {};
			const verifierSessionByReviewId = {};
			for (const s of allSessions) {
				if (s?.nodeId && (s.role === "explorer" || s.role === "lineage_companion")) {
					const k = `${s.nodeId}:${s.role}`;
					if (!latestNodeSessionByRole[k]) latestNodeSessionByRole[k] = s;
				}
				if (s?.role === "library_verifier" && s.reviewId && !verifierSessionByReviewId[s.reviewId]) {
					verifierSessionByReviewId[s.reviewId] = s;
				}
			}

			const isLiveController = payload?.source === "live_controller";
			const poolState = st.poolState || st.state || (isLiveController ? "idle" : "archived");
			const kernelAlive = st.kernelAlive === true || Boolean(insp.snapshot);
			const lastError = st.lastError || "";
			const knownWorkspaces = payload?.knownWorkspaces || [];

			const effWindow = Math.max(1, Number(st.effectiveContextWindow || 500000));
			const effWindowK = Math.round(effWindow / 1000);
			const modelLabel = st.modelBinding?.provider && st.modelBinding?.model
				? `${st.modelBinding.provider}/${st.modelBinding.model}`
				: "";
			const specRev = Number(st.latestSpecRevision ?? snap.latest_spec_revision ?? 0);
			const closureStatus = snap.closure_state?.status || st.closureStatus || "OPEN";

			const orderStatus = snap.question_order_status || {};
			const qIds = Array.isArray(snap.required_questions) && snap.required_questions.length
				? snap.required_questions
				: Object.keys(orderStatus).length ? Object.keys(orderStatus) : ["Q1"];
			const ambiguousAlerts = snap.ambiguous_spec_alerts || st.ambiguousSpecAlerts || [];
			const orphanedRevs = topo.orphaned_blind_review_revisions || snap.orphaned_blind_review_revisions || [];
			const understaffedQs = topo.understaffed_questions || snap.understaffed_questions || [];
			const brokenItems = st.circuitBrokenItems || [];

			const obsPassCount = obsList.filter((o) => o.obs_status === "VALID_PASS").length;
			const obsRejCount = obsList.filter((o) => o.obs_status === "MEASURED_REJECTION").length;
			const obsErrCount = obsList.filter((o) => o.obs_status === "CANDIDATE_ERROR" || o.obs_status === "INSTRUMENT_ERROR").length;

			// 按 branch_id 分组谱系树
			const nodesByBranch = {};
			for (const nd of lineageNodes) {
				const b = nd.branch_id || "default";
				if (!nodesByBranch[b]) nodesByBranch[b] = [];
				nodesByBranch[b].push(nd);
			}
			const branchEntries = Object.entries(nodesByBranch);

			const handleSelectNode = (nid) => {
				setSelectedNodeId(nid);
				setSelectedFileRel("");
				setAbortNodeId(nid);
				void fetchStatus(undefined, nid, "");
			};

			return jsxs("div", {
				className: "gw-console-root",
				children: [
					// 1. 顶部双态指挥横幅
					jsxs("div", {
						className: "gw-console-header",
						children: [
							jsxs("div", {
								className: "gw-console-title-wrap",
								children: [
									jsx("strong", { children: "长城指挥舱 v3.0" }),
									jsx("span", {
										className: stateBadgeClass(poolState),
										children: isLiveController ? poolState : `📦 历史存档 (${poolState})`
									}),
									jsx("span", {
										className: kernelAlive ? "gw-console-badge gw-badge-run" : "gw-console-badge gw-badge-pause",
										title: kernelAlive ? "SQLite 控制面真相库已连接" : (lastError || "未连接活跃控制器"),
										children: isLiveController ? (kernelAlive ? "内核在线" : "内核离线") : "只读回放就绪"
									}),
									jsx("span", { className: "gw-muted", children: `${snap.stage || st.stage || "STAGE2_EVOLVE"} · v${specRev}` })
								]
							}),
							jsxs("div", {
								className: "gw-console-actions",
								children: [
									jsx("button", { type: "button", className: "gw-btn", disabled: busy, onClick: () => void fetchStatus(), children: "刷新" }),
									poolState === "running"
										? jsx("button", { type: "button", className: "gw-btn", disabled: busy || !isLiveController, onClick: () => void sendControl("pause"), children: "暂停" })
										: jsx("button", { type: "button", className: "gw-btn gw-btn-primary", disabled: busy || !isLiveController || poolState !== "paused", onClick: () => void sendControl("resume"), children: "恢复" }),
									jsx("button", { type: "button", className: "gw-btn gw-btn-danger", disabled: busy || !isLiveController || poolState === "idle" || poolState === "stopped", onClick: () => void sendControl("human_stop", { note: "UI_HUMAN_STOP" }), title: "写入人类叫停真源并进入 Stage 3 部分交付", children: "叫停结项" }),
									jsx("button", { type: "button", className: "gw-btn gw-btn-danger", disabled: busy || !isLiveController || poolState === "idle" || poolState === "stopped", onClick: () => void sendControl("stop"), children: "强停" })
								]
							})
						]
					}),

					// 2. 四大导航 Tab
					jsxs("div", {
						className: "gw-tabs",
						children: [
							jsx("button", {
								type: "button",
								className: `gw-tab ${activeTab === "flow" ? "gw-tab-active" : ""}`,
								onClick: () => setActiveTab("flow"),
								children: `🌿 谱系 Flow (${lineageNodes.length})`
							}),
							jsx("button", {
								type: "button",
								className: `gw-tab ${activeTab === "docs" ? "gw-tab-active" : ""}`,
								onClick: () => setActiveTab("docs"),
								children: `📋 节点文书 & 37%反思 (${nodeDetail ? nodeDetail.node_id.slice(-8) : "未选"})`
							}),
							jsx("button", {
								type: "button",
								className: `gw-tab ${activeTab === "worktree" ? "gw-tab-active" : ""}`,
								onClick: () => setActiveTab("worktree"),
								children: `📂 Worktree 源码 (${nodeDetail?.worktree_files?.length || 0})`
							}),
							jsx("button", {
								type: "button",
								className: `gw-tab ${activeTab === "gov" ? "gw-tab-active" : ""}`,
								onClick: () => setActiveTab("gov"),
								children: `🛡️ 监察 & 盲审 (${reviewsList.length}/${worksTickets.length})`
							})
						]
					}),

					// 3. 主滚动区
					jsxs("div", {
						className: "gw-scroll",
						children: [
							notice && jsx("div", { className: "gw-log-line", children: notice }),
							knownWorkspaces.length > 0 && jsxs("div", {
								className: "gw-form-row",
								children: [
									jsx("span", { className: "gw-muted", style: { flex: "none" }, children: "工作区：" }),
									jsx("select", {
										className: "gw-select",
										value: selectedWs || payload?.workspaceRoot || "",
										onChange: (e) => {
											updateSelectedWs(e.target.value);
											setSelectedNodeId("");
											setSelectedFileRel("");
											void fetchStatus(e.target.value, "", "");
										},
										children: knownWorkspaces.map((w) => jsx("option", { value: w, children: w }, w))
									})
								]
							}),

							// 全局告警条（孤儿返工单 / 单线独苗退化 / 口径红灯 / 熔断）
							orphanedRevs.length > 0 && jsx("div", {
								className: "gw-log-line",
								style: { borderColor: "rgba(220,38,38,.45)", color: "#dc2626" },
								children: `🚨 孤儿盲审返工单 (${orphanedRevs.map((r) => `${r.review_id}@${r.source_node_id}`).join(", ")})：原分支已被中止，恢复运行后后勤总管将自动 fork_branch 继承快照与返工单！`
							}),
							understaffedQs.length > 0 && jsx("div", {
								className: "gw-log-line",
								style: { borderColor: "rgba(217,119,6,.45)", color: "#d97706" },
								children: `⚠️ 单线独苗退化告警：${understaffedQs.map((u) => `${u.question_id} 仅 ${u.active_branch_count}/${(u.registered_active_families || []).length} 学派在跑（缺编: ${(u.missing_active_family_ids || []).join(", ")}）`).join("；")}`
							}),
							ambiguousAlerts.length > 0 && jsx("div", {
								className: "gw-log-line",
								style: { borderColor: "rgba(220,38,38,.45)", color: "#dc2626" },
								children: `🔴 ALERT_AMBIGUOUS_SPEC (${ambiguousAlerts.length})：${ambiguousAlerts[0]?.notes || ""}`
							}),
							brokenItems.length > 0 && jsx("div", {
								className: "gw-log-line",
								style: { borderColor: "rgba(217,119,6,.45)", color: "#d97706" },
								children: `🟠 单项治理熔断 (${brokenItems.length})：${brokenItems.map((b) => b.key).join(", ")}`
							}),

							// 4 张顶部高密度科研指标卡
							jsxs("div", {
								className: "gw-kpi-grid",
								children: [
									jsxs("div", {
										className: "gw-kpi-box",
										children: [
											jsx("span", { className: "gw-muted", children: "🌿 并发槽位 & 学派覆盖" }),
											jsx("strong", { children: `${slotUtil.active_branches_count || 0} / ${slotUtil.slot_cap || 6} 活跃分支 (${families.length} 学派)` }),
											jsx("span", { className: "gw-muted", children: `待分诊: ${(snap.awaiting_triage || []).length} · 断代: ${(topo.stalled_or_aborted_branches || []).length}` })
										]
									}),
									jsxs("div", {
										className: "gw-kpi-box",
										children: [
											jsx("span", { className: "gw-muted", children: "🔬 观测 [Obs] & 探针 [Probe]" }),
											jsx("strong", { children: `PASS:${obsPassCount} · REJ:${obsRejCount} · ERR:${obsErrCount}` }),
											jsx("span", { className: "gw-muted", children: `总 Obs: ${obsList.length} · Probe 日志: ${probesList.length}` })
										]
									}),
									jsxs("div", {
										className: "gw-kpi-box",
										children: [
											jsx("span", { className: "gw-muted", children: "🏛️ 盲审 & 图书馆 L3/L2" }),
											jsx("strong", { children: `L3/L2: ${ledgerList.length} · 盲审单: ${reviewsList.length}` }),
											jsx("span", { className: "gw-muted", children: `外藏 [R]: ${snap.external_literature_count || 0} · 终局: ${closureStatus}` })
										]
									}),
									jsxs("div", {
										className: "gw-kpi-box",
										children: [
											jsx("span", { className: "gw-muted", children: "🛠️ 活跃仪器 & 裁决口径" }),
											jsx("strong", { children: `活跃仪器: ${(snap.active_instruments || []).length} · 裁决 v${specRev}` }),
											jsx("span", { className: "gw-muted", children: `${modelLabel || "自适应时钟"} · 窗口 ${effWindowK}k` })
										]
									})
								]
							}),

							// ==================== TAB 1: 🌿 谱系演化流 Flow (DAG 树) ====================
							activeTab === "flow" && jsxs(Fragment, {
								children: [
									// 子题流水线状态
									jsxs("div", {
										className: "gw-card",
										children: [
											jsxs("div", {
												className: "gw-card-title",
												children: [
													jsx("span", { children: "子题流水线 & 公开裁决摘要" }),
													jsx("span", { className: "gw-muted", children: `最新裁决 v${specRev}` })
												]
											}),
											jsxs("div", {
												className: "gw-q-grid",
												children: qIds.map((qid) => {
													const info = orderStatus[qid] || {};
													const l3c = Number(info.full_goal_l3_count ?? 0);
													const blocked = info.unlocked === false;
													const qFams = families.filter((f) => f.question_id === qid);
													const qNodes = lineageNodes.filter((n) => n.question_id === qid);
													return jsxs("div", {
														className: "gw-q-item",
														children: [
															jsxs("div", {
																className: "gw-row",
																children: [
																	jsx("strong", { children: qid }),
																	jsx("span", {
																		className: blocked ? "gw-badge-pause gw-console-badge" : (l3c > 0 ? "gw-badge-run gw-console-badge" : "gw-badge-info gw-console-badge"),
																		children: blocked ? "待解锁" : (l3c > 0 ? `L3×${l3c}` : "攻关中")
																	})
																]
															}),
															jsx("div", { className: "gw-muted", children: `学派: ${qFams.length} · 节点: ${qNodes.length}` })
														]
													}, qid);
												})
											}),
											snap.latest_ruling_summary_md && jsx("div", {
												className: "gw-log-line gw-mono",
												children: `📜 公开裁决 (v${specRev})：${snap.latest_ruling_summary_md}`
											})
										]
									}),

									// 探索分支与代际 DAG 树（置顶核心视图！）
									jsxs("div", {
										className: "gw-card",
										children: [
											jsxs("div", {
												className: "gw-card-title",
												children: [
													jsx("span", { children: "🌿 探索者谱系演化树 (点击任意节点查看五段看板 / 37%元反思 / 70%遗嘱 / 代码)" }),
													jsx("span", { className: "gw-muted", children: `${branchEntries.length} 条分支 · ${lineageNodes.length} 个节点` })
												]
											}),
											branchEntries.length === 0
												? jsx("div", { className: "gw-muted", children: "暂无探索者节点" })
												: branchEntries.map(([bid, bNodes]) => {
													const latestNd = bNodes[bNodes.length - 1] || {};
													const famId = latestNd.family_id || "未归类";
													const famObj = families.find((f) => f.family_id === famId);
													return jsxs("div", {
														className: "gw-log-line",
														style: { display: "flex", flexDirection: "column", gap: 6 },
														children: [
															jsxs("div", {
																className: "gw-row",
																children: [
																	jsxs("span", {
																		style: { fontWeight: 600 },
																		children: [
																			`[${latestNd.question_id || "Q1"}] 分支 `,
																			jsx("span", { className: "gw-mono", children: bid }),
																			` · 学派: `,
																			jsx("span", { className: "gw-console-badge gw-badge-info", children: famId })
																		]
																	}),
																	jsx("span", { className: stateBadgeClass(latestNd.node_status), children: latestNd.node_status })
																]
															}),
															famObj && jsx("div", { className: "gw-muted", children: `机理签名：${famObj.mechanism_signature}` }),
															// 代际节点链 Gen 1 -> Gen 2 -> Gen 3
															jsxs("div", {
																style: { display: "flex", flexDirection: "column", gap: 5, paddingLeft: 6, borderLeft: "2px solid var(--dsw-alias-border-l3)" },
																children: bNodes.map((nd) => {
																	const isSel = selectedNodeId === nd.node_id || (!selectedNodeId && nodeDetail?.node_id === nd.node_id);
																	const pct = Math.min(100, Number(nd.pressure_pct || 0));
																	const fillCls = pct >= 70 ? "gw-bar-fill gw-bar-hot" : (pct >= 37 ? "gw-bar-fill gw-bar-warn" : "gw-bar-fill");
																	const obsIds = nd.bound_obs_ids || [];
																	const expSess = latestNodeSessionByRole[`${nd.node_id}:explorer`] || null;
																	const compSess = latestNodeSessionByRole[`${nd.node_id}:lineage_companion`] || null;
																	return jsxs("div", {
																		className: `gw-node-card ${isSel ? "gw-node-selected" : ""}`,
																		onClick: () => handleSelectNode(nd.node_id),
																		children: [
																			jsxs("div", {
																				className: "gw-row",
																				children: [
																					jsxs("span", {
																						style: { fontWeight: 600 },
																						children: [
																							`Gen ${nd.generation} · `,
																							jsx("span", { className: "gw-mono", children: nd.node_id }),
																							` (v${nd.spec_revision ?? 0})`
																						]
																					}),
																					jsxs("div", {
																						style: { display: "flex", gap: 4, alignItems: "center" },
																						children: [
																							nd.first_reflection_unlocked ? jsx("span", { className: "gw-console-badge gw-badge-warn", title: "已完成 37% 外部专家元反思并解锁内藏", children: "💡37%反思" }) : null,
																							nd.evidence_grade && nd.evidence_grade !== "NONE" ? jsx("span", { className: "gw-console-badge gw-badge-info", children: nd.evidence_grade }) : null,
																							jsx("span", { className: stateBadgeClass(nd.node_status), children: nd.node_status })
																						]
																					})
																				]
																			}),
																			nd.mechanism_summary && jsx("div", { style: { fontSize: 11 }, children: `🔬 ${nd.mechanism_summary}` }),
																			jsxs("div", {
																				className: "gw-row gw-muted",
																				children: [
																					jsx("span", { children: `水位: ${Math.round((nd.pressure_tokens || 0) / 1000)}k / ${Math.round((nd.effective_context_window || 500000) / 1000)}k (${pct}%)` }),
																					obsIds.length > 0
																						? jsx("span", { className: "gw-mono", children: `绑定: ${obsIds.join(", ")}` })
																						: (nd.candidate_rel_path ? jsx("span", { className: "gw-mono", children: `产物: ${nd.candidate_rel_path}` }) : jsx("span", { children: "点击查看文书 →" }))
																				]
																			}),
																			// 0% - 37% - 70% 三段刻度水位条
																			jsxs("div", {
																				className: "gw-bar-wrap",
																				title: "37% 触发外部专家元反思 | 70% 触发亲笔遗嘱与伴随 A/B 交接",
																				children: [
																					jsx("div", { className: fillCls, style: { width: `${pct}%` } }),
																					jsx("div", { className: "gw-bar-tick", style: { left: "37%" } }),
																					jsx("div", { className: "gw-bar-tick", style: { left: "70%" } })
																				]
																			}),
																			jsxs("div", {
																				className: "gw-console-actions",
																				style: { marginTop: 2 },
																				children: [
																					jsx("button", {
																						type: "button",
																						className: "gw-btn gw-btn-primary",
																						onClick: (e) => { e.stopPropagation(); handleSelectNode(nd.node_id); setActiveTab("docs"); },
																						children: "📋 查看五段看板/反思/遗嘱"
																					}),
																					jsx("button", {
																						type: "button",
																						className: "gw-btn",
																						onClick: (e) => { e.stopPropagation(); handleSelectNode(nd.node_id); setActiveTab("worktree"); },
																						children: "📂 浏览 Worktree 代码"
																					}),
																					expSess && jsx("button", {
																						type: "button",
																						className: "gw-btn",
																						onClick: (e) => {
																							e.stopPropagation();
																							void openNativeSession(expSess.sessionId, { status: expSess.status, archived: expSess.archived, archiveError: expSess.archiveError, workspaceRoot: expSess.workspaceRoot, label: expSess.title || `探索者 ${nd.node_id}` });
																						},
																						children: "💬 探索者对话"
																					}),
																					compSess && jsx("button", {
																						type: "button",
																						className: "gw-btn",
																						onClick: (e) => {
																							e.stopPropagation();
																							void openNativeSession(compSess.sessionId, { status: compSess.status, archived: compSess.archived, archiveError: compSess.archiveError, workspaceRoot: compSess.workspaceRoot, label: compSess.title || `伴随 ${nd.node_id}` });
																						},
																						children: "💬 伴随对话"
																					})
																				]
																			})
																		]
																	}, nd.node_id);
																})
															})
														]
													}, bid);
												})
										]
									}),

									// 确定性单节点中止 + 治理角色折叠区
									jsxs("div", {
										className: "gw-card",
										children: [
											jsx("div", { className: "gw-card-title", children: "确定性单节点中止 (abort_node)" }),
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
													}),
													jsx("button", {
														type: "button",
														className: "gw-btn gw-btn-danger",
														disabled: busy || !isLiveController || !abortNodeId.trim(),
														onClick: () => void sendControl("abort_node", { nodeId: abortNodeId.trim(), reason: abortReason.trim() || "UI_ABORT_NODE" }),
														children: "中止节点"
													})
												]
											})
										]
									}),

									jsxs("div", {
										className: "gw-card",
										children: [
											jsxs("div", {
												className: "gw-card-title",
												style: { cursor: "pointer" },
												onClick: () => setShowGovSessions(!showGovSessions),
												children: [
													jsx("span", { children: `🏛️ 治理与保障角色会话组 (${govSessions.length}) ${showGovSessions ? "▾" : "▸"}` }),
													jsx("span", { className: "gw-muted", children: "后勤 / 伴随 / 工造司 / 盲审 / 监察" })
												]
											}),
											showGovSessions && govSessions.slice(0, 20).map((s) => jsxs("div", {
												className: "gw-log-line",
												children: [
													jsxs("div", {
														className: "gw-row",
														children: [
															jsx("strong", { children: s.title || s.role }),
															jsxs("div", {
																style: { display: "flex", alignItems: "center", gap: 4 },
																children: [
																	jsx("span", { className: stateBadgeClass(s.status), children: s.status }),
																	jsx("button", {
																		type: "button",
																		className: "gw-btn gw-btn-primary",
																		onClick: () => void openNativeSession(s.sessionId, { status: s.status, archived: s.archived, archiveError: s.archiveError, workspaceRoot: s.workspaceRoot, label: s.title || s.role }),
																		children: "打开对话"
																	})
																]
															})
														]
													}),
													jsxs("div", {
														className: "gw-row gw-muted gw-mono",
														children: [
															jsx("span", { children: `${s.sessionId}${s.reviewId ? ` · ${s.reviewId}` : ""}${s.deliveryId ? ` · ${s.deliveryId}` : ""}` }),
															jsx("span", { children: String(s.startedAt || "").slice(11, 19) })
														]
													}),
													s.archiveError && jsx("div", { className: "gw-muted", style: { color: "#d97706" }, children: `归档提示：${s.archiveError}` })
												]
											}, s.sessionId))
										]
									})
								]
							}),

							// ==================== TAB 2: 📋 节点内部文书 & 37%元反思 & 70%遗嘱 & 跨cwd会话 ====================
							activeTab === "docs" && jsxs(Fragment, {
								children: [
									// 节点切换器
									jsxs("div", {
										className: "gw-form-row",
										children: [
											jsx("span", { className: "gw-muted", style: { flex: "none" }, children: "选择探索节点：" }),
											jsx("select", {
												className: "gw-select",
												value: nodeDetail?.node_id || selectedNodeId || "",
												onChange: (e) => handleSelectNode(e.target.value),
												children: lineageNodes.map((n) => jsx("option", {
													value: n.node_id,
													children: `[${n.question_id}] Gen ${n.generation} · ${n.node_id} (${n.family_id || "未归类"} · ${n.node_status} · ${n.pressure_pct}%)`
												}, n.node_id))
											})
										]
									}),

									!nodeDetail
										? jsx("div", { className: "gw-muted", children: "请先在上方或 Flow 树中选择一个探索节点" })
										: jsxs(Fragment, {
											children: [
												// 二级文书切换栏
												jsxs("div", {
													className: "gw-console-actions",
													children: [
														jsx("button", {
															type: "button",
															className: `gw-btn ${docSubTab === "briefing" ? "gw-btn-primary" : ""}`,
															onClick: () => setDocSubTab("briefing"),
															children: `1. 五段看板 (${nodeDetail.briefings?.length || 0})`
														}),
														jsx("button", {
															type: "button",
															className: `gw-btn ${docSubTab === "reflect37" ? "gw-btn-primary" : ""}`,
															onClick: () => setDocSubTab("reflect37"),
															children: `2. 💡37% 元反思 (${nodeDetail.reflections?.length || 0})`
														}),
														jsx("button", {
															type: "button",
															className: `gw-btn ${docSubTab === "handoff70" ? "gw-btn-primary" : ""}`,
															onClick: () => setDocSubTab("handoff70"),
															children: "3. 📜70% 遗嘱 & A/B 交接单"
														}),
														jsx("button", {
															type: "button",
															className: `gw-btn ${docSubTab === "chat" ? "gw-btn-primary" : ""}`,
															onClick: () => setDocSubTab("chat"),
															children: `4. 💬跨cwd会话轨迹 (${nodeConversations.length})`
														}),
														jsx("button", {
															type: "button",
															className: `gw-btn ${docSubTab === "obs" ? "gw-btn-primary" : ""}`,
															onClick: () => setDocSubTab("obs"),
															children: `5. ⚖️观测 & 死胡同 (${(nodeDetail.observations?.length || 0)}/${(nodeDetail.dead_ends?.length || 0)})`
														})
													]
												}),

												// 子页 1：伴随五段看板
												docSubTab === "briefing" && jsxs("div", {
													className: "gw-card",
													children: [
														jsxs("div", {
															className: "gw-card-title",
															children: [
																jsx("span", { children: `伴随五段状态看板 (Rewrite_<=2200) · ${nodeDetail.node_id}` }),
																jsx("span", { className: "gw-muted", children: `分支: ${nodeDetail.branch_id}` })
															]
														}),
														(nodeDetail.active_revision_requests || []).length > 0 && jsx("div", {
															className: "gw-log-line",
															style: { borderColor: "rgba(147,51,234,.45)", color: "#9333ea" },
															children: `🟣 活跃盲审返工要求 (REVISE)：${JSON.stringify(nodeDetail.active_revision_requests)}`
														}),
														(nodeDetail.briefings || []).length === 0
															? jsx("div", { className: "gw-muted", children: "该节点暂无五段看板记录" })
															: (nodeDetail.briefings || []).map((br) => jsxs("div", {
																className: "gw-log-line",
																style: { display: "flex", flexDirection: "column", gap: 6 },
																children: [
																	jsxs("div", {
																		className: "gw-row gw-muted",
																		children: [
																			jsx("strong", { children: `看板 ${br.briefing_id} (对应节点 ${br.node_id})` }),
																			jsx("span", { children: `总字数: ${br.total_chars} / 2200` })
																		]
																	}),
																	jsx("pre", {
																		className: "gw-pre",
																		children: [
																			`【段1 核心机制】\n${br.sec1_mechanism}\n`,
																			`【段2 已证实基线与返工要求】\n${br.sec2_verified_baseline}\n`,
																			`【段3 当前核心矛盾】\n${br.sec3_bottleneck}\n`,
																			`【段4 关键死胡同精选】\n${br.sec4_dead_ends}\n`,
																			`【段5 本代首要遗嘱 (Immediate Will)】\n${br.sec5_immediate_will}`
																		].join("\n")
																	})
																]
															}, br.briefing_id))
													]
												}),

												// 子页 2：37% 外部专家元反思问答
												docSubTab === "reflect37" && jsxs("div", {
													className: "gw-card",
													children: [
														jsxs("div", {
															className: "gw-card-title",
															children: [
																jsx("span", { children: `💡 37% 临床诊断与夜科学元反思 (${nodeDetail.node_id})` }),
																jsx("span", { className: "gw-muted", children: nodeDetail.first_reflection_unlocked ? "✅ 已解锁全馆 L3/L2" : "🔒 尚未到达 37%" })
															]
														}),
														(nodeDetail.reflections || []).length === 0
															? jsx("div", { className: "gw-muted", children: "该节点尚未触发或未保存 37% 元反思" })
															: (nodeDetail.reflections || []).map((rf, idx) => jsxs("div", {
																className: "gw-log-line",
																style: { display: "flex", flexDirection: "column", gap: 6 },
																children: [
																	jsxs("div", {
																		className: "gw-row",
																		children: [
																			jsx("strong", { children: `夜科学题 #${rf.holiday_prompt_id} · 诊断分类: ${(rf.selected_categories || []).join(", ")}` }),
																			jsx("span", { className: "gw-console-badge gw-badge-info", children: rf.verdict_3state })
																		]
																	}),
																	(rf.turns || []).map((t, tidx) => jsxs("div", {
																		style: { display: "flex", flexDirection: "column", gap: 4 },
																		children: [
																			jsx("pre", { className: "gw-pre", children: `🧑‍⚕️ [伴随·外部领域专家追问 Turn ${tidx + 1}]:\n${t.question}` }),
																			jsx("pre", { className: "gw-pre", children: `🧑‍🔬 [探索者·自省与下半场决断 Turn ${tidx + 1}]:\n${t.answer}` })
																		]
																	}, tidx))
																]
															}, idx))
													]
												}),

												// 子页 3：70% 亲笔遗嘱与伴随 A/B 双栏交接单
												docSubTab === "handoff70" && jsxs("div", {
													className: "gw-card",
													children: [
														jsxs("div", {
															className: "gw-card-title",
															children: [
																jsx("span", { children: `📜 70% 探索者亲笔遗嘱 & 伴随客观 A/B 双栏交接单 (${nodeDetail.node_id})` }),
																jsx("span", { className: "gw-console-badge gw-badge-info", children: `证据等级: ${nodeDetail.evidence_grade}` })
															]
														}),
														nodeDetail.mechanism_summary && jsx("div", { className: "gw-log-line", children: `核心机制摘要 (<100字)：${nodeDetail.mechanism_summary}` }),
														jsx("div", { className: "gw-muted", children: "✅ A 栏：已核验客观实测事实与推导资产（供 Stage 1 盲审）" }),
														jsx("pre", { className: "gw-pre", children: nodeDetail.column_a_facts_md || "(尚未交接或 A 栏为空)" }),
														jsx("div", { className: "gw-muted", children: "⚠️ B 栏：未核验机理猜想与反常线索（Stage 1 盲审物理屏蔽）" }),
														jsx("pre", { className: "gw-pre", children: nodeDetail.column_b_hypothesis_md || "(B 栏为空)" }),
														jsx("div", { className: "gw-muted", children: "🧑‍🔬 探索者 70% 退场前亲笔遗嘱 (Explorer Raw Will) & 伴随核定遗嘱" }),
														jsx("pre", { className: "gw-pre", children: `【伴随核定下代遗嘱】\n${nodeDetail.will_md || "(空)"}\n\n【探索者亲笔原文】\n${nodeDetail.explorer_will_md || "(空)"}` })
													]
												}),

												// 子页 4：跨 cwd 探索者与伴随实时对话轨迹
												docSubTab === "chat" && jsxs("div", {
													className: "gw-card",
													children: [
														jsxs("div", {
															className: "gw-card-title",
															children: [
																jsx("span", { children: `💬 跨 cwd 节点实时会话与工具执行流 (${nodeDetail.node_id})` }),
																jsx("span", { className: "gw-muted", children: "绕过左侧栏 cwd 过滤直读" })
															]
														}),
														nodeConversations.length === 0
															? jsx("div", { className: "gw-muted", children: "当前会话存储中未找到该节点的实时对话缓存（历史文书请看 1–3 标签页）" })
															: nodeConversations.map((c) => jsxs("div", {
																className: "gw-log-line",
																style: { display: "flex", flexDirection: "column", gap: 4 },
																children: [
																	jsxs("div", {
																		className: "gw-row",
																		children: [
																			jsx("strong", { children: `${c.title} (${c.role})` }),
																			jsxs("div", {
																				style: { display: "flex", alignItems: "center", gap: 4 },
																				children: [
																					jsx("span", { className: stateBadgeClass(c.status), children: `${c.status} · ${Math.round((c.pressureTokens || 0) / 1000)}k` }),
																					jsx("button", {
																						type: "button",
																						className: "gw-btn gw-btn-primary",
																						onClick: () => void openNativeSession(c.sessionId, { status: c.status, archived: c.archived, archiveError: c.archiveError, label: `${c.title} (${c.role})` }),
																						children: "打开对话"
																					})
																				]
																			})
																		]
																	}),
																	jsx("div", { className: "gw-muted gw-mono", children: `sessionId: ${c.sessionId}` }),
																	jsx("pre", { className: "gw-pre", children: c.traceText || "(无外显文本)" })
																]
															}, c.sessionId))
													]
												}),

												// 子页 5：节点观测与本脉死胡同
												docSubTab === "obs" && jsxs("div", {
													className: "gw-card",
													children: [
														jsx("div", { className: "gw-card-title", children: `⚖️ 本节点正式观测 [Obs] (${nodeDetail.observations?.length || 0}) & 本脉死胡同 (${nodeDetail.dead_ends?.length || 0})` }),
														(nodeDetail.observations || []).map((o) => jsxs("div", {
															className: "gw-log-line",
															children: [
																jsxs("div", {
																	className: "gw-row",
																	children: [
																		jsx("strong", { className: "gw-mono", children: `${o.obs_id} · ${o.instrument_id}@v${o.instrument_version}` }),
																		jsx("span", { className: stateBadgeClass(o.obs_status), children: o.obs_status })
																	]
																}),
																jsx("pre", { className: "gw-pre", children: `${o.details_text || ""}\ntracks: ${o.tracks_json || "{}"}` })
															]
														}, o.obs_id)),
														(nodeDetail.dead_ends || []).map((de) => jsxs("div", {
															className: "gw-log-line",
															children: [
																jsxs("div", {
																	className: "gw-row",
																	children: [
																		jsx("strong", { children: `🛑 死胡同 ${de.dead_end_id} (${de.node_id})` }),
																		jsx("span", { className: "gw-console-badge gw-badge-err", children: de.category })
																	]
																}),
																jsx("div", { className: "gw-muted", children: `条件范围：${de.scope_condition_md}` }),
																jsx("div", { children: `失灵机理：${de.failure_mechanism_md}` })
															]
														}, de.dead_end_id))
													]
												})
											]
										})
								]
							}),

							// ==================== TAB 3: 📂 Worktree 文件树与源码/Diff 浏览器 ====================
							activeTab === "worktree" && jsxs(Fragment, {
								children: [
									jsxs("div", {
										className: "gw-form-row",
										children: [
											jsx("span", { className: "gw-muted", style: { flex: "none" }, children: "分支节点：" }),
											jsx("select", {
												className: "gw-select",
												value: nodeDetail?.node_id || selectedNodeId || "",
												onChange: (e) => handleSelectNode(e.target.value),
												children: lineageNodes.map((n) => jsx("option", {
													value: n.node_id,
													children: `[${n.question_id}] ${n.branch_id} · Gen ${n.generation} (${n.node_id})`
												}, n.node_id))
											})
										]
									}),
									!nodeDetail
										? jsx("div", { className: "gw-muted", children: "请选择一个节点以浏览其 Worktree" })
										: jsxs("div", {
											className: "gw-card",
											children: [
												jsxs("div", {
													className: "gw-card-title",
													children: [
														jsx("span", { children: `📂 Worktree 文件浏览器 (${nodeDetail.branch_id})` }),
														jsx("span", { className: "gw-muted", children: `${(nodeDetail.worktree_files || []).length} 个文件` })
													]
												}),
												jsx("div", { className: "gw-muted gw-mono", children: nodeDetail.worktree_abs_path }),
												jsxs("div", {
													className: "gw-form-row",
													children: [
														jsx("span", { className: "gw-muted", style: { flex: "none" }, children: "选择文件：" }),
														jsx("select", {
															className: "gw-select",
															value: nodeDetail.preview_file_rel || selectedFileRel || "",
															onChange: (e) => {
																setSelectedFileRel(e.target.value);
																void fetchStatus(undefined, nodeDetail.node_id, e.target.value);
															},
															children: (nodeDetail.worktree_files || []).map((f) => jsx("option", {
																value: f.rel_path,
																children: `${f.rel_path} (${f.size} B)`
															}, f.rel_path))
														})
													]
												}),
												nodeDetail.preview_file_rel && jsxs(Fragment, {
													children: [
														jsx("div", { className: "gw-muted gw-mono", children: `📄 ${nodeDetail.preview_file_rel}` }),
														jsx("pre", { className: "gw-pre", style: { maxHeight: 420 }, children: nodeDetail.preview_file_content || "(空文件或二进制文件)" })
													]
												}),
												nodeDetail.sanitized_code_diff_md && jsxs(Fragment, {
													children: [
														jsx("div", { className: "gw-muted", children: "🔍 交接脱敏代码快照 / Diff" }),
														jsx("pre", { className: "gw-pre", children: nodeDetail.sanitized_code_diff_md })
													]
												})
											]
										})
								]
							}),

							// ==================== TAB 4: 🛡️ 监察委员会、盲审账本与工造司工单 ====================
							activeTab === "gov" && jsxs(Fragment, {
								children: [
									// 1. 同行盲审队列与详细核验账本
									jsxs("div", {
										className: "gw-card",
										children: [
											jsx("div", { className: "gw-card-title", children: `⚖️ 中央图书馆·隔离沙箱盲审账本 (${reviewsList.length})` }),
											reviewsList.length === 0
												? jsx("div", { className: "gw-muted", children: "暂无盲审记录" })
												: reviewsList.map((rv) => {
													const verSess = verifierSessionByReviewId[rv.review_id] || null;
													return jsxs("div", {
													className: "gw-log-line",
													style: { display: "flex", flexDirection: "column", gap: 5 },
													children: [
														jsxs("div", {
															className: "gw-row",
															children: [
																jsx("strong", { children: `${rv.review_id} (${rv.question_id} · 源节点 ${rv.source_node_id} · v${rv.spec_revision ?? 0})` }),
																jsxs("div", {
																	style: { display: "flex", alignItems: "center", gap: 4 },
																	children: [
																		jsx("span", { className: stateBadgeClass(rv.final_verdict || rv.review_status), children: rv.final_verdict || rv.review_status }),
																		verSess && jsx("button", {
																			type: "button",
																			className: "gw-btn gw-btn-primary",
																			onClick: () => void openNativeSession(verSess.sessionId, { status: verSess.status, archived: verSess.archived, archiveError: verSess.archiveError, workspaceRoot: verSess.workspaceRoot, label: verSess.title || `盲审 ${rv.review_id}` }),
																			children: "打开盲审对话"
																		})
																	]
																})
															]
														}),
														jsx("div", { children: `手稿标题：${rv.manuscript_title}` }),
														rv.revision_requests_json && rv.revision_requests_json !== "[]" && jsx("pre", {
															className: "gw-pre",
															children: `【退回返工要求 (revision_requests)】\n${rv.revision_requests_json}`
														}),
														rv.stage1_ledger_json && jsx("pre", {
															className: "gw-pre",
															children: `【Stage 1 盲审实测核验账本】\n${rv.stage1_ledger_json}`
														})
													]
												}, rv.review_id); })
										]
									}),

									// 2. 工造司工单队列
									jsxs("div", {
										className: "gw-card",
										children: [
											jsx("div", { className: "gw-card-title", children: `🛠️ 工造司（科研仪器科）工单台账 (${worksTickets.length})` }),
											worksTickets.slice(0, 12).map((t) => jsxs("div", {
												className: "gw-log-line",
												children: [
													jsxs("div", {
														className: "gw-row",
														children: [
															jsx("strong", { className: "gw-mono", children: `${t.ticket_id} · ${t.ticket_type} (${t.instrument_id || t.question_id})` }),
															jsx("span", { className: stateBadgeClass(t.status === "RESOLVED" ? "PASSED" : "paused"), children: t.status })
														]
													}),
													jsx("pre", { className: "gw-pre", children: t.payload_json })
												]
											}, t.ticket_id))
										]
									}),

									// 3. 监察委员会审计记录
									jsxs("div", {
										className: "gw-card",
										children: [
											jsx("div", { className: "gw-card-title", children: `🛡️ 监察委员会合规巡检日志 (${complianceLogs.length})` }),
											complianceLogs.slice(0, 10).map((c) => jsxs("div", {
												className: "gw-log-line",
												children: [
													jsxs("div", {
														className: "gw-row",
														children: [
															jsx("strong", { children: `${c.alert_id} · ${c.stage}` }),
															jsx("span", { className: stateBadgeClass(c.status), children: c.status })
														]
													}),
													jsx("div", { className: "gw-muted", children: c.notes })
												]
											}, c.alert_id))
										]
									})
								]
							})
						]
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
					description: () => "谱系 DAG Flow・五段看板与37%元反思・跨cwd探索者/伴随/盲审直达・Worktree源码",
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

		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
