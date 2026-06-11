// Clicks REPLAY, then polls the event counter and screenshots key moments.
import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1720, height: 960 } });
const errors = [];
page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
page.on("pageerror", (err) => errors.push(String(err)));

await page.goto("http://127.0.0.1:5180", { waitUntil: "networkidle" });
await page.waitForTimeout(6000);
// Optional source/window adjustment for uncached chunks: ADJUST=1 node replay-watch.mjs
if (process.env.ADJUST) {
  const modis = page.locator(".sbRow--toggle", { hasText: "MODIS" });
  if (await modis.count()) await modis.click();
  const endInput = page.locator(".sbField", { hasText: "END" }).locator("input");
  await endInput.fill("2024-07-21");
  await page.waitForTimeout(400);
}
await page.locator(".tlReplayBtn").click();

let lastCount = "";
let threatSeen = false;
const t0 = Date.now();

// arm the zoom-enhance watcher up-front; fires the moment the overlay mounts
const enhanceShot = page
  .waitForSelector(".enhanceOverlay--on", { timeout: 0 })
  .then(async () => {
    await page.waitForTimeout(1500);
    await page.screenshot({ path: "/tmp/fg-threat-enhance.png" });
    console.log("enhance overlay captured");
  })
  .catch(() => {});
for (let i = 0; i < 60; i++) {
  await page.waitForTimeout(3000);
  const counter = await page.locator(".etCounter").textContent().catch(() => "");
  const status = await page.locator(".tlStatus").textContent().catch(() => "");
  const threat = await page.locator(".threatPanel").count();
  const secs = Math.round((Date.now() - t0) / 1000);
  if (counter !== lastCount || threat) {
    console.log(`[${secs}s] ${counter} | ${status?.slice(0, 80)} | threat=${threat}`);
    lastCount = counter;
  }
  if (threat && !threatSeen) {
    threatSeen = true;
    await page.screenshot({ path: "/tmp/fg-threat.png" });
  }
  if (status?.includes("Complete")) {
    console.log(`[${secs}s] COMPLETE`);
    break;
  }
}
await page.screenshot({ path: "/tmp/fg-final.png" });
await page.locator(".centerPanel").screenshot({ path: "/tmp/fg-center-final.png" });
await page.locator(".sidebar").screenshot({ path: "/tmp/fg-sidebar-final.png" });
// close the intelligence overlay to capture the post-run operational view
const closeBtn = page.locator('.agentOverlay button[title="Close"]');
if (await closeBtn.count()) {
  await closeBtn.click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: "/tmp/fg-postrun.png" });
}
if (errors.length) { console.log("ERRORS:"); errors.slice(0, 8).forEach((e) => console.log(" -", e.slice(0, 200))); }
await browser.close();
