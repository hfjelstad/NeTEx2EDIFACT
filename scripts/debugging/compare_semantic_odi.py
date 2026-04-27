# -*- coding: utf-8 -*-
"""
Compare ODI semantics between two SKDUPD EDIFACT files.

Outputs:
- exact ODI signature overlap (includes stop range)
- coarse ODI signature overlap (ignores stop range)
- top missing coarse semantics (reference file minus candidate file)
"""

from __future__ import annotations

import argparse
import csv
import io
import zipfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

from merits.skdupd.edifact_to_csvs import EdifactToCsvs


def _read_edifact(path: Path) -> str:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".r")]
            if not names:
                raise FileNotFoundError(f"No .r file found in zip: {path}")
            return zf.read(names[0]).decode("utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_csv_text(text: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows: List[Dict[str, str]] = []
    for row in reader:
        rows.append({k: (v or "").strip() for k, v in row.items()})
    return rows


def _extract_signatures(edifact_text: str) -> Tuple[Counter, Counter]:
    parser = EdifactToCsvs()
    try:
        parser.load(edifact_text)
    except Exception:
        # Normalize and trim interchange wrappers for robust parsing.
        segments = [s.strip() for s in edifact_text.replace("\r", "").replace("\n", "").split("'") if s.strip()]
        if not segments:
            raise

        if segments and segments[-1].startswith("UIZ"):
            segments = segments[:-1]

        # Try multiple entry points because different files include different wrappers.
        candidate_starts = ["UIH", "MSD", "ORG", "HDR", "PRD"]
        last_exc: Exception | None = None
        for start in candidate_starts:
            idx = next((i for i, s in enumerate(segments) if s.startswith(start)), -1)
            if idx < 0:
                continue
            candidate = segments[idx:]
            # Drop trailing message/footer wrappers if still present.
            while candidate and candidate[-1].startswith(("UIT", "UIZ")):
                candidate = candidate[:-1]
            normalized = "'\n".join(candidate) + "'"
            try:
                parser = EdifactToCsvs()
                parser.load(normalized)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc is not None:
            raise last_exc
    csvs = parser.get_csv_file_name_2_content()

    train_rows = _parse_csv_text(csvs["SKDUPD_TRAIN.csv"])
    odi_rows = _parse_csv_text(csvs["SKDUPD_ODI.csv"])

    train_id_to_service: Dict[str, str] = {
        r.get("train_id", ""): r.get("service_number", "")
        for r in train_rows
    }

    exact = Counter()
    coarse = Counter()

    for r in odi_rows:
        service_number = train_id_to_service.get(r.get("train_id", ""), "")
        sig_exact = (
            service_number,
            r.get("from_stop_number", ""),
            r.get("to_stop_number", ""),
            r.get("tff_or_asd_or_ser", ""),
            r.get("reservation", ""),
            r.get("equipment", ""),
            r.get("tariff_or_quantity", ""),
        )
        sig_coarse = (
            service_number,
            r.get("tff_or_asd_or_ser", ""),
            r.get("reservation", ""),
            r.get("equipment", ""),
            r.get("tariff_or_quantity", ""),
        )
        exact[sig_exact] += 1
        coarse[sig_coarse] += 1

    return exact, coarse


def _overlap_stats(ref_counter: Counter, cand_counter: Counter) -> Tuple[int, int, int]:
    ref_total = sum(ref_counter.values())
    cand_total = sum(cand_counter.values())
    overlap = sum((ref_counter & cand_counter).values())
    return ref_total, cand_total, overlap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True, help="Reference SKDUPD .r or .zip")
    ap.add_argument("--candidate", required=True, help="Candidate SKDUPD .r or .zip")
    ap.add_argument("--top", type=int, default=25, help="Top missing coarse signatures to print")
    args = ap.parse_args()

    ref_text = _read_edifact(Path(args.reference)).strip()
    cand_text = _read_edifact(Path(args.candidate)).strip()

    ref_exact, ref_coarse = _extract_signatures(ref_text)
    cand_exact, cand_coarse = _extract_signatures(cand_text)

    r_tot_e, c_tot_e, ov_e = _overlap_stats(ref_exact, cand_exact)
    r_tot_c, c_tot_c, ov_c = _overlap_stats(ref_coarse, cand_coarse)

    print("ODI semantic comparison")
    print("=======================")
    print(f"Reference: {args.reference}")
    print(f"Candidate: {args.candidate}")
    print()
    print("Exact signature (includes stop range):")
    print(f"  reference rows : {r_tot_e}")
    print(f"  candidate rows : {c_tot_e}")
    print(f"  overlap rows   : {ov_e}")
    print(f"  ref coverage   : {(100.0 * ov_e / r_tot_e) if r_tot_e else 0:.2f}%")
    print()
    print("Coarse signature (ignores stop range):")
    print(f"  reference rows : {r_tot_c}")
    print(f"  candidate rows : {c_tot_c}")
    print(f"  overlap rows   : {ov_c}")
    print(f"  ref coverage   : {(100.0 * ov_c / r_tot_c) if r_tot_c else 0:.2f}%")

    missing = ref_coarse - cand_coarse
    print()
    print(f"Top missing coarse semantics (reference - candidate), top {args.top}:")
    for sig, count in missing.most_common(args.top):
        service, tff_asd_ser, reservation, equipment, tariff = sig
        print(
            f"  x{count:>4} service={service} tff/asd/ser={tff_asd_ser} "
            f"res={reservation} eq={equipment} tariff={tariff}"
        )


if __name__ == "__main__":
    main()
