#!/usr/bin/env python3

import sys
import json
import hashlib
import re
from pathlib import Path
from collections import defaultdict

# That is to remove all DEBUG messages from AnalyzeAPK
from loguru import logger
logger.remove()

from androguard.misc import AnalyzeAPK
EXODUS_DB = "exodus.json"

"""Calculate SHA-256 hash of the APK."""
def sha256_file(path):

    sha256 = hashlib.sha256()

    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            sha256.update(chunk)

    return sha256.hexdigest()


def analyze_apk(apk_path):

    apk_path = Path(apk_path)

    if not apk_path.exists():
        raise FileNotFoundError(f"APK not found: {apk_path}")

    print(f"Analyzing: {apk_path}")

    # ---------------------------------------------------------
    # SHA-256
    # ---------------------------------------------------------

    sha256 = sha256_file(apk_path)

    # ---------------------------------------------------------
    # Androguard analysis
    # ---------------------------------------------------------

    a, d, dx = AnalyzeAPK(str(apk_path))

    # ---------------------------------------------------------
    # Basic APK information
    # ---------------------------------------------------------

    package = a.get_package()
    app_name = a.get_app_name()
    version_name = a.get_androidversion_name()
    version_code = a.get_androidversion_code()

    # ---------------------------------------------------------
    # SDK versions
    # ---------------------------------------------------------

    sdk = {
        "min": a.get_min_sdk_version(),
        "target": a.get_target_sdk_version(),
        "max": a.get_max_sdk_version()
    }

    # ---------------------------------------------------------
    # Permissions
    # ---------------------------------------------------------

    permissions = sorted(a.get_permissions())

    # ---------------------------------------------------------
    # Components
    # ---------------------------------------------------------

    activities = sorted(a.get_activities())
    services = sorted(a.get_services())
    receivers = sorted(a.get_receivers())
    providers = sorted(a.get_providers())
    dex_strings = get_dex_strings(d)

    # ---------------------------------------------------------
    # DEX classes
    # ---------------------------------------------------------

    dex_classes = []

    for dex in d:
        for cls in dex.get_classes():
            dex_classes.append(cls.name)

    dex_classes.sort()
    trackers = load_trackers()

    code_detected = detect_code_trackers (dex_classes, trackers)
    network_detected = detect_network_trackers(dex_strings, trackers)

    # ---------------------------------------------------------
    # APK files
    # ---------------------------------------------------------

    apk_files = []

    for filename in a.get_files():
        apk_files.append(filename)

    apk_files.sort()

    # ---------------------------------------------------------
    # Result
    # ---------------------------------------------------------

    result = {
        "apk": apk_path.name,
        "sha256": sha256,
        "package": package,
        "name": app_name,
        "version_name": version_name,
        "version_code": version_code,
        "sdk": sdk,
        "permissions": permissions,
        "activities": activities,
        "services": services,
        "receivers": receivers,
        "providers": providers,
        "dex_classes": dex_classes,
        "files": apk_files,
        "domains": [],
        "trackers": {
           "code": group_trackers (code_detected),
           "network": group_trackers (network_detected)
        }
    }

    # ---------------------------------------------------------
    # Print summary
    # ---------------------------------------------------------

    code_trackers = {
        tracker["id"]
        for detection in code_detected
        for tracker in detection.get("trackers", [])
    }

    network_trackers = {
        tracker["id"]
        for detection in network_detected
        for tracker in detection.get("trackers", [])
    }

    total_trackers = len(code_trackers | network_trackers)
    number_permissions = len(permissions)

    print()
    print("========================================")
    print("APK SUMMARY")
    print("========================================")
    print(f"Trackers found       : {total_trackers}")
    print(f"Permissions required : {number_permissions}")
    print("========================================")

    return result



"""
Detect code trackers by comparing the signature of the known ones with dex_classes.
dex_classes = those identified in the APK being analyzed
trackers = trackers identified in the EXODUS_DB
returns list of detected code trackers.
"""
def detect_code_trackers(dex_classes, trackers):

    detections = []

    # Normalize all DEX class names once
    normalized_classes = [
        normalize_class_name(c)
        for c in dex_classes
    ]

    for tracker in trackers:
        signature = tracker.get("code_signature")
        if not signature:
            continue

        # Exodus uses | to separate alternative signatures
        signatures = signature.split("|")

        matches = []
        for sig in signatures:
            sig = sig.strip()
            if not sig:
                continue

            for class_name in normalized_classes:
                if sig in class_name:
                    matches.append({
                        "signature": sig,
                        "class": class_name
                    })

        if matches:
            detections.append({
                "id": tracker["id"],
                "name": tracker["name"],
                "categories": tracker.get("categories", []),
                "type": "code",
                "matches": matches
            })

    return detections



"""
Detect network trackers by comparing the regular expressions of the known ones 
with those of the APK being analyzed.
dex_strings = regular expressions in the APK being analyzed
trackers = trackers identified in the EXODUS_DB
returns list of detected network trackers.
"""
def detect_network_trackers(dex_strings, trackers):

    detections = []
    for tracker in trackers:
        network_signature = tracker.get("network_signature")
        if not network_signature:
            continue

        matches = []
        for sig in network_signature.split("|"):
            sig = sig.strip()
            if not sig:
                continue

            try:
                pattern = re.compile(sig, re.IGNORECASE)
            except re.error as e:
                print(f"Invalid network signature {sig!r}: {e}")
                continue

            for string in dex_strings:
                if pattern.search(string):
                    matches.append({
                        "signature": sig,
                        "string": string
                    })

        if matches:
            detections.append({
                "id": tracker["id"],
                "name": tracker["name"],
                "categories": tracker.get("categories", []),
                "type": "network",
                "matches": matches
            })

    return detections

"""
dexs is a list of strings or the APK (may be > 1000) 
but we eliminate duplicates by using set
"""
def get_dex_strings(dexs):
    strings = set()

    for dex in dexs:
        for string in dex.get_strings():
            strings.add(string)

    return strings


"""
Group trakers by signature. But keep all the
matches for potential further investigations.
"""
def group_trackers(detected):

    groups = defaultdict(lambda: {
        "type": "code",
        "trackers": [],
        "matches": []
    })

    for tracker in detected:
        for match in tracker["matches"]:
            signature = match["signature"]
            group = groups[signature]

            # Add tracker only once
            if not any(
                t["id"] == tracker["id"]
                for t in group["trackers"]
            ):
                group["trackers"].append({
                    "id": tracker["id"],
                    "name": tracker["name"],
                    "categories": tracker.get("categories", [])
                })

            class_name = match["class"]

            if class_name not in group["matches"]:
                group["matches"].append(class_name)

    return [
        {
            "type": group["type"],
            "signature": signature,
            "trackers": group["trackers"],
            "matches": group["matches"]
        }
        for signature, group in groups.items()
    ]

"""
Get the trackers identified by Exodus
"""
def load_trackers(filename = EXODUS_DB):

    with open(filename, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        return list(data.values())

    return data


"""Convert a DEX class name to normal Java-style notation."""
def normalize_class_name(name):

    if name.startswith("L"):
        name = name[1:]

    if name.endswith(";"):
        name = name[:-1]

    return name.replace("/", ".")



def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <apk>")
        sys.exit(1)

    apk_path = sys.argv[1]

    try:

        result = analyze_apk(apk_path)

        # JSON filename
        output_path = Path(apk_path).with_suffix(".json")

        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                result,
                f,
                indent=4,
                ensure_ascii=False
            )

        print()
        print(f"JSON written to: {output_path}")

    except Exception as e:

        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()