"""Estimated difficulty per person, from BoilerClasses grade data + RateMyProfessors.

Scrapes both sources, scores every course out of 10, writes difficulty.json.
Bundled schedules only: CSVs uploaded in the browser are never scored.
Run: python difficulty.py
"""
import json, re, io, collections, urllib.request, time
import syllabus

SCHOOL = "U2Nob29sLTc4Mw=="                        # Purdue, RateMyProfessors node id
RMPQ = ("query S($t:String!,$s:ID!){newSearch{teachers(query:{text:$t,schoolID:$s},first:8)"
        "{edges{node{firstName lastName department avgRating avgDifficulty numRatings}}}}}")
GET = lambda u: urllib.request.urlopen(
    urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode("utf-8", "replace")


def instructors(s):
    """'Diaz Rivas, Rosa E (Instr) Wu, Can (Instr)' -> ['Rosa Diaz Rivas', 'Can Wu']"""
    out = []
    for part in (x.strip().strip(",") for x in re.split(r"\(Instr\)", s or "") if x.strip()):
        if "," in part:
            last, first = part.split(",", 1)
            out.append((first.split() or [""])[0] + " " + last.strip())
    return [n.strip() for n in out if n.strip()]


def boilerclasses(subjects):
    """Every course in a subject already sits in the /dir page's Next.js payload."""
    out = {}
    for sub in sorted(subjects):
        d = json.loads(re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                                 GET("https://boilerclasses.com/dir/" + sub), re.S).group(1))
        for c in d["props"]["pageProps"]["courses"]:
            v = c["value"]
            out[v["subjectCode"] + " " + str(int(v["courseCode"]))] = {
                "title": v["title"], "credits": v["credits"][0], "gpa": v["gpa"]}
    return out


def ratemyprofessors(names):
    out = {}
    for name in sorted(names):
        first, last = name.split(" ", 1)
        body = json.dumps({"query": RMPQ, "variables": {"t": name, "s": SCHOOL}}).encode()
        req = urllib.request.Request("https://www.ratemyprofessors.com/graphql", data=body,
                                     headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0",
                                              "Authorization": "Basic dGVzdDp0ZXN0"})
        try:
            eds = [e["node"] for e in json.loads(urllib.request.urlopen(req, timeout=30).read())
                   ["data"]["newSearch"]["teachers"]["edges"]]
        except Exception:
            eds = []
        hit = ([n for n in eds if n["lastName"].lower() == last.lower()
                and n["firstName"].lower().startswith(first.lower())]
               or [n for n in eds if n["lastName"].lower() == last.lower()])
        out[name] = hit[0] if hit and hit[0]["numRatings"] else None
        time.sleep(.25)
    return out


def course_gpa(bc, who_teaches):
    """Their own instructor's GPA if that pairing has history, else the course average."""
    gpa = bc["gpa"]
    for who in who_teaches:
        if who in gpa and gpa[who]:
            return round(sum(t[-1] for t in gpa[who].values()) / len(gpa[who]), 2), who
    terms = [t[-1] for by in gpa.values() for t in by.values()]
    return (round(sum(terms) / len(terms), 2), None) if terms else (None, None)


clamp = lambda x, lo=0, hi=10: max(lo, min(hi, x))
LEVEL = {1: 3.0, 2: 5.0, 3: 7.0, 4: 8.0, 5: 9.0}


def score(gpa, rmp):
    """0-10. Grades carry it; the professor's own difficulty and the course level nudge it."""
    g = 5.0 if gpa is None else clamp((3.9 - gpa) / 1.5 * 10)   # 3.9 GPA course -> 0, 2.4 -> 10
    if rmp:
        n = rmp["numRatings"]
        p = 5.0 + ((rmp["avgDifficulty"] - 1) / 4 * 10 - 5.0) * n / (n + 5)   # thin samples pull to average
    else:
        p = g                                                                 # no ratings: grades speak for both
    return g, p


def stretch(x):     # spread the top: a hard term should read hard, not "6.1 like everyone else"
    return 5 + (x - 5) * 1.4 if x > 5 else x


def main():
    sched = json.load(open("schedule.json", encoding="utf-8"))
    taking = collections.defaultdict(list)                   # (person, course) -> instructors, lecture ones first
    sections = {}
    for who, p in sched.items():
        for b in p["blocks"]:
            sections.setdefault((who, b["course"]), b["section"].split("-")[-1])
            t = taking[(who, b["course"])]
            for n in instructors(b.get("instructor")):
                if n not in t: t.insert(0, n) if not re.search(r"Lab|Recit", b["type"]) else t.append(n)
        for u in p.get("untimed", []):
            taking.setdefault((who, u["course"]), [])

    bc = boilerclasses({c.split()[0] for _, c in taking})
    syl = syllabus.fetch({(c, s) for (_, c), s in sections.items()})
    rmp = ratemyprofessors({n for v in taking.values() for n in v})

    people = {}
    for (who, course), profs in sorted(taking.items()):
        meta = bc.get(course, {"title": course, "credits": 3, "gpa": {}})
        gpa, gsrc = course_gpa(meta, profs)
        prof = next((p for p in profs if rmp.get(p)), None)
        r = rmp.get(prof)
        g, p = score(gpa, r)
        lvl = LEVEL[int(course.split()[1][0])]
        doc = syl.get(course, {})
        rig, flags = syllabus.rigor(doc["text"]) if doc.get("text") else (None, [])
        # The syllabus is a nudge, not a pillar: it says how the course is run, not how hard it grades.
        d = clamp(round(.5 * g + .3 * p + .2 * lvl + (0 if rig is None else (rig - 5) * .2), 1))
        cr = meta["credits"] or 1
        people.setdefault(who, {"courses": []})["courses"].append({
            "course": course, "title": meta["title"], "credits": cr, "score": d,
            "gpa": gpa, "gpaOf": gsrc, "prof": prof, "rating": r and r["avgRating"],
            "profDiff": r and r["avgDifficulty"], "ratings": r["numRatings"] if r else 0,
            "dept": r and r["department"], "syllabus": rig, "syllabusOf": doc.get("section"), "syllabusUrl": doc.get("url"),
            "desc": syllabus.describe(doc["text"]) if doc.get("text") else None, "flags": [{"why": n, "w": w} for n, w in flags],
            "parts": {"grades": round(g, 1), "prof": round(p, 1), "level": lvl}})

    for who, p in people.items():
        cr = sum(c["credits"] for c in p["courses"])
        base = sum(c["score"] * c["credits"] for c in p["courses"]) / cr
        # 15 credits / 15 contact hours is a normal term. Hours count too: a 1-credit lab or
        # ensemble still eats an afternoon, and credits alone said those weeks were empty.
        hrs = sum(b["end"] - b["start"] for b in sched[who]["blocks"]) / 60
        load = clamp((cr - 15) * .15 + (hrs - 15) * .08, -1.5, 2.5)
        p["credits"], p["hours"], p["load"] = cr, round(hrs, 1), round(load, 1)
        p["score"] = clamp(round(stretch(base + load), 1))
        p["courses"].sort(key=lambda c: -c["score"])
    json.dump(people, open("difficulty.json", "w", encoding="utf-8"), indent=1)
    return people


def _test(people):
    assert instructors("Diaz Rivas, Rosa E (Instr) Wu, Can (Instr)") == ["Rosa Diaz Rivas", "Can Wu"]
    assert round(score(3.9, None)[0], 6) == 0 and round(score(2.4, None)[0], 6) == 10
    assert score(None, {"avgDifficulty": 5, "numRatings": 5})[1] == 7.5    # half weight at n=5
    assert set(people) == set(json.load(open("schedule.json", encoding="utf-8")))
    assert all(0 <= c["score"] <= 10 for p in people.values() for c in p["courses"])
    assert all(p["courses"] for p in people.values())
    assert stretch(4) == 4 and stretch(7) == 7.8
    scored = [c for p in people.values() for c in p["courses"] if c["syllabus"] is not None]
    assert len(scored) > 20 and all(0 <= c["syllabus"] <= 10 for c in scored), len(scored)


if __name__ == "__main__":
    ppl = main()
    _test(ppl)
    for w, p in sorted(ppl.items(), key=lambda x: -x[1]["score"]):
        print(f"{w:7} {p['score']:4.1f}/10  {p['credits']:2}cr {p['hours']:4.1f}h  " +
              " ".join(f"{c['course'].replace(' ','')}:{c['score']}" for c in p["courses"]))
