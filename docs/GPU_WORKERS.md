# GPU Scene Workers

## Integration choice

SceneForge exports one prompt per planned shot. The current reference integration is **ComfyUI + ComfyUI-Distributed**:

- The ComfyUI master owns the workflow and the queue.
- Remote ComfyUI instances are the GPU workers.
- A DistributedCollector with load_balance=true lets each submitted scene job go to an available participant.
- SceneForge's submitter posts each planned scene to POST /distributed/queue.

This is job-level distribution. It does **not** merge worker VRAM, and it does not make one individual scene render faster. The benefit is that several independent shots can be rendered on different GPUs.

## What you need on the compute side

1. A ComfyUI master with the ComfyUI-Distributed custom node installed.
2. At least one reachable ComfyUI worker with the same required workflow nodes and model files.
3. A valid **ComfyUI API-format prompt JSON** exported from your configured workflow. The normal visual workflow JSON is not the same format.
4. The API-format graph must contain a DistributedCollector whose inputs.load_balance is true.
5. Note the worker IDs from GET /distributed/config.

The upstream project provides a [WAN 2.2 14B T2V distributed workflow](https://github.com/robertvoy/ComfyUI-Distributed/blob/main/workflows/distributed-wan-2.2_14b_t2v.json). It is a starting point, not proof that every worker can load that model. Models and custom nodes must match across participating workers.

## Submit a manifest

1. In SceneForge, create the story scenes and press **Export scene jobs**.
2. On a machine/session that can reach your ComfyUI master, save the exported file as scene-jobs.json.
3. Export your configured ComfyUI workflow in **API format** as workflow-api.json.
4. Identify the node ID and input name for the positive text prompt. Usually the input name is text, but use the exact name in your workflow.
5. Run the standard-library submitter:

    python tools/submit_scene_jobs.py --manifest scene-jobs.json --workflow workflow-api.json --master-url https://YOUR-PRIVATE-COMFYUI-MASTER --workers 1,2 --prompt-node 6 --prompt-input text --checkpoint sceneforge-queue-checkpoint.json

Replace the example worker IDs and prompt node ID with values from your actual ComfyUI configuration. If your workflow uses a different seed node/input, add --seed-node NODE_ID --seed-input INPUT_NAME.

The script validates that the API workflow contains a load-balanced DistributedCollector, then queues each scene separately. It records acknowledged job IDs in the checkpoint file so reruns skip them. The ComfyUI API does not guarantee idempotency: if a network failure occurs after the server accepted a job but before the client received the response, check the ComfyUI queue/history before retrying that one job.

For an authenticated reverse proxy, set SCENEFORGE_PROXY_TOKEN in the submitter environment. This header is for the proxy only; it is **not** native ComfyUI authentication.

## Critical security warning

The upstream /distributed/queue API is experimental and does not add authentication or authorization. Never expose a raw ComfyUI master port to the public internet. Use a private network/VPN or an HTTPS reverse proxy with strong authentication and access restrictions. Do not put tokens in the browser app, Git repository, scene manifest, or shared workflow file.

## Model and hardware guidance

- Start with short test shots and low resolution before planning a long film.
- A 10-minute film made from 5-second shots needs about 120 successful shots; with 8-second shots about 75; with 10-second shots about 60. The manifest shows planned duration so a short script does not quietly pretend to cover ten minutes.
- WanGP advertises some workflows on as little as 6 GB VRAM, but this is model/profile-specific and not a guarantee for Wan 2.2 14B, 720p, or every video model. WanGP is a separate app/engine; it is not automatically a ComfyUI-Distributed worker.
- Use each worker's tested model, VRAM, RAM, resolution and frame-count limits to choose a compatible workflow. A lower-VRAM worker may need a different model or quantized workflow.

## Current boundary

The SceneForge web app can create the manifest. The CLI bridge can submit it to a reachable ComfyUI-Distributed master when a valid API workflow and worker IDs are supplied. The repository does not provision GPU machines, download multi-gigabyte model weights, or keep a free GPU runtime alive. No worker is considered online until the ComfyUI master reports it reachable.
