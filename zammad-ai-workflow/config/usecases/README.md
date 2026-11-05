# Usecase Configuration

Place one YAML file per usecase in this directory and reference the directory
from `router.usecase_config_dir` in `config.yaml`.

Each file must define a unique `name`, at least one `match` or `polling_match`
rule, and optional settings under `config`. Those settings override the shared
root configuration for that usecase.

A usecase without `match` rules never matches Kafka events, whether it is the
only configured usecase or one of many. With more than one usecase, a usecase
without `polling_match` rules never matches polled tickets.

See `permits.yaml.example` for a complete, ready-to-copy example.
