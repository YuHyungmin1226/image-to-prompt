from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import httpx
from fastapi.testclient import TestClient
from PIL import Image

import main


REQUIRED_SYSTEM_TERMS = [
    "do not refuse",
    "do not replace visible anatomy or clothing details with euphemisms",
    "anatomy",
    "clothing state",
    "skin exposure",
    "nudity",
    "partial nudity",
    "cleavage",
    "underwear",
    "lingerie",
    "transparent fabric",
    "exact clothing state",
]

REQUIRED_USER_TERMS = [
    "anatomy",
    "clothing state",
    "body shape",
    "body parts",
    "skin exposure",
    "nudity level",
    "garment type",
    "garment fit",
    "fabric transparency",
    "exact clothing coverage",
    "without euphemism",
    "never shorten the result just to be safe or generic",
]

MOCK_CASES = [
    {
        "name": "lingerie_visibility",
        "description": (
            "woman with long black hair, lace bra, open blazer, sheer blouse, visible cleavage, "
            "short skirt, garter straps, high heels, soft window light"
        ),
        "expect": ["lace bra", "sheer blouse", "visible cleavage", "garter straps"],
    },
    {
        "name": "shirtless_male",
        "description": (
            "muscular man, shirtless torso, visible abs, open leather jacket, low-rise jeans, "
            "chain necklace, stage lighting"
        ),
        "expect": ["shirtless torso", "visible abs", "open leather jacket", "low-rise jeans"],
    },
]


@dataclass
class AuditResult:
    name: str
    ok: bool
    details: list[str]


def print_result(result: AuditResult) -> None:
    status = "PASS" if result.ok else "FAIL"
    print(f"[{status}] {result.name}")
    for detail in result.details:
        print(f"  - {detail}")


def build_test_png_bytes() -> bytes:
    image = Image.new("RGB", (16, 16), color=(255, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def missing_terms(text: str, terms: Iterable[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term.lower() not in lowered]


def run_prompt_scan() -> AuditResult:
    details: list[str] = []
    failures: list[str] = []

    system_prompt = main.load_system_prompt()
    details.append(f"system prompt source: {main.SYSTEM_PROMPT_FILE or 'built-in default'}")

    missing_system = missing_terms(system_prompt, REQUIRED_SYSTEM_TERMS)
    if missing_system:
        failures.append("system prompt is missing terms: " + ", ".join(missing_system))

    for target in ("stable-diffusion", "midjourney", "dall-e"):
        _, user_prompt = main.build_prompt_request(target, "high")
        missing_user = missing_terms(user_prompt, REQUIRED_USER_TERMS)
        if missing_user:
            failures.append(f"{target} request is missing terms: " + ", ".join(missing_user))
        else:
            details.append(f"{target} request contains anatomy/clothing coverage guardrails")

    if not failures:
        details.append("prompt-building path explicitly asks for direct anatomy and clothing-state wording")
        return AuditResult("prompt-scan", True, details)

    details.extend(failures)
    return AuditResult("prompt-scan", False, details)


def run_mock_check() -> AuditResult:
    original_model = main.model
    original_status = main.model_status
    original_status_message = main.model_status_message

    class DummyModel:
        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.pending_description = ""

        def create_chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            return {"choices": [{"message": {"content": self.pending_description}}]}

    details: list[str] = []
    failures: list[str] = []
    dummy = DummyModel()
    main.model = dummy
    main.model_status = "ready"
    main.model_status_message = "audit"

    image_bytes = build_test_png_bytes()

    try:
        with TestClient(main.app) as client:
            for target in ("stable-diffusion", "midjourney", "dall-e"):
                for case in MOCK_CASES:
                    dummy.pending_description = case["description"]
                    response = client.post(
                        "/api/generate-prompt",
                        files={"image": ("audit.png", image_bytes, "image/png")},
                        data={"target": target, "style": "none", "detail": "high"},
                    )
                    if response.status_code != 200:
                        failures.append(f"{target}/{case['name']} returned HTTP {response.status_code}")
                        continue

                    payload = response.json()
                    combined = " ".join(
                        str(payload.get(field, "")) for field in ("description", "positive_prompt")
                    ).lower()
                    missing = [term for term in case["expect"] if term.lower() not in combined]
                    if missing:
                        failures.append(
                            f"{target}/{case['name']} dropped expected terms: {', '.join(missing)}"
                        )
                    else:
                        details.append(
                            f"{target}/{case['name']} preserved terms: {', '.join(case['expect'])}"
                        )

        if dummy.calls:
            max_tokens = dummy.calls[0].get("max_tokens")
            details.append(f"mock path used max_tokens={max_tokens}")
    finally:
        main.model = original_model
        main.model_status = original_status
        main.model_status_message = original_status_message

    if not failures:
        return AuditResult("mock-check", True, details)

    details.extend(failures)
    return AuditResult("mock-check", False, details)


def run_live_check(
    api_url: str,
    image_path: Path,
    target: str,
    style: str,
    detail_level: str,
    expect_terms: list[str],
    fields: list[str],
    timeout_seconds: float,
    dump_json: bool,
) -> AuditResult:
    details: list[str] = [f"api_url={api_url}", f"image={image_path}"]

    if not image_path.exists():
        return AuditResult("live-check", False, details + [f"image not found: {image_path}"])

    mime_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(
            api_url,
            data={"target": target, "style": style, "detail": detail_level},
            files={"image": (image_path.name, image_path.read_bytes(), mime_type)},
        )

    if response.status_code != 200:
        return AuditResult(
            "live-check",
            False,
            details + [f"HTTP {response.status_code}", response.text],
        )

    payload = response.json()
    combined = " ".join(str(payload.get(field, "")) for field in fields).lower()
    missing = [term for term in expect_terms if term.lower() not in combined]

    if dump_json:
        details.append(json.dumps(payload, ensure_ascii=False, indent=2))

    if missing:
        details.append("missing expected terms: " + ", ".join(missing))
        return AuditResult("live-check", False, details)

    details.append("all expected terms were found in fields: " + ", ".join(fields))
    return AuditResult("live-check", True, details)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit whether anatomy/clothing details survive the image-to-prompt pipeline."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("prompt-scan", help="Inspect the built system/user prompts for direct wording guardrails.")
    subparsers.add_parser("mock-check", help="Run the FastAPI path with a dummy model and verify post-processing preserves terms.")

    live_parser = subparsers.add_parser("live-check", help="Call a running server with a real image and expected terms.")
    live_parser.add_argument("--api-url", default="http://127.0.0.1:8088/api/generate-prompt")
    live_parser.add_argument("--image", required=True, type=Path)
    live_parser.add_argument(
        "--target",
        default="stable-diffusion",
        choices=("stable-diffusion", "midjourney", "dall-e"),
    )
    live_parser.add_argument(
        "--style",
        default="none",
        choices=("realistic", "anime", "fantasy", "sci-fi", "oil-painting", "concept-art", "none"),
    )
    live_parser.add_argument("--detail", default="high", choices=("low", "medium", "high"))
    live_parser.add_argument(
        "--field",
        dest="fields",
        action="append",
        default=["description", "positive_prompt"],
        help="Response field to scan for expected terms. Can be provided multiple times.",
    )
    live_parser.add_argument(
        "--expect",
        dest="expect_terms",
        action="append",
        required=True,
        help="Expected term that should survive in the chosen response fields. Can be provided multiple times.",
    )
    live_parser.add_argument("--timeout", type=float, default=120.0)
    live_parser.add_argument("--dump-json", action="store_true")

    subparsers.add_parser("all", help="Run prompt-scan and mock-check together.")
    return parser


def main_cli() -> int:
    args = build_parser().parse_args()

    results: list[AuditResult] = []
    if args.command == "prompt-scan":
        results.append(run_prompt_scan())
    elif args.command == "mock-check":
        results.append(run_mock_check())
    elif args.command == "live-check":
        results.append(
            run_live_check(
                api_url=args.api_url,
                image_path=args.image,
                target=args.target,
                style=args.style,
                detail_level=args.detail,
                expect_terms=args.expect_terms,
                fields=args.fields,
                timeout_seconds=args.timeout,
                dump_json=args.dump_json,
            )
        )
    else:
        results.append(run_prompt_scan())
        results.append(run_mock_check())

    for result in results:
        print_result(result)

    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main_cli())
