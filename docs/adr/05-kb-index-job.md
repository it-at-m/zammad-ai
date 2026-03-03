# ADR 05: Knowledge Base Indexing Strategy

| Status   | proposed                     |
| -------- | ---------------------------- |
| Author   | @freinold                    |
| Voters   | @freinold, @pilitz, @l0renor |
| Drafted  | 2026-03-03                   |
| Timeline | TBD                          |

## Context and Problem Statement

The Zammad-AI integration relies on a vector database (Qdrant) to provide context-aware answers. To maintain its effectiveness, the Knowledge Base (KB) index must be kept synchronized with the Zammad instance. This involves:

- **Initial Bootstrapping**: Indexing the entire KB for the first time.
- **Incremental Synchronization**: Updating or removing entries as KB content changes in Zammad.

We need to decide where this indexing logic should reside and how it should be executed to ensure system stability and maintainability.

## Decision Drivers

- **System Stability**: Indexing operations (especially initial runs) should not impact the latency or reliability of core triage and answering services.
- **Operational Independence**: The ability to scale or update the indexing logic without redeploying the core message processing services.
- **Code Sustainability**: Minimizing duplication while avoiding premature abstraction.
- **Velocity**: Ease of initial implementation and deployment.

## Considered Options

### Option A: Integrated Core Logic

Integrate the indexing process directly into the existing `zammad-ai` core services (e.g., as a background task).

- **Pro**: Zero code duplication; shared access to all models and utilities.
- **Con**: High risk of resource contention; tightly couples indexing lifecycle with message processing.

### Option B: Independent Job with Shared Library

Implement indexing as a separate service or scheduled job, extracting common logic (Zammad API clients, Qdrant models) into a shared internal library.

- **Pro**: Excellent decoupling and scaling; clean architecture.
- **Con**: Highest initial overhead due to library management and CI/CD complexity.

### Option C: Monorepo with Separate Projects

Maintain indexing as a separate Python project (e.g., `zammad-ai-index/`) alongside the main `zammad-ai/` service within the same git repository.

- **Pro**: Complete isolation of dependencies and Dockerfiles; unique image for each service; no code execution coupling.
- **Con**: Potential for code duplication unless a local shared library or common internal module is used.

## Evaluation

| Criterion              | Option A | Option B | Option C |
| ---------------------- | -------- | -------- | -------- |
| Performance Isolation  | --       | ++       | ++       |
| Maintainability        | -        | ++       | +        |
| Ease of Implementation | ++       | -        | ++       |
| Scalability            | -        | ++       | ++       |
| Infrastructure Simp.   | ++       | -        | +        |

## Proposed Decision

We have chosen **Option C: Monorepo with Separate Projects**.

We will implement the indexing logic as its own standalone project within the same repository. This allows for:

1. **Independent Docker Images**: Each project has its own `Dockerfile`, resulting in leaner, specialized containers.
2. **Split-Container Execution**: The triage service and the indexing job run as truly independent containers from the start.
3. **Internal Code Sharing**: While projects are separate, we can still share critical logic (like Pydantic models or API clients) by referencing them via `uv` workspace features or shared local paths, avoiding the need for an external package registry.

### Consequences

- **Good**: Maximum flexibility for the indexing job's own lifecycle and dependencies.
- **Good**: Deployment pipeline can build and push separate images (`zammad-ai` and `zammad-ai-index`).
- **Good**: No risk of the indexing job's dependencies bloating the main service image.
- **Risk**: Maintaining consistency between shared models across two projects requires discipline (e.g., using `uv` workspaces).

## Final Decision

The proposed decision is accepted. We will proceed with implementing the indexing logic as a separate project within the monorepo, ensuring that we establish clear guidelines for sharing code and managing dependencies to mitigate potential risks.
