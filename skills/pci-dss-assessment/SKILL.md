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

Before starting, read the repo's `CLAUDE.md` and any relevant notes under `memory/` (e.g. `memory/repo/<repo>/`, `memory/feedback/`) for prior decisions and constraints.

## Process

### Step 1: Context & Research
- Review any existing pci dss assessment documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: PCI DSS 4.0, PCI SSC SAQ Types, PA-DSS

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the pci dss assessment
- Identify gaps, opportunities, and risks
- Define success metrics: Requirement Compliance Rate (12 Requirements), SAQ/ROC Completion Status, ASV Scan Pass Rate, Segmentation Validation Results
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the pci dss assessment using the output format below
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
- [ ] Follows best practice: Determine correct SAQ type based on actual cardholder data flow — not assumptions

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
