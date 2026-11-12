# Usecase Configuration

Place one YAML file per usecase in this directory and reference the directory
from `router.usecase_config_dir` in `config.yaml`.

Each file must define a unique `name`. Everything else is optional: `match`
rules are optional routing rules for Kafka events, `polling_match` rules are
optional routing rules for polled tickets, and settings under `config`
override the shared root configuration for that usecase. For example,
`frontend.feedback.score_name` gives each usecase its own Langfuse feedback
score, resolved from the trace's usecase tag by the feedback frontend.

Do not override `kafka` settings per usecase. Kafka subscribers bind to the
topics of the shared root configuration, while retry publishing uses the
effective per-usecase settings, so a mismatched `retry_topic` would strand
retry events on a topic that no subscriber consumes.

A usecase without `match` rules never matches Kafka events, whether it is the
only configured usecase or one of many. With more than one usecase, a usecase
without `polling_match` rules never matches polled tickets.

See `permits.yaml.example` for a complete, ready-to-copy example.
