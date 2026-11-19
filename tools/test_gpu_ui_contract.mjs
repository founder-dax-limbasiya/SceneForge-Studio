import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(root, "index.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/);
assert.ok(script, "index.html must contain the application script");
new Function(script[1]);

const requiredIds = [
  "gpuMasterUrl", "gpuProxyToken", "gpuConnectBtn", "gpuWorkers",
  "gpuWorkflowFile", "gpuPromptNode", "gpuPromptInput", "gpuQueueBtn",
  "gpuStatusBtn", "gpuJobList",
];
for (const id of requiredIds) {
  assert.ok(html.includes('id="' + id + '"'), "Missing GPU connection UI element: " + id);
}

const requiredFeatures = [
  "'/distributed/config'",
  "'/distributed/queue'",
  "'/history/'+encodeURIComponent(job.prompt_id)",
  "enabled_worker_ids",
  "trace_execution_id",
  "load_balance===true",
  "credentials:'omit'",
  "mode:'cors'",
  "gpuJobs=readGpuJobs()",
  "status='unknown'",
];
for (const feature of requiredFeatures) {
  assert.ok(script[1].includes(feature), "Missing direct GPU integration feature: " + feature);
}

assert.ok(
  html.includes("Never expose raw ComfyUI port 8188") ||
  html.includes("Never expose a raw ComfyUI master port"),
  "The UI must warn against exposing ComfyUI directly to the public internet",
);
assert.ok(
  !/localStorage\.setItem\([^\n]*gpuProxyToken/.test(script[1]),
  "Proxy bearer token must never be written to local storage",
);
console.log("GPU browser integration contract: OK");
