# SceneForge Studio

A mobile-friendly, browser-based film assembly studio. This starter focuses on scene planning, a silent visual master, and a separate non-destructive post-production pass.

## Current functionality

- Turn script paragraphs into editable scenes.
- Apply shared visual style, character-continuity notes, and a negative prompt to every shot.
- Auto-save the text draft and render settings locally in the browser; imported media files are session-only.
- Add local image assets to scenes.
- Render a silent visual master in the browser.
- Upload voiceover and background music independently.
- Toggle voiceover, music, and subtitles independently for the final pass.
- Burn simple scene-timed captions into the final video.
- Export a WebM file from the browser.

## Important limitations

This repository does **not** yet include text-to-video inference, GPU worker pooling, automatic voice generation, Whisper speech recognition, or word-level subtitle alignment. The UI reports GPU workers as disconnected until a real worker service is integrated.

The visual master renderer uses browser Canvas + MediaRecorder and records in real time. Keep the tab open and the device awake. Long renders may fail on mobile devices due to browser memory, battery, thermal, or background-tab limitations. WebM is the supported export format in this starter.

Files are processed locally in the active browser session. The app does not upload user media to a server. Keep copies of important source files and exported masters.

## Run and deploy

This is a static site. Open `index.html` in a modern browser, or serve the folder with any static web server. Connect this Git repository to Vercel with the project root set to the repository root.

## Planned architecture

1. **Studio frontend** — project/script/scene editor and local preview.
2. **Control plane** — durable projects, scene jobs, worker heartbeats, leases, and retry state.
3. **GPU workers** — authorized workers that advertise supported model, VRAM, resolution, and current capacity.
4. **Scene scheduler** — dispatch independent scene jobs to compatible workers; unrelated internet GPUs do not share one VRAM pool.
5. **Assembly** — combine completed scene clips with voice, music, and subtitles after generation.

A worker should only be marked available after it passes a real health check and reports its capabilities. Free GPU services have quotas and provider restrictions; there is no promise of unlimited or always-on free compute.


## GPU scene-job handoff

The Studio can export a SceneForge scene-job manifest. The standard-library submitter in tools/submit_scene_jobs.py converts each scene prompt into a separate ComfyUI-Distributed queue request, maps optional frame/size/seed settings into workflow nodes, can auto-discover enabled workers, and saves ComfyUI prompt IDs for status checks. See docs/GPU_WORKERS.md for setup, workflow mapping, queueing, status, and security.

The queue bridge requires a reachable ComfyUI-Distributed master, worker IDs, and a ComfyUI API-format workflow with a load-balanced DistributedCollector. It does not provision a GPU or make an unauthenticated public ComfyUI endpoint safe.

## Tests

Run the Python submitter tests with:

    python -m unittest discover -s tools -p "test_*.py" -v

List GPU worker IDs:

    python tools/submit_scene_jobs.py --master-url https://YOUR-PRIVATE-COMFYUI-MASTER --list-workers

Queue to all enabled workers with `--workers auto`; inspect acknowledgements with `--status`.

Check the browser JavaScript syntax with:

    node tools/check_frontend.mjs
