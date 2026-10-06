# Defect classification

- **Production regression:** shipped behavior that previously worked for production users and now fails.
- **Current-PR defect:** introduced by the current unmerged change.
- **Greenfield capability gap:** required behavior never implemented.
- **Historical defect in unshipped code:** predates current change but never formed a production baseline.

Review discovery does not change category.

Only a production regression automatically carries the `regression` label, and it is reproduced red-first (`test-requirements.md`). All other categories use the normal test policy.

Security, privacy, compliance, correctness, and data integrity remain binding for all categories.
