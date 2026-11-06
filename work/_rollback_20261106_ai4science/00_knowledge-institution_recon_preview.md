# 03 知识制度 Recon+Preview
`knowledge-institution`｜2026-11-06｜已读：shared_frame、证据规范、05/06/07/04、work/01、2502.14297 §2.3–2.8、2610.08927、2608.23691（精读）。

## A. 约束备忘
**必须支持**[E]：Record→Ledger→Archive 三态各设门禁；档案收解释/障碍/反例；结论带条件/来源/版本；公私记忆分权；更正可反向传播；信用按"被使用"计。
**现有设计缺**[E]：shared_frame 对象字典无 ArchiveEntry/Lineage/Credit/Correction/Reproduction；Paper 有 retracted 无转换接口；Review 有 blind 无校准；LedgerEntry 只有"复验通过"无复验者/环境。

**3 条关键约束**
1. **单评审阈值不够**。Station 1–10 分、≥6 接收（2608 §Archive Room）[B]；ARI：单 LLM 评审 7/7 自产稿全拒却漏掉全部严重缺陷（4/7 含错误/幻觉数值），10 篇人类稿拒 9（含 4 篇真接收）、接受 1 篇真拒稿（2502.14297 §2.5–2.6）[B]。→ 确定性检查先行+多评委校准，评审只筛选/排序。
2. **公私分权，代际只传身份+笔记+交接卡**。Lineage=同名+私笔记+连续身份；前 40 tick（v2=20）隔离只读本 lineage（2608 §Lineage/§生命周期；2610 附录 v2=150/20/90）[B；无消融]。
3. **入库≠已验证，须能更正/降级**。无 Archive 站 Agent 宣称某类构造≤582 点且被采纳（2608 meta_analysis）[B]；档案单 reviewer、无复现准入、未报告撤稿（2608 §Archive Room）[B]；2610 的 LoRA 倒 U 被 feng2026 质疑（转引）[C]。

**3 个待定问题**
Q1 评审几票、校准集多大、注入哪些错误？Station 单 reviewer、ARI 无校准。[E]
Q2 claim 级复现谁做？Station 仅整站级 3 实例复现（均达 604，2608 §Result reproducibility）[B]，无逐 claim 准入。[E]
Q3 信用能否自动化？Station 以"产物被实质使用"定贡献者，但归因是作者事后人工判定（Claude 18/GPT 9/Gemini 1，additional_analysis）[B]，无自动 credit。[E]

## B. 设计立场
**核心主张**：知识制度的单位是"带条件的可引用断言+引用边"而非论文。档案是引用图非文件柜；准入是门禁非评分；信用是"被用"非"发表"。铁律：**引用即承诺**——下游记版本与证据等级，更正反向传播。

**对象/接口**（对齐 shared_frame；新增标"提案"）
沿用 Paper（含 retracted）、Review、LedgerEntry、ArchivePaper、HandoffCard。
提案：`Lineage{id,generation,identity,notes,isolation_until}`；`AdmissionDecision{object,gate,verdict,version,recheck_at}`；`Reproduction{claim,env,executor,result}`；`Correction{target,kind,affected_refs}`；`CreditEdge{consumer→producer,material_use}`。
接口：`admit()`、`verify()`、`reproduce()`、`cite(id,version)`、`issue_correction()`、`handoff()`。
冲突：Archive/Ledger/Record/Lineage 只在 shared_frame"制度层"出现、对象字典无定义；Paper.retracted 无转换接口。[未改名]

**依赖**：01 Claim/Evidence 条件字段定 Ledger schema；02 GapCard/失败进 Record；04 worktree 版本指纹是复现前提；05 共用校准集；06 外部专家终审。
**最大风险**：制度成本反噬——Station 单站 125 篇/199 拒稿/55/125 至少被拒（meta_analysis）；16 站 Gemini 2,652 投稿仅 508 接收（19.2%）、GPT 388/506（76.7%）（additional_analysis）[B]。若 L1 也送审，评审变 attractor 且奖励灌水/迎合评审风格[E]。缓解：L1 不审、L2 复验、L3 评审+复审；评审预算上限；信用加自引打折/环检测；KPI 只认被使用（21/28 用到早期论文）[B]。

## C. 自检
最可靠：21/28 被使用、Archive 整屋消融 0/3 vs 3/3、单 LLM 评审漏检 [B]。最不确定：隔离期、引用信用、≥6 阈值迁移 [E]。冲突见 B 段。
