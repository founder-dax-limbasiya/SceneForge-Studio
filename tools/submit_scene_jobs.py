#!/usr/bin/env python3
"""Submit SceneForge scene jobs to a ComfyUI-Distributed master.

Uses only the Python standard library. The queue API is experimental and does
not provide authentication itself. Connect only through a trusted private
network or an authenticated HTTPS reverse proxy.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return value


def extract_prompt(workflow_doc: dict[str, Any]) -> dict[str, Any]:
    prompt = workflow_doc.get("prompt", workflow_doc)
    if not isinstance(prompt, dict) or not prompt:
        raise ValueError("Workflow must be a non-empty ComfyUI API-format prompt object.")
    return prompt


def validate_workflow(prompt: dict[str, Any]) -> None:
    collectors = [
        node for node in prompt.values()
        if isinstance(node, dict) and node.get("class_type") == "DistributedCollector"
    ]
    if not collectors:
        raise ValueError(
            "API workflow has no DistributedCollector node. Use a ComfyUI-Distributed workflow."
        )
    if not any(
        isinstance(node.get("inputs"), dict)
        and node["inputs"].get("load_balance") is True
        for node in collectors
    ):
        raise ValueError(
            "No DistributedCollector has inputs.load_balance=true. "
            "Enable load balancing so each scene job can go to the next free participant."
        )


def set_node_input(
    prompt: dict[str, Any],
    node_id: str,
    input_name: str,
    value: Any,
) -> None:
    node = prompt.get(str(node_id))
    if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
        raise ValueError(f"Node {node_id!r} or its inputs were not found.")
    if input_name not in node["inputs"]:
        raise ValueError(f"Input {input_name!r} does not exist on node {node_id!r}.")
    node["inputs"][input_name] = value


def apply_job(
    prompt_template: dict[str, Any],
    job: dict[str, Any],
    prompt_node_id: str,
    prompt_input: str,
    seed_node_id: str | None = None,
    seed_input: str = "seed",
    frames_node_id: str | None = None,
    frames_input: str = "length",
    width_node_id: str | None = None,
    width_input: str = "width",
    height_node_id: str | None = None,
    height_input: str = "height",
    negative_node_id: str | None = None,
    negative_input: str = "text",
) -> dict[str, Any]:
    prompt = copy.deepcopy(prompt_template)
    text = job.get("prompt")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Job {job.get('jobId', '?')} has an empty prompt.")
    set_node_input(prompt, prompt_node_id, prompt_input, text.strip())

    if negative_node_id is not None:
        negative_text = job.get("negativePrompt", "")
        if not isinstance(negative_text, str):
            raise ValueError(f"Job {job.get('jobId', '?')} has an invalid negativePrompt.")
        set_node_input(prompt, negative_node_id, negative_input, negative_text.strip())

    if seed_node_id is not None:
        seed = job.get("seed")
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            raise ValueError(f"Job {job.get('jobId', '?')} has an invalid seed.")
        set_node_input(prompt, seed_node_id, seed_input, seed)

    if frames_node_id is not None:
        frame_count = job.get("frameCount")
        if not isinstance(frame_count, int) or isinstance(frame_count, bool) or frame_count < 1:
            duration = job.get("durationSeconds")
            fps = job.get("frameRate", 16)
            if not isinstance(duration, (int, float)) or not isinstance(fps, (int, float)):
                raise ValueError(f"Job {job.get('jobId', '?')} needs a valid frameCount or durationSeconds/frameRate.")
            frame_count = int(round(duration * fps)) + 1
        set_node_input(prompt, frames_node_id, frames_input, frame_count)

    requested = job.get("requestedOutput", {})
    if not isinstance(requested, dict):
        raise ValueError(f"Job {job.get('jobId', '?')} has invalid requestedOutput.")
    if width_node_id is not None:
        width = requested.get("width")
        if not isinstance(width, int) or isinstance(width, bool) or width < 1:
            raise ValueError(f"Job {job.get('jobId', '?')} has invalid requestedOutput.width.")
        set_node_input(prompt, width_node_id, width_input, width)
    if height_node_id is not None:
        height = requested.get("height")
        if not isinstance(height, int) or isinstance(height, bool) or height < 1:
            raise ValueError(f"Job {job.get('jobId', '?')} has invalid requestedOutput.height.")
        set_node_input(prompt, height_node_id, height_input, height)
    return prompt


def enabled_worker_ids(config: dict[str, Any]) -> list[str]:
    workers = config.get("workers", [])
    if not isinstance(workers, list):
        raise ValueError("ComfyUI /distributed/config did not return a workers array.")
    ids = []
    for worker in workers:
        if not isinstance(worker, dict) or worker.get("enabled") is not True:
            continue
        worker_id = worker.get("id")
        if worker_id is not None and str(worker_id).strip():
            ids.append(str(worker_id).strip())
    return ids


def format_worker_list(config: dict[str, Any]) -> list[str]:
    workers = config.get("workers", [])
    if not isinstance(workers, list):
        raise ValueError("ComfyUI /distributed/config did not return a workers array.")
    lines = []
    for worker in workers:
        if not isinstance(worker, dict):
            continue
        worker_id = str(worker.get("id", "?"))
        name = str(worker.get("name") or "Unnamed worker")
        worker_type = str(worker.get("type") or "local")
        enabled = worker.get("enabled") is True
        lines.append(f"{worker_id}\t{name}\t{worker_type}\t{'enabled' if enabled else 'disabled'}")
    return lines


def safe_master_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Master URL must start with https:// (or http://localhost for local testing).")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and parsed.hostname not in local_hosts:
        raise ValueError("Refusing an insecure non-local HTTP master URL. Use HTTPS.")
    if parsed.username or parsed.password:
        raise ValueError("Do not embed credentials in the master URL. Use SCENEFORGE_PROXY_TOKEN.")
    return value.rstrip("/")


def read_checkpoint(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    data = load_json(path)
    modern = data.get("queued_jobs")
    if isinstance(modern, dict):
        result: dict[str, dict[str, Any]] = {}
        for job_id, record in modern.items():
            if isinstance(job_id, str) and isinstance(record, dict):
                result[job_id] = record
        return result
    # Backward compatibility with early checkpoints containing only IDs.
    legacy = data.get("queued_job_ids", [])
    if not isinstance(legacy, list) or not all(isinstance(x, str) for x in legacy):
        raise ValueError("Checkpoint queued_jobs must be an object or queued_job_ids an array.")
    return {job_id: {"prompt_id": None, "legacy": True} for job_id in legacy}


def save_checkpoint(path: Path | None, queued: dict[str, dict[str, Any]]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    payload = {"version": 2, "updated_at": time.time(), "queued_jobs": queued}
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def request_json(
    url: str,
    timeout: int,
    proxy_token: str | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    method = "GET"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
        method = "POST"
    if proxy_token:
        headers["Authorization"] = f"Bearer {proxy_token}"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Master returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not reach ComfyUI master: {exc}") from exc
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Master returned non-JSON response: {body[:500]}") from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"Master returned an unexpected JSON response: {result}")
    return result


def print_status(master_url: str, queued: dict[str, dict[str, Any]], timeout: int, token: str | None) -> int:
    if not queued:
        print("No acknowledged jobs in the checkpoint yet.")
        return 0
    counts = {"success": 0, "error": 0, "pending": 0, "unknown": 0}
    for job_id, record in queued.items():
        prompt_id = record.get("prompt_id")
        if not prompt_id:
            print(f"{job_id}: acknowledged previously, but no prompt_id was stored; inspect ComfyUI manually.")
            counts["unknown"] += 1
            continue
        url = master_url + "/history/" + quote(str(prompt_id), safe="")
        try:
            history = request_json(url, timeout, token)
        except Exception as exc:
            print(f"{job_id}: status lookup failed: {exc}")
            counts["unknown"] += 1
            continue
        entry = history.get(str(prompt_id))
        if not isinstance(entry, dict):
            print(f"{job_id}: not present in ComfyUI history yet (may still be queued or history may have rolled over).")
            counts["pending"] += 1
            continue
        status = entry.get("status", {})
        if not isinstance(status, dict):
            status = {}
        status_text = str(status.get("status_str", "unknown")).lower()
        completed = status.get("completed") is True
        if completed and status_text in {"success", "completed"}:
            label = "success"
        elif status_text in {"error", "failed"}:
            label = "error"
        else:
            label = "pending"
        outputs = entry.get("outputs", {})
        output_nodes = len(outputs) if isinstance(outputs, dict) else 0
        print(f"{job_id}: {label} · prompt_id={prompt_id} · output_nodes={output_nodes}")
        counts[label] += 1
    print("Summary: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Queue SceneForge prompts as independent ComfyUI-Distributed jobs."
    )
    parser.add_argument("--manifest", type=Path, help="SceneForge scene-jobs.json")
    parser.add_argument("--workflow", type=Path, help="ComfyUI API-format workflow JSON")
    parser.add_argument("--master-url", default=os.getenv("SCENEFORGE_COMFY_MASTER_URL"),
                        help="Trusted ComfyUI master URL (or SCENEFORGE_COMFY_MASTER_URL)")
    parser.add_argument("--workers", default=os.getenv("SCENEFORGE_WORKER_IDS", ""),
                        help="Comma-separated ComfyUI-Distributed worker IDs")
    parser.add_argument("--prompt-node", help="API workflow node ID containing the text prompt")
    parser.add_argument("--prompt-input", default="text", help="Prompt input name (default: text)")
    parser.add_argument("--negative-node", help="Optional API workflow negative-prompt node ID")
    parser.add_argument("--negative-input", default="text", help="Negative prompt input name (default: text)")
    parser.add_argument("--seed-node", help="Optional API workflow seed node ID")
    parser.add_argument("--seed-input", default="seed", help="Seed input name (default: seed)")
    parser.add_argument("--frames-node", help="Optional node ID for the per-shot frame-count input")
    parser.add_argument("--frames-input", default="length", help="Frame-count input name (default: length)")
    parser.add_argument("--width-node", help="Optional node ID for the output width input")
    parser.add_argument("--width-input", default="width", help="Width input name (default: width)")
    parser.add_argument("--height-node", help="Optional node ID for the output height input")
    parser.add_argument("--height-input", default="height", help="Height input name (default: height)")
    parser.add_argument("--checkpoint", type=Path, default=Path("sceneforge-queue-checkpoint.json"),
                        help="Local checkpoint file containing scene job IDs and ComfyUI prompt IDs")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print prompts without queueing")
    parser.add_argument("--status", action="store_true", help="Read ComfyUI history for acknowledged jobs")
    parser.add_argument("--list-workers", action="store_true", help="List configured ComfyUI-Distributed worker IDs")
    parser.add_argument("--pause", type=float, default=0.25, help="Delay between submissions in seconds")
    args = parser.parse_args()

    try:
        if not args.master_url:
            if args.dry_run:
                master_url = ""
            else:
                raise ValueError("Provide --master-url or SCENEFORGE_COMFY_MASTER_URL.")
        else:
            master_url = safe_master_url(args.master_url)

        token = os.getenv("SCENEFORGE_PROXY_TOKEN")
        queued = read_checkpoint(args.checkpoint)

        if args.status or args.list_workers:
            if not master_url:
                raise ValueError("--status and --list-workers require --master-url.")
            config = request_json(master_url + "/distributed/config", args.timeout, token)
            if args.list_workers:
                lines = format_worker_list(config)
                print("ID\\tNAME\\tTYPE\\tSTATE")
                print("\\n".join(lines) if lines else "No workers are configured.")
                print("Use --workers auto to submit to all enabled workers.")
                return 0
            return print_status(master_url, queued, args.timeout, token)

        if args.manifest is None or args.workflow is None or args.prompt_node is None:
            raise ValueError("--manifest, --workflow, and --prompt-node are required when submitting jobs.")

        manifest = load_json(args.manifest)
        workflow_doc = load_json(args.workflow)
        prompt_template = extract_prompt(workflow_doc)
        validate_workflow(prompt_template)
        jobs = manifest.get("jobs")
        if not isinstance(jobs, list) or not jobs:
            raise ValueError("Manifest jobs must be a non-empty array.")
        if args.workers.strip().lower() == "auto":
            if not master_url:
                raise ValueError("--workers auto requires --master-url.")
            config = request_json(master_url + "/distributed/config", args.timeout, token)
            workers = enabled_worker_ids(config)
        else:
            workers = [item.strip() for item in args.workers.split(",") if item.strip()]
        if not args.dry_run and not workers:
            raise ValueError("No worker IDs selected. Configure workers in ComfyUI or pass --workers ID1,ID2.")
        if not args.dry_run and not master_url:
            raise ValueError("Provide --master-url or SCENEFORGE_COMFY_MASTER_URL.")

        endpoint = master_url + "/distributed/queue"
        print(f"Project: {manifest.get('project', {}).get('title', 'SceneForge project')}")
        print(f"Jobs in manifest: {len(jobs)} | already acknowledged: {len(queued)}")
        if args.dry_run:
            for job in jobs:
                prepared = apply_job(
                    prompt_template, job, args.prompt_node, args.prompt_input,
                    args.seed_node, args.seed_input, args.frames_node, args.frames_input,
                    args.width_node, args.width_input, args.height_node, args.height_input,
                    args.negative_node, args.negative_input,
                )
                text_value = prepared[str(args.prompt_node)]["inputs"][args.prompt_input]
                print(f"[DRY RUN] {job.get('jobId')}: {text_value[:100]}")
            return 0

        for index, job in enumerate(jobs, start=1):
            job_id = job.get("jobId")
            if not isinstance(job_id, str) or not job_id:
                raise ValueError(f"Job at index {index} is missing jobId.")
            if job_id in queued and queued[job_id].get("prompt_id"):
                print(f"[{index}/{len(jobs)}] skip {job_id} (already acknowledged)")
                continue

            prompt = apply_job(
                prompt_template, job, args.prompt_node, args.prompt_input,
                args.seed_node, args.seed_input, args.frames_node, args.frames_input,
                args.width_node, args.width_input, args.height_node, args.height_input,
                args.negative_node, args.negative_input,
            )
            payload = {
                "prompt": prompt,
                "client_id": "sceneforge-studio",
                "delegate_master": False,
                "enabled_worker_ids": workers,
                "auto_prepare": True,
                "trace_execution_id": job_id,
            }
            try:
                result = request_json(endpoint, args.timeout, token, payload)
            except Exception as exc:
                print(f"STOPPED at {job_id}: {exc}", file=sys.stderr)
                print("Do not blindly rerun without checking the ComfyUI master queue/history first.", file=sys.stderr)
                return 2

            prompt_id = result.get("prompt_id")
            if not isinstance(prompt_id, str) or not prompt_id:
                raise RuntimeError(f"Queue response for {job_id} did not include prompt_id: {result}")
            queued[job_id] = {
                "prompt_id": prompt_id,
                "worker_count": result.get("worker_count"),
                "submitted_at": time.time(),
            }
            save_checkpoint(args.checkpoint, queued)
            print(
                f"[{index}/{len(jobs)}] queued {job_id} -> prompt_id={prompt_id} "
                f"(workers={result.get('worker_count', 'unknown')})"
            )
            if args.pause > 0:
                time.sleep(args.pause)

        print(f"Done. Acknowledged {len(queued)} job(s). Use --status to inspect ComfyUI history.")
        return 0
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
