from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Sequence

from legal_assistant.config.bootstrap import build_agent_container


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ask the citation-grounded Persian legal research agent."
    )
    parser.add_argument("question", nargs="+", help="Persian legal question")
    parser.add_argument("--thread-id", default=None)
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the complete structured response as JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    question = " ".join(args.question)
    with build_agent_container() as container:
        answer = container.agent.ask(question, thread_id=args.thread_id)
    if args.as_json:
        print(json.dumps(asdict(answer), ensure_ascii=False, indent=2))
    else:
        print(answer.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
