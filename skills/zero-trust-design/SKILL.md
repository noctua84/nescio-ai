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

Check the brain's notes for prior decisions and constraints on this repo: `~/.claude/memory/repo/<repo>/` and `~/.claude/memory/feedback/`.

## Process

Build on any existing zero trust architecture design documents in the project and pick the framework that fits (NIST SP 800-207, CISA Zero Trust Maturity Model, Google BeyondCorp). Never trust, always verify — apply to internal traffic, not just perimeter. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Microsegmentation Coverage %, Identity Verification Rate, Continuous Authentication Score, Lateral Movement Prevention Rate.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

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
