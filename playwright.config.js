const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "./tests/browser",
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: process.env.LAB_URL || "http://127.0.0.1:8765",
    browserName: "chromium",
    viewport: { width: 1440, height: 1100 },
  },
  reporter: "list",
});
