/** GreatWall v0.3 子题活体全局总览（<=1500字）、OPEN 悬赏缺口与大外环圆桌视图。 */
function LivingSurveyView({ data }) {
  const insp = data?.inspector || {};
  const rawSurveys = insp.living_surveys_list || insp.living_surveys || [];
  const surveys = Array.isArray(rawSurveys) ? rawSurveys : Object.values(rawSurveys || {});
  const gaps = (insp.open_lemma_gaps || []).filter((g) => g.status === "OPEN");
  const waves = insp.wave_conferences || [];

  return jsxs("div", {
    style: { display: "flex", flexDirection: "column", gap: "9px" },
    children: [
      jsxs("div", {
        className: "gw-card",
        children: [
          jsx("div", { className: "gw-card-hd", children: `子题全局总览（<=1500 字导览索引，共 ${surveys.length} 份）` }),
          surveys.length === 0
            ? jsx("div", { className: "gw-muted", children: "尚无已发布的《子题全局总览》，首个波次圆桌完成后将自动呈现。" })
            : surveys.map((sv) =>
                jsxs("div", {
                  className: "gw-item",
                  children: [
                    jsxs("div", {
                      className: "gw-row",
                      children: [
                        jsx("strong", { children: `${sv.question_id} · r${sv.revision} (${sv.total_chars}/1500 字)` }),
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
                    })
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
                    w.minutes_md ? jsx("div", { className: "gw-muted", children: String(w.minutes_md).slice(0, 220) }) : null
                  ]
                }, w.conference_id)
              )
        ]
      })
    ]
  });
}
