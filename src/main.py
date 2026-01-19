import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.logging import configure_logging
from config.settings import Settings
from core.pipeline import DomainPipeline
from providers.pagespeed_client import PageSpeedClient
from providers.serper_client import SerperClient
from providers.webtech_client import WebTechClient


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find domains that match a prompt and verify they are the sites described."
    )
    parser.add_argument("prompt", help="Prompt describing the site type to find.")
    parser.add_argument("--max-results", type=int, default=None, help="Max results to return.")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    load_dotenv()
    settings = Settings.from_env()
    configure_logging(args.log_level)

    serper = SerperClient(api_key=settings.serper_api_key, endpoint=settings.serper_endpoint)
    pagespeed = PageSpeedClient(api_key=settings.pagespeed_api_key)
    webtech = WebTechClient()

    pipeline = DomainPipeline(
        settings=settings,
        serper_client=serper,
        pagespeed_client=pagespeed,
        webtech_client=webtech,
    )

    results = pipeline.run(prompt=args.prompt, max_results=args.max_results)
    print(json.dumps([r.to_dict() for r in results], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
