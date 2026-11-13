---
name: secure-design-spec
description: Use when writing a secure design specification for a new system or feature — defining security requirements, authentication, authorization, encryption, and trust assumptions at design time with OWASP Secure Design Principles/Microsoft SDL/NIST SSDF. Triggers on "secure design spec", "security requirements", "security by design", "least privilege", "data classification".
user-invocable: true
---

# Secure Design Spec

## Purpose

Create a secure design specification that delivers actionable, measurable results.

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

Build on any existing secure design specification documents in the project and pick the framework that fits (OWASP Secure Design Principles, Microsoft SDL, NIST SSDF (SP 800-218)). Define security requirements before functional requirements. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Security Requirements Coverage, Threat Mitigation Coverage, Design Review Findings, Crypto Standard Compliance.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# Secure Design Specification

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
- OWASP Secure Design Principles
- Microsoft SDL
- NIST SSDF (SP 800-218)
- BSIMM
- Security by Design (ENISA)

## Key Metrics
- Security Requirements Coverage
- Threat Mitigation Coverage
- Design Review Findings
- Crypto Standard Compliance
- Authentication Mechanism Strength
- Data Protection Control Count

## Best Practices
- Define security requirements before functional requirements
- Specify authentication, authorization, and encryption at the design phase
- Apply least privilege and defense in depth as architectural constraints
- Document all trust assumptions explicitly — they become attack vectors when wrong
- Include data flow diagrams with classification labels for every data store
