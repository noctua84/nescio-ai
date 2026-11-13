---
name: iso27001-isms
description: Use when building or documenting an ISO 27001 ISMS — scoping the ISMS, producing a Statement of Applicability, implementing Annex A controls, and preparing for certification. Triggers on "ISO 27001", "ISMS", "Annex A", "Statement of Applicability", "SoA", "ISO 27002", "ISO 27005", "risk treatment plan", "certification".
user-invocable: true
---

# ISO 27001 ISMS

## Purpose

Create ISO 27001 ISMS documentation that delivers actionable, measurable results.

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

Build on any existing iso 27001 isms documentation documents in the project and pick the framework that fits (ISO/IEC 27001:2022, ISO/IEC 27002:2022, ISO/IEC 27005). Scope the ISMS carefully — too broad makes certification impractical. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Annex A Control Implementation %, Statement of Applicability Completeness, Internal Audit Nonconformity Count, Risk Treatment Plan Progress.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# ISO 27001 ISMS Documentation

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
- ISO/IEC 27001:2022
- ISO/IEC 27002:2022
- ISO/IEC 27005 (Risk Management)
- ISO/IEC 27017 (Cloud)
- ISO/IEC 27701 (Privacy)

## Key Metrics
- Annex A Control Implementation %
- Statement of Applicability Completeness
- Internal Audit Nonconformity Count
- Risk Treatment Plan Progress
- Corrective Action Closure Rate
- Management Review Frequency

## Best Practices
- Scope the ISMS carefully — too broad makes certification impractical
- Create a Statement of Applicability (SoA) mapping all 93 Annex A controls
- Conduct management reviews at least quarterly, not just annually
- Integrate risk assessment with business risk processes
- Train all employees within ISMS scope, not just IT staff
