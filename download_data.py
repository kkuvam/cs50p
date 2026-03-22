#!/usr/bin/env python3
"""
Exomiser Data Manager
Checks installed datasets and downloads updates.

Datasets managed:
  core     -- Exomiser variant databases (hg19/hg38/phenotype) from Monarch Initiative
  remm     -- Regulatory Mendelian Mutation scores from BIH (hg19/hg38, ~16 GB each)
  cadd     -- CADD SNV and InDel scores from UW/BIH (hg19/hg38, ~80 GB + ~2 GB each)

Note: ClinVar whitelists are bundled inside the core hg19/hg38 zip packages — no
      separate download is needed.

Usage:
    python download_data.py --list                         # show installed vs available
    python download_data.py                                # download all datasets
    python download_data.py --dataset core                 # core data only
    python download_data.py --dataset cadd --assembly hg19 # CADD hg19 only
    python download_data.py --dataset remm --assembly hg38 # REMM hg38 only
    python download_data.py --core-version 2512            # pin a specific core version
    python download_data.py --data-dir /custom/path
"""

import hashlib
import argparse
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DATA_DIR = "/Volumes/Extreme/Exomiser/data"

# Core (Monarch Initiative)
MONARCH_BASE = "https://data.monarchinitiative.org/exomiser/data"

# REMM (BIH)
REMM_BASE = "https://kircherlab.bihealth.org/download/ReMM"
REMM_LATEST = "0.4"
REMM_FILES = {
    "hg19": [
        "ReMM.v{version}.hg19.tsv.gz",
        "ReMM.v{version}.hg19.tsv.gz.tbi",
    ],
    "hg38": [
        "ReMM.v{version}.hg38.tsv.gz",
        "ReMM.v{version}.hg38.tsv.gz.tbi",
    ],
}
REMM_MD5_URL = REMM_BASE + "/ReMM.v{version}.{assembly}.md5"

# CADD (University of Washington / BIH mirror)
CADD_BASE_US = "https://krishna.gs.washington.edu/download/CADD"
CADD_BASE_DE = "https://kircherlab.bihealth.org/download/CADD"
CADD_LATEST = "1.7"
# Files per assembly — {indel} is substituted per-assembly
CADD_FILES = {
    "hg19": {
        "assembly_dir": "GRCh37",
        "files": [
            "whole_genome_SNVs.tsv.gz",
            "whole_genome_SNVs.tsv.gz.tbi",
            "gnomad.genomes-exomes.r4.0.indel.tsv.gz",
            "gnomad.genomes-exomes.r4.0.indel.tsv.gz.tbi",
        ],
    },
    "hg38": {
        "assembly_dir": "GRCh38",
        "files": [
            "whole_genome_SNVs.tsv.gz",
            "whole_genome_SNVs.tsv.gz.tbi",
            "gnomad.genomes.r4.0.indel.tsv.gz",
            "gnomad.genomes.r4.0.indel.tsv.gz.tbi",
        ],
    },
}

ALL_ASSEMBLIES = ["hg19", "hg38"]


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _fmt_size(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} PB"


def _print_progress(downloaded: int, total: int) -> None:
    if total > 0:
        pct = min(100, downloaded * 100 // total)
        print(f"\r    {pct:3d}%  {_fmt_size(downloaded)} / {_fmt_size(total)}", end="", flush=True)
    else:
        print(f"\r    {_fmt_size(downloaded)}", end="", flush=True)


def download_with_resume(url: str, dest: Path, desc: str = "") -> bool:
    """
    Download a file with resume support (HTTP Range requests).
    Partial downloads are saved to <dest>.part and renamed on completion.
    Handles KeyboardInterrupt gracefully — partial file is kept for resuming.
    """
    part_path = dest.with_suffix(dest.suffix + ".part")
    start_byte = part_path.stat().st_size if part_path.exists() else 0

    headers: dict[str, str] = {"User-Agent": "ExomiserDataManager/1.0"}
    if start_byte > 0:
        headers["Range"] = f"bytes={start_byte}-"
        print(f"    Resuming {desc or dest.name} from {_fmt_size(start_byte)} ...")
    else:
        print(f"    Downloading {desc or dest.name} ...")

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=60) as resp:
            status = resp.status
            content_length = int(resp.headers.get("Content-Length", 0) or 0)

            # If server returned 200 (not 206), it doesn't support resume
            if start_byte > 0 and status == 200:
                print("    Server does not support resume — restarting.")
                start_byte = 0
                part_path.unlink(missing_ok=True)

            total = content_length + start_byte if start_byte > 0 else content_length
            downloaded = start_byte
            mode = "ab" if start_byte > 0 else "wb"

            with open(part_path, mode) as f:
                while True:
                    chunk = resp.read(1024 * 1024)  # 1 MB chunks
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    _print_progress(downloaded, total)

        print()  # newline after progress
        part_path.rename(dest)
        return True

    except HTTPError as e:
        if e.code == 416:
            # Range Not Satisfiable — file is already fully downloaded
            print("    File already complete (416).")
            if part_path.exists():
                part_path.rename(dest)
            return True
        print(f"\n    HTTP {e.code}: {e.reason}")
        return False
    except URLError as e:
        print(f"\n    Network error: {e.reason}")
        return False
    except KeyboardInterrupt:
        print(f"\n    Interrupted. Partial file kept at: {part_path}")
        print("    Re-run the script to resume.")
        sys.exit(1)


def verify_md5(file_path: Path, md5_url: str) -> bool:
    """Download MD5 from URL and verify file. Returns True if OK or checksum unavailable."""
    try:
        req = Request(md5_url, headers={"User-Agent": "ExomiserDataManager/1.0"})
        with urlopen(req, timeout=30) as resp:
            expected = resp.read().decode().split()[0].strip()
    except HTTPError as e:
        print(f"    Checksum not available (HTTP {e.code}) — skipping verification.")
        return True
    except Exception as e:
        print(f"    Could not fetch checksum ({e}) — skipping verification.")
        return True

    print("    Verifying MD5 ... ", end="", flush=True)
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            md5.update(chunk)
    actual = md5.hexdigest()

    if actual == expected:
        print("OK")
        return True
    print(f"FAILED\n    Expected: {expected}\n    Got:      {actual}")
    return False


def verify_sha256(file_path: Path, sha256_url: str) -> bool:
    """Download SHA256 from URL and verify file. Returns True if OK or unavailable."""
    try:
        req = Request(sha256_url, headers={"User-Agent": "ExomiserDataManager/1.0"})
        with urlopen(req, timeout=30) as resp:
            expected = resp.read().decode().split()[0].strip()
    except HTTPError as e:
        print(f"    Checksum not available (HTTP {e.code}) — skipping verification.")
        return True
    except Exception as e:
        print(f"    Could not fetch checksum ({e}) — skipping verification.")
        return True

    print("    Verifying SHA256 ... ", end="", flush=True)
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    actual = sha256.hexdigest()

    if actual == expected:
        print("OK")
        return True
    print(f"FAILED\n    Expected: {expected}\n    Got:      {actual}")
    return False


# ---------------------------------------------------------------------------
# Core data (Monarch Initiative)
# ---------------------------------------------------------------------------

class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for attr, value in attrs:
                if attr == "href" and value and not value.startswith("?") and value != "../":
                    self.links.append(value.rstrip("/"))


def fetch_core_versions() -> list[str]:
    """Return core data versions available on Monarch (newest first)."""
    try:
        req = Request(MONARCH_BASE + "/", headers={"User-Agent": "ExomiserDataManager/1.0"})
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8")
    except Exception as e:
        print(f"  Error fetching version list: {e}", file=sys.stderr)
        return []

    parser = _LinkParser()
    parser.feed(html)
    versions: set[str] = set()
    for link in parser.links:
        m = re.match(r'^(\d{4})_(hg19|hg38|phenotype)\.zip$', link)
        if m:
            versions.add(m.group(1))
    return sorted(versions, reverse=True)


def get_installed_core_versions(data_dir: Path) -> dict[str, str]:
    """Scan data_dir for extracted {version}_{assembly} dirs, return highest per assembly."""
    installed: dict[str, str] = {}
    if not data_dir.exists():
        return installed
    for item in data_dir.iterdir():
        m = re.match(r'^(\d{4})_(hg19|hg38|phenotype)$', item.name)
        if m and item.is_dir():
            assembly, version = m.group(2), m.group(1)
            if assembly not in installed or version > installed[assembly]:
                installed[assembly] = version
    return installed


def download_core_dataset(version: str, assembly: str, data_dir: Path) -> bool:
    """Download, verify SHA256, and extract one core data package."""
    extract_dir = data_dir / f"{version}_{assembly}"
    if extract_dir.exists():
        print(f"    Already installed at {extract_dir.name}")
        return True

    zip_name = f"{version}_{assembly}.zip"
    zip_path = data_dir / zip_name
    zip_url = f"{MONARCH_BASE}/{zip_name}"
    sha256_url = f"{MONARCH_BASE}/{version}_{assembly}.sha256"

    if not download_with_resume(zip_url, zip_path):
        return False

    if not verify_sha256(zip_path, sha256_url):
        zip_path.unlink(missing_ok=True)
        return False

    print("    Extracting ... ", end="", flush=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(data_dir)
        zip_path.unlink()
        print("done")
        return True
    except zipfile.BadZipFile as e:
        print(f"failed: {e}")
        zip_path.unlink(missing_ok=True)
        return False


# ---------------------------------------------------------------------------
# REMM
# ---------------------------------------------------------------------------

def get_installed_remm_version(remm_dir: Path) -> str | None:
    """Return latest installed REMM version by scanning remm/ for .tsv.gz files."""
    if not remm_dir.exists():
        return None
    versions: list[str] = []
    for f in remm_dir.iterdir():
        m = re.match(r'^ReMM\.v([\d.post]+)\.hg19\.tsv\.gz$', f.name)
        if m:
            versions.append(m.group(1))
    return sorted(versions)[-1] if versions else None


def download_remm(version: str, assembly: str, remm_dir: Path) -> bool:
    """Download REMM .tsv.gz and .tbi for one assembly, with MD5 verification."""
    remm_dir.mkdir(parents=True, exist_ok=True)
    all_ok = True

    for filename in REMM_FILES[assembly]:
        fname = filename.format(version=version)
        dest = remm_dir / fname
        url = f"{REMM_BASE}/{fname}"

        if dest.exists():
            print(f"    Already exists: {fname}")
            continue

        if not download_with_resume(url, dest, fname):
            all_ok = False
            continue

        # Verify MD5 for the main tsv.gz (not the .tbi)
        if fname.endswith(".tsv.gz"):
            md5_url = REMM_MD5_URL.format(version=version, assembly=assembly)
            if not verify_md5(dest, md5_url):
                dest.unlink(missing_ok=True)
                all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# CADD
# ---------------------------------------------------------------------------

def get_installed_cadd_versions(cadd_dir: Path) -> dict[str, str]:
    """Return highest installed CADD version per assembly."""
    installed: dict[str, str] = {}
    if not cadd_dir.exists():
        return installed
    for version_dir in cadd_dir.iterdir():
        if not re.match(r'^\d+\.\d+$', version_dir.name):
            continue
        version = version_dir.name
        for assembly in ALL_ASSEMBLIES:
            asm_dir = version_dir / assembly
            if asm_dir.is_dir() and any(asm_dir.iterdir()):
                if assembly not in installed or version > installed[assembly]:
                    installed[assembly] = version
    return installed


def download_cadd(version: str, assembly: str, cadd_dir: Path, mirror: str = "US") -> bool:
    """Download CADD SNV and InDel files (with .tbi indexes) for one assembly."""
    cfg = CADD_FILES[assembly]
    base = CADD_BASE_US if mirror == "US" else CADD_BASE_DE
    url_base = f"{base}/v{version}/{cfg['assembly_dir']}"

    dest_dir = cadd_dir / version / assembly
    dest_dir.mkdir(parents=True, exist_ok=True)

    all_ok = True
    for filename in cfg["files"]:
        dest = dest_dir / filename
        url = f"{url_base}/{filename}"

        if dest.exists():
            print(f"    Already exists: {filename}")
            continue

        if not download_with_resume(url, dest, filename):
            all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

def print_status(data_dir: Path, assemblies: list[str]) -> None:
    """Print installed vs latest for all datasets."""
    print(f"\nData directory: {data_dir}\n")

    # Core
    print("Core data (Exomiser variant databases):")
    available = fetch_core_versions()
    latest_core = available[0] if available else "unknown"
    local_core = get_installed_core_versions(data_dir)
    core_assemblies = assemblies + ["phenotype"]
    for asm in core_assemblies:
        inst = local_core.get(asm, "not installed")
        note = "up to date" if inst == latest_core else (
            f"update available ({inst} → {latest_core})" if inst != "not installed" else "not installed"
        )
        print(f"  {asm:<12} {inst:<8}  {note}")
    if available:
        print(f"  Available versions: {', '.join(available[:6])}{'...' if len(available) > 6 else ''}")

    # REMM
    print("\nReMM (Regulatory Mendelian Mutation scores):")
    remm_dir = data_dir / "remm"
    inst_remm = get_installed_remm_version(remm_dir)
    for asm in assemblies:
        files_present = all(
            (remm_dir / f.format(version=inst_remm or "")).exists()
            for f in REMM_FILES[asm]
        ) if inst_remm else False
        status = "up to date" if (inst_remm == REMM_LATEST and files_present) else (
            f"update available ({inst_remm} → {REMM_LATEST})" if inst_remm else "not installed"
        )
        print(f"  {asm:<12} {(inst_remm or 'none'):<8}  {status}")

    # CADD
    print("\nCADD (Combined Annotation Dependent Depletion):")
    cadd_dir = data_dir / "cadd"
    inst_cadd = get_installed_cadd_versions(cadd_dir)
    for asm in assemblies:
        inst = inst_cadd.get(asm, "not installed")
        note = "up to date" if inst == CADD_LATEST else (
            f"update available ({inst} → {CADD_LATEST})" if inst != "not installed" else "not installed"
        )
        print(f"  {asm:<12} {inst:<8}  {note}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and update Exomiser data files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--data-dir", default=DEFAULT_DATA_DIR,
        help=f"Exomiser data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--dataset", choices=["core", "remm", "cadd", "all"], default="all",
        help="Which dataset to download (default: all)",
    )
    parser.add_argument(
        "--assembly", choices=ALL_ASSEMBLIES + ["all"], default=None,
        help="Assembly to download (default: hg19 only, use 'all' for both)",
    )
    parser.add_argument(
        "--core-version",
        help="Specific core data version to download (e.g. 2512). Default: latest.",
    )
    parser.add_argument(
        "--remm-version", default=REMM_LATEST,
        help=f"REMM version to download (default: {REMM_LATEST})",
    )
    parser.add_argument(
        "--cadd-version", default=CADD_LATEST,
        help=f"CADD version to download (default: {CADD_LATEST})",
    )
    parser.add_argument(
        "--cadd-mirror", choices=["US", "DE"], default="US",
        help="CADD download mirror: US (UW, default) or DE (BIH, Europe)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Show installed vs available versions and exit.",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: data directory not found: {data_dir}")
        sys.exit(1)

    # Determine assemblies
    if args.assembly == "all":
        assemblies = ALL_ASSEMBLIES
    elif args.assembly:
        assemblies = [args.assembly]
    else:
        assemblies = ["hg19"]  # default: only what application.properties enables

    print_status(data_dir, assemblies)

    if args.list:
        return

    failed: list[str] = []

    # ---- Core data ----
    if args.dataset in ("core", "all"):
        print("=" * 60)
        print("Downloading core data ...")
        available = fetch_core_versions()
        if not available:
            print("  Could not fetch available versions.")
            failed.append("core")
        else:
            target = args.core_version or available[0]
            local_core = get_installed_core_versions(data_dir)
            core_assemblies = assemblies + ["phenotype"]
            for asm in core_assemblies:
                if local_core.get(asm) == target:
                    print(f"\n[core/{asm}] Already at {target}")
                    continue
                print(f"\n[core/{asm}] version {target}")
                if not download_core_dataset(target, asm, data_dir):
                    failed.append(f"core/{asm}")

    # ---- REMM ----
    if args.dataset in ("remm", "all"):
        print("\n" + "=" * 60)
        print("Downloading ReMM data ...")
        remm_dir = data_dir / "remm"
        for asm in assemblies:
            inst = get_installed_remm_version(remm_dir)
            if inst == args.remm_version and all(
                (remm_dir / f.format(version=inst)).exists()
                for f in REMM_FILES[asm]
            ):
                print(f"\n[remm/{asm}] Already at {args.remm_version}")
                continue
            print(f"\n[remm/{asm}] version {args.remm_version}")
            if not download_remm(args.remm_version, asm, remm_dir):
                failed.append(f"remm/{asm}")

    # ---- CADD ----
    if args.dataset in ("cadd", "all"):
        print("\n" + "=" * 60)
        print(f"Downloading CADD data (mirror: {args.cadd_mirror}) ...")
        print("  Note: SNV files are ~80 GB each. Resume is supported if interrupted.")
        cadd_dir = data_dir / "cadd"
        inst_cadd = get_installed_cadd_versions(cadd_dir)
        for asm in assemblies:
            if inst_cadd.get(asm) == args.cadd_version:
                print(f"\n[cadd/{asm}] Already at {args.cadd_version}")
                continue
            print(f"\n[cadd/{asm}] version {args.cadd_version}")
            if not download_cadd(args.cadd_version, asm, cadd_dir, args.cadd_mirror):
                failed.append(f"cadd/{asm}")

    # ---- Summary ----
    print("\n" + "=" * 60)
    if not failed:
        print("All downloads complete.")
        core_target = args.core_version or (fetch_core_versions() or ["?"])[0]
        print(f"\nIf you updated core data, set in application.properties:")
        if "hg19" in assemblies:
            print(f"  exomiser.hg19.data-version={core_target}")
        if "hg38" in assemblies:
            print(f"  exomiser.hg38.data-version={core_target}")
        print(f"  exomiser.phenotype.data-version={core_target}")
        if "remm" in args.dataset or args.dataset == "all":
            print(f"\nIf you updated REMM, set in application.properties:")
            print(f"  remm.version={args.remm_version}")
        if "cadd" in args.dataset or args.dataset == "all":
            print(f"\nIf you updated CADD, set in application.properties:")
            print(f"  cadd.version={args.cadd_version}")
    else:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
