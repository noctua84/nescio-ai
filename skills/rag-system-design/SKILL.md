---
name: rag-system-design
description: Use when designing a retrieval-augmented generation system — chunking, embeddings, vector store, hybrid retrieval, reranking, and evaluation. Triggers on "RAG", "retrieval-augmented", "vector database", "chunking strategy", "embeddings", "reranking", "context window".
user-invocable: true
---

# RAG System Design

## Purpose

Create a RAG system design that delivers actionable, measurable results.

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

Build on any existing rag system design documents in the project and pick the framework that fits (AI Readiness Assessment, Automation ROI Calculator, Human-in-the-Loop Design). Start with high-volume, low-risk tasks. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Time Saved Per Task, Automation Rate, Error Reduction %, Cost Per AI Operation.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# RAG System Design

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
- AI Readiness Assessment
- Automation ROI Calculator
- Human-in-the-Loop Design
- RAG Architecture
- Agent Orchestration Patterns
- Responsible AI Framework

## Key Metrics
- Time Saved Per Task
- Automation Rate
- Error Reduction %
- Cost Per AI Operation
- User Adoption Rate
- Output Quality Score

## Best Practices
- Start with high-volume, low-risk tasks
- Always keep human review for critical outputs
- Measure time saved, not just accuracy
- Version control prompts like code
- Monitor for drift and degradation monthly
