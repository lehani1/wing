---
name: prove-it-works
description: Verify a change against the real behavior or artifact the user asked for.
---

Write down what the user should observe. Run the real entry point and compare
its result with that expectation. Inspect the actual output, resulting state, or
rendered artifact. Use compile and lint results as additional checks.

If the real check is blocked, report the exact boundary you reached and what
remains unverified.
