import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { E2E_APP_URL } from "../../e2e-settings";

function captureBrowserFailures(page: Page, failures: string[]) {
  page.on("console", (message) => {
    if (message.type() === "error") failures.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => failures.push(`page: ${error.message}`));
  page.on("requestfailed", (request) => {
    const failure = request.failure()?.errorText ?? "request failed";
    if (failure.toLowerCase().includes("cors")) failures.push(`CORS: ${failure}`);
  });
}

test("teacher to isolated learner to teacher report", async ({ page, browser }, testInfo) => {
  const browserFailures: string[] = [];
  captureBrowserFailures(page, browserFailures);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Counterexamples for teacher review" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByRole("link", { name: "Open the teacher lab" }).click();
  await page.getByLabel("First integer").fill("-3");
  await page.getByLabel("Second integer").fill("5");
  await page.getByLabel("Observed work").fill("-3 - 5 = 2");
  await page.getByRole("button", { name: "Create and analyze" }).click();
  await expect(page).toHaveURL(/\/case\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: "Compiled probe" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  const compiledProbeBox = await page
    .getByRole("region", { name: "Compiled probe" })
    .boundingBox();
  const decisionBox = await page
    .getByRole("region", { name: "Teacher probe decision" })
    .boundingBox();
  expect(compiledProbeBox).not.toBeNull();
  expect(decisionBox).not.toBeNull();
  expect(compiledProbeBox!.y + compiledProbeBox!.height).toBeLessThanOrEqual(
    decisionBox!.y,
  );

  await page.getByRole("button", { name: "Approve probe" }).click();
  const firstLearnerLink = await page.getByLabel("Learner response link").inputValue();
  await page.reload();
  const learnerLink = await page.getByLabel("Learner response link").inputValue();
  expect(learnerLink).toBe(firstLearnerLink);
  expect(learnerLink.startsWith(`${E2E_APP_URL}/respond/`)).toBe(true);
  const learnerToken = learnerLink.split("/").at(-1)!;

  const learnerContext = await browser.newContext({
    viewport: testInfo.project.use.viewport ?? undefined,
  });
  const learnerPage = await learnerContext.newPage();
  captureBrowserFailures(learnerPage, browserFailures);
  const learnerNavigation = await learnerPage.goto(learnerLink);
  expect(learnerNavigation?.headers()["cache-control"]).toBe("no-store, private");
  expect(learnerNavigation?.headers()["referrer-policy"]).toBe("no-referrer");
  const problemText = await learnerPage.getByText(/^Solve:/).textContent();
  const values = problemText?.match(/-?\d+/g)?.map(Number);
  expect(values).toHaveLength(2);
  await learnerPage.getByLabel("Your signed integer").fill(String(values![0]! - values![1]!));
  await learnerPage.getByRole("button", { name: "Submit response" }).click();
  await expect(learnerPage.getByRole("heading", { name: "Response received" })).toBeVisible();
  expect((await new AxeBuilder({ page: learnerPage }).analyze()).violations).toEqual([]);
  await learnerContext.close();

  await expect(page.getByRole("link", { name: "Open teacher report" })).toBeVisible({
    timeout: 15_000,
  });
  await page.getByRole("link", { name: "Open teacher report" }).click();
  await expect(page.getByRole("heading", { name: "Deterministic evidence" })).toBeVisible();
  await page.getByLabel("Teacher note").fill("Teacher-reviewed deterministic evidence.");
  await page.getByRole("button", { name: "Save review" }).click();
  await expect(page.getByText("APPROVED", { exact: true })).toBeVisible();
  await expect(page.getByText("approved", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("approved", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Append-only workflow audit" })).toBeVisible();

  const workflowId = new URL(page.url()).pathname.split("/").at(-1)!;
  await page.goto(`/runtime?workflow_id=${workflowId}`);
  await expect(page.getByText("deterministic-test-fixture")).toBeVisible();
  await expect(page.getByText("test-fixture-request")).toBeVisible();
  expect((await page.locator("body").textContent()) ?? "").not.toContain(learnerToken);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(browserFailures).toEqual([]);
});
