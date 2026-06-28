---
issue: "#18"
status: Active
---

# Assumption: Platform-specific sandboxing for NFR-03 is feasible within the stated scope

**Date:** 2026-06-28
**Status:** Active
**Author:** Requirements reviewer

---

## Statement

The NFR-03 sandbox requirement (verdict parsers run in a sandboxed subprocess with no network access unless explicitly configured) can be implemented at acceptable cost using platform-specific mechanisms: Linux namespaces/seccomp, macOS sandbox-exec or a pure-userspace proxy approach, and Windows Job Objects + Windows Filtering Platform.

## Basis

Similar subprocess sandboxing exists in tools like Bubblewrap (Linux), sandbox-exec (macOS), and Firejail. A lighter approach using a `LD_PRELOAD` hook or `ptrace`-based syscall filtering on Linux, combined with a simple TCP/DNS proxy that blocks outbound connections, can provide a cross-platform baseline without requiring full containerization.

## Confidence

**Level:** Low

No prototype or spike has been run for this specific use case. The macOS and Windows approaches in particular need validation.

## Risk if Wrong

**Impact:** High

If robust cross-platform sandboxing is impractical, NFR-03 must be relaxed (e.g., Linux-only enforcement, warning on other platforms) or the architecture must adopt a container-based approach (Docker), which increases deployment complexity and contradicts the constraint against requiring elevated privileges.

## Validation Plan

**Method:** Build a small spike that runs a subprocess with network blocked on each target platform, measure complexity and false positives (non-malicious parsers that need network).
**Owner:** Implementation engineer
**By:** Before implementation begins (spike in design phase)

## Related

- requirements.md: NFR-03, Open Question 10
