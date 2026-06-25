# BS Detector — Reflection Document

## Overview

This document reflects on design decisions made during development of the BS Detector prototype and production readiness plan. It serves both as a record of reasoning and as a guide for future iterations.

---

## Part 1: Choices We Made & Why

### 1.1 Multi-Agent Decomposition

**Choice:** Four distinct agents (CitationExtractor → CitationVerifier → FactConsistency → JudicialMemo)

**Why:** 
- Separation of concerns: each agent has one job, making prompts precise and failures isolatable
- Evals become modular: can test each agent independently
- Extensibility: easy to add agents (e.g., statute-of-limitations checker) without rewriting pipeline

**Alternative and tradeoffs:** Monolithic agent (one prompt does all four jobs)
- Simpler code, but harder to debug; one bad extraction ruins verification

---

### 1.2 Confidence Scoring (Objective vs Interpretive Facts)

**Choice:** Facts get `confidence = 1.0` (verifiable), interpretations get variable confidence

**Why:**
- Legal reasoning requires precision: a date mismatch is certain, PPE usage is interpretive
- Forces agent prompts to distinguish objective from subjective
- Eval harness can be strict (threshold 0.9) without being unfair

**Alternative and tradeoffs:** All findings weighted equally
- Would drown real issues in noise

---

### 1.3 Provider Registry Pattern (Config-Driven)

**Choice:** Single `llm.py` with `PROVIDERS` dict; swap provider via `LLM_PROVIDER` env var

**Why:**
- Zero code duplication (OpenAI SDK works for both Gemini + OpenAI)
- Non-engineers can switch providers (ops team, not code team)
- Enables A/B testing (measure cost/quality of each provider)

**Alternative and tradeoffs:** Separate LLM adapters per provider
- More abstraction, harder to debug; not worth it for 2 providers

---

### 1.4 Fixture-Based Evals (Not LLM-as-Judge)

**Choice:** Hardcoded `KNOWN_FLAWS` matched against pipeline output via keyword search

**Why:**
- Zero API cost (eval harness runs infinitely)
- Deterministic: same output always produces same metrics
- Forces precision in matching logic (no hand-waving)

**Trade-off:** Only measures recall/precision on known issues, not hallucination depth
- Acceptable for prototype; LLM-as-judge deferred to production

---

### 1.5 Async Job Queue (Celery + RabbitMQ)

**Choice:** Async from day one in production plan (not sync HTTP)

**Why:**
- Document processing is latency-tolerant (30s acceptable for legal work)
- Async = graceful degradation: slow LLM doesn't timeout user
- Enables retry/fallback without user re-uploading

**Alternative and tradeoffs:** Sync HTTP (prototype approach)
- Works for single user, breaks at 100+ concurrent

---

### 1.6 Graceful Degradation Over Fail-Fast

**Choice:** Pipeline continues even if CitationVerifier fails on 3/10 citations

**Why:**
- Partial results are better than no results (lawyer sees 7 verified, 3 failed)
- Matches legal practice: incomplete discovery is still useful
- Reduces frustration (one slow API call doesn't block entire analysis)

**Risk:** Lawyer might miss something
- Mitigated by UI showing which findings are "error" status

---

### 1.7 Multitenancy (Single DB, Not Sharded)

**Choice:** One PostgreSQL with `tenant_id` in every table

**Why:**
- Simpler backups, disaster recovery, ACID guarantees
- Learned Hand likely <1000 orgs; sharding overhead not justified
- Easier audit compliance (all data in one place)

**Assumption:** Scales to ~100k orgs before hitting limits
- If wrong, sharding is a later migration

---

### 1.8 S3 with Lifecycle (Not Just References)

**Choice:** Store documents in S3 with 90-day auto-delete

**Why:**
- Audit trail: can re-analyze old cases
- CCPA-compliant: user can request deletion, it happens automatically
- Cost negligible (~$2/month for 100 org-cases)

**Alternative and tradeoffs:** Delete immediately after analysis
- Would break compliance audit ("where's the original document?")

---

## Part 2: Questions for You

### 2.1 What Would You Do Differently (If Starting Over)?

**In the prototype:**
- Add unit tests per agent (verify each works in isolation before integration)
- Validate prompts with legal expert before shipping (not just iteration on output)

**In the production plan:**
- Build more robust eval harness: LLM-as-judge instead of just fixtures (more nuanced quality assessment)
- Implement smarter fallback strategy (not just provider switching, but cost/latency optimization)

**Takeaway:** Prototype was right to move fast, but production needs stronger quality gates and expert validation.

---

### 2.2 Tradeoffs Assessment

**Fixture evals vs LLM-as-judge:**
Made reasonable choices for the current stage, but as the product grows, we may need to re-evaluate. For example, LLM-as-judge could provide deeper insights into the quality of analyses, and a smarter provider selection could optimize costs and performance. 

**Config-driven fallback vs smart provider selection:**
Same reasoning applies. Simpler for now, but revisit when there's more data.

**Async queue from day one:**
Essential for scalability, but it also increases operational complexity. However, in this specific case, I consider it fundamental for good product performance, even at small scale.

**Conclusion:** Reasonable choices for this stage, but we should re-evaluate as we grow and get more data.

---

### 2.3 Lessons Learned

**What worked well:**
- LLM output quality was high (legal document analysis is well within LLM capability)
- Multi-agent orchestration was easier than expected (modular design + clear responsibilities = robust)
- Structured JSON outputs from agents worked seamlessly (typed Pydantic models prevented parsing errors)

**What was harder:**
- Confidence scoring required iterative prompt tuning (not a simple heuristic; needed explicit instructions)
- Prompt precision matters enormously (small word changes = big difference in output quality)
- Distinguishing objective facts (1.0 confidence) from interpretive findings (variable confidence) required explicit reasoning in prompts

**Insight:** The bottleneck is prompt engineering, not architecture. Better prompts > better algorithms.

---

### 2.4 Integration with Real Users

**Confidence ratings usage:**
I think lawyers would use confidence ratings as long as they are reliable enough. Detailed explanations of why citations fail would be very useful, especially for justifying decisions in legal cases. 

**Compliance features:**
It would be interesting to implement automatic checks for attorney-client privilege and alerts about possible confidentiality violations.

---

### 2.5 Priority: One More Week

**Better UI, for sure.** Visualizing results in a clear and intuitive way would help lawyers understand the analyses quickly and make informed decisions.

**Continuous eval pipeline with LLM-as-judge** could provide valuable feedback on the quality of analyses in real time, allowing quick adjustments and continuous improvements to the system.

**Smarter provider switching** would also be useful to ensure service reliability, especially during high demand or provider failures.

---

## Part 3: Implementation Notes

### Tier 3: UI & Streaming

Implemented two significant UX improvements:

**Server-Sent Events (SSE) Streaming:**
- `/analyze` endpoint now streams real-time progress instead of returning JSON after completion
- Backend sends event for each agent completion: extraction → verification → fact-checking → summary
- Frontend displays spinner with stage + count details (e.g., "Verifying citations... 11 checked, 3 issues")
- No additional API calls — same 4 LLM calls, just streamed with progress events
- Significantly better UX: user sees work happening, not just "Analyzing..."

**UI Design (Tier 3):**
- Replaced simple JSON display with structured findings interface
- Card-based layout (not table) for better responsiveness
- Inline expandable rows for details (reasoning, source quotes)
- Filters: verdict, confidence (low/medium/high/100%), type, plus asc/desc sort toggle
- Design inspired by minimalist web standards: generous whitespace, clear typography, subtle colors

### Summary

The LLM analyzed the documents accordingly, but the precision of the responses varied depending on the prompt. Confidence scoring was harder to calibrate than expected, requiring fine-tuning in the prompts and evaluation logic. However, multi-agent orchestration was easier than expected to implement, thanks to the modularity of the design and the clarity of each agent's responsibilities.

Architecture has a huge impact, but prompt engineering can work miracles. The right prompt can make a big difference in output quality, usually with minimal architectural changes.
