from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


DEFAULT_PATCH_MAPPING = {
    "voip/line/0/description": "extension",
    "voip/line/0/extension_display": "display_no",
    "network/lan/location/location_uri": "ipcc_location",
    "network/lan/vlan/priority": "priority",
    "system/display/message_on_screen": "main_line",
    "voip/line/0/enabled": 1,
}


def load_cfg_file(cfg_path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    with cfg_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key] = value
    return data


def build_patch_values(entry: dict, base_cfg: Dict[str, str]) -> Dict[str, str]:
    patch_values: Dict[str, str] = {}
    overrides = entry.get("set", {})
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            patch_values[key] = str(value)

    mapping = entry.get("mapping", DEFAULT_PATCH_MAPPING)
    if not isinstance(mapping, dict):
        mapping = DEFAULT_PATCH_MAPPING

    for target_key, source in mapping.items():
        if isinstance(source, str):
            value = entry.get(source)
            if value is None and source in base_cfg:
                value = base_cfg[source]
            if value is not None and target_key not in patch_values:
                patch_values[target_key] = str(value)
        else:
            patch_values[target_key] = str(source)

    return patch_values


def build_case_payload(title: str, description: str, cfg_data: Dict[str, str], patch_values: Dict[str, str], extra_meta: dict) -> dict:
    payload = {
        "title": title,
        "description": description,
        "config": cfg_data,
    }
    if patch_values:
        payload["patches"] = [{"set": patch_values}]
    if extra_meta:
        payload["metadata"] = extra_meta
    return payload


def load_plan(plan_path: Path) -> dict:
    with plan_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_output_name(cfg_path: Path, prefix: str, suffix: str) -> Path:
    stem = cfg_path.stem
    return Path(f"{prefix}{stem}{suffix}.json")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def iter_entries(plan: dict) -> Iterable[dict]:
    entries = plan.get("entries", [])
    if not isinstance(entries, list):
        return []
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate reusable ACSA cases from real AudioCodes cfg exports")
    parser.add_argument("--cfg-dir", default="New branch MK real conf", help="Directory containing real cfg exports")
    parser.add_argument("--plan", required=True, help="Branch plan JSON with entries to convert")
    parser.add_argument("--output-dir", default="cases/generated", help="Where to write generated JSON files")
    parser.add_argument("--baseline-prefix", default="baseline_", help="Prefix for baseline JSON files")
    parser.add_argument("--case-prefix", default="case_", help="Prefix for patch case JSON files")
    args = parser.parse_args()

    cfg_dir = Path(args.cfg_dir)
    plan_path = Path(args.plan)
    output_dir = Path(args.output_dir)
    plan = load_plan(plan_path)

    summary: List[Tuple[str, str, str]] = []
    for entry in iter_entries(plan):
        cfg_name = entry.get("cfg_file")
        if not cfg_name:
            raise ValueError("Each plan entry requires cfg_file")

        cfg_path = cfg_dir / cfg_name
        if not cfg_path.exists():
            raise FileNotFoundError(f"Missing cfg file: {cfg_path}")

        cfg_data = load_cfg_file(cfg_path)
        patch_values = build_patch_values(entry, cfg_data)

        ext = str(entry.get("extension") or entry.get("ext") or cfg_path.stem)
        title = str(entry.get("title") or f"Mong Kok L branch {ext}")
        description = str(
            entry.get("description")
            or f"Generated from {cfg_path.name}"
        )
        metadata = {
            "cfg_file": cfg_path.name,
            "extension": ext,
            "display_no": entry.get("display_no"),
            "priority": entry.get("priority"),
            "ipcc_location": entry.get("ipcc_location"),
            "main_line": entry.get("main_line"),
        }

        baseline_payload = build_case_payload(title, description, cfg_data, {}, metadata)
        case_payload = build_case_payload(title, description, cfg_data, patch_values, metadata)

        baseline_path = output_dir / resolve_output_name(cfg_path, args.baseline_prefix, "")
        case_path = output_dir / resolve_output_name(cfg_path, args.case_prefix, "_patch")
        write_json(baseline_path, baseline_payload)
        write_json(case_path, case_payload)

        summary.append((cfg_path.name, baseline_path.name, case_path.name))

    print(json.dumps({"generated": summary, "output_dir": str(output_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())