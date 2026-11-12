---
name: pci-dss-assessment
description: Use when assessing PCI DSS compliance for systems that store, process, or transmit cardholder data — scoping the CDE, selecting the SAQ type, validating segmentation, and tracking the 12 requirements. Triggers on "PCI DSS", "cardholder data", "CDE", "SAQ", "ROC", "ASV scan", "PCI 4.0", "tokenization".
user-invocable: true
---

# PCI DSS Assessment

## Purpose

Create a PCI DSS assessment that delivers actionable, measurable results.

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

Build on any existing pci dss assessment documents in the project and pick the framework that fits (PCI DSS 4.0, PCI SSC SAQ Types, PA-DSS). Determine correct SAQ type based on actual cardholder data flow — not assumptions. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Requirement Compliance Rate (12 Requirements), SAQ/ROC Completion Status, ASV Scan Pass Rate, Segmentation Validation Results.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# PCI DSS Assessment

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
- PCI DSS 4.0
- PCI SSC SAQ Types (A, A-EP, B, C, D)
- PA-DSS
- PCI PIN Security
- PCI P2PE

## Key Metrics
- Requirement Compliance Rate (12 Requirements)
- SAQ/ROC Completion Status
- ASV Scan Pass Rate
- Segmentation Validation Results
- Compensating Control Count
- CDE Scope Size

## Best Practices
- Determine correct SAQ type based on actual cardholder data flow — not assumptions
- Minimize cardholder data environment (CDE) scope through segmentation and tokenization
- Run ASV scans quarterly and after any significant infrastructure change
- Document all compensating controls with detailed justification
- Track PCI DSS 4.0 future-dated requirements and verify compliance
