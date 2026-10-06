# Architecture Decision Gate

Run this gate before making a significant architectural choice. Always run it before introducing custom authentication, storage, cryptography, or persistent infrastructure.

1. State the decision and the outcome it must enable.
2. List every constraint and label it as **user**, **legal/security**, **product**, **inferred**, or **agent-proposed**. Validate inferred and agent-proposed constraints with the user before treating them as hard requirements; otherwise keep them explicit assumptions.
3. Compare these options before designing a custom solution:
   - managed or platform-native capability;
   - the simplest replaceable solution;
   - accepting the limitation or deferring the capability;
   - a custom solution.
4. Compare each viable option on:
   - fitness for the stated outcome and constraints;
   - implementation and test effort in engineer-days;
   - ongoing operational ownership;
   - incident detection and response burden;
   - reversibility and migration path;
   - recurring service cost;
   - expected failure modes and blast radius;
   - vendor, protocol, and data lock-in.
5. Recommend one option and explain the decisive tradeoffs and assumptions.
6. Before choosing a custom solution, present the comparison and recommendation to the user and obtain explicit approval. Do not begin custom design or implementation without it.

Never choose production architecture solely because it is easier to emulate in LocalStack or exercise in e2e tests. Treat local test convenience as a test-strategy concern, not a production requirement.
