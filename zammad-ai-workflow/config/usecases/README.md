# Usecase Configuration

Place one YAML file per usecase in this directory and reference the directory
from `router.usecase_config_dir` in `config.yaml`.

Each file must define a unique `name`. Everything else is optional: `match`
rules are optional routing rules for Kafka events, `polling_match` rules are
optional routing rules for polled tickets, and settings under `config`
override the shared root configuration for that usecase. For example,
`frontend.feedback.score_name` gives each usecase its own Langfuse feedback
score, resolved from the trace's usecase tag by the feedback frontend.

Per-usecase `kafka` overrides are rejected at startup. Kafka subscribers bind to
the topics of the shared root configuration, while retry publishing uses the
effective per-usecase settings, so a mismatched `retry_topic` would strand
retry events on a topic that no subscriber consumes.

A usecase without `match` rules never matches Kafka events, whether it is the
only configured usecase or one of many. With more than one usecase, a usecase
without `polling_match` rules never matches polled tickets. A sole usecase
without `match` rules additionally warns at startup when
`router.unmatched_policy` is `skip`, because every Kafka event would then be
dropped without processing.

When multiple usecases enable polling, keep each usecase's
`config.polling.search_query` aligned with its `polling_match` rules. Every
polling service searches Zammad with its own query, and a ticket found by
usecase A's query but routed to usecase B is only processed when B's own query
also finds it. With divergent queries a ticket can therefore be skipped by
every poller and never processed. Sharing the default query avoids this.

See `permits.yaml.example` for a complete, ready-to-copy example.
