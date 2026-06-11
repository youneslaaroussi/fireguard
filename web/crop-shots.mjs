import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1720, height: 960 } });
await page.goto("http://127.0.0.1:5180", { waitUntil: "networkidle" });
await page.waitForTimeout(5000);
await page.locator(".appHeader").screenshot({ path: "/tmp/fg-header.png" });
await page.locator(".tlBar").screenshot({ path: "/tmp/fg-tlbar.png" });
await page.locator(".agentBar").screenshot({ path: "/tmp/fg-agentbar.png" });
await browser.close();
