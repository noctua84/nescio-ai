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

Before starting, read the repo's `CLAUDE.md` and any relevant notes under `memory/` (e.g. `memory/repo/<repo>/`, `memory/feedback/`) for prior decisions and constraints.

## Process

### Step 1: Context & Research
- Review any existing vulnerability assessment report documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: CVSS v4.0, CIS Controls v8.1, NIST SP 800-40

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the vulnerability assessment report
- Identify gaps, opportunities, and risks
- Define success metrics: Total Vulnerabilities by Severity, Patch Compliance Rate, Vulnerability Density per Host, Mean Time to Remediate
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the vulnerability assessment report using the output format below
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
- [ ] Follows best practice: Prioritize by exploitability (EPSS score), not just CVSS severity

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
