#!/usr/bin/env python3
"""Domain checks and shortlist rendering for a naming research folder.

  naming.py check <dir> <name>[=<extra.domain>,...] ... [--direction D] [--round N] [--force]
  naming.py shortlist <dir>

`check` looks up <label>.<tld> for every TLD in names.json `tlds`, plus any extra
domains given after `=`, and writes the results into the name's `domains` field.
Entries checked within FRESH_DAYS are skipped, so re-running a round costs nothing.

Lookup order, cheapest first:
  1. DNS (`dig NS`). NOERROR means the domain is delegated -> taken. NXDOMAIN proves
     nothing: registered domains on hold or without nameservers are NXDOMAIN too.
  2. The registry, via RDAP when IANA's bootstrap lists the TLD (200 taken, 404 free),
     otherwise via whois. rdap.org answers 404 for TLDs it has no server for -- .io,
     .co, .eu, .de among them -- so a 404 from it would report google.io as free.

"likely-free" means the registry has no record. Whether the name can actually be
bought at the normal price (registry premium, reserved names) only a registrar knows.

Standard library only; shells out to `dig` and `whois`.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

FRESH_DAYS = 14
TIMEOUT = 10
BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
BOOTSTRAP_CACHE = Path(os.environ.get("TMPDIR", tempfile.gettempdir())) / "naming-rdap-bootstrap.json"
REGISTRAR_STATUSES = {"free", "premium"}

WHOIS_FREE = re.compile(
    r"no match|not found|no entries found|no object found|does not exist|"
    r"no data found|status:\s*(free|available)|is available for",
    re.I,
)
WHOIS_TAKEN = re.compile(
    r"registrar:|nserver:|name server:|creation date:|created:|registered:|"
    r"registry domain id:|status:\s*(connect|active|registered|ok)|on-site\(s\):|registrant:",
    re.I,
)


def today():
    return date.today().isoformat()


def label_for(name):
    return re.sub(r"[^a-z0-9-]", "", name.lower())


def load_bootstrap():
    if BOOTSTRAP_CACHE.exists() and time.time() - BOOTSTRAP_CACHE.stat().st_mtime < 86400:
        data = json.loads(BOOTSTRAP_CACHE.read_text())
    else:
        with urllib.request.urlopen(BOOTSTRAP_URL, timeout=TIMEOUT) as r:
            data = json.load(r)
        BOOTSTRAP_CACHE.write_text(json.dumps(data))
    servers = {}
    for tlds, urls in data["services"]:
        for tld in tlds:
            servers[tld] = urls[0].rstrip("/") + "/"
    return servers


def dns(domain):
    try:
        out = subprocess.run(
            ["dig", "+noall", "+comments", "+time=3", "+tries=2", domain, "NS"],
            capture_output=True, text=True, timeout=TIMEOUT,
        ).stdout
    except subprocess.TimeoutExpired:
        return None
    m = re.search(r"status: (\w+)", out)
    return m.group(1) if m else None


def rdap(domain, server):
    req = urllib.request.Request(server + "domain/" + domain, headers={"Accept": "application/rdap+json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT):
            return "taken"
    except urllib.error.HTTPError as e:
        return "likely-free" if e.code == 404 else None
    except Exception:
        return None


def whois_server(tld):
    try:
        out = subprocess.run(["whois", "-h", "whois.iana.org", tld],
                             capture_output=True, text=True, timeout=TIMEOUT).stdout
    except subprocess.TimeoutExpired:
        return None
    m = re.search(r"^whois:\s*(\S+)", out, re.M)
    return m.group(1) if m else None


def whois(domain, server):
    try:
        out = subprocess.run(["whois", "-h", server, domain],
                             capture_output=True, text=True, timeout=TIMEOUT).stdout
    except subprocess.TimeoutExpired:
        return None
    body = "\n".join(l for l in out.splitlines() if not l.lstrip().startswith(("%", "#", ">>>")))
    if WHOIS_FREE.search(body):
        return "likely-free"
    if WHOIS_TAKEN.search(body):
        return "taken"
    return None


def lookup(domain, rdap_servers, whois_servers):
    tld = domain.rsplit(".", 1)[1]
    if dns(domain) == "NOERROR":
        return {"status": "taken", "method": "dns"}
    if tld in rdap_servers:
        status, method = rdap(domain, rdap_servers[tld]), "rdap"
    elif whois_servers.get(tld):
        status, method = whois(domain, whois_servers[tld]), "whois"
    else:
        status, method = None, "none"
    return {"status": status or "unknown", "method": method}


def is_fresh(entry):
    try:
        checked = datetime.fromisoformat(entry["checked_at"]).date()
    except (KeyError, ValueError):
        return False
    return date.today() - checked < timedelta(days=FRESH_DAYS)


def load(folder):
    path = Path(folder) / "names.json"
    if not path.exists():
        sys.exit(f"{path} not found -- create it with at least {{\"tlds\": [...], \"names\": {{}}}}")
    return path, json.loads(path.read_text())


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def cmd_check(args):
    path, data = load(args.dir)
    names = data.setdefault("names", {})
    todo = []
    for arg in args.names:
        name, _, extra = arg.partition("=")
        entry = names.setdefault(name, {})
        # First sighting wins: a re-check in a later round must not rewrite where a name came from.
        if args.direction:
            entry.setdefault("direction", args.direction)
        if args.round:
            entry.setdefault("round", args.round)
        domains = entry.setdefault("domains", {})
        wanted = [f"{label_for(name)}.{tld}" for tld in data["tlds"]]
        wanted += [d.strip().lower() for d in extra.split(",") if d.strip()]
        for d in wanted:
            if args.force or not is_fresh(domains.get(d, {})):
                todo.append((name, d))

    if todo:
        rdap_servers = load_bootstrap()
        tlds = {d.rsplit(".", 1)[1] for _, d in todo} - set(rdap_servers)
        whois_servers = {t: whois_server(t) for t in tlds}
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = pool.map(lambda nd: lookup(nd[1], rdap_servers, whois_servers), todo)
            for (name, d), res in zip(todo, results):
                old = names[name]["domains"].get(d, {})
                # A registrar's answer is stronger evidence than "the registry has no record".
                if old.get("status") in REGISTRAR_STATUSES and res["status"] == "likely-free":
                    old["checked_at"] = today()
                    continue
                names[name]["domains"][d] = {**res, "checked_at": today()}
        save(path, data)

    for arg in args.names:
        name = arg.partition("=")[0]
        cells = [f"{d}={v['status']}" for d, v in names[name]["domains"].items()]
        print(f"{name}: " + "  ".join(cells))
    print(f"({len(todo)} looked up, the rest fresh within {FRESH_DAYS} days)", file=sys.stderr)


def qualifies(name, entry, tlds, required):
    if entry.get("verdict") in ("rejected", "dropped"):
        return False
    if any(c.get("severity") == "blocking" for c in entry.get("conflicts", [])):
        return False
    # Only the bare name counts; get<name>.com and the like are shown but never qualify it.
    bare = label_for(name) + "."
    open_tlds = {d[len(bare):] for d, v in entry.get("domains", {}).items()
                 if d.startswith(bare) and v.get("status") in ("likely-free", "free")}
    return set(required) <= open_tlds if required else bool(open_tlds & set(tlds))


def cmd_shortlist(args):
    path, data = load(args.dir)
    tlds, required = data["tlds"], data.get("required_tlds", [])
    picked = [(n, e) for n, e in data.get("names", {}).items() if qualifies(n, e, tlds, required)]
    picked.sort(key=lambda ne: (ne[1].get("verdict") != "liked", ne[0]))

    rule = f"{', '.join('.' + t for t in required)} {'is' if len(required) == 1 else 'are'} open" \
        if required else f"at least one of {', '.join('.' + t for t in tlds)} is open"
    lines = [
        "# Shortlist",
        "",
        f"Generated from `names.json` on {today()} -- do not edit by hand. A name is here when it has "
        f"no blocking conflict, has not been rejected, and {rule}. "
        "\"likely-free\" means the registry has no record; \"free\" means a registrar offered it.",
        "",
        "| Name | Direction | Domains | Conflicts | Notes |",
        "|-|-|-|-|-|",
    ]
    for name, e in picked:
        doms = ", ".join(
            f"{d} {v['status']}" + (f" ({v['price']})" if v.get("price") else "")
            for d, v in e.get("domains", {}).items() if v.get("status") != "taken"
        )
        found = [c for c in e.get("conflicts", []) if c.get("severity") != "noise"]
        conflicts = "; ".join(f"{c['who']} ({c['severity']})" for c in found) or "none found"
        notes = " / ".join(filter(None, [
            "**liked**" if e.get("verdict") == "liked" else "",
            e.get("phonetics", ""),
            *e.get("feedback", []),
        ]))
        lines.append(f"| {name} | {e.get('direction', '')} | {doms} | {conflicts} | {notes} |")
    if not picked:
        lines.append("| — | | | | nothing qualifies yet |")
    (Path(args.dir) / "SHORTLIST.md").write_text("\n".join(lines) + "\n")
    print(f"{len(picked)} names on the shortlist")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("dir")
    c.add_argument("names", nargs="+")
    c.add_argument("--direction", help="record the direction these names came from")
    c.add_argument("--round", type=int, help="record the round these names were checked in")
    c.add_argument("--force", action="store_true", help="re-check even fresh entries")
    c.set_defaults(func=cmd_check)
    s = sub.add_parser("shortlist")
    s.add_argument("dir")
    s.set_defaults(func=cmd_shortlist)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
