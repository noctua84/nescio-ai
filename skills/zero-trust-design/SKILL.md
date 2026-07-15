---
name: zero-trust-design
description: Use when designing a zero trust architecture — microsegmentation, identity-aware proxies, continuous authentication, and policy decision points per NIST SP 800-207, CISA Zero Trust Maturity Model, and BeyondCorp. Triggers on "zero trust", "ZTA", "microsegmentation", "never trust always verify", "identity-aware proxy", "lateral movement".
user-invocable: true
---

# Zero Trust Design

## Purpose

Create a zero trust architecture design that delivers actionable, measurable results.

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
- Review any existing zero trust architecture design documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: NIST SP 800-207, CISA Zero Trust Maturity Model, Google BeyondCorp

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the zero trust architecture design
- Identify gaps, opportunities, and risks
- Define success metrics: Microsegmentation Coverage %, Identity Verification Rate, Continuous Authentication Score, Lateral Movement Prevention Rate
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the zero trust architecture design using the output format below
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
- [ ] Follows best practice: Never trust, always verify — apply to internal traffic, not just perimeter

## Output Format

```markdown
# Zero Trust Architecture Design

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
- NIST SP 800-207
- CISA Zero Trust Maturity Model
- Google BeyondCorp
- Microsoft Zero Trust Model
- Forrester ZTX
- DoD Zero Trust Reference Architecture

## Key Metrics
- Microsegmentation Coverage %
- Identity Verification Rate
- Continuous Authentication Score
- Lateral Movement Prevention Rate
- Policy Decision Point Response Time
- Zero Trust Maturity Level

## Best Practices
- Never trust, always verify — apply to internal traffic, not just perimeter
- Implement microsegmentation starting with crown jewel assets
- Deploy identity-aware proxies for all application access
- Encrypt all traffic (east-west and north-south) regardless of network location
- Implement continuous posture assessment for all endpoints
