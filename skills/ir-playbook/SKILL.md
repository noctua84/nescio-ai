---
name: ir-playbook
description: Use when writing a scenario-specific incident response playbook — ransomware, phishing, data breach, insider threat, or DDoS — with containment steps, exact commands, and decision trees per NIST SP 800-61, SANS PICERL, MITRE ATT&CK, and D3FEND. Triggers on "IR playbook", "runbook", "ransomware response", "containment steps", "PICERL".
user-invocable: true
---

# IR Playbook

## Purpose

Create an incident response playbook that delivers actionable, measurable results.

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
- Review any existing incident response playbook documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: NIST SP 800-61 Rev 2, MITRE ATT&CK (Defensive), SANS PICERL

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the incident response playbook
- Identify gaps, opportunities, and risks
- Define success metrics: MTTR per Scenario Type, Containment Time, Evidence Collection Completeness, Playbook Execution Success Rate
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the incident response playbook using the output format below
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
- [ ] Follows best practice: Create separate playbooks per scenario: ransomware, phishing, data breach, insider threat, DDoS

## Output Format

```markdown
# Incident Response Playbook

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
- MITRE ATT&CK (Defensive)
- SANS PICERL
- D3FEND
- CISA IR Playbooks

## Key Metrics
- MTTR per Scenario Type
- Containment Time
- Evidence Collection Completeness
- Playbook Execution Success Rate
- Lessons Learned Implementation Rate
- Recovery Time per Scenario

## Best Practices
- Create separate playbooks per scenario: ransomware, phishing, data breach, insider threat, DDoS
- Include exact commands, tool references, and decision trees — not just narrative
- Define containment actions that preserve forensic evidence
- Include communication flow diagrams for each stakeholder group
- Review and update playbooks after every real incident and every exercise
