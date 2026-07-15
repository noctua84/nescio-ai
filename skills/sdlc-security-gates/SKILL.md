---
name: sdlc-security-gates
description: Use when defining or auditing security gates across the SDLC — mandatory checkpoints at design, code, build, test, and deploy with SAST/DAST/SCA/secrets scanning in CI/CD using Microsoft SDL/OWASP SAMM/NIST SSDF. Triggers on "SDLC security gates", "DevSecOps", "CI/CD security", "gate pass rate", "shift left".
user-invocable: true
---

# SDLC Security Gates

## Purpose

Create secure SDLC security gates that deliver actionable, measurable results.

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
- Review any existing secure sdlc security gates documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: Microsoft SDL, OWASP SAMM, NIST SSDF (SP 800-218)

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the secure sdlc security gates
- Identify gaps, opportunities, and risks
- Define success metrics: Gate Pass Rate per Phase, Critical Finding Escape Rate, Security Requirement Coverage, Mean Time to Fix Security Bugs
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the secure sdlc security gates using the output format below
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
- [ ] Follows best practice: Define mandatory gates at design, code, build, test, and deploy phases

## Output Format

```markdown
# Secure SDLC Security Gates

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
- Microsoft SDL
- OWASP SAMM
- NIST SSDF (SP 800-218)
- BSIMM
- DevSecOps Maturity Model (DSOMM)

## Key Metrics
- Gate Pass Rate per Phase
- Critical Finding Escape Rate
- Security Requirement Coverage
- Mean Time to Fix Security Bugs
- Security Training Completion Rate
- Automated Scan Coverage

## Best Practices
- Define mandatory gates at design, code, build, test, and deploy phases
- Automate SAST, DAST, SCA, and secrets scanning in CI/CD pipeline
- Block deployments with Critical/High findings — no exceptions without CISO sign-off
- Require threat models for all new features above a risk threshold
- Track security bug fix time separately from functional bugs — they have different SLAs
