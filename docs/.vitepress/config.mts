import { defineConfig } from "vitepress";

// https://vitepress.dev/reference/site-config
export default defineConfig({
  title: "Zammad-AI",
  description: "GenAI-powered agent for Zammad",
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    nav: [
      { text: "Home", link: "/" },
      { text: "ADR", link: "/adr" },
    ],

    sidebar: [
      {
        text: "ADR",
        items: [
          {
            text: "01: System Architecture",
            link: "/adr/01-system-architecture",
          },
        ],
      },
    ],

    socialLinks: [
      { icon: "github", link: "https://github.com/it-at-m/zammad-ai" },
    ],
  },
});
