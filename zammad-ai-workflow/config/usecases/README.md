# Usecase Configuration

Place one YAML file per usecase in this directory and reference the directory
from `router.usecase_config_dir` in `config.yaml`.

Each file must define a unique `name`, at least one `match` or `polling_match`
rule, and optional settings under `config`. Those settings override the shared
root configuration for that usecase.
