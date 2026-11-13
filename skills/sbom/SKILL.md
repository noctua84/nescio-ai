---
name: sbom
description: Use when generating or reviewing a software bill of materials — component inventory, transitive dependencies, license compliance, and CVE cross-referencing with CycloneDX, SPDX, NTIA Minimum Elements, and SLSA. Triggers on "SBOM", "software bill of materials", "dependency inventory", "CycloneDX", "SPDX", "supply chain security".
user-invocable: true
---

# SBOM

## Purpose

Create a software bill of materials (SBOM) that delivers actionable, measurable results.

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

Build on any existing software bill of materials (sbom) documents in the project and pick the framework that fits (NTIA Minimum Elements, CISA SBOM Guidance, CycloneDX). Generate SBOMs automatically in CI/CD pipeline — manual inventory is always incomplete. Structure the deliverable in the output format below, and state your assumptions and dependencies. Measure it with: Component Count, Known Vulnerability Count (CVEs), License Compliance Rate, SBOM Freshness.

Recommendations must be specific to this system rather than generic advice, and any number you cite needs a source or a stated basis.

## Output Format

```markdown
# Software Bill of Materials (SBOM)

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
- NTIA Minimum Elements
- CISA SBOM Guidance (2025)
- CycloneDX
- SPDX (ISO/IEC 5962)
- SLSA Framework

## Key Metrics
- Component Count
- Known Vulnerability Count (CVEs)
- License Compliance Rate
- SBOM Freshness (Last Generated)
- Dependency Depth
- Transitive Dependency Count

## Best Practices
- Generate SBOMs automatically in CI/CD pipeline — manual inventory is always incomplete
- Use CycloneDX or SPDX format for interoperability
- Include transitive dependencies — most vulnerabilities are in indirect dependencies
- Cross-reference all components against NVD/OSV for known CVEs
- Update SBOMs with every build, not just releases
