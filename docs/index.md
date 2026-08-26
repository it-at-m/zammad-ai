---
layout: home

hero:
  name: "Zammad-AI"
  text: "GenAI workflow for Zammad"
  tagline: "Ticket triage, answer generation, Kafka processing, and knowledge base indexing."
  actions:
    - theme: brand
      text: Configuration
      link: /configuration
    - theme: secondary
      text: API
      link: /api
    - theme: secondary
      text: Components
      link: /components
    - theme: secondary
      text: ADRs
      link: /adr
    - theme: secondary
      text: Release Workflow
      link: /release-workflow

features:
  - title: Workflow service
    details: Run triage and answer generation as a FastAPI plus FastStream backend with optional Gradio UI.
  - title: Index job
    details: Sync Zammad knowledge base content into Qdrant with snapshot-safe batch updates.
  - title: Observable by default
    details: Trace with Langfuse and export metrics to Prometheus for local and production use.
  - title: Content safety
    details: Offload prompt and response checks to the separate slm-guardrails service.
---
