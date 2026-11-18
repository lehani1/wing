---
name: poteto-mode
description: Choose an engineering workflow for a coding, debugging, or repository investigation task.
---

State the user's intended outcome and the smallest change likely to meet it.
Trace the normal entry point before changing it. Reuse the repo's existing types
and behavior.

- For a feature or structural change, use `architect` when types or boundaries
  need a decision.
- For a reported bug, use `fix-root-causes`.
- For a read-only question, use `investigation`.

Break multi-step work into units you can verify independently. Use the todo
tool when tracking those units helps you resume or recover. Finish code changes
with `prove-it-works`. Report the observed result and any check you could not
run. Keep the reply short and specific.
