"""Evaluate a running OCR service against saved synthetic images and expectations."""

import argparse
import json
import time
import urllib.request
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="layout_corpus.py results.json")
    parser.add_argument("--url", default="http://127.0.0.1:8001/ocr")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for case in json.loads(args.manifest.read_text()):
        data = (args.manifest.parent / (case["case"] + ".png")).read_bytes()
        boundary = uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
            'filename="card.png"\r\nContent-Type: image/png\r\n\r\n'
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(
            args.url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        start = time.monotonic()
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
        row = dict(
            case=case["case"], expected=case["expected"], **result,
            seconds=round(time.monotonic() - start, 3),
        )
        row["exact"] = sum(row["fields"].get(k) == v for k, v in row["expected"].items())
        results.append(row)
        print(row["case"], row["exact"], row["seconds"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("TOTAL", sum(row["exact"] for row in results), "/",
          sum(len(row["expected"]) for row in results))


if __name__ == "__main__":
    main()
