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

Check the brain's notes for prior decisions and constraints on this repo: `~/.claude/memory/repo/<repo>/` and `~/.claude/memory/feedback/`.

## Process

Build on any existing hipaa security assessment documents in the project and pick the framework that fits (HIPAA Security Rule (45 CFR Part 164), HITECH Act, NIST SP 800-66). Conduct a thorough ePHI inventory — you cannot protect what you do not know exists. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: ePHI Safeguard Coverage, Risk Assessment Completeness, BAA Inventory Compliance, Security Incident Count.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

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
