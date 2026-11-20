"""Write a Blender caption only for an explicitly reviewed rounded estimate."""
import argparse
import json
from pathlib import Path


def approved_caption(report, value, reviewer):
    if not reviewer.strip() or report.get("baseline", {}).get("rounded") != value:
        raise ValueError("Reviewer and matching rounded estimate are required")
    return {
        "caption": f"About {value:,} residents within a {report.get('minutes', 10):g}-minute walk",
        "source": f"{report['period']} ACS, area-weighted estimate",
        "approved_by": reviewer.strip(),
        "value": value,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--value", type=int, required=True)
    parser.add_argument("--approved-by", required=True)
    args = parser.parse_args()
    report = json.loads(args.review.read_text(encoding="utf-8"))
    result = approved_caption(report, args.value, args.approved_by)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
