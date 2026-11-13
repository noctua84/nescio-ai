---
name: api-security-assessment
description: Use when assessing the security of an API — testing for BOLA/broken object-level authorization, broken authentication, excessive data exposure, rate limiting, and JWT flaws against the OWASP API Security Top 10 and OAuth 2.0/OIDC. Triggers on "API security assessment", "OWASP API Top 10", "BOLA", "JWT validation", "rate limiting".
user-invocable: true
---

# API Security Assessment

## Purpose

Create an API security assessment that delivers actionable, measurable results.

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

Build on any existing api security assessment documents in the project and pick the framework that fits (OWASP API Security Top 10, OpenAPI Specification Security Schemes, OAuth 2.0/OIDC). Test against all OWASP API Security Top 10 categories. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Vulnerability Count per API, Authentication Bypass Attempts, Authorization Test Coverage, Rate Limiting Effectiveness.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# API Security Assessment

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
- OWASP API Security Top 10
- OpenAPI Specification Security Schemes
- OAuth 2.0/OIDC
- NIST SP 800-204 (Microservices Security)
- CIS API Security Benchmark

## Key Metrics
- Vulnerability Count per API
- Authentication Bypass Attempts
- Authorization Test Coverage
- Rate Limiting Effectiveness
- Data Exposure Finding Count
- JWT Implementation Score

## Best Practices
- Test against all OWASP API Security Top 10 categories
- Validate object-level authorization (BOLA) — the #1 API vulnerability
- Test rate limiting under load — misconfigured limits enable abuse
- Check for excessive data exposure in API responses (return only required fields)
- Validate JWT implementation: signature verification, expiry enforcement, audience restrictions
