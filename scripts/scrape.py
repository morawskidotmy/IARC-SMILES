#!/usr/bin/env python3
"""Scrape IARC carcinogen classifications and fetch canonical SMILES from PubChem.

Saves results incrementally — each SMILES is flushed to disk as soon as it's found.
At the end, files are sorted and deduplicated.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

IARC_URL = "https://monographs.iarc.who.int/list-of-classifications/"
PUBCHEM_API = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{}/property/CanonicalSMILES/JSON"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

GROUP_MAP = {
    "1": "group1",
    "2A": "group2a",
    "2B": "group2b",
    "3": "group3",
}


def load_smi(filepath: str) -> dict[str, str]:
    """Load .smi file into {smiles: name} dict."""
    entries = {}
    if os.path.exists(filepath):
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    entries[parts[0]] = parts[1]
    return entries


def sort_and_dedup_smi(filepath: str) -> int:
    """Sort a .smi file by name, deduplicate by SMILES. Returns entry count."""
    entries = load_smi(filepath)
    with open(filepath, "w") as f:
        for smiles, name in sorted(entries.items(), key=lambda x: x[1].lower()):
            f.write(f"{smiles}\t{name}\n")
    return len(entries)


def scrape_iarc() -> dict[str, list[tuple[str, str]]]:
    """Scrape all agents from the IARC classifications page.

    Returns dict of group -> list of (cas, name).
    """
    print("Starting headless Firefox...")
    opts = Options()
    opts.add_argument("--headless")
    opts.set_preference("dom.webdriver.enabled", False)
    opts.set_preference(
        "general.useragent.override",
        "Mozilla/5.0 (X11; Linux x86_64; rv:137.0) Gecko/20100101 Firefox/137.0",
    )

    driver = webdriver.Firefox(options=opts)
    try:
        driver.get(IARC_URL)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.dataTable")))
        time.sleep(2)

        agents: dict[str, list[tuple[str, str]]] = {g: [] for g in GROUP_MAP}
        seen: dict[str, set[str]] = {g: set() for g in GROUP_MAP}

        def collect_page():
            for row in driver.find_elements(By.CSS_SELECTOR, "table.dataTable tbody tr"):
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) < 3:
                    continue
                cas = cols[0].text.strip()
                name = cols[1].text.strip()
                group = cols[2].text.strip()
                if name and group in GROUP_MAP and name not in seen[group]:
                    seen[group].add(name)
                    agents[group].append((cas, name))

        collect_page()
        while True:
            try:
                nxt = driver.find_element(By.CSS_SELECTOR, ".paginate_button.next:not(.disabled)")
                driver.execute_script("arguments[0].click();", nxt)
                time.sleep(1.5)
                collect_page()
            except Exception:
                break

        total = sum(len(v) for v in agents.values())
        print(f"Scraped {total} agents across {len(agents)} groups")
        return agents
    finally:
        driver.quit()


def pubchem_lookup(term: str) -> str | None:
    """Query PubChem for canonical SMILES by name or CAS."""
    url = PUBCHEM_API.format(urllib.request.quote(term, safe=""))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "iarc-smiles-scraper/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            props = data.get("PropertyTable", {}).get("Properties", [])
            if props:
                return props[0].get("CanonicalSMILES") or props[0].get("ConnectivitySMILES") or None
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        pass
    return None


def clean_name_variants(name: str) -> list[str]:
    """Generate cleaned name variants for PubChem lookup."""
    variants: list[str] = []

    cleaned = re.sub(r"\s*\(see\s[^)]*\)", "", name, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\([^)]*infection[^)]*\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\(occupational[^)]*\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\(workplace[^)]*\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\(consumption of\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\(combined\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\(technical-grade\)", "", cleaned, flags=re.IGNORECASE)

    for pat in [
        r",?\s+in alcoholic beverages$",
        r",?\s+associated with consumption of alcoholic beverages$",
        r",?\s+analgesic mixtures containing$",
        r",?\s+plus ultraviolet A radiation$",
        r",?\s+plants containing$",
        r",?\s+Chinese-style$",
        r",?\s+as phosphate$",
        r",?\s+dyes metabolized to$",
        r",?\s+mixture of isotopes$",
        r",?\s+all forms.*$",
        r",?\s+all types.*$",
        r",?\s+including\b.*$",
    ]:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()

    if cleaned and cleaned != name:
        variants.append(cleaned)

    # "Perfluorooctanoic acid (PFOA)" -> try without abbr, then abbr alone
    m = re.match(r"^(.+?)\s*\(([A-Z][A-Z0-9-]{1,10})\)\s*$", cleaned or name)
    if m:
        variants.append(m.group(1).strip())
        variants.append(m.group(2).strip())

    # "Foo (Semustine)" -> try alternate name
    m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", cleaned or name)
    if m and not re.match(r"^[A-Z][A-Z0-9-]{1,10}$", m.group(2)):
        base, alt = m.group(1).strip(), m.group(2).strip()
        if base and base not in variants:
            variants.append(base)
        if alt and alt not in variants:
            variants.append(alt)

    # Split compound entries
    base = cleaned or name
    if " and " in base:
        for p in base.split(" and "):
            p = re.sub(r"\s*\([^)]*\)", "", p).strip()
            if p and p not in variants:
                variants.append(p)
    if "; " in base:
        for p in base.split("; "):
            p = re.sub(r"\s*\([^)]*\)", "", p).strip()
            if p and p not in variants:
                variants.append(p)

    return variants


def lookup_smiles(cas: str, name: str) -> str | None:
    """Try CAS, original name, then cleaned variants."""
    # 1. CAS number
    if cas and cas.strip() and cas != "-":
        for c in cas.split(","):
            c = c.strip()
            if c:
                result = pubchem_lookup(c)
                if result:
                    return result
                time.sleep(0.25)

    # 2. Original name
    result = pubchem_lookup(name)
    if result:
        return result
    time.sleep(0.25)

    # 3. Cleaned variants
    for variant in clean_name_variants(name):
        result = pubchem_lookup(variant)
        if result:
            return result
        time.sleep(0.25)

    return None


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Load existing data for incremental updates
    existing: dict[str, dict[str, str]] = {}
    for group_key, file_stem in GROUP_MAP.items():
        existing[group_key] = load_smi(os.path.join(DATA_DIR, f"{file_stem}.smi"))

    existing_names: dict[str, set[str]] = {}
    for gk, entries in existing.items():
        existing_names[gk] = {n.lower() for n in entries.values()}

    # Scrape
    print("Scraping IARC classifications...")
    agents = scrape_iarc()

    # Open file handles for incremental appending
    handles: dict[str, object] = {}
    for group_key, file_stem in GROUP_MAP.items():
        filepath = os.path.join(DATA_DIR, f"{file_stem}.smi")
        if not os.path.exists(filepath):
            open(filepath, "w").close()
        handles[group_key] = open(filepath, "a")

    failed: list[tuple[str, str, str]] = []
    stats: dict[str, dict[str, int]] = {gk: {"new": 0, "skip": 0, "fail": 0} for gk in GROUP_MAP}

    try:
        for group_key in ["1", "2A", "2B", "3"]:
            group_agents = agents.get(group_key, [])
            if not group_agents:
                continue

            print(f"\n--- Group {group_key} ({len(group_agents)} agents) ---")

            for cas, name in group_agents:
                if name.lower() in existing_names[group_key]:
                    stats[group_key]["skip"] += 1
                    continue

                print(f"  [{group_key}] {name} (CAS: {cas or 'none'})...", end=" ", flush=True)
                smiles = lookup_smiles(cas, name)

                if smiles:
                    if smiles not in existing[group_key]:
                        existing[group_key][smiles] = name
                        existing_names[group_key].add(name.lower())
                        # Flush to disk immediately
                        handles[group_key].write(f"{smiles}\t{name}\n")
                        handles[group_key].flush()
                        stats[group_key]["new"] += 1
                        print(f"✓ {smiles[:60]}")
                    else:
                        stats[group_key]["skip"] += 1
                        print(f"DEDUP (= {existing[group_key][smiles]})")
                else:
                    cas_str = cas if cas and cas.strip() and cas != "-" else "none"
                    failed.append((group_key, name, cas_str))
                    stats[group_key]["fail"] += 1
                    print("✗")

    finally:
        for fh in handles.values():
            fh.close()

    # Sort and deduplicate all files
    print("\nSorting and deduplicating...")
    for group_key, file_stem in GROUP_MAP.items():
        filepath = os.path.join(DATA_DIR, f"{file_stem}.smi")
        count = sort_and_dedup_smi(filepath)
        s = stats[group_key]
        print(f"  Group {group_key}: {count} total ({s['new']} new, {s['skip']} skipped, {s['fail']} failed)")

    # Write failed lookups
    failed_path = os.path.join(DATA_DIR, "failed_lookups.txt")
    with open(failed_path, "w") as f:
        for group, name, cas in sorted(failed, key=lambda x: (x[0], x[1].lower())):
            f.write(f"{group}\t{name}\t{cas}\n")

    print(f"\nFailed lookups: {len(failed)} agents (saved to {failed_path})")


if __name__ == "__main__":
    main()
