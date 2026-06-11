// Usage: node scripts/screenshot.mjs <outfile> [mode] [waitMs]
// mode: "idle" (default) just loads the page; "replay" clicks REPLAY and
// captures mid-replay + threat states.
import { chromium } from "playwright";

const out = process.argv[2] ?? "/tmp/fireguard.png";
const mode = process.argv[3] ?? "idle";
const waitMs = Number(process.argv[4] ?? 6000);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1720, height: 960 } });
const errors = [];
page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
page.on("pageerror", (err) => errors.push(String(err)));

await page.goto("http://127.0.0.1:5180", { waitUntil: "networkidle" });
await page.waitForTimeout(waitMs);

if (mode === "replay") {
  const btn = page.locator(".tlReplayBtn").first();
  if (await btn.count()) {
    await btn.click();
    const base = out.replace(/\.png$/, "");
    // capture progressive states
    await page.waitForTimeout(8000);
    await page.screenshot({ path: `${base}-1-loading.png` });
    await page.waitForTimeout(15000);
    await page.screenshot({ path: `${base}-2-mid.png` });
    await page.waitForTimeout(25000);
    await page.screenshot({ path: `${base}-3-late.png` });
  }
}

await page.screenshot({ path: out });
if (errors.length) {
  console.log("CONSOLE ERRORS:");
  for (const e of errors.slice(0, 12)) console.log(" -", e.slice(0, 300));
} else {
  console.log("no console errors");
}
await browser.close();
