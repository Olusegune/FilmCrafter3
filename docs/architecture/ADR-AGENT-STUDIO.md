# ADR: Agent Studio is an orchestrator over the existing project

Status: accepted for the first implementation slice.

FilmCrafter already has durable projects, versioned jobs and takes, approval records, queues, pricing, export checks and a single-use spend-token boundary. Building a second automatic production system would create competing truth for assets, costs and recovery.

Agent Studio therefore stores only workflow concerns: the creative brief, ordered stages, pause state, explicit approvals, revision proposals and activity. It derives job counts and spending from the existing job ledger. It may not submit provider work. Paid execution remains in the existing queue commands behind the existing confirmation token.

This makes restart recovery and switching to Manual Studio straightforward and protects existing projects. The cost is that autonomous execution must be integrated stage by stage with the existing commands rather than implemented as a parallel pipeline.
