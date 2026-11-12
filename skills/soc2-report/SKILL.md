---
name: soc2-report
description: Use when preparing a SOC 2 report or readiness assessment — mapping controls to the Trust Services Criteria, choosing Type I vs Type II, gathering audit evidence, and tracking exceptions. Triggers on "SOC 2", "Type I", "Type II", "Trust Services Criteria", "TSC", "audit evidence", "AICPA", "control exception".
user-invocable: true
---

# SOC 2 Report

## Purpose

Create a SOC 2 compliance report that delivers actionable, measurable results.

**Category**: Cybersecurity & Information Security

## Inputs

### Required
- **Objective**: What you want to achieve with this deliverable
- **Context**: Relevant background information (systems, scope, environment)

### Optional
- **Constraints**: Any limitations or requirements to consider
- **Existing Work**: Previous documents or data to build on

## Context

Check the brain's notes for prior decisions and constraints on this repo: `~/.claude/memory/repo/<repo>/` and `~/.claude/memory/feedback/`.

## Process

Build on any existing soc 2 compliance report documents in the project and pick the framework that fits (AICPA Trust Services Criteria, SOC 2 Type I/II, COSO Internal Control Framework). Start with Type I (point-in-time) to establish baseline before Type II (period). Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Control Count by Trust Category, Exception Rate, Remediation Completion Rate, Evidence Collection Completeness %.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# SOC 2 Compliance Report

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
- AICPA Trust Services Criteria (TSC)
- SOC 2 Type I/II
- COSO Internal Control Framework
- CIS Controls v8.1
- ISO 27001 (cross-mapping)

## Key Metrics
- Control Count by Trust Category
- Exception Rate
- Remediation Completion Rate
- Audit Finding Trend
- Evidence Collection Completeness %
- Control Effectiveness Score

## Best Practices
- Start with Type I (point-in-time) to establish baseline before Type II (period)
- Map existing controls to Trust Services Criteria before identifying gaps
- Automate evidence collection — manual evidence gathering does not scale
- Maintain continuous monitoring, not just annual audit preparation
- Cross-map SOC 2 controls to ISO 27001 for dual-framework efficiency
