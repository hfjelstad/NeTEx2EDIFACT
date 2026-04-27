# -*- coding: utf-8 -*-
"""
Raw SKDUPD ODI comparison without MERITS parser.
Compares ODI signatures in PRD context (service number).
"""

from __future__ import annotations

import argparse
import zipfile
from collections import Counter
from pathlib import Path
from typing import List, Tuple


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".r")]
            if not names:
                raise FileNotFoundError(f"No .r file in zip: {path}")
            return zf.read(names[0]).decode("utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace")


def _segments(text: str) -> List[str]:
    return [s.strip() for s in text.replace("\r", "").replace("\n", "").split("'") if s.strip()]


def _service_number(prd_segment: str) -> str:
    # PRD+1880:::37:::+1076**92  -> 1880
    # PRD+1880+FLB               -> 1880
    parts = prd_segment.split("+")
    if len(parts) < 2:
        return ""
    return parts[1].split(":")[0].strip()


def _extract_signatures(text: str) -> Tuple[Counter, Counter]:
    segs = _segments(text)
    service = ""
    exact = Counter()
    coarse = Counter()

    for seg in segs:
        if seg.startswith("PRD+"):
            service = _service_number(seg)
            continue

        if not seg.startswith("ODI+"):
            continue

        parts = seg.split("+")
        # parts[0]=ODI, parts[1]=range field, remaining are payload-like fields
        range_field = parts[1] if len(parts) > 1 else ""
        payload = tuple(parts[2:]) if len(parts) > 2 else tuple()

        exact[(service, range_field, *payload)] += 1
        coarse[(service, *payload)] += 1

    return exact, coarse


def _stats(ref: Counter, cand: Counter) -> Tuple[int, int, int, float]:
    ref_total = sum(ref.values())
    cand_total = sum(cand.values())
    overlap = sum((ref & cand).values())
    coverage = (100.0 * overlap / ref_total) if ref_total else 0.0
    return ref_total, cand_total, overlap, coverage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    ref_text = _read_text(Path(args.reference))
    cand_text = _read_text(Path(args.candidate))

    ref_exact, ref_coarse = _extract_signatures(ref_text)
    cand_exact, cand_coarse = _extract_signatures(cand_text)

    r1, c1, o1, cv1 = _stats(ref_exact, cand_exact)
    r2, c2, o2, cv2 = _stats(ref_coarse, cand_coarse)

    print("Raw ODI comparison in PRD context")
    print("=================================")
    print(f"Reference: {args.reference}")
    print(f"Candidate: {args.candidate}")
    print()
    print("Exact signature (includes ODI range field):")
    print(f"  reference ODI rows : {r1}")
    print(f"  candidate ODI rows : {c1}")
    print(f"  overlap ODI rows   : {o1}")
    print(f"  reference coverage : {cv1:.2f}%")
    print()
    print("Coarse signature (ignores ODI range field):")
    print(f"  reference ODI rows : {r2}")
    print(f"  candidate ODI rows : {c2}")
    print(f"  overlap ODI rows   : {o2}")
    print(f"  reference coverage : {cv2:.2f}%")
    print()

    missing = ref_coarse - cand_coarse
    print(f"Top missing coarse ODI signatures (reference - candidate), top {args.top}:")
    for sig, count in missing.most_common(args.top):
        service = sig[0] if sig else ""
        payload = " | ".join(sig[1:]) if len(sig) > 1 else ""
        print(f"  x{count:>4} service={service} payload={payload}")


if __name__ == "__main__":
    main()
