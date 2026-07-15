---
name: prompt-testing-plan
description: Use when designing a prompt testing plan — test cases, regression suites, coverage, and pass/fail criteria for prompts across versions. Triggers on "prompt testing", "test plan", "regression testing", "prompt QA", "test cases", "prompt versions".
user-invocable: true
---

# Prompt Testing Plan

## Purpose

Design and document a prompt testing plan that delivers actionable, measurable results.

**Category**: AI & Automation

## Inputs

### Required
- **Objective**: What you want to achieve with this deliverable
- **Context**: Relevant background information

### Optional
- **Constraints**: Any limitations or requirements to consider
- **Existing Work**: Previous documents or data to build on

## Context

Before starting, read the repo's `CLAUDE.md` and any relevant notes under `memory/` (e.g. `memory/repo/<repo>/`, `memory/feedback/`) for prior decisions and constraints.

## Process

### Step 1: Context & Research
- Review any existing prompt testing plan documents in the project
- Identify key stakeholders and their requirements
- Select the most appropriate framework: AI Readiness Assessment, Automation ROI Calculator, Human-in-the-Loop Design

### Step 2: Analysis & Framework Application
- Apply the selected framework to structure the prompt testing plan
- Identify gaps, opportunities, and risks
- Define success metrics: Time Saved Per Task, Automation Rate, Error Reduction %, Cost Per AI Operation
- Document assumptions and dependencies
- Validate approach against industry best practices

### Step 3: Build the Deliverable
- Structure the prompt testing plan using the output format below
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
- [ ] Follows best practice: Start with high-volume, low-risk tasks

## Output Format

```markdown
# Prompt Testing Plan

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
- AI Readiness Assessment
- Automation ROI Calculator
- Human-in-the-Loop Design
- RAG Architecture
- Agent Orchestration Patterns
- Responsible AI Framework

## Key Metrics
- Time Saved Per Task
- Automation Rate
- Error Reduction %
- Cost Per AI Operation
- User Adoption Rate
- Output Quality Score

## Best Practices
- Start with high-volume, low-risk tasks
- Always keep human review for critical outputs
- Measure time saved, not just accuracy
- Version control prompts like code
- Monitor for drift and degradation monthly
