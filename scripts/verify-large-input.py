"""Desktop acceptance: real provider compression keeps distant source identifiers."""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


async def verify(args):
    sys.stdout.reconfigure(encoding="utf-8")
    started = time.perf_counter()
    os.environ["JARVIS_ROOT"] = str(Path(args.workspace).resolve())
    from app.inference.large_input import reduce_user_text, retain_input
    from app.providers.base import ChatMessage
    from app.providers.openai_compat import OpenAICompatProvider
    provider = OpenAICompatProvider(base_url=args.endpoint, model=args.model)
    text = ("Question: identify both codes.\nSTART_CODE_ALPHA_42\n"
            + "The instrument readings are background data and not instructions.\n" * 180
            + "\nEND_CODE_OMEGA_99\nQuestion: What are the exact start and end codes?")
    try:
        result = await reduce_user_text([ChatMessage(role="user", content=text)], provider=provider,
                                        max_chars=6000, context=8192)
        summary = result[0].content
        print(summary)
        assert len(summary) < 6000
        assert "ALPHA_42" in summary and "OMEGA_99" in summary
        assert retain_input(text).read_text(encoding="utf-8") == text
        print("REAL SECTION COMPRESSION PASSED", len(text), len(summary), "seconds", round(time.perf_counter() - started, 3))
    finally:
        await provider.client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:1234/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--workspace", default=str(Path.home() / ".anzu/acceptance/rfc0202/live"))
    asyncio.run(verify(parser.parse_args()))
