# Release Workflow

Zammad-AI uses semantic release to create version tags, and each tag push immediately triggers the Docker image release.

## Semantic release

- `zammad-ai-workflow` and `zammad-ai-index` both use `python-semantic-release` on `main`.
- Conventional commits drive the version bump.
- Examples:
  - `fix:` usually creates a patch release, for example `fix: handle missing ticket metadata`.
  - `feat:` usually creates a minor release, for example `feat: add reply draft preview`.
  - `feat!:` or a commit with a `BREAKING CHANGE:` footer usually creates a major release.
  - Non-user-facing changes like `docs:` or `chore:` typically do not create a release by themselves.
- A release commit updates the package version and creates a tag in the form `zammad-ai-workflow-{version}` or `zammad-ai-index-{version}`.
- The release job only runs when the corresponding service directory changes, which keeps version bumps scoped to that service.

## Docker release

- Tag pushes matching `zammad-ai-workflow-*` or `zammad-ai-index-*` trigger the Docker release workflows immediately.
- In practice, semantic release creates the tag and that tag push starts the Docker build and publish step.
- The workflows build the service image from the matching directory and push it to GitHub Container Registry.
- Each image is published with both the version tag and `latest`.
- Manual dispatch is also supported if you need to rebuild a specific tag.

## What to expect

1. Merge the service change to `main`.
2. Let semantic release create the version tag.
3. Let the Docker workflow build and publish the image for that tag.

This keeps code releases and container releases aligned while still allowing the two services to ship on their own cadence.
