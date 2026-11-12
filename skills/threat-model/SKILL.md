---
name: threat-model
description: Use when threat modeling a system, feature, or architecture — enumerating attack surfaces, trust boundaries, and mitigations with STRIDE/PASTA/LINDDUN/MITRE ATT&CK. Triggers on "threat model", "attack surface", "trust boundary", "abuse cases".
user-invocable: true
---

# Threat Model

## Purpose

Create a threat model that delivers actionable, measurable results.

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

Build on any existing threat model documents in the project and pick the framework that fits (STRIDE, PASTA, LINDDUN). Create data flow diagrams with explicit trust boundaries before identifying threats. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Threats Identified per Component, Mitigations Coverage %, Residual Risk Score, Trust Boundary Violations.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# Threat Model

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
- STRIDE
- PASTA (Process for Attack Simulation and Threat Analysis)
- DREAD
- LINDDUN (Privacy Threats)
- MITRE ATT&CK
- Attack Trees

## Key Metrics
- Threats Identified per Component
- Mitigations Coverage %
- Residual Risk Score
- Trust Boundary Violations
- Threat-to-Mitigation Ratio
- Data Flow Diagram Completeness
- Abuse Case Coverage

## Best Practices
- Create data flow diagrams with explicit trust boundaries before identifying threats
- Apply STRIDE per-element systematically — not ad hoc brainstorming
- Prioritize threats using DREAD or risk matrix (likelihood x impact)
- Update threat models when architecture changes — they are living documents
- Include abuse cases alongside use cases in the threat enumeration
