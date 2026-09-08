import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

const baseURL = "http://127.0.0.1:8517";
const neutralBaseURL = "http://127.0.0.1:8518";
const virtualenvPython = process.platform === "win32"
  ? ".venv\\Scripts\\python.exe"
  : ".venv/bin/python";
const python = process.env.PYTHON
  ?? (existsSync(virtualenvPython)
    ? virtualenvPython
    : process.platform === "win32" ? "python" : "python3");

export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  expect: {
    timeout: 10_000,
  },
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"]],
  use: {
    baseURL,
    browserName: "chromium",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command:
        `${python} -m streamlit run app.py --server.headless=true `
        + "--server.address=127.0.0.1 --server.port=8517 "
        + "--browser.gatherUsageStats=false",
      url: `${baseURL}/_stcore/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command:
        `${python} -m streamlit run neutral_app.py --server.headless=true `
        + "--server.address=127.0.0.1 --server.port=8518 "
        + "--browser.gatherUsageStats=false",
      url: `${neutralBaseURL}/_stcore/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
  projects: [
    {
      name: "mobile-touch",
      use: {
        viewport: { width: 390, height: 844 },
        hasTouch: true,
        isMobile: true,
      },
    },
    {
      name: "desktop-mouse",
      use: {
        viewport: { width: 1440, height: 1000 },
        hasTouch: false,
        isMobile: false,
      },
    },
  ],
});
