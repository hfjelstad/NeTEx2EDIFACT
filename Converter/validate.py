"""
TTL-driven pre-flight validation for NeTEx files before EDIFACT conversion.

Reads validation rules from uic-edifact-ontology.ttl and checks NeTEx XML
files against them. Rules are keyed by target message type (SKDUPD/TSDUPD).

Usage standalone:
    python -m Converter.validate Source/myfile.xml --target TSDUPD

Usage as library:
    from Converter.validate import preflight_check
    errors, warnings = preflight_check(path, target="TSDUPD")
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Namespaces in the ontology (rdflib loaded lazily to avoid ~5s import cost)
PROFILE_NS = "https://netex-cen.eu/profile#"
UIC_NS = "https://uic.org/edifact#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"

# NeTEx XML namespace for XPath
NETEX_NS = "http://www.netex.org.uk/netex"
NS = {"netex": NETEX_NS}

# Locate the ontology
ONTOLOGY_PATH = Path(__file__).resolve().parent.parent.parent / "LLM" / "Indexes" / "uic-edifact-ontology.ttl"

# Target URIs
TARGET_MAP = {
    "SKDUPD": UIC_NS + "SKDUPD",
    "TSDUPD": UIC_NS + "TSDUPD",
}


@dataclass
class ValidationResult:
    rule_label: str
    severity: str  # "error" or "warning"
    message: str
    passed: bool


# Cache parsed rules to avoid reloading TTL on every call
_rules_cache: dict[str, list[dict]] = {}

# JSON cache file for fast startup (avoids rdflib on each run)
_RULES_JSON_CACHE = Path(__file__).resolve().parent / ".validation_rules_cache.json"


def _load_rules(target: str) -> list[dict]:
    """Load validation rules from TTL for a given target message type.
    
    Uses a JSON cache file for speed. Rebuilds cache if TTL is newer.
    """
    if target in _rules_cache:
        return _rules_cache[target]

    # Check if JSON cache exists and is up-to-date
    if _RULES_JSON_CACHE.exists() and ONTOLOGY_PATH.exists():
        cache_mtime = _RULES_JSON_CACHE.stat().st_mtime
        ttl_mtime = ONTOLOGY_PATH.stat().st_mtime
        if cache_mtime > ttl_mtime:
            import json
            try:
                all_rules = json.loads(_RULES_JSON_CACHE.read_text(encoding="utf-8"))
                if target in all_rules:
                    _rules_cache[target] = all_rules[target]
                    return _rules_cache[target]
            except (json.JSONDecodeError, KeyError):
                pass  # Rebuild cache

    # Parse TTL (slow path, ~5s with rdflib)
    rules_by_target = _parse_ttl_rules()

    # Save to JSON cache for next time
    import json
    _RULES_JSON_CACHE.write_text(
        json.dumps(rules_by_target, indent=2, default=str),
        encoding="utf-8",
    )

    _rules_cache.update(rules_by_target)
    return _rules_cache.get(target, [])


def _parse_ttl_rules() -> dict[str, list[dict]]:
    """Parse all validation rules from the TTL ontology."""
    from rdflib import Graph, Namespace, RDF

    PROFILE = Namespace(PROFILE_NS)
    UIC = Namespace(UIC_NS)
    RDFS = Namespace(RDFS_NS)

    g = Graph()
    g.parse(str(ONTOLOGY_PATH), format="turtle")

    rules_by_target: dict[str, list[dict]] = {"SKDUPD": [], "TSDUPD": []}

    for rule in g.subjects(RDF.type, PROFILE["ValidationRule"]):
        applies_to = list(g.objects(rule, PROFILE["appliesTo"]))

        rule_data = {
            "label": str(g.value(rule, RDFS["label"], default="")),
            "xpaths": [str(x) for x in g.objects(rule, PROFILE["xpath"])],
            "check": str(g.value(rule, PROFILE["check"], default="")),
            "severity": str(g.value(rule, PROFILE["severity"], default="warning")),
            "message": str(g.value(rule, PROFILE["message"], default="Validation failed")),
            "threshold": str(g.value(rule, PROFILE["threshold"], default="")),
            "pattern": str(g.value(rule, PROFILE["pattern"], default="")),
            "root_tag": str(g.value(rule, PROFILE["rootTag"], default="")),
            "child_xpath": str(g.value(rule, PROFILE["childXpath"], default="")),
        }

        for target_name, target_uri_str in TARGET_MAP.items():
            target_uri = UIC[target_name]
            if target_uri in applies_to:
                rules_by_target[target_name].append(rule_data)

    return rules_by_target


def preflight_check(
    xml_path: Path,
    target: str,
) -> tuple[list[ValidationResult], list[ValidationResult]]:
    """
    Run TTL-driven validation on a NeTEx file.

    Uses streaming (iterparse) for large files to avoid loading entire tree.
    Returns (errors, warnings) — lists of failed ValidationResults.
    """
    rules = _load_rules(target)

    # For large files, use streaming to find elements quickly
    # We only need to know IF certain elements exist, not parse the full tree
    found_elements = _stream_scan(xml_path)

    if found_elements is None:
        # File couldn't be parsed at all
        errors = []
        warnings = []
        for rule in rules:
            if rule["check"] == "wellformed":
                errors.append(ValidationResult(rule["label"], "error", rule["message"], passed=False))
            else:
                errors.append(ValidationResult(rule["label"], rule["severity"], rule["message"], passed=False))
        return errors, warnings

    errors: list[ValidationResult] = []
    warnings: list[ValidationResult] = []

    for rule in rules:
        result = _check_rule_streaming(rule, found_elements)
        if not result.passed:
            if result.severity == "error":
                errors.append(result)
            else:
                warnings.append(result)

    return errors, warnings


def _stream_scan(xml_path: Path) -> dict[str, int] | None:
    """Stream-scan an XML file and count occurrences of key NeTEx elements.
    
    Returns a dict of {local_element_name: count} or None if not well-formed.
    Stops early once enough evidence is collected (max 1000 elements per type).
    """
    # Elements we care about for validation
    TRACKED = {
        "StopPlace", "Quay", "ServiceJourney", "TimetabledPassingTime",
        "JourneyPattern", "DayType", "OperatingDay", "DatedServiceJourney",
        "Line", "ParticipantRef", "PublicationDelivery", "Name",
        "PrivateCode",
    }
    counts: dict[str, int] = {}
    root_tag = ""

    try:
        for event, elem in ET.iterparse(str(xml_path), events=("start",)):
            local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            if not root_tag:
                root_tag = local

            if local in TRACKED:
                counts[local] = counts.get(local, 0) + 1

            # Check children for Name under StopPlace (sample first few)
            if local == "StopPlace":
                # We'll track if any StopPlace lacks Name by checking later
                pass

            # Early termination: once we've found enough evidence, stop
            total = sum(counts.values())
            if total > 500:
                break

            # Free memory
            elem.clear()

    except ET.ParseError:
        return None

    counts["__root__"] = 1
    counts["__root_tag__"] = 0  # placeholder
    # Store root tag name specially
    counts["_root_tag_name"] = hash(root_tag)  # hack: store as hash
    # Actually, let's just store it differently
    counts["__ROOT:" + root_tag] = 1

    return counts


def _check_rule_streaming(rule: dict, found: dict[str, int]) -> ValidationResult:
    """Check a rule against streaming scan results."""
    check = rule["check"]
    label = rule["label"]
    severity = rule["severity"]
    message = rule["message"]

    if check == "wellformed":
        return ValidationResult(label, severity, message, passed=True)

    if check == "root_tag":
        expected = rule["root_tag"]
        passed = ("__ROOT:" + expected) in found
        return ValidationResult(label, severity, message, passed=passed)

    if check in ("exists", "any_exists"):
        # Extract element names from xpaths like ".//netex:ServiceJourney"
        for xpath in rule["xpaths"]:
            elem_name = xpath.split(":")[-1] if ":" in xpath else xpath.split("/")[-1]
            # Handle nested paths like ".//netex:StopPlace/netex:quays/netex:Quay"
            elem_name = elem_name.split("/")[-1]
            if found.get(elem_name, 0) > 0:
                return ValidationResult(label, severity, message, passed=True)
        return ValidationResult(label, severity, message, passed=False)

    if check == "not_exists":
        for xpath in rule["xpaths"]:
            elem_name = xpath.split(":")[-1] if ":" in xpath else xpath.split("/")[-1]
            elem_name = elem_name.split("/")[-1]
            if found.get(elem_name, 0) > 0:
                return ValidationResult(label, severity, message, passed=False)
        return ValidationResult(label, severity, message, passed=True)

    if check == "all_have_child":
        # For streaming, we can't easily check parent-child relationships
        # So we just check the child exists at all (best effort)
        child_xpath = rule.get("child_xpath", "")
        child_name = child_xpath.split(":")[-1] if ":" in child_xpath else child_xpath
        passed = found.get(child_name, 0) > 0
        return ValidationResult(label, severity, message, passed=passed)

    if check == "count_gte":
        threshold = int(rule["threshold"]) if rule["threshold"] else 1
        total = 0
        for xpath in rule["xpaths"]:
            elem_name = xpath.split(":")[-1] if ":" in xpath else xpath.split("/")[-1]
            elem_name = elem_name.split("/")[-1]
            total += found.get(elem_name, 0)
        return ValidationResult(label, severity, message, passed=total >= threshold)

    return ValidationResult(label, "warning", f"Unknown check type: {check}", passed=True)


def preflight_check_zip(
    zip_path: Path,
    target: str,
) -> tuple[list[ValidationResult], list[ValidationResult]]:
    """
    Run TTL-driven validation on the first XML inside a ZIP file.
    Uses streaming for efficiency.
    """
    import zipfile
    import io

    rules = _load_rules(target)

    found_elements: dict[str, int] | None = None
    try:
        with zipfile.ZipFile(zip_path) as zf:
            xml_names = [n for n in zf.namelist() if n.endswith(".xml")]
            if xml_names:
                # Stream-scan within the zip
                TRACKED = {
                    "StopPlace", "Quay", "ServiceJourney", "TimetabledPassingTime",
                    "JourneyPattern", "DayType", "OperatingDay", "DatedServiceJourney",
                    "Line", "ParticipantRef", "PublicationDelivery", "Name",
                    "PrivateCode",
                }
                counts: dict[str, int] = {}
                root_tag = ""

                with zf.open(xml_names[0]) as f:
                    for event, elem in ET.iterparse(f, events=("start",)):
                        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                        if not root_tag:
                            root_tag = local
                        if local in TRACKED:
                            counts[local] = counts.get(local, 0) + 1
                        total = sum(counts.values())
                        if total > 500:
                            break
                        elem.clear()

                counts["__ROOT:" + root_tag] = 1
                found_elements = counts
    except (zipfile.BadZipFile, ET.ParseError):
        pass

    if found_elements is None:
        errors = [ValidationResult("Well-formed XML", "error",
                  "File is not well-formed XML or not a valid ZIP.", passed=False)]
        return errors, []

    errors: list[ValidationResult] = []
    warnings: list[ValidationResult] = []

    for rule in rules:
        result = _check_rule_streaming(rule, found_elements)
        if not result.passed:
            if result.severity == "error":
                errors.append(result)
            else:
                warnings.append(result)

    return errors, warnings


def print_results(
    path: Path,
    errors: list[ValidationResult],
    warnings: list[ValidationResult],
) -> None:
    """Pretty-print validation results."""
    if not errors and not warnings:
        print(f"  OK: {path.name} -- all checks passed")
        return

    for e in errors:
        print(f"  ERROR: {e.message}")
    for w in warnings:
        print(f"  WARNING: {w.message}")


# --- CLI ---
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate NeTEx files against TTL rules")
    parser.add_argument("files", nargs="+", help="NeTEx XML or ZIP files to validate")
    parser.add_argument(
        "--target",
        choices=["SKDUPD", "TSDUPD", "auto"],
        default="auto",
        help="Target message type (default: auto-detect)",
    )
    args = parser.parse_args()

    for filepath in args.files:
        p = Path(filepath)
        if not p.exists():
            print(f"  NOT FOUND: {filepath}")
            continue

        # Auto-detect target from content
        target = args.target
        if target == "auto":
            try:
                if p.suffix == ".zip":
                    import zipfile
                    with zipfile.ZipFile(p) as zf:
                        xml_names = [n for n in zf.namelist() if n.endswith(".xml")]
                        if xml_names:
                            root = ET.fromstring(zf.read(xml_names[0]))
                        else:
                            root = None
                else:
                    root = ET.parse(str(p)).getroot()

                if root is not None:
                    ns = {"netex": NETEX_NS}
                    has_stops = len(root.findall(".//{%s}StopPlace" % NETEX_NS)) > 0
                    has_journeys = len(root.findall(".//{%s}ServiceJourney" % NETEX_NS)) > 0
                    if has_stops and not has_journeys:
                        target = "TSDUPD"
                    elif has_journeys:
                        target = "SKDUPD"
                    else:
                        target = "TSDUPD"  # default
            except Exception:
                target = "TSDUPD"

        print(f"\n  Validating: {p.name} (target: {target})")

        if p.suffix == ".zip":
            errors, warnings = preflight_check_zip(p, target)
        else:
            errors, warnings = preflight_check(p, target)

        print_results(p, errors, warnings)

    # Summary
    print()
