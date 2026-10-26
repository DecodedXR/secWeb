"""Difficulty for planned courses, written to difficulty-plan.json. Run: python plandiff.py

Same per-course model as difficulty.py - boiler.tools GPA and DFW scaled up for how many
starters its prerequisites filter out, plus how hard the material is - minus what a course
three years out does not have yet: no instructor (so grades stand in for the RateMyProfessors
share, the "no ratings" path difficulty.py already takes) and no posted syllabus. Courses not in
difficulty.MATERIAL fall back to their level for the material share.
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
    want = sorted(codes())
    print(f"{len(want)} courses")
    bt = {}
    for i, c in enumerate(want, 1):
        bt.update(D.boilertools({c: None}))   # one at a time: a dead page must not lose the rest
        if i % 50 == 0: print(f"  [{i}/{len(want)}] {len(bt)} found", flush=True)
    subs = sorted({c.split()[0] for c in want if c not in bt})
    bc = {}
    for s in subs:                            # BoilerClasses for what boiler.tools has no grades for
        try:
            bc.update(D.boilerclasses({s}))
        except Exception as e:
            print(f"  !! {s}: {e}")
        time.sleep(.2)

    out = {}
    for c in want:
        b, meta = bt.get(c), bc.get(c)
        if b and b["gpa"] is not None:
            gpa, dfw = round(b["gpa"], 2), round(b["dfw"], 1)
            s = D.reach(b["prereq"], entry=c.split()[1][0] == "1")
        elif meta and D.course_gpa(meta, [])[0] is not None:
            gpa, dfw, s = D.course_gpa(meta, [])[0], None, 1.0
        else:
            continue
        lvl = D.LEVEL[int(c.split()[1][0])]
        m = D.MATERIAL.get(c, (lvl, None))[0]
        g = D.score(gpa, None)[0]
        f = D.dfw_score(dfw, b and b["w"])
        o = D.general(g if f is None else .6 * g + .4 * f, s)
        out[c] = {"s": D.clamp(round(.65 * o + .35 * m, 1)),   # instructor share falls back to grades
                  "g": gpa, "dfw": dfw, "reach": round(s, 2),
                  "cr": (meta or {}).get("credits") or (b and b["credits"]) or 3,
                  "t": (meta or {}).get("title") or (b and b["title"]) or c}
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
