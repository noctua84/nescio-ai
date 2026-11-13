---
name: risk-assessment
description: Use when performing a cybersecurity risk assessment — identifying threats, scoring likelihood and business impact, separating inherent from residual risk, and quantifying exposure. Triggers on "risk assessment", "threat likelihood", "inherent risk", "residual risk", "FAIR", "NIST SP 800-30", "ISO 27005", "OCTAVE".
user-invocable: true
---

# Risk Assessment

## Purpose

Create a cybersecurity risk assessment that delivers actionable, measurable results.

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

Build on any existing cybersecurity risk assessment documents in the project and pick the framework that fits (NIST SP 800-30, ISO 27005, FAIR). Quantify risks in financial terms using FAIR. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Total Risks Identified, Risk Distribution by Level, Residual Risk Count, Risk Treatment Coverage %.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# Cybersecurity Risk Assessment

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
- NIST SP 800-30
- ISO 27005
- FAIR (Factor Analysis of Information Risk)
- OCTAVE
- CIS RAM

## Key Metrics
- Total Risks Identified
- Risk Distribution by Level
- Residual Risk Count
- Risk Treatment Coverage %
- Cost of Risk Mitigation vs. Exposure
- Risk Score Trend

## Best Practices
- Quantify risks in financial terms using FAIR — qualitative-only assessments lack decision power
- Include threat likelihood AND business impact in every risk score
- Separate inherent risk from residual risk (after controls)
- Involve business stakeholders — they understand impact better than IT
- Update risk assessments after every significant change, not just annually
