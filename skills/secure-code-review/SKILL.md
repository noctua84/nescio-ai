---
name: secure-code-review
description: Use when reviewing source code for security vulnerabilities — auditing authentication, authorization, cryptography, and input validation, and classifying findings by CWE. Triggers on "secure code review", "SAST findings", "CWE Top 25", "OWASP ASVS", "vulnerability review".
user-invocable: true
---

# Secure Code Review

## Purpose

Create a secure code review report that delivers actionable, measurable results.

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

Build on any existing secure code review report documents in the project and pick the framework that fits (OWASP Code Review Guide, OWASP ASVS v4.0, CWE Top 25). Combine SAST tool results with manual review — neither alone is sufficient. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Vulnerability Count by CWE Category, Severity Distribution, Lines of Code Reviewed, Finding Density.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# Secure Code Review Report

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
- OWASP Code Review Guide
- OWASP ASVS v4.0
- CWE Top 25
- SANS Top 25
- NIST SSDF (SP 800-218)

## Key Metrics
- Vulnerability Count by CWE Category
- Severity Distribution (Critical/High/Medium/Low)
- Lines of Code Reviewed
- Finding Density (Findings per KLOC)
- Remediation Acceptance Rate
- Review Turnaround Time

## Best Practices
- Combine SAST tool results with manual review — neither alone is sufficient
- Focus manual review on authentication, authorization, cryptography, and input validation
- Classify findings using CWE identifiers for consistency and trending
- Provide remediation code examples, not just vulnerability descriptions
- Review within the development sprint — findings delivered after release have 10x lower fix rate
