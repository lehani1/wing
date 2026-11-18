---
name: fix-root-causes
description: Reproduce a reported bug, trace the first incorrect state, and verify the fix.
---

Reproduce the symptom through the entry point the user reported. Trace the
inputs and state backwards until you find the first incorrect decision or
value. Check that a fix at that point accounts for the reproduction.

Change the code that produced the bad state. Rerun the original reproduction.
Check an adjacent case that depends on existing behavior.
