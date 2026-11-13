---
name: vuln-assessment
description: Use when producing a vulnerability assessment report — scoring, prioritizing, and remediating findings with CVSS v4.0, EPSS, CISA KEV, CIS Controls v8.1, and NIST SP 800-40. Triggers on "vulnerability assessment", "vuln scan report", "CVE prioritization", "patch compliance", "remediation plan".
user-invocable: true
---

# Vulnerability Assessment

## Purpose

Create a vulnerability assessment report that delivers actionable, measurable results.

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

Build on any existing vulnerability assessment report documents in the project and pick the framework that fits (CVSS v4.0, CIS Controls v8.1, NIST SP 800-40). Prioritize by exploitability (EPSS score), not just CVSS severity. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Total Vulnerabilities by Severity, Patch Compliance Rate, Vulnerability Density per Host, Mean Time to Remediate.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# Vulnerability Assessment Report

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
- CVSS v4.0
- CIS Controls v8.1
- NIST SP 800-40 (Patch Management)
- CVE/NVD Database
- CISA KEV (Known Exploited Vulnerabilities)
- EPSS (Exploit Prediction Scoring System)

## Key Metrics
- Total Vulnerabilities by Severity
- Patch Compliance Rate
- Vulnerability Density per Host
- Mean Time to Remediate
- Age of Open Vulnerabilities
- EPSS Score Distribution
- CISA KEV Match Count

## Best Practices
- Scan with both authenticated and unauthenticated methods for complete coverage
- Cross-reference findings against CISA KEV for active exploitation status
- Remove false positives through manual validation before reporting
- Track vulnerability trends over time — single snapshots are insufficient
- Prioritize by exploitability (EPSS score), not just CVSS severity
