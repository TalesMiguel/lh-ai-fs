import sys
from pathlib import Path
from main import load_documents, run_pipeline

KNOWN_FLAWS = {
    "F1": {
        "type": "misquote",
        "keywords": ["privette", "never liable"],
        "description": "Privette v. Superior Court misquoted with 'never' — real holding narrower",
    },
    "F2": {
        "type": "fabricated_case",
        "keywords": ["whitmore", "delgado", "334 f. supp. 2d 1189"],
        "description": "Whitmore v. Delgado Scaffolding Co. — likely fabricated case",
    },
    "F3": {
        "type": "fabricated_cases",
        "keywords": ["kellerman", "pacific coast", "dixon", "okafor"],
        "description": "Kellerman, Dixon, Okafor citations — likely fabricated",
    },
    "F4": {
        "type": "fact_contradiction",
        "keywords": ["ppe", "not wearing", "hard hat"],
        "description": "MSJ claims Rivera was NOT wearing PPE; police report says he WAS",
    },
    "F5": {
        "type": "date_contradiction",
        "keywords": ["march 14", "march 12"],
        "description": "MSJ says March 14, 2021; documents say March 12, 2021",
    },
}


def normalize_text(text: str) -> str:
    return text.lower().strip()


def matches_keywords(text: str, keywords: list[str]) -> bool:
    normalized = normalize_text(text)
    return any(kw.lower() in normalized for kw in keywords)


def evaluate_pipeline(report_dict: dict) -> dict:
    report = report_dict["report"]

    matched_flaws = set()
    false_positives = 0

    for finding in report.get("citations", []):
        if finding["verdict"] in ("likely_fabricated", "does_not_support"):
            if finding["confidence"] > 0.5:
                reasoning = finding["reasoning"]
                case_name = finding["citation"]["case_name"]
                combined = f"{case_name} {reasoning}"

                found_match = False
                for flaw_id, flaw_info in KNOWN_FLAWS.items():
                    if matches_keywords(combined, flaw_info["keywords"]):
                        matched_flaws.add(flaw_id)
                        found_match = True

                if not found_match and finding["confidence"] > 0.9:
                    false_positives += 1

    for finding in report.get("facts", []):
        if finding["verdict"] == "contradicts":
            if finding["confidence"] > 0.5:
                claim = finding["claim"]
                source_quote = finding["source_quote"]
                combined = f"{claim} {source_quote}"

                found_match = False
                for flaw_id, flaw_info in KNOWN_FLAWS.items():
                    flaw_type = flaw_info["type"]
                    is_fact_type = flaw_type in ("fact_contradiction", "date_contradiction")

                    if is_fact_type and matches_keywords(combined, flaw_info["keywords"]):
                        matched_flaws.add(flaw_id)
                        found_match = True

                if not found_match and finding["confidence"] > 0.9:
                    false_positives += 1

    total_flags = sum(
        1
        for f in report.get("citations", [])
        if f["verdict"] in ("likely_fabricated", "does_not_support")
        and f["confidence"] > 0.5
    ) + sum(
        1 for f in report.get("facts", []) if f["verdict"] == "contradicts" and f["confidence"] > 0.5
    )

    high_confidence_citations = sum(
        1
        for f in report.get("citations", [])
        if f["verdict"] in ("likely_fabricated", "does_not_support")
        and f["confidence"] > 0.9
    )
    high_confidence_facts = sum(
        1
        for f in report.get("facts", [])
        if f["verdict"] == "contradicts"
        and f["confidence"] > 0.9
    )
    high_confidence_flags = high_confidence_citations + high_confidence_facts

    recall = len(matched_flaws) / len(KNOWN_FLAWS) if KNOWN_FLAWS else 0
    precision = len(matched_flaws) / total_flags if total_flags > 0 else 0
    hallucination_rate = false_positives / max(total_flags, 1)

    return {
        "matched_flaws": sorted(matched_flaws),
        "total_flags": total_flags,
        "false_positives": false_positives,
        "high_confidence_flags": high_confidence_flags,
        "recall": recall,
        "precision": precision,
        "hallucination_rate": hallucination_rate,
    }


def main():
    import json
    import argparse

    parser = argparse.ArgumentParser(description="BS Detector Evaluation Harness")
    parser.add_argument(
        "--cache",
        action="store_true",
        help="Use cached pipeline output (mock_api_call.json) instead of calling API"
    )
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("BS DETECTOR EVALUATION HARNESS")
    print("=" * 80 + "\n")

    cached_result_file = Path(__file__).parent / "mock_api_call.json"

    if args.cache:
        if not cached_result_file.exists():
            print(f"ERROR: --cache flag used but {cached_result_file.name} not found")
            sys.exit(1)
        print(f"Loading cached pipeline output from {cached_result_file.name}...")
        try:
            with open(cached_result_file) as f:
                report = json.load(f)
            print("Loaded from cache (no API calls made)")
        except Exception as e:
            print(f"ERROR: Failed to load cache: {e}")
            sys.exit(1)
    else:
        print("Running pipeline (this will use API quota)...")
        documents = load_documents()
        print(f"Loaded {len(documents)} documents:")
        for doc_name in sorted(documents.keys()):
            print(f"  - {doc_name}")

        print("\nRunning pipeline...")
        try:
            report = {"report": run_pipeline(documents).model_dump()}
            with open(cached_result_file, "w") as f:
                json.dump(report, f, indent=2)
            print(f"Cached result to {cached_result_file.name}")
        except Exception as e:
            print(f"ERROR: Pipeline failed: {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)

    print("Evaluating results...\n")
    metrics = evaluate_pipeline(report)

    print("KNOWN FLAWS:")
    for flaw_id, flaw_info in KNOWN_FLAWS.items():
        status = "✓ DETECTED" if flaw_id in metrics["matched_flaws"] else "✗ MISSED"
        print(f"  {flaw_id}: {flaw_info['description']}")
        print(f"       {status}\n")

    print("=" * 80)
    print("METRICS")
    print("=" * 80)
    print(f"Recall (caught known flaws):     {metrics['recall']:.1%} ({len(metrics['matched_flaws'])}/{len(KNOWN_FLAWS)})")
    print(f"Precision (no false flags):      {metrics['precision']:.1%}")
    print(
        f"Hallucination Rate (bad flags):  {metrics['hallucination_rate']:.1%} ({metrics['false_positives']} false positives)"
    )
    print(f"\nTotal flags raised: {metrics['total_flags']}")
    print(f"High-confidence flags (>0.9):   {metrics['high_confidence_flags']}")
    print("=" * 80 + "\n")

    if metrics["recall"] < 0.4:
        print("⚠️  WARNING: Low recall. Pipeline is missing many known issues.")
    if metrics["hallucination_rate"] > 0.3:
        print("⚠️  WARNING: High hallucination rate. Pipeline is flagging things that aren't real issues.")
    if metrics["precision"] > 0.5 and metrics["recall"] > 0.4:
        print("✓ Results look reasonable. Good balance of precision and recall.")

    print()


if __name__ == "__main__":
    main()
