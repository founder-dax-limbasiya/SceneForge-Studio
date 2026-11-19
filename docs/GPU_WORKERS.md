# GPU Scene Workers

## Browser-based connection (recommended for SceneForge Studio)

The Studio now has a **Connect your GPU render engine** panel directly below the scene-job planner. The browser can connect to a ComfyUI-Distributed master without running the Python submitter.

1. Start a ComfyUI master with ComfyUI-Distributed installed.
2. Configure at least one reachable worker. All participating workers need the same workflow custom nodes and model files.
3. Put the master behind a private network/VPN or an authenticated HTTPS reverse proxy. The upstream distributed queue API does not add authentication itself.
4. Enable browser CORS on the master/proxy. The ComfyUI-Distributed docs call out `--enable-cors-header` for browser/remote workflows.
5. In SceneForge, enter the secure master URL and (only if your proxy requires it) its bearer token. Press **Test connection & find workers**. The token is held in this page's memory only; it is not written to local storage.
6. Upload the **ComfyUI API-format JSON** workflow. This is not the normal workflow canvas JSON.
7. Set the positive prompt node ID and input name. Open Advanced workflow mapping to optionally map negative prompt, seed, frame count, width, and height node inputs.
8. Press **Queue GPU scenes**. SceneForge sends each shot as a separate POST to `/distributed/queue`, using enabled worker IDs from the master config. Confirm the queue action before submission.
9. Use **Check render status** to read the accepted prompt IDs from ComfyUI's normal `/history/{prompt_id}` endpoint.

The browser panel uses the ComfyUI API directly. The master URL and bearer token are not sent to Vercel. The optional bearer token is for an authenticated reverse proxy, not native ComfyUI authentication. The browser sends requests cross-origin, so a correct CORS policy is required. If connection fails, check the master URL, HTTPS certificate, proxy access rules, OPTIONS preflight, and CORS headers.

### API workflow requirements

- Export a ComfyUI **API-format** prompt graph. The file must be a JSON object of nodes with `class_type` and `inputs` (or an object with that graph under `prompt`).
- Include a `DistributedCollector` node with `inputs.load_balance=true`.
- The positive prompt node and input must match the graph exactly (for example, node `6`, input `text`; these IDs are not universal).
- Optional mapping fields are only changed when a node ID is supplied. A wrong node ID/input stops the run before any request is sent.
- Shot frame count is initially requested as `seconds × 16 + 1`. Each model workflow has its own valid frame and resolution constraints; check the loaded model workflow before running.

The master config's enabled workers are **configured/enabled**, not guaranteed online. The master performs the actual reachability/dispatch checks when each scene is queued. A queue acknowledgement with `prompt_id` only means ComfyUI accepted the prompt; a `worker_count` of zero does not prove a remote worker rendered the scene. Check history and the worker logs for actual results.

### Ambiguous submission and duplicate prevention

SceneForge saves accepted ComfyUI prompt IDs in this browser's local storage. A network failure may happen after the master accepted a job but before the browser received its response. Such a shot is marked **unknown**, not automatically retried. Inspect the master's queue/history before pressing Queue again; a second run is intentionally treated as a new generation run and can create duplicate compute.

## Python submitter (optional)

For a headless render machine, the repo also includes a standard-library script:

    python tools/submit_scene_jobs.py --manifest scene-jobs.json --workflow workflow-api.json --master-url https://YOUR-PRIVATE-COMFYUI-MASTER --workers auto --prompt-node 6 --prompt-input text

The helper supports optional negative prompt, seed, frames, width, and height node mapping. Use `--list-workers`, `--dry-run`, and `--status` as described in the command help.

## Integration architecture and limitations

- The ComfyUI master owns the workflow and queue; remote ComfyUI instances supply GPU execution.
- SceneForge submits one independent prompt per shot. A load-balanced DistributedCollector allows the master to dispatch each workflow to an available participant.
- This is job-level distribution. It does **not** merge VRAM or make one individual scene render faster. It allows several independent shots to be rendered across multiple GPUs.
- The upstream queue API is experimental, has no built-in authentication/authorization, and has no separate durable SceneForge job-status API. SceneForge polls normal ComfyUI history.
- No worker is considered live until the master can reach it. The app never infers live GPU status merely from a worker being enabled in config.

## Model and hardware guidance

- Start with short test shots and low resolution before planning a long film.
- A 10-minute film made from 5-second shots needs about 120 completed shots; 8-second shots need about 75; 10-second shots need about 60.
- WanGP advertises selected configurations using as little as 6 GB VRAM. This is model/profile-specific and is not a guarantee for Wan 2.2 14B, 720p, or every video model. WanGP is a separate runtime, not automatically a ComfyUI-Distributed worker.
- Use each worker's tested model, VRAM, RAM, resolution, and frame-count limits to choose a compatible workflow.
- Free GPU availability is not a production SLA. Respect provider session and usage limits. Do not use persistent tunnels to evade provider restrictions.
