---
name: hipaa-assessment
description: Use when assessing HIPAA compliance for systems handling ePHI — evaluating Administrative, Physical, and Technical Safeguards, Business Associate Agreements, and breach risk. Triggers on "HIPAA", "ePHI", "Security Rule", "Privacy Rule", "HITECH", "BAA", "OCR audit", "45 CFR 164".
user-invocable: true
---

# HIPAA Assessment

## Purpose

Create a HIPAA security assessment that delivers actionable, measurable results.

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
- Review any existing hipaa security assessment documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: HIPAA Security Rule (45 CFR Part 164), HITECH Act, NIST SP 800-66

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the hipaa security assessment
- Identify gaps, opportunities, and risks
- Define success metrics: ePHI Safeguard Coverage, Risk Assessment Completeness, BAA Inventory Compliance, Security Incident Count
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the hipaa security assessment using the output format below
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
- [ ] Follows best practice: Conduct a thorough ePHI inventory — you cannot protect what you do not know exists

## Output Format

```markdown
# HIPAA Security Assessment

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
- HIPAA Security Rule (45 CFR Part 164)
- HIPAA Privacy Rule
- HITECH Act
- NIST SP 800-66 (HIPAA Implementation Guide)
- HHS OCR Audit Protocol

## Key Metrics
- ePHI Safeguard Coverage (Administrative/Physical/Technical)
- Risk Assessment Completeness
- BAA Inventory Compliance
- Security Incident Count
- Training Completion Rate
- Audit Log Retention Compliance

## Best Practices
- Conduct a thorough ePHI inventory — you cannot protect what you do not know exists
- Ensure all business associates have current BAAs (Business Associate Agreements)
- Implement minimum necessary standard for all ePHI access
- Maintain audit logs for all ePHI access with 6-year retention
- Train all workforce members (not just employees) who handle ePHI
