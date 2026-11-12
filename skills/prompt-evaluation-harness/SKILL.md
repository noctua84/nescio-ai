---
name: prompt-evaluation-harness
description: Use when building a prompt evaluation harness — LLM-as-judge, G-Eval, faithfulness and answer-relevancy scoring, hallucination rate, and CI/CD regression suites. Triggers on "eval harness", "LLM-as-judge", "DeepEval", "RAGAS", "faithfulness", "hallucination rate", "G-Eval".
user-invocable: true
---

# Prompt Evaluation Harness

## Purpose

Create a prompt evaluation harness that delivers actionable, measurable results.

**Category**: AI & Automation

## Inputs

### Required
- **Objective**: What you want to achieve with this deliverable
- **Context**: Relevant background information

### Optional
- **Constraints**: Any limitations or requirements to consider
- **Existing Work**: Previous documents or data to build on

## Context

Check the brain's notes for prior decisions and constraints on this repo: `~/.claude/memory/repo/<repo>/` and `~/.claude/memory/feedback/`.

## Process

Build on any existing prompt evaluation harness documents in the project and pick the framework that fits (DeepEval (50+ metrics), RAGAS, HELM (Stanford)). Treat prompt evaluation like unit testing — use pytest-style test suites in CI/CD. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Faithfulness Score, Answer Relevancy, Hallucination Rate, Contextual Precision/Recall.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# Prompt Evaluation Harness

## Executive Summary
[2-3 sentence overview of the deliverable and key recommendations]

## Context & Objectives
- **Objective**: [What this achieves]
- **Audience**: [Who this is for]
- **Timeline**: [When this applies]

## Analysis
[Structured analysis using the selected framework]

## Recommendations
1. [Specific, actionable recommendation with expected impact]
2. [Specific, actionable recommendation with expected impact]
3. [Specific, actionable recommendation with expected impact]

## Implementation
| Action | Owner | Timeline | Priority |
|--------|-------|----------|----------|
| [Action item] | [Who] | [When] | [High/Medium/Low] |

## Success Metrics
| Metric | Current | Target | Measurement Method |
|--------|---------|--------|-------------------|
| [KPI] | [Baseline] | [Goal] | [How to measure] |

## Risks & Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| [Risk] | [H/M/L] | [H/M/L] | [Action] |

## Next Steps
- [ ] [Immediate next action]
- [ ] [Follow-up action]
- [ ] [Review date]
```

## Applicable Frameworks
- DeepEval (50+ metrics)
- RAGAS (RAG-specific evaluation)
- HELM (Stanford curated benchmarks)
- BIG-bench
- Custom Evals (model-generated, human-verified)

## Key Metrics
- Faithfulness Score
- Answer Relevancy
- Hallucination Rate
- Contextual Precision/Recall
- Regression Rate Across Prompt Versions
- Human-AI Agreement Score

## Best Practices
- Treat prompt evaluation like unit testing — use pytest-style test suites in CI/CD
- Evaluate at both component and end-to-end levels using LLM tracing
- Use LLM-as-judge with research-backed metrics (G-Eval), not vibes
- Run regression testing across prompt versions
- Combine automated and human evaluation — human for high-stakes, automated for continuous
