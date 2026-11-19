# GPU Scene Workers

## Integration choice

SceneForge exports one prompt per planned shot. The reference integration is **ComfyUI + ComfyUI-Distributed**:

- The ComfyUI master owns the workflow and queue.
- Remote ComfyUI instances provide GPU execution.
- A DistributedCollector with load_balance enabled lets each submitted scene job go to an available participant.
- The SceneForge submitter posts each shot to POST /distributed/queue.

This is job-level distribution. It does **not** merge worker VRAM or make one individual scene render faster. Its benefit is that several independent shots can render on different GPUs.

## What you need on the compute side

1. A ComfyUI master with the ComfyUI-Distributed custom node installed.
2. At least one reachable ComfyUI worker with the same required workflow nodes and model files.
3. A valid **ComfyUI API-format prompt JSON** exported from your configured workflow. The normal visual workflow JSON is not the same format.
4. The API-format graph must contain a DistributedCollector whose inputs.load_balance is true.
5. Note the worker IDs from GET /distributed/config, or let SceneForge's submitter discover enabled IDs with --workers auto.

The upstream project provides a [WAN 2.2 14B T2V distributed workflow](https://github.com/robertvoy/ComfyUI-Distributed/blob/main/workflows/distributed-wan-2.2_14b_t2v.json). It is a reference starting point, not proof that every worker can load the model. Models and custom nodes must match across participating workers.

## Submit a manifest

1. In SceneForge, create the story scenes and press **Export scene jobs**.
2. On a machine/session that can reach your ComfyUI master, save the exported file as scene-jobs.json.
3. Export your configured ComfyUI workflow in **API format** as workflow-api.json.
4. Identify the node ID and input name for the positive text prompt. Use the exact field name from your API workflow.
5. Run the standard-library submitter:

    python tools/submit_scene_jobs.py --manifest scene-jobs.json --workflow workflow-api.json --master-url https://YOUR-PRIVATE-COMFYUI-MASTER --workers auto --prompt-node 6 --prompt-input text --checkpoint sceneforge-queue-checkpoint.json

Replace the prompt node ID with the value from your actual ComfyUI workflow. Use --workers auto to take enabled IDs from the master's config, or pass a comma-separated list. To list IDs and names first, run: python tools/submit_scene_jobs.py --master-url https://YOUR-PRIVATE-COMFYUI-MASTER --list-workers.

### Map model settings

The manifest includes requestedOutput width/height, frameRate, and frameCount. The submitter can write them into chosen workflow nodes. Example:

    python tools/submit_scene_jobs.py --manifest scene-jobs.json --workflow workflow-api.json --master-url https://YOUR-PRIVATE-COMFYUI-MASTER --workers 1,2 --prompt-node 6 --prompt-input text --seed-node 57 --seed-input seed --frames-node 41 --frames-input length --width-node 41 --width-input width --height-node 41 --height-input height

Node IDs and input names above are examples only. Look them up in your own API-format workflow. Not every model workflow uses the same frame, width, and height controls. If you omit the optional mapping flags, the workflow keeps its own defaults. A frame count of duration × 16 + 1 is requested for these starter jobs; the actual model workflow remains responsible for its valid frame constraints.

### Dry run and status

Validate the local manifest and API workflow without sending jobs:

    python tools/submit_scene_jobs.py --manifest scene-jobs.json --workflow workflow-api.json --prompt-node 6 --dry-run

Inspect acknowledged jobs using ComfyUI history:

    python tools/submit_scene_jobs.py --master-url https://YOUR-PRIVATE-COMFYUI-MASTER --checkpoint sceneforge-queue-checkpoint.json --status

A successful queue acknowledgement only means the master accepted a prompt ID. It does not prove a video was rendered or saved. The status command reads normal ComfyUI history; a job not shown there may still be queued or may have aged out of history.

The checkpoint stores each SceneForge job ID, ComfyUI prompt ID, worker count, and submission time. It skips jobs already acknowledged. The ComfyUI API does not promise end-to-end idempotency: after a network failure between server acceptance and client acknowledgement, inspect the queue/history before retrying to avoid duplicate generation.

For an authenticated reverse proxy, set SCENEFORGE_PROXY_TOKEN in the submitter environment. This header is for the proxy only; it is **not** native ComfyUI authentication.

## Critical security warning

The upstream /distributed/queue API is experimental and does not add authentication or authorization. Never expose a raw ComfyUI master port to the public internet. Use a private network/VPN or an HTTPS reverse proxy with strong authentication and access restrictions. Do not put tokens in the browser app, Git repository, scene manifest, or shared workflow file.

## Model and hardware guidance

- Start with short test shots and low resolution before planning a long film.
- A 10-minute film made from 5-second shots needs about 120 completed shots; 8-second shots need about 75; 10-second shots need about 60. The manifest shows planned duration so a short script does not silently pretend to cover ten minutes.
- WanGP advertises selected configurations using as little as 6 GB VRAM. This is model/profile-specific and is not a guarantee for Wan 2.2 14B, 720p, or every video model. WanGP is a separate runtime, not automatically a ComfyUI-Distributed worker.
- Use each worker's tested model, VRAM, RAM, resolution, and frame-count limits to choose a compatible workflow. A lower-VRAM worker may need a different model or quantized workflow.
- Free GPU availability is not a production SLA. Kaggle documents weekly GPU quotas and session limits; Colab says its free resources, GPU availability, and usage limits vary. Respect the provider's policies and stop when a session ends; do not build persistent tunnels to evade limits.

## Current boundary

The SceneForge web app exports a job manifest. The CLI bridge can submit it to a reachable ComfyUI-Distributed master when a valid API workflow and worker IDs are supplied. The repository does not provision GPU machines, download multi-gigabyte model weights, or keep a free GPU runtime alive. No worker is considered online until the ComfyUI master reports it reachable.
