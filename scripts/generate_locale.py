#!/usr/bin/env python3
"""
Offline locale generation script — uses OpenRouter to draft translations.

NEVER called at runtime or in production. Admin tool only.

Usage:
    python scripts/generate_locale.py --locale fr --source locales/en.json
"""

import argparse
import json
import os
import sys

import httpx


def main():
    parser = argparse.ArgumentParser(description="Generate a locale draft via OpenRouter")
    parser.add_argument("--locale", required=True, help="Target locale code (e.g., fr, ar)")
    parser.add_argument("--source", default="locales/en.json", help="Source translation file")
    parser.add_argument("--output", help="Output path (default: locales/{locale}.json)")
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    with open(args.source, encoding="utf-8") as f:
        source = json.load(f)

    prompt = (
        f"Translate the following JSON UI strings from English to locale '{args.locale}'. "
        f"Preserve JSON structure exactly. Return only valid JSON.\n\n"
        f"```json\n{json.dumps(source, indent=2, ensure_ascii=False)}\n```"
    )

    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "anthropic/claude-sonnet-4",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

    # Extract JSON from response (handle markdown code blocks)
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]

    translated = json.loads(content.strip())

    output_path = args.output or f"locales/{args.locale}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(translated, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Draft translation written to {output_path}")
    print("IMPORTANT: Review and edit before committing!")


if __name__ == "__main__":
    main()
