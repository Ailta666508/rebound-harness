/**
 * End-to-end inspector smoke against a running, disposable local workspace.
 * Start `rebound serve --data /tmp/rebound-smoke --port 8787` first.
 * Run `pnpm smoke`; BASE_URL also supports the Vite proxy on port 5173.
 * The browser uses an isolated context, never an existing user profile.
 */
import assert from "node:assert/strict";
import { mkdir, readFile, readdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const baseURL = process.env.BASE_URL ?? "http://127.0.0.1:8787";
const repository = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const output = resolve(
  process.env.SCREENSHOT_DIR ??
    resolve(dirname(fileURLToPath(import.meta.url)), "../../docs/assets"),
);
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.BROWSER_EXECUTABLE || undefined,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("console", (message) => {
  if (message.type() === "error") errors.push(message.text());
});
page.setDefaultTimeout(15000);

async function createExperiment(scenarioName, steps) {
  await page
    .getByRole("button", { name: "New experiment", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("radio", { name: new RegExp(scenarioName) })
    .check();
  await page
    .getByRole("spinbutton", { name: "Task length" })
    .fill(String(steps));
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/demo") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create run", exact: true }).click();
  const response = await responsePromise;
  assert.equal(response.status(), 201, await response.text());
  const run = await response.json();
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  await page.getByRole("heading", { name: run.title, exact: true }).waitFor();
  return run;
}

async function assertDesktopLayout() {
  const layout = await page.evaluate(() => {
    const bounds = (selector) => {
      const rect = document.querySelector(selector).getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom, height: rect.height };
    };
    return {
      sidebar: bounds(".sidebar"),
      main: bounds("main"),
      trace: bounds(".trace-panel"),
      detail: bounds(".detail-panel"),
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: {
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
      },
    };
  });
  assert.deepEqual(layout.viewport, { width: 1440, height: 900 });
  assert.equal(
    layout.document.width,
    layout.viewport.width,
    "Desktop width must match viewport",
  );
  assert.equal(
    layout.document.height,
    layout.viewport.height,
    "Desktop height must match viewport",
  );
  assert.ok(
    Math.abs(layout.sidebar.bottom - 900) < 1,
    "Sidebar must end at viewport bottom",
  );
  assert.ok(
    Math.abs(layout.main.bottom - 900) < 1,
    "Main must end at viewport bottom",
  );
  assert.ok(
    Math.abs(layout.trace.top - layout.detail.top) < 1,
    "Inspector panel tops must align",
  );
  assert.ok(
    Math.abs(layout.trace.bottom - layout.detail.bottom) < 1,
    "Inspector panel bottoms must align",
  );
  assert.ok(
    Math.abs(layout.trace.height - layout.detail.height) < 1,
    "Inspector panels must have equal heights",
  );
}

try {
  await mkdir(output, { recursive: true });
  await page.goto(baseURL);
  await page
    .getByRole("heading", { name: "Recovery inspector", exact: true })
    .waitFor();

  const uncertain = await createExperiment("Unavailable evidence", 8);
  assert.equal(uncertain.status, "needs_review");
  await page
    .getByText("This run needs a confirmed outcome.", { exact: true })
    .waitFor();
  const resumedResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/api/runs/${uncertain.id}/resume`),
  );
  await page.getByRole("button", { name: "Resume run", exact: true }).click();
  const resumed = await (await resumedResponse).json();
  assert.equal(resumed.status, "needs_review");
  assert.equal(
    resumed.metrics.effects,
    uncertain.metrics.effects,
    "Probe-only resume must not repeat uncertain writes",
  );
  assert.ok(resumed.metrics.probes > uncertain.metrics.probes);
  await page.getByRole("tab", { name: "Operations", exact: true }).click();
  await assertDesktopLayout();
  await page.screenshot({
    path: resolve(output, "inspector-review.png"),
    fullPage: false,
  });
  await page
    .getByRole("button", { name: "Confirm result", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Confirm an operation result" })
    .waitFor();
  await page.getByRole("button", { name: "Close dialog", exact: true }).click();

  const recovered = await createExperiment("Delayed visibility", 12);
  assert.equal(recovered.status, "completed");
  assert.equal(recovered.metrics.effects, 12);
  assert.equal(recovered.metrics.duplicate_effects, 0);
  assert.equal(recovered.metadata.policy, "evidence");
  assert.equal(recovered.metadata.simulated, true);
  await page.getByText("Duplicate effects", { exact: true }).waitFor();
  await page
    .getByText("Provider oracle · simulated runs only", { exact: true })
    .waitFor();
  assert.ok(
    recovered.events.some(
      (event) =>
        event.kind === "recovery.probe" && event.payload.status === "absent",
    ),
  );
  assert.ok(
    recovered.events.some(
      (event) =>
        event.kind === "recovery.decision" && event.payload.action === "reuse",
    ),
  );
  await page.getByLabel("Filter events").selectOption("recovery");
  await page
    .getByRole("button")
    .filter({ hasText: "recovery · decision" })
    .last()
    .click();
  await page.getByText("Recorded evidence", { exact: true }).waitFor();
  assert.equal(
    await page
      .getByRole("button", { name: "Run complete", exact: true })
      .isDisabled(),
    true,
  );

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export trace", exact: true }).click();
  const downloaded = await downloadPromise;
  const trace = JSON.parse(await readFile(await downloaded.path(), "utf8"));
  assert.equal(trace.id, recovered.id);
  assert.equal(trace.metrics.duplicate_effects, 0);
  assert.equal(trace.events.length, recovered.events.length);

  await page.getByLabel("Filter events").selectOption("all");
  await page
    .getByRole("button")
    .filter({ hasText: "recovery · decision" })
    .last()
    .click();
  await assertDesktopLayout();
  assert.equal(
    await page
      .locator(".table-scroll")
      .evaluate((node) => node.scrollHeight > node.clientHeight),
    true,
    "Long trace must scroll inside its panel",
  );
  assert.equal(
    await page
      .locator(".detail-scroll")
      .evaluate((node) => node.scrollHeight > node.clientHeight),
    true,
    "Evidence payload must scroll inside its panel",
  );
  await page.screenshot({
    path: resolve(output, "inspector.png"),
    fullPage: false,
  });
  await page.getByRole("tab", { name: "Operations", exact: true }).click();
  await assertDesktopLayout();
  await page.screenshot({
    path: resolve(output, "inspector-operations.png"),
    fullPage: false,
  });
  await page.getByRole("tab", { name: "Execution trace", exact: true }).click();
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
    false,
    "Desktop has horizontal overflow",
  );

  await page.setViewportSize({ width: 1440, height: 520 });
  assert.equal(
    await page.evaluate(
      () =>
        document.documentElement.scrollHeight > window.innerHeight &&
        getComputedStyle(document.body).overflow !== "hidden",
    ),
    true,
    "Short desktop must allow access below the viewport",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("heading", { name: recovered.title, exact: true })
    .waitFor();
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
    false,
    "Mobile has horizontal overflow",
  );
  await page.screenshot({
    path: resolve(output, "inspector-mobile.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "New experiment", exact: true })
    .click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("button", { name: "Close dialog", exact: true }).click();
  assert.deepEqual(errors, [], "Browser console/runtime errors");

  const svgPreviews = [];
  if (process.env.QA_SCREENSHOT_DIR) {
    const qaOutput = resolve(process.env.QA_SCREENSHOT_DIR);
    await mkdir(qaOutput, { recursive: true });
    const assets = resolve(repository, "docs/assets");
    const svgFiles = (await readdir(assets))
      .filter((name) => name.endsWith(".svg"))
      .map((name) => resolve(assets, name));
    svgFiles.push(
      resolve(repository, "benchmarks/reference/recovery-results.svg"),
    );
    const svgPage = await context.newPage();
    await svgPage.setViewportSize({ width: 1600, height: 1200 });
    for (const svgFile of svgFiles) {
      // Render authored SVG as an image: scripts inside SVG cannot execute and
      // the image retains its native dimensions without a screenshot crop.
      const source = (await readFile(svgFile)).toString("base64");
      await svgPage.setContent(
        `<html><body style="margin:0;background:white"><img alt="Diagram preview" src="data:image/svg+xml;base64,${source}"></body></html>`,
      );
      await svgPage.locator("img").evaluate((img) => img.decode());
      const preview = resolve(qaOutput, `${basename(svgFile, ".svg")}.png`);
      await svgPage.locator("img").screenshot({ path: preview });
      svgPreviews.push(preview);
    }
    await svgPage.close();
  }
  process.stdout.write(
    `${JSON.stringify({ status: "passed", baseURL, scenarios: ["unavailable", "delayed_visibility"], run: recovered.id, checks: ["create", "resume without duplicate effects", "manual resolution dialog", "evidence inspection", "JSON download", "desktop/mobile overflow", "mobile dialog", "browser errors"], screenshots: output, svgPreviews }, null, 2)}\n`,
  );
} catch (error) {
  await page
    .screenshot({ path: resolve(output, "smoke-failure.png"), fullPage: true })
    .catch(() => {});
  throw error;
} finally {
  await context.close();
  await browser.close();
}
