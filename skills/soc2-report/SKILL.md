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

Before starting, read the repo's `CLAUDE.md` and any relevant notes under `memory/` (e.g. `memory/repo/<repo>/`, `memory/feedback/`) for prior decisions and constraints.

## Process

### Step 1: Context & Research
- Review any existing soc 2 compliance report documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: AICPA Trust Services Criteria, SOC 2 Type I/II, COSO Internal Control Framework

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the soc 2 compliance report
- Identify gaps, opportunities, and risks
- Define success metrics: Control Count by Trust Category, Exception Rate, Remediation Completion Rate, Evidence Collection Completeness %
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the soc 2 compliance report using the output format below
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
- [ ] Follows best practice: Start with Type I (point-in-time) to establish baseline before Type II (period)

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
