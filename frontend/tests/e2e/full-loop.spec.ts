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

function consumeExpectedFailure(failures: string[], message: string) {
  const index = failures.findIndex((failure) => failure.includes(message));
  expect(index, `Expected browser failure containing: ${message}`).toBeGreaterThanOrEqual(0);
  failures.splice(index, 1);
}

test("landing reflows at 200 percent equivalent with reduced motion", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 720, height: 450 },
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Counterexamples for teacher review" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open the teacher lab" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Worked compiler example table" })).toBeVisible();
  await expect(page.locator('meta[name="viewport"]')).toHaveAttribute("content", /width=device-width/);
  await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content", "COGNISECT");
  await page.getByRole("link", { name: "Open the teacher lab" }).focus();
  expect(
    await page.getByRole("link", { name: "Open the teacher lab" }).evaluate(
      (element) => getComputedStyle(element).outlineColor,
    ),
  ).toBe("rgb(255, 200, 120)");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  const traceAnimationSeconds = await page.locator(".topology-traces line").first().evaluate(
    (element) => Number.parseFloat(getComputedStyle(element).animationDuration),
  );
  expect(traceAnimationSeconds).toBeLessThanOrEqual(0.001);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await context.close();
});

test("keyboard-only entry exposes honest slow-network timeout state", async ({ page }) => {
  await page.goto("/lab");

  for (let index = 0; index < 10; index += 1) {
    await page.keyboard.press("Tab");
    if ((await page.evaluate(() => document.activeElement?.id)) === "first-integer") break;
  }
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("first-integer");
  await page.keyboard.type("-3");
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("second-integer");
  await page.keyboard.type("5");
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("observed-work");
  await page.keyboard.type("-3 - 5 = 2");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Create and analyze" })).toBeFocused();

  await page.route("**/api/backend/v1/cases", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    await route.abort("timedout");
  }, { times: 1 });
  await page.keyboard.press("Enter");
  await expect(page.getByText("Creating and analyzing the case…")).toBeVisible();
  expect((await page.locator("body").textContent()) ?? "").not.toMatch(/\b\d{1,3}%\b/);
  await expect(
    page.getByText("The request could not reach the service. You can retry safely."),
  ).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("teacher to isolated learner to teacher report", async ({ page, browser }, testInfo) => {
  test.setTimeout(120_000);
  const browserFailures: string[] = [];
  captureBrowserFailures(page, browserFailures);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Counterexamples for teacher review" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);

  await page.getByRole("link", { name: "Open the teacher lab" }).click();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByLabel("First integer").focus();
  expect(
    await page.getByLabel("First integer").evaluate(
      (element) => getComputedStyle(element).outlineColor,
    ),
  ).toBe("rgb(10, 98, 94)");
  await page.getByLabel("First integer").fill("-3");
  await page.getByLabel("Second integer").fill("5");
  await page.getByLabel("Observed work").fill("-3 - 5 = 2");

  await page.route("**/api/backend/v1/cases", async (route) => {
    await route.abort("failed");
  }, { times: 1 });
  await page.getByRole("button", { name: "Create and analyze" }).click();
  await expect(page.getByText("The request could not reach the service. You can retry safely.")).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  consumeExpectedFailure(browserFailures, "net::ERR_FAILED");
  await page.unroute("**/api/backend/v1/cases");
  await page.getByRole("button", { name: "Retry exact command" }).click();
  await expect(page).toHaveURL(/\/case\/[0-9a-f-]+$/, { timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Compiled probe" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
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
  await expect(page.getByText("QR transport ready.")).toBeVisible();
  await expect(page.getByRole("img", { name: "QR code for the learner response link" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
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
  await expect(
    learnerPage.getByRole("heading", { level: 1, name: "Learner response" }),
  ).toBeVisible();
  const problemText = await learnerPage.locator(".math-problem").textContent();
  const values = problemText?.match(/-?\d+/g)?.map(Number);
  expect(values).toHaveLength(2);
  expect((await new AxeBuilder({ page: learnerPage }).analyze()).violations).toEqual([]);

  await learnerPage.route("**/api/backend/v1/respond/*", async (route) => {
    await route.fulfill({
      status: 410,
      contentType: "application/json",
      body: JSON.stringify({ detail: "expired test state" }),
    });
  }, { times: 1 });
  await learnerPage.getByLabel("Your signed integer").fill(String(values![0]! - values![1]!));
  await learnerPage.getByRole("button", { name: "Submit response" }).click();
  await expect(learnerPage.locator(".form-alert")).toHaveText("This learner link has expired.");
  expect((await new AxeBuilder({ page: learnerPage }).analyze()).violations).toEqual([]);
  consumeExpectedFailure(browserFailures, "status of 410");
  await learnerPage.unroute("**/api/backend/v1/respond/*");
  await learnerPage.reload();

  const duplicatePage = await learnerContext.newPage();
  captureBrowserFailures(duplicatePage, browserFailures);
  await duplicatePage.goto(learnerLink);
  await expect(duplicatePage.getByRole("heading", { name: "Learner response" })).toBeVisible();

  await learnerPage.getByLabel("Your signed integer").fill(String(values![0]! - values![1]!));
  await learnerPage.getByRole("button", { name: "Submit response" }).click();
  await expect(learnerPage.getByRole("heading", { name: "Response received" })).toBeVisible();
  expect((await new AxeBuilder({ page: learnerPage }).analyze()).violations).toEqual([]);

  await duplicatePage.getByLabel("Your signed integer").fill(String(values![0]! - values![1]!));
  await duplicatePage.getByRole("button", { name: "Submit response" }).click();
  await expect(duplicatePage.locator(".form-alert")).toHaveText(
    "A response has already been recorded for this learner link.",
  );
  expect((await new AxeBuilder({ page: duplicatePage }).analyze()).violations).toEqual([]);
  consumeExpectedFailure(browserFailures, "status of 409");
  await learnerContext.close();

  await expect(page.getByRole("link", { name: "Open teacher report" })).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("link", { name: "Open teacher report" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Teacher report" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Deterministic evidence" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByLabel("Teacher note").fill("Teacher-reviewed deterministic evidence.");
  await page.getByRole("button", { name: "Save review" }).click();
  await expect(page.locator('[data-state="APPROVED"]')).toBeVisible();
  await expect(page.getByText("approved", { exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
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

test("teacher abstention and unavailable learner states stay explicit", async ({ page }) => {
  await page.goto("/respond/not-a-real-token");
  await expect(page.getByRole("heading", { name: "Learner response unavailable" })).toBeVisible();
  await expect(page.locator('p[role="alert"]')).toHaveText(
    "This learner link is invalid or unavailable.",
  );
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.goto("/lab");
  await page.getByLabel("First integer").fill("-3");
  await page.getByLabel("Second integer").fill("5");
  await page.getByLabel("Observed work").fill("-3 - 5 = 2");
  await page.getByRole("button", { name: "Create and analyze" }).click();
  await expect(page.getByRole("button", { name: "Decline probe" })).toBeVisible({
    timeout: 20_000,
  });
  await page.getByRole("button", { name: "Decline probe" }).click();
  await expect(page.locator('[data-state="ABSTAINED"]')).toBeVisible();
  await expect(
    page.getByText(
      "The teacher declined this probe. The workflow abstained and no learner link was created.",
    ),
  ).toBeVisible();
  await expect(page.getByLabel("Learner response link")).toHaveCount(0);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
