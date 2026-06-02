# References (pointers only)

LabMate's design borrows from prior work. **PDFs are intentionally NOT in this repo** (copyright + size);
this file lists the papers worth consulting, with arXiv IDs and a one-line "what to borrow".
Look them up on arXiv if you need detail. The actionable design is already distilled into the other docs here.

## Base platform (build on this)
- **LabUtopia** — arXiv 2505.22634 — the Isaac Sim lab simulator we extend: scenes, hierarchical tasks, scripted FSM controllers, `ObjectUtils`, task/controller factories. Drive the **scripted controllers** (not learned policies) for reliable execution.

## Planner baselines (how to plan language → skills)
- **SayCan** — 2204.01691 — score `p_LLM(useful) × p_affordance(feasible)`; enumerate skills as candidates. Borrow the scoring loop; replace learned value functions with a deterministic precondition checker over sim state.
- **Inner Monologue** — 2207.05608 — closed-loop transcript: inject `Scene:` / `Success:` / human answers back into the prompt → monitoring, recovery, clarification. Use the open-loop-vs-closed-loop contrast as a headline result.
- **Code-as-Policies** — 2209.07753 — borrow `parse_obj` (NL description → concrete scene object) and the `exec` sandbox (whitelisted APIs only) for safety enforcement.
- **Text2Motion** — 2303.12153 — predict symbolic goal propositions + `F_sat` checker → automatic plan-validity + termination; the OOD/infeasibility filter is where safety rejection plugs in.

## Schema + benchmark design
- **PARTNR** — 2411.00081 — episode = (instruction, init state, programmatic eval fn with propositions/dependencies/constraints); metrics: Percent Complete, Success, Failure Explanation, Extraneous effort.

## Clarification / when-to-ask
- **AmbiK** — 2506.04089 — behavior-keyed ambiguity taxonomy (preferences→always ask, common_sense→act, safety→ask/refuse) + paired ambiguous/unambiguous tasks.
- **Ask-to-Act** — 2504.00907 — make "ask" an explicit action; ARS / Question-Ratio efficiency metrics.
- **AbstainEQA** — 2512.04597 — 5 abstention categories; **prompted explicit decision token beats trained classifiers** (don't train, don't use conformal); Abstention Recall/Precision metrics.
- **Ask-to-Clarify** — 2509.15061 — ask-vs-act signal-token router (validates our 4-token `{ACT, ASK, RESOLVED, REFUSE}` plan).

## Safety (decision + shield + metrics)
- **RoboGuard** — 2503.07885 — **the shield pattern to copy**: a deterministic gate is the final arbiter, the LLM only proposes; check rules over current state before every action.
- **AGENTSAFE / SAFE** — 2506.14697 — per-stage failure attribution (perception / planning / execution); key lesson: score on **executed actions**, not refusal text ("said refuse but still acted").
- **LABSHIELD** — 2603.11987 — validates our 4-tier scheme {EXECUTE, SAFE_SLOW, STOP_AND_ALERT, REFUSE}; Tier-Underestimation metric. (Also our closest competitor — no execution/clarification/monitoring.)
- **LabSafety Bench** — 2410.14182 — 4×10 hazard taxonomy for naming categories. (Sim MVP: re-ground to boolean object flags, do NOT claim OSHA/GHS compliance.)

## Motivation: VLAs misinterpret/ignore instructions (why structure is needed)
- **LIBERO-Plus** — 2510.13626 — VLAs largely **ignore language**; 95%→<30% under perturbation.
- **LIBERO-PRO** — 2510.03827 — 90%→**0.0%** under perturbation; outputs unchanged under corrupted instructions (memorization, not understanding).
- **"Linguistic blindness" / IGAR** — 2603.06001 — Pi0/Pi0.5/OpenVLA-OFT execute despite contradictory instructions.
- **Vision overrides language** — 2602.17659 — VLAs take visual shortcuts over language intent.
- **VLA-Risk** — OpenReview 31EjDFwFEe (ICLR 2026) — SOTA VLAs fail under perturbation (296 scenarios / 3784 episodes).

> Full categorized library (PDFs, local only) lives outside this repo in the workspace `References/` folder.
