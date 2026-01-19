import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.logging import configure_logging
from config.settings import Settings
from core.pipeline import DomainPipeline
from core.prompt_parser import PromptParser
from providers.pagespeed_client import PageSpeedClient
from providers.serper_client import SerperClient
from providers.webtech_client import WebTechClient


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the prompt-driven domain discovery pipeline."
    )
    parser.add_argument("prompt", nargs="?", help="Prompt describing the target site.")
    parser.add_argument(
        "--prompt-file",
        type=Path,
        help="Path to a file containing the prompt.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt for input when no prompt is provided.",
    )
    parser.add_argument("--serper-key", help="Serper API key.")
    parser.add_argument("--pagespeed-key", help="PageSpeed API key.")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to .env file.",
    )
    parser.add_argument("--max-results", type=int, default=None, help="Max results to return.")
    parser.add_argument("--matched-only", action="store_true", help="Return only matched domains.")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    parser.add_argument(
        "--pretty",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pretty-print JSON output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON output to a file instead of stdout.",
    )
    return parser


def resolve_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return args.prompt_file.read_text(encoding="utf-8").strip()
    if args.prompt:
        return args.prompt.strip()
    if args.interactive:
        return input("Prompt: ").strip()
    raise SystemExit("Prompt is required. Provide a prompt or use --interactive.")


def apply_env_overrides(args: argparse.Namespace) -> None:
    if args.serper_key:
        os.environ["SERPER_API_KEY"] = args.serper_key.strip()
    if args.pagespeed_key:
        os.environ["PAGESPEED_API_KEY"] = args.pagespeed_key.strip()


def build_pipeline(settings: Settings) -> DomainPipeline:
    serper = SerperClient(api_key=settings.serper_api_key, endpoint=settings.serper_endpoint)
    pagespeed = PageSpeedClient(api_key=settings.pagespeed_api_key)
    webtech = WebTechClient()
    return DomainPipeline(
        settings=settings,
        serper_client=serper,
        pagespeed_client=pagespeed,
        webtech_client=webtech,
    )


def serialize_results(results, matched_only: bool) -> list[dict]:
    filtered = [item for item in results if item.matched or not matched_only]
    return [item.to_dict() for item in filtered]


def write_output(payload: list[dict], output: Optional[Path], pretty: bool) -> None:
    if pretty:
        text = json.dumps(payload, indent=2, sort_keys=True)
    else:
        text = json.dumps(payload, separators=(",", ":"), sort_keys=False)
    if output:
        output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.env_file and args.env_file.exists():
        load_dotenv(args.env_file)
    else:
        load_dotenv()
    apply_env_overrides(args)

    configure_logging(args.log_level)

    prompt = resolve_prompt(args)
    settings = Settings.from_env()

    if not settings.serper_api_key:
        raise SystemExit("SERPER_API_KEY is required to run searches.")

    spec = PromptParser().parse(prompt)
    if spec.metrics.needs_pagespeed() and not settings.pagespeed_api_key:
        raise SystemExit("PAGESPEED_API_KEY is required for prompts with metrics.")

    pipeline = build_pipeline(settings)
    results = pipeline.run(prompt=prompt, max_results=args.max_results)

    payload = serialize_results(results, matched_only=args.matched_only)
    write_output(payload, output=args.output, pretty=args.pretty)


if __name__ == "__main__":
    main()
