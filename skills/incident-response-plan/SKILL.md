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

Before starting, read the repo's `CLAUDE.md` and any relevant notes under `memory/` (e.g. `memory/repo/<repo>/`, `memory/feedback/`) for prior decisions and constraints.

## Process

### Step 1: Context & Research
- Review any existing incident response plan documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: NIST SP 800-61 Rev 2, SANS Incident Handling Process, ISO 27035

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the incident response plan
- Identify gaps, opportunities, and risks
- Define success metrics: Mean Time to Detect (MTTD), Mean Time to Respond (MTTR), Incident Classification Accuracy, Communication Time to Stakeholders
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the incident response plan using the output format below
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
- [ ] Follows best practice: Define incident classification levels (P1-P4) with clear escalation criteria

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
