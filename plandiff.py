"""Difficulty for planned courses, written to difficulty-plan.json. Run: python plandiff.py

The site already scores the courses people are enrolled in (difficulty.py), but that path
needs an instructor: it blends grade history, the professor's own RateMyProfessors difficulty
and the posted syllabus. A course three years out has none of those, so this scores the only
thing that exists yet - the course's grade history across every instructor on record, plus its
level. That is the same "no ratings at all" path difficulty.py already falls back to.
"""
import json, time, collections
import difficulty as D                       # same sources and the same scoring curve

def codes():
    """Every course the plan names, plus every course its dropdowns can offer."""
    plan = json.load(open("plan.data.json", encoding="utf-8"))
    opts = json.load(open("options.json", encoding="utf-8"))
    out = {c["c"] for c in plan["courses"]}
    for s in plan["plus1"]["swaps"]:          # "ECE 56200 · Introduction to Data Management (3)"
        out.add(" ".join(s["in"].split()[:2]))
    for t in plan["plus1"]["grad"]:
        out |= {c["c"] for c in t["courses"]}
    for k in ("sci", "brd", "ece"):
        out |= {c["c"] for c in opts[k]}
    for g in opts["genEd"]:
        out |= {f'{g["s"]} {c["n"].rstrip("*")}' for c in g["c"]}
    # placeholders ("GEN ED 3", "SCI SEL") and the transfer stub carry no real course number
    return {c for c in out if len(c.split()) == 2 and c.split()[1].isdigit()}


def main():
    want = codes()
    subs = sorted({c.split()[0] for c in want})
    print(f"{len(want)} courses across {len(subs)} subjects")
    bc = {}
    for i, s in enumerate(subs, 1):
        try:
            bc.update(D.boilerclasses({s}))
        except Exception as e:                # a dead subject page must not lose the other 59
            print(f"  !! {s}: {e}")
        print(f"  [{i}/{len(subs)}] {s} -> {len(bc)}", flush=True)
        time.sleep(.2)

    out = {}
    for c in sorted(want):
        meta = bc.get(c)
        if not meta: continue
        gpa, _ = D.course_gpa(meta, [])       # no instructor yet, so the course average is the whole story
        if gpa is None: continue
        g, _ = D.score(gpa, None)
        lvl = D.LEVEL[int(c.split()[1][0])]
        out[c] = {"s": D.clamp(round(.5 * g + .3 * g + .2 * lvl, 1)),   # prof term falls back to grades
                  "g": gpa, "cr": meta["credits"], "t": meta["title"]}
    json.dump(out, open("difficulty-plan.json", "w", encoding="utf-8"), separators=(",", ":"))
    print(f"scored {len(out)} of {len(want)}")
    return out


def _test(out):
    assert out, "nothing scored"
    assert all(0 <= v["s"] <= 10 for v in out.values())
    # an easy-grading course must not outrank a brutal one at the same level
    ece = {k: v for k, v in out.items() if k.startswith("ECE 3")}
    assert ece, "no 300-level ECE scored"
    lo = min(ece.values(), key=lambda v: v["s"]); hi = max(ece.values(), key=lambda v: v["s"])
    assert lo["g"] > hi["g"], (lo, hi)        # lower score <=> higher GPA
    assert "ECE 27000" in out


if __name__ == "__main__":
    _test(main())
