---
name: hermes-dev-domain-guard
description: 'Before any Edit/Write, verify the target file is in this Developer''s allowed domain. Trigger from Phase 3 PreToolUse hooks on Edit/Write.'
---

1. Determine current role from chat context: Developer Core or Developer Edge.
2. Read the `AGENTS.md` domain map.
3. If target file is outside allowed domain, block and respond: `Out of domain. This file belongs to <other role>. Escalate via MAIN if cross-domain work is needed.`
4. If target file is in shared domain, block and respond: `Shared domain belongs to MAIN. Request via escalation.`
5. Otherwise, proceed.
