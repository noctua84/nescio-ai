---
name: iso27001-isms
description: Use when building or documenting an ISO 27001 ISMS — scoping the ISMS, producing a Statement of Applicability, implementing Annex A controls, and preparing for certification. Triggers on "ISO 27001", "ISMS", "Annex A", "Statement of Applicability", "SoA", "ISO 27002", "ISO 27005", "risk treatment plan", "certification".
user-invocable: true
---

# ISO 27001 ISMS

## Purpose

Create ISO 27001 ISMS documentation that delivers actionable, measurable results.

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
- Review any existing iso 27001 isms documentation documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: ISO/IEC 27001:2022, ISO/IEC 27002:2022, ISO/IEC 27005

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the iso 27001 isms documentation
- Identify gaps, opportunities, and risks
- Define success metrics: Annex A Control Implementation %, Statement of Applicability Completeness, Internal Audit Nonconformity Count, Risk Treatment Plan Progress
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the iso 27001 isms documentation using the output format below
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
- [ ] Follows best practice: Scope the ISMS carefully — too broad makes certification impractical

## Output Format

```markdown
# ISO 27001 ISMS Documentation

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
- ISO/IEC 27001:2022
- ISO/IEC 27002:2022
- ISO/IEC 27005 (Risk Management)
- ISO/IEC 27017 (Cloud)
- ISO/IEC 27701 (Privacy)

## Key Metrics
- Annex A Control Implementation %
- Statement of Applicability Completeness
- Internal Audit Nonconformity Count
- Risk Treatment Plan Progress
- Corrective Action Closure Rate
- Management Review Frequency

## Best Practices
- Scope the ISMS carefully — too broad makes certification impractical
- Create a Statement of Applicability (SoA) mapping all 93 Annex A controls
- Conduct management reviews at least quarterly, not just annually
- Integrate risk assessment with business risk processes
- Train all employees within ISMS scope, not just IT staff
