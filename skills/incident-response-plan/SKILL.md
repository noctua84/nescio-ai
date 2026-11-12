---
name: incident-response-plan
description: Use when building an incident response plan — classification levels (P1-P4), escalation criteria, roles, and communication templates aligned to NIST SP 800-61, SANS, and ISO 27035. Triggers on "incident response plan", "IR plan", "incident classification", "escalation criteria", "MTTD", "MTTR", "CSIRT".
user-invocable: true
---

# Incident Response Plan

## Purpose

Create an incident response plan that delivers actionable, measurable results.

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

Build on any existing incident response plan documents in the project and pick the framework that fits (NIST SP 800-61 Rev 2, SANS Incident Handling Process, ISO 27035). Define incident classification levels (P1-P4) with clear escalation criteria. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Mean Time to Detect (MTTD), Mean Time to Respond (MTTR), Incident Classification Accuracy, Communication Time to Stakeholders.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# Incident Response Plan

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
- NIST SP 800-61 Rev 2
- SANS Incident Handling Process
- ISO 27035
- CISA Incident Response Playbooks
- FIRST CSIRT Framework

## Key Metrics
- Mean Time to Detect (MTTD)
- Mean Time to Respond (MTTR)
- Incident Classification Accuracy
- Communication Time to Stakeholders
- Plan Test Frequency
- Evidence Preservation Rate

## Best Practices
- Define incident classification levels (P1-P4) with clear escalation criteria
- Include communication templates for internal, customer, regulatory, and media notifications
- Test the plan via tabletop exercises at least twice per year
- Establish clear roles: Incident Commander, Technical Lead, Communications Lead, Legal
- Include evidence preservation procedures from the start — not as an afterthought
