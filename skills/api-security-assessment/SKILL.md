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

Before starting, read the repo's `CLAUDE.md` and any relevant notes under `memory/` (e.g. `memory/repo/<repo>/`, `memory/feedback/`) for prior decisions and constraints.

## Process

### Step 1: Context & Research
- Review any existing api security assessment documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: OWASP API Security Top 10, OpenAPI Specification Security Schemes, OAuth 2.0/OIDC

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the api security assessment
- Identify gaps, opportunities, and risks
- Define success metrics: Vulnerability Count per API, Authentication Bypass Attempts, Authorization Test Coverage, Rate Limiting Effectiveness
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the api security assessment using the output format below
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
- [ ] Follows best practice: Test against all OWASP API Security Top 10 categories

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
