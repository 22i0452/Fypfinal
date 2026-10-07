// Isolated browser check: every request uses synthetic data or local assets.
const { chromium } = require("playwright");
const fs = require("node:fs/promises");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "..");

(async () => {
  const output = path.join(root, "artifacts", "receptionist");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
  const results = [];
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      const context = await browser.newContext({ viewport });
      const page = await context.newPage();
      const errors = [];
      const writes = [];
      page.on("pageerror", error => errors.push(error.message));
      let patient = {
        _id: "PT-SYNTHETIC-BROWSER", patient_id: "PT-SYNTHETIC-BROWSER",
        name: "Synthetic Browser Patient", age: "30", phone_number: "03000000111",
        first_visit: "Yes", past_medical_history: "No synthetic history",
        current_complaint: "Synthetic complaint", updated_at: "2030-01-01T09:00:00+00:00",
      };
      await page.addInitScript(() => {
        window.WebSocket = class { static OPEN = 1; readyState = 0; close() {} send() {} };
      });
      await page.route("**/*", async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.hostname !== "medflow.test") return route.abort();
        if (url.pathname === "/workspace") return route.fulfill({
          contentType: "text/html", body: await fs.readFile(path.join(root, "scribe", "index.html"), "utf8"),
        });
        if (url.pathname === "/assets/ui.css" || url.pathname === "/assets/ui.js") return route.fulfill({
          contentType: url.pathname.endsWith(".css") ? "text/css" : "application/javascript",
          body: await fs.readFile(path.join(root, "scribe", url.pathname.slice(1)), "utf8"),
        });
        if (url.pathname.startsWith("/branding/")) return route.fulfill({
          contentType: "image/svg+xml", body: await fs.readFile(path.join(root, "consultation/assets/medflow-logo.svg"), "utf8"),
        });
        let body = {};
        if (url.pathname === "/api/auth/me") body = { full_name: "Synthetic Doctor", role: "DOCTOR", practitioner_id: "DOC-SYNTHETIC" };
        else if (url.pathname === "/api/patients") body = [patient];
        else if (url.pathname.endsWith("/doctor-queue")) body = { appointments: [] };
        else if (url.pathname === "/api/patients/" + patient.patient_id) body = patient;
        else if (url.pathname === "/api/patients/" + patient.patient_id + "/intake") {
          assert.equal(request.method(), "PATCH");
          const payload = request.postDataJSON();
          assert.equal(payload.confirmed, true);
          assert.equal(payload.expected_updated_at, patient.updated_at);
          writes.push(payload);
          patient = { ...patient, ...payload.changes, updated_at: "2030-01-01T10:00:00+00:00" };
          body = patient;
        } else if (url.pathname.includes("notes")) body = [];
        else if (url.pathname.includes("templates")) body = { templates: [] };
        return route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
      });
      await page.goto("http://medflow.test/workspace");
      await page.waitForFunction(() => document.getElementById("correctIntakeBtn") && typeof renderSelectedPatient === "function");
      await page.evaluate(data => {
        selectedPatient = data;
        activeEncounter = null;
        renderSelectedPatient();
        showVisitWorkspace();
      }, patient);
      await page.getByRole("button", { name: "Correct intake", exact: true }).click();
      const dialog = page.locator("#intakeCorrectionDialog");
      await dialog.waitFor({ state: "visible" });
      await page.locator("#intakeCorrectionField").selectOption("current_complaint");
      await page.locator("#intakeCorrectionValue").fill("مصنوعی شکایت کی درست تفصیل۔ Synthetic corrected complaint.");
      assert.equal(await page.locator("#intakeCorrectionConfirmed").isChecked(), false);
      const box = await dialog.boundingBox();
      assert(box.x >= 0 && box.x + box.width <= viewport.width + 1);
      assert(box.y >= 0 && box.y + box.height <= viewport.height + 1);
      await page.screenshot({ path: path.join(output, "doctor-correction-" + viewport.width + ".png") });
      await page.locator("#intakeCorrectionConfirmed").check();
      await page.getByRole("button", { name: "Save correction", exact: true }).click();
      await page.waitForFunction(() => !document.getElementById("intakeCorrectionDialog").open);
      assert.equal(writes.length, 1);
      assert.match(await page.locator("#intakeGrid").innerText(), /Synthetic corrected complaint/);
      assert.deepEqual(errors, []);
      results.push({ viewport, result: "PASS", writes: writes.length });
      await context.close();
    }
  } finally {
    await browser.close();
  }
  await fs.writeFile(path.join(output, "browser-results.json"), JSON.stringify({ synthetic_only: true, results }, null, 2));
  console.log(JSON.stringify(results));
})().catch(error => { console.error(error); process.exitCode = 1; });
