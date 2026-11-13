---
name: risk-register
description: Use when building or maintaining a risk register — logging risks with named owners, inherent and residual scores, treatment decisions (Accept/Mitigate/Transfer/Avoid), and tracking open/overdue items. Triggers on "risk register", "risk owner", "residual risk", "risk treatment", "risk score", "ISO 31000", "risk log".
user-invocable: true
---

# Risk Register

## Purpose

Create a risk register that delivers actionable, measurable results.

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

Build on any existing risk register documents in the project and pick the framework that fits (ISO 31000, ISO 27005, NIST SP 800-39). Assign a named owner for every risk — unowned risks never get mitigated. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Total Open Risks, Risk Age (Days Open), Risk Treatment Status Distribution, Top 10 Risks by Score.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# Risk Register

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
- ISO 31000
- ISO 27005
- NIST SP 800-39
- FAIR
- COSO ERM Framework

## Key Metrics
- Total Open Risks
- Risk Age (Days Open)
- Risk Treatment Status Distribution
- Top 10 Risks by Score
- Risk Trend (New vs. Closed per Quarter)
- Overdue Treatment Actions

## Best Practices
- Assign a named owner for every risk — unowned risks never get mitigated
- Review the register quarterly with risk owners present
- Track risk treatment decisions explicitly: Accept, Mitigate, Transfer, Avoid
- Include residual risk scores after controls — not just inherent risk
- Integrate with the enterprise risk management process
