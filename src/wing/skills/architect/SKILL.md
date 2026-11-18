---
name: architect
description: Choose types, module boundaries, and public interfaces before implementing a structural change.
---

Trace the existing callers and write down which states must stay valid.
Sketch the caller's normal usage and the data shape that makes it work. Compare
two shapes when a decision would be hard to reverse. Prefer the interface that
keeps ownership clear and leaves the caller fewer cases to handle.

Implement the chosen shape in a small verifiable unit. Revisit the shape if
multiple callers need exceptions for the same reason.
