/** 子题活体总览、承重缺口与波次圆桌视图。 */
function LivingSurveyView({ data }) {
  const [expandedWaves, setExpandedWaves] = (typeof React !== "undefined" && typeof React.useState === "function")
    ? React.useState({})
    : [{}, () => {}];
  const insp = data?.inspector || {};
  const rawSurveys = insp.living_surveys_list || insp.living_surveys || [];
  const surveys = Array.isArray(rawSurveys) ? rawSurveys : Object.values(rawSurveys || {});
  const gaps = (insp.open_lemma_gaps || []).filter((g) => g.status === "OPEN");
  const waves = insp.wave_conferences || [];
  const extCards = insp.external_literature_cards || [];

  return jsxs("div", {
    style: { display: "flex", flexDirection: "column", gap: "9px" },
    children: [
      jsxs("div", {
        className: "gw-card",
        children: [
          jsx("div", { className: "gw-card-hd", children: `左翼外藏文献卡 R###（共 ${extCards.length} 张）` }),
          extCards.length === 0
            ? jsx("div", { className: "gw-muted", children: "尚无外藏文献卡，Stage 1 对外采编完成后将自动呈现。" })
            : extCards.map((c) =>
                jsxs("div", {
                  className: "gw-item",
                  children: [
                    jsxs("div", {
                      className: "gw-row",
                      children: [
                        jsx("strong", { className: "gw-mono", children: `${c.ref_id} (${c.question_id})` }),
                        c.read_depth ? jsx("span", { className: "gw-badge gw-b-info", children: c.read_depth }) : null
                      ]
                    }),
                    jsx("div", { children: c.title }),
                    c.abstract_md ? jsx("div", { className: "gw-muted", children: String(c.abstract_md).slice(0, 220) }) : null
                  ]
                }, c.ref_id)
              )
        ]
      }),
      jsxs("div", {
        className: "gw-card",
        children: [
          jsx("div", { className: "gw-card-hd", children: `右翼内藏 · 子题全局总览（<=4000 字阶段总览，共 ${surveys.length} 份）` }),
          surveys.length === 0
            ? jsx("div", { className: "gw-muted", children: "尚无已发布的《子题全局总览》，首个波次圆桌完成后将自动呈现。" })
            : surveys.map((sv) =>
                jsxs("div", {
                  className: "gw-item",
                  children: [
                    jsxs("div", {
                      className: "gw-row",
                      children: [
                        jsx("strong", { children: `${sv.question_id} · r${sv.revision} (${sv.total_chars}/4000 字)` }),
                        jsx("span", { className: "gw-badge gw-b-info", children: sv.trigger_reason || "WAVE" })
                      ]
                    }),
                    jsx("pre", {
                      className: "gw-pre",
                      children: [
                        `[1. 基线与仪器]\n${sv.sec1_baseline_and_instruments_md || ""}`,
                        `[2. L3 引理树]\n${sv.sec2_l3_lemma_tree_md || ""}`,
                        `[3. 排雷雷达]\n${sv.sec3_avoidance_radar_md || ""}`,
                        `[4. 明确缺口]\n${sv.sec4_explicit_gaps_md || ""}`
                      ].join("\n\n")
                    }),
                    sv.marginal_notes_md ? jsxs("details", {
                      children: [
                        jsx("summary", { children: "边缘研究注记" }),
                        jsx("pre", { className: "gw-pre", children: sv.marginal_notes_md })
                      ]
                    }) : null
                  ]
                }, sv.survey_id)
              )
        ]
      }),
      jsxs("div", {
        className: "gw-card",
        children: [
          jsx("div", { className: "gw-card-hd", children: `全馆 OPEN 引理悬赏榜 (${gaps.length})` }),
          gaps.length === 0
            ? jsx("div", { className: "gw-muted", children: "当前无未核销的引理悬赏缺口。" })
            : gaps.map((g) =>
                jsxs("div", {
                  className: "gw-item",
                  children: [
                    jsxs("div", {
                      className: "gw-row",
                      children: [
                        jsx("strong", { className: "gw-mono", children: `${g.gap_id} (${g.question_id})` }),
                        jsx("span", { className: "gw-badge gw-b-warn", children: `阻塞节点 ${g.blocked_node_id}` })
                      ]
                    }),
                    jsx("div", { children: g.formal_statement_md })
                  ]
                }, g.gap_id)
              )
        ]
      }),
      jsxs("div", {
        className: "gw-card",
        children: [
          jsx("div", { className: "gw-card-hd", children: `宏观大外环圆桌会议 (${waves.length})` }),
          waves.length === 0
            ? jsx("div", { className: "gw-muted", children: "尚未触发波次圆桌会议。" })
            : waves.slice(0, 6).map((w) =>
                jsxs("div", {
                  className: "gw-item",
                  children: [
                    jsxs("div", {
                      className: "gw-row",
                      children: [
                        jsx("strong", { className: "gw-mono", children: `${w.question_id} Wave ${w.wave_no} (${w.conference_id})` }),
                        jsx("span", { className: stateBadgeClass(w.status), children: w.status })
                      ]
                    }),
                    w.minutes_md
                      ? jsxs("div", {
                          children: [
                            jsx("div", {
                              className: "gw-summary",
                              children: expandedWaves[w.conference_id] || String(w.minutes_md).length <= 180
                                ? String(w.minutes_md)
                                : `${String(w.minutes_md).slice(0, 180)}…`
                            }),
                            String(w.minutes_md).length > 180
                              ? jsx("button", {
                                  className: "gw-link-btn",
                                  onClick: () => setExpandedWaves((prev) => ({ ...prev, [w.conference_id]: !prev[w.conference_id] })),
                                  children: expandedWaves[w.conference_id] ? "收起纪要" : "展开完整纪要"
                                })
                              : null
                          ]
                        })
                      : null
                  ]
                }, w.conference_id)
              )
        ]
      })
    ]
  });
}
