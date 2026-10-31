"""Maker-checker sign-off for rules. A rule goes live only after two different people sign it
against the cited page of the official PDF.

    python -m app.verify_rule list
    python -m app.verify_rule sign <rule_id> <your-name>
"""
import datetime as dt
import json
import sys

from app.rules import RULES_DIR, is_published


def _files():
    return {f: json.loads(f.read_text(encoding="utf-8")) for f in sorted(RULES_DIR.glob("*.json"))}


def main(argv: list[str]) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = argv[0] if argv else "list"
    files = _files()
    if cmd == "list":
        for rules in files.values():
            for r in rules:
                s = r["source"]
                print(f"{r['status']:10} {len(r.get('verifications', []))}/2  {r['rule_id']:40} "
                      f"p.{s['page']} item {s['item']}  {s['quote']}")
        return
    if cmd == "sign":
        rule_id, who = argv[1], argv[2]
        for f, rules in files.items():
            for r in rules:
                if r["rule_id"] != rule_id:
                    continue
                if any(v["by"] == who for v in r.get("verifications", [])):
                    sys.exit(f"{who} already signed {rule_id}; a second, different person must sign")
                r.setdefault("verifications", []).append({"by": who, "at": dt.datetime.now().isoformat(timespec="seconds")})
                r["status"] = "published" if len({v["by"] for v in r["verifications"]}) >= 2 else "verified_1"
                assert r["status"] != "published" or is_published(r)
                f.write_text(json.dumps(rules, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"{rule_id}: {r['status']}")
                return
        sys.exit(f"no rule {rule_id}")


if __name__ == "__main__":
    main(sys.argv[1:])
