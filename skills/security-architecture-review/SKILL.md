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

Before starting, read the repo's `CLAUDE.md` and any relevant notes under `memory/` (e.g. `memory/repo/<repo>/`, `memory/feedback/`) for prior decisions and constraints.

## Process

### Step 1: Context & Research
- Review any existing security architecture review documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: TOGAF Security Architecture, SABSA, NIST SP 800-160

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the security architecture review
- Identify gaps, opportunities, and risks
- Define success metrics: Control Coverage %, Architecture Gap Count, Defense-in-Depth Layer Score, Compliance Alignment %
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the security architecture review using the output format below
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
- [ ] Follows best practice: Review architecture diagrams with explicit security control annotations

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
