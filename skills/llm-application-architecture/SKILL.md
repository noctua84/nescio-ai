---
name: llm-application-architecture
description: Use when architecting an LLM application — agent patterns (chaining, routing, orchestrator-workers), model gateway, guardrails, retrieval, and latency/cost tradeoffs. Triggers on "LLM architecture", "agent patterns", "routing", "model gateway", "guardrails", "TTFT", "orchestrator-workers".
user-invocable: true
---

# LLM Application Architecture

## Purpose

Create an LLM application architecture that delivers actionable, measurable results.

**Category**: AI & Automation

## Inputs

### Required
- **Objective**: What you want to achieve with this deliverable
- **Context**: Relevant background information

### Optional
- **Constraints**: Any limitations or requirements to consider
- **Existing Work**: Previous documents or data to build on

## Context

Before starting, read the repo's `CLAUDE.md` and any relevant notes under `memory/` (e.g. `memory/repo/<repo>/`, `memory/feedback/`) for prior decisions and constraints.

## Process

### Step 1: Context & Research
- Review any existing llm application architecture documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: Anthropic 6 Agent Patterns, RAG Architecture, GenAI Platform Stack

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the llm application architecture
- Identify gaps, opportunities, and risks
- Define success metrics: TTFT (Time to First Token), Retrieval Precision/Recall, Guardrail Trigger Rate, End-to-End Latency
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the llm application architecture using the output format below
- Include specific, actionable recommendations — not generic advice
- Add concrete numbers, timelines, and benchmarks where applicable
- Cross-reference with existing project documents for consistency
- Ensure every section adds value — remove filler

### Step 4: Quality Validation
- [ ] All required inputs have been addressed
- [ ] Recommendations are specific and actionable (not vague)
- [ ] Numbers and benchmarks are realistic and sourced
- [ ] Output format matches the specification below
- [ ] No contradictions with CLAUDE.md or memory/ constraints
- [ ] Follows best practice: Start simple — many applications need only optimized single LLM calls with retrieval

## Output Format

```markdown
# LLM Application Architecture

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
- Anthropic 6 Agent Patterns (Chaining, Routing, Parallelization, Orchestrator-Workers, Evaluator-Optimizer, Autonomous)
- RAG Architecture (Term+Embedding+Hybrid+Reranking)
- GenAI Platform Stack
- LangChain/LangGraph
- Model Gateway Pattern

## Key Metrics
- TTFT (Time to First Token)
- Retrieval Precision/Recall
- Guardrail Trigger Rate (FP and TP)
- End-to-End Latency per Pattern
- Cost per Query across Routing Tiers
- Agent Task Completion Rate

## Best Practices
- Start simple — many applications need only optimized single LLM calls with retrieval
- Use routing to match query complexity to model cost (40-60% savings)
- Implement guardrails as a parallel layer, not serial bottleneck
- Build RAG with cheap retriever then expensive reranker sequential pattern
- Invest in tool/API interface design — poor tool descriptions are the primary cause of agent failures
