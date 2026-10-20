import { defineConfig } from "vitepress";

// https://vitepress.dev/reference/site-config
export default defineConfig({
  lang: "en-US",
  title: "Zammad-AI",
  description: "GenAI-powered agent for Zammad",
  base: "/zammad-ai/",
  cleanUrls: true,
  lastUpdated: true,
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    nav: [
      { text: "Home", link: "/" },
      { text: "ADR", link: "/adr" },
      { text: "Components", link: "/components" },
      { text: "API", link: "/api" },
      { text: "Config", link: "/configuration" },
    ],

    sidebar: [
      {
        text: "Documentation",
        items: [
          { text: "Configuration Guide", link: "/configuration" },
          { text: "REST API Reference", link: "/api" },
        ],
      },
      {
        text: "ADR",
        link: "/adr",
        items: [
          {
            text: "01: System architecture",
            link: "/adr/01-system-architecture",
          },
          {
            text: "02: Two-way processing of tickets",
            link: "/adr/02-two-way-processing-of-tickets",
          },
          {
            text: "03: Vector database selection",
            link: "/adr/03-vector-database",
          },
          {
            text: "04: Knowledge management system",
            link: "/adr/04-knowledge-management-system",
          },
          {
            text: "05: Knowledgebase index job",
            link: "/adr/05-kb-index-job",
          },
          {
            text: "06: Multiple Usecases",
            link: "/adr/06-system-architecture-multiple-usecases",
          },
        ],
      },
      {
        text: "Components",
        link: "/components",
        items: [
          {
            text: "Kafka message broker",
            link: "/components/kafka",
          },
          {
            text: "Frontend module",
            link: "/components/frontend",
          },
          {
            text: "Triage",
            link: "/components/triage",
          },
          {
            text: "Zammad Integration",
            link: "/components/zammad",
          },
          {
            text: "Qdrant Vector Database",
            link: "/components/qdrant",
          },
          {
            text: "Observability (Langfuse)",
            link: "/components/observability",
          },
          {
            text: "Prometheus Metrics",
            link: "/components/prometheus",
          },
        ],
      },
    ],

    socialLinks: [
      { icon: "github", link: "https://github.com/it-at-m/zammad-ai" },
    ],
  },
});
