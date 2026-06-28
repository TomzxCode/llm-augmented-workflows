---
artifact: existing-solutions
verdict: changes-requested
reviewed_at: 2026-06-28
---

## Coverage

### Missing Python plugin-loading libraries

The survey references StackStorm's stevedore for plugin loading (FR-09) but omits `pluggy`, the de facto Python plugin framework used by pytest, tox, and devpi. pluggy's hookspec/hookimpl pattern is simpler than stevedore and directly applicable to the distributable-parser design in FR-09. Adding it would strengthen the build recommendation with a proven Python-native pattern.

### Missing Python subprocess libraries

`sh` (34M+ downloads), `invoke`, and `plumbum` are well-known Python libraries for subprocess management that could inform the parser contract and command execution design. While the recommendation is to build, these represent proven patterns the implementation should reference.

### Security posture of candidates not assessed

Given NFR-03 (sandboxed parsers), the security model of each candidate should be noted. For example, MCP enforces a strict stdout-is-protocol-traffic rule and restricts subprocess communication to JSON-RPC over stdio — directly relevant to the parser sandbox design.

## Evaluation Rigor

### Unsupported claim about verdict library

The survey states verdict (haizelabs) is "over-engineered for verdict parsing" without citing documentation or providing evidence. The library is a declarative LLM-as-a-judge framework (not a CLI parser), so the claim that it is over-engineered for a different use case is subjective. Either remove the characterization or cite specific reasons.

## Accuracy

No issues found.

## Due Diligence

### Maintenance health only partially assessed

Only flowai-workflow's maintenance health is assessed (single maintainer, 8 weekly downloads). The survey should note maintenance status for other adopt-relevant candidates, especially opencode-cli-enforcer (which appears to be a small npm package) and cli-agent-spec (draft spec with only 5 stars).

### Commercial cost scaling not detailed

n8n Cloud and Temporal Cloud are listed as candidates but their cost models and scaling characteristics are not discussed. For completeness, note pricing model or mark as "not evaluated" if out of scope.

## Recommendation Soundness

No issues found.
