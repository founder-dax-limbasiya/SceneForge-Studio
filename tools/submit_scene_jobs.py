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
from urllib.parse import urlparse
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


def apply_job(
    prompt_template: dict[str, Any],
    job: dict[str, Any],
    prompt_node_id: str,
    prompt_input: str,
    seed_node_id: str | None = None,
    seed_input: str = "seed",
) -> dict[str, Any]:
    prompt = copy.deepcopy(prompt_template)
    node = prompt.get(prompt_node_id)
    if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
        raise ValueError(f"Prompt node {prompt_node_id!r} or its inputs were not found.")
    if prompt_input not in node["inputs"]:
        raise ValueError(
            f"Input {prompt_input!r} does not exist on prompt node {prompt_node_id!r}."
        )
    text = job.get("prompt")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Job {job.get('jobId', '?')} has an empty prompt.")
    node["inputs"][prompt_input] = text.strip()

    if seed_node_id is not None:
        seed_node = prompt.get(seed_node_id)
        if not isinstance(seed_node, dict) or not isinstance(seed_node.get("inputs"), dict):
            raise ValueError(f"Seed node {seed_node_id!r} or its inputs were not found.")
        if seed_input not in seed_node["inputs"]:
            raise ValueError(f"Seed input {seed_input!r} not found on node {seed_node_id!r}.")
        seed = job.get("seed")
        if not isinstance(seed, int) or seed < 0:
            raise ValueError(f"Job {job.get('jobId', '?')} has an invalid seed.")
        seed_node["inputs"][seed_input] = seed
    return prompt


def safe_master_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Master URL must start with https:// (or http://localhost for local testing).")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and parsed.hostname not in local_hosts:
        raise ValueError("Refusing an insecure non-local HTTP master URL. Use HTTPS.")
    return value.rstrip("/")


def read_checkpoint(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    data = load_json(path)
    values = data.get("queued_job_ids", [])
    if not isinstance(values, list) or not all(isinstance(x, str) for x in values):
        raise ValueError("Checkpoint queued_job_ids must be an array of strings.")
    return set(values)


def save_checkpoint(path: Path | None, queued: set[str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps({"queued_job_ids": sorted(queued)}, indent=2), encoding="utf-8")
    temp.replace(path)


def post_job(
    endpoint: str,
    payload: dict[str, Any],
    timeout: int,
    proxy_token: str | None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if proxy_token:
        # This token is for an authenticated reverse proxy, not native ComfyUI auth.
        headers["Authorization"] = f"Bearer {proxy_token}"
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
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
    if not isinstance(result, dict) or not result.get("prompt_id"):
        raise RuntimeError(f"Queue response did not include prompt_id: {result}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Queue each SceneForge prompt as an independent ComfyUI-Distributed job."
    )
    parser.add_argument("--manifest", type=Path, required=True, help="SceneForge scene-jobs.json")
    parser.add_argument("--workflow", type=Path, required=True, help="ComfyUI API-format workflow JSON")
    parser.add_argument("--master-url", default=os.getenv("SCENEFORGE_COMFY_MASTER_URL"),
                        help="Trusted ComfyUI master URL (or SCENEFORGE_COMFY_MASTER_URL)")
    parser.add_argument("--workers", default=os.getenv("SCENEFORGE_WORKER_IDS", ""),
                        help="Comma-separated ComfyUI-Distributed worker IDs")
    parser.add_argument("--prompt-node", required=True, help="API workflow node ID containing the text prompt")
    parser.add_argument("--prompt-input", default="text", help="Prompt input name (default: text)")
    parser.add_argument("--seed-node", help="Optional API workflow seed node ID")
    parser.add_argument("--seed-input", default="seed", help="Seed input name (default: seed)")
    parser.add_argument("--checkpoint", type=Path, default=Path("sceneforge-queue-checkpoint.json"),
                        help="Local checkpoint file to avoid re-queueing acknowledged job IDs")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print prompts without queueing")
    parser.add_argument("--pause", type=float, default=0.25, help="Delay between submissions in seconds")
    args = parser.parse_args()

    try:
        manifest = load_json(args.manifest)
        workflow_doc = load_json(args.workflow)
        prompt_template = extract_prompt(workflow_doc)
        validate_workflow(prompt_template)
        jobs = manifest.get("jobs")
        if not isinstance(jobs, list) or not jobs:
            raise ValueError("Manifest jobs must be a non-empty array.")
        workers = [item.strip() for item in args.workers.split(",") if item.strip()]
        if not args.dry_run and not workers:
            raise ValueError("Provide at least one worker ID with --workers or SCENEFORGE_WORKER_IDS.")
        if not args.dry_run and not args.master_url:
            raise ValueError("Provide --master-url or SCENEFORGE_COMFY_MASTER_URL.")
        master_url = safe_master_url(args.master_url) if args.master_url else ""
        endpoint = master_url + "/distributed/queue"
        token = os.getenv("SCENEFORGE_PROXY_TOKEN")
        queued = read_checkpoint(args.checkpoint)

        print(f"Project: {manifest.get('project', {}).get('title', 'SceneForge project')}")
        print(f"Jobs in manifest: {len(jobs)} | already acknowledged: {len(queued)}")
        if args.dry_run:
            for job in jobs:
                prepared = apply_job(prompt_template, job, args.prompt_node, args.prompt_input,
                                     args.seed_node, args.seed_input)
                print(f"[DRY RUN] {job.get('jobId')}: {prepared[args.prompt_node]['inputs'][args.prompt_input][:100]}")
            return 0

        for index, job in enumerate(jobs, start=1):
            job_id = job.get("jobId")
            if not isinstance(job_id, str) or not job_id:
                raise ValueError(f"Job at index {index} is missing jobId.")
            if job_id in queued:
                print(f"[{index}/{len(jobs)}] skip {job_id} (already acknowledged)")
                continue

            prompt = apply_job(prompt_template, job, args.prompt_node, args.prompt_input,
                               args.seed_node, args.seed_input)
            payload = {
                "prompt": prompt,
                "client_id": "sceneforge-studio",
                "delegate_master": False,
                "enabled_worker_ids": workers,
                "auto_prepare": True,
                "trace_execution_id": job_id,
            }
            try:
                result = post_job(endpoint, payload, args.timeout, token)
            except Exception as exc:
                print(f"STOPPED at {job_id}: {exc}", file=sys.stderr)
                print("Do not blindly rerun without checking the ComfyUI master queue/history first.", file=sys.stderr)
                return 2

            queued.add(job_id)
            save_checkpoint(args.checkpoint, queued)
            print(
                f"[{index}/{len(jobs)}] queued {job_id} -> prompt_id={result['prompt_id']} "
                f"(workers={result.get('worker_count', 'unknown')})"
            )
            if args.pause > 0:
                time.sleep(args.pause)

        print(f"Done. Acknowledged {len(queued)} job(s). Check ComfyUI history for render results.")
        return 0
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
