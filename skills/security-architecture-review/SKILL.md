---
name: security-architecture-review
description: Use when reviewing a system's security architecture — assessing control coverage, defense-in-depth layers, single points of failure, and zero-trust alignment with TOGAF/SABSA/NIST SP 800-160. Triggers on "security architecture review", "defense in depth", "control coverage", "zero trust", "north-south east-west traffic".
user-invocable: true
---

# Security Architecture Review

## Purpose

Create a security architecture review that delivers actionable, measurable results.

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

Build on any existing security architecture review documents in the project and pick the framework that fits (TOGAF Security Architecture, SABSA, NIST SP 800-160). Review architecture diagrams with explicit security control annotations. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Control Coverage %, Architecture Gap Count, Defense-in-Depth Layer Score, Compliance Alignment %.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# Security Architecture Review

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
- TOGAF Security Architecture
- SABSA
- NIST SP 800-160
- Zero Trust Architecture (NIST SP 800-207)
- Defense in Depth Model
- ISO 27001 Annex A

## Key Metrics
- Control Coverage %
- Architecture Gap Count
- Defense-in-Depth Layer Score
- Compliance Alignment %
- Risk Reduction Estimate
- Single Points of Failure Count

## Best Practices
- Review architecture diagrams with explicit security control annotations
- Validate defense-in-depth — ensure no single-layer protection for critical assets
- Map each architectural component to specific security controls
- Identify single points of failure in security infrastructure
- Assess both north-south and east-west traffic security controls
