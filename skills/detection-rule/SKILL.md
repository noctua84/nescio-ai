---
name: detection-rule
description: Use when authoring a SIEM detection rule or use case — mapping to MITRE ATT&CK techniques, writing Sigma rules, and tuning false positives for Splunk/Elastic/Sentinel. Triggers on "detection rule", "SIEM use case", "Sigma rule", "ATT&CK detection", "alert tuning", "detection engineering".
user-invocable: true
---

# Detection Rule

## Purpose

Create a detection rule / SIEM use case that delivers actionable, measurable results.

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
- Review any existing detection rule / siem use case documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: Sigma Rules Standard, MITRE ATT&CK Detection, Splunk/Elastic/Sentinel Detection Frameworks

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the detection rule / siem use case
- Identify gaps, opportunities, and risks
- Define success metrics: True Positive Rate, False Positive Rate, Alert Volume per Rule, ATT&CK Technique Coverage
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the detection rule / siem use case using the output format below
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
- [ ] Follows best practice: Map every detection rule to a specific MITRE ATT&CK technique

## Output Format

```markdown
# Detection Rule / SIEM Use Case

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
- Sigma Rules Standard
- MITRE ATT&CK Detection
- Splunk/Elastic/Sentinel Detection Frameworks
- NIST SP 800-92 (Log Management)
- SOC-CMM Detection Engineering

## Key Metrics
- True Positive Rate
- False Positive Rate
- Alert Volume per Rule
- ATT&CK Technique Coverage
- Mean Time from Rule Creation to Production
- Data Source Availability

## Best Practices
- Map every detection rule to a specific MITRE ATT&CK technique
- Write rules in Sigma format first for portability across SIEM platforms
- Include tuning guidance — expected false positive sources and whitelist criteria
- Test rules against known-good and known-bad data before production deployment
- Document data source requirements — a rule without its data source is useless
