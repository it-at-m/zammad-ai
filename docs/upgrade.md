# Upgrade Notes

Breaking changes and required configuration migrations between releases. Check
this page before upgrading a running deployment.

## Multi-usecase release (workflow and index job)

The multi-usecase release restructures how the workflow service and the index
job are configured. Existing deployments fail at startup until the
configuration is migrated.

### Workflow service

- **`usecases` are now required.** Configure at least one usecase either inline
  under `usecases` in `config.yaml` or as usecase definition files in the
  directory referenced by `router.usecase_config_dir`. Startup fails when no
  usecase resolves. A root-level `usecase` block is no longer supported and is
  rejected at startup.
- **Usecases need `match` rules for Kafka intake.** A usecase without `match`
  rules never matches a Kafka event. With the default
  `router.unmatched_policy: skip`, a sole ruleless usecase silently drops every
  Kafka event; this combination now also produces a startup warning.
- **Polling-enabled usecases need `polling_match` rules once more than one
  usecase is configured.** A sole usecase receives every polled ticket, but
  with two or more usecases a usecase without `polling_match` rules never
  matches polled tickets; those tickets are skipped every polling cycle and
  remain unprocessed. Add `polling_match` rules to each polling-enabled usecase
  before adding a second usecase.
- **`kafka.event_processing.*` keys were removed.** Event filtering is now
  driven by usecase `match` rules and `router.unmatched_policy`; the old keys
  are no longer read.
- **Per-usecase `kafka` overrides are rejected at startup.** Kafka subscribers
  bind to the topics of the shared root configuration, so a per-usecase
  override such as a different `retry_topic` would strand retry events on a
  topic that no subscriber consumes. Keep all `kafka` settings in the root
  configuration.
- **Retries with a stale usecase header are dropped.** A retry event whose
  usecase header names a usecase that is no longer configured is acknowledged
  and dropped instead of being re-resolved from its payload. Resolving the
  payload could process the retry against a different Zammad instance than the
  one that produced it. Retries already sitting in the retry topic when a
  usecase is renamed or removed are therefore lost; drain or re-create them
  before upgrading.

### Index job

- **`targets` are now required.** Define at least one indexing target under
  `targets`; each target resolves to one Qdrant collection and one Zammad
  knowledge base. Targets run independently, and a failing target no longer
  stops the remaining targets.
- **Root-level `laws` are ignored.** Define laws per target under
  `targets[].laws`.
- **`qdrant.collection_name` and `zammad.knowledge_base_id` must resolve per
  target.** Root-level values act as shared defaults, but every target must
  end up with both values set.

### Migration pointers

- Copy the new structure from `zammad-ai-workflow/config.example.yaml` and
  `zammad-ai-index/config.example.yaml`.
- See the [Configuration Guide](/configuration) for the full settings
  reference and `zammad-ai-workflow/config/usecases/README.md` for usecase
  definition files.
