const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "./tests/demo",
  workers: 1,
  use: {
    baseURL: process.env.DEMO_URL || "http://127.0.0.1:8879",
    viewport: { width: 1440, height: 1100 },
  },
  reporter: "list",
});
