# SceneForge Studio — Architecture Roadmap

## Goal

Support long-form film projects (target length: 10 minutes) by splitting work into independently renderable scenes, then assembling results. Scene length, frame count, output resolution, and model choice must be constrained by each worker's actual capabilities.

## Core services

### 1. Studio frontend
Owns project editing, scene order, prompts and asset inputs, track switches, preview, and final export. The current app is a browser-only prototype and stores working media in memory/object URLs.

### 2. Control plane
A future backend should persist projects, scenes, generation parameters, job status, attempt count, lease owner and expiry, worker heartbeats and capabilities, and generated asset metadata/storage keys.

### 3. Worker registry
Each worker reports its authenticated owner, GPU model and free VRAM, supported models and precision modes, tested resolution and frame-count limits, heartbeat timestamp, current job, and provider/runtime restrictions. A stale heartbeat makes a worker ineligible for new jobs.

### 4. Scene scheduler
Dispatch one scene (or a small batch) to a compatible worker. Jobs need idempotency keys, bounded retries, timeouts, and expiring leases so a disconnected worker does not permanently lock a scene.

This is **job-level distribution**, not shared VRAM. Separate GPUs on unrelated machines cannot simply be pooled into one larger GPU. Model sharding is a separate, network-sensitive mode for compatible multi-GPU nodes.

### 5. Render and assembly pipeline
Generate scene clips, validate codec/duration/frame rate/dimensions, retry or mark failed scenes, assemble clips in storyboard order, apply voice/music/subtitles in a separate post-production stage, and retain the visual-only master for edits that should not regenerate scenes.

## Security requirements

- Workers authenticate with short-lived credentials.
- Never ship backend service-role keys or worker secrets to the browser.
- Validate project ownership on every API operation.
- Use signed URLs for media objects.
- Enforce upload size, codec, duration, and storage quotas.
- Treat prompts and generated media as untrusted inputs.
- Respect provider rules for free GPU sessions; do not create persistent tunnels or evade quotas.

## Current implementation boundary

The repository currently includes the browser studio, a local still-image scene compositor, and separate post-production track controls. No GPU job API or worker process is connected yet. The UI correctly reports **GPU workers not connected** until a real service is deployed and health-checked.
