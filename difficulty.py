"""Estimated difficulty per person, from boiler.tools + BoilerClasses grade data, RateMyProfessors,
and a hand-assessed read of how hard each course's material is to understand.

Scrapes the sources, scores every course out of 10, sums them into a semester load, writes difficulty.json.
Bundled schedules only: CSVs uploaded in the browser are never scored.
Run: python difficulty.py
"""
import json, re, io, math, collections, urllib.request, time
from statistics import NormalDist
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


def _unflatten(a):
    """SvelteKit's __data.json is devalue: one flat array, every container holding indexes into it."""
    memo = {}
    def h(i):
        if i < 0: return None
        if i not in memo:
            v = a[i]
            memo[i] = [h(x) for x in v] if isinstance(v, list) else {k: h(x) for k, x in v.items()} if isinstance(v, dict) else v
        return memo[i]
    return h(0)


def _bt(slug):
    node = json.loads(GET(f"https://boiler.tools/c/{slug}/__data.json"))["nodes"][-1]
    return _unflatten(node["data"]) if node and node.get("type") == "data" else None


RECENT = 202310                                  # Fall 2022 on: the last four academic years


def boilertools(courses):
    """{course: block title} -> recent GPA, DFW and withdrawal rates, peer percentile, per-instructor records.
    Variable-title courses (ENGR 10301) list topics; the block's title picks the one being taken."""
    out = {}
    for course, title in sorted(courses.items()):
        try:
            o = _bt(course.lower().replace(" ", "-"))
            if o and "topics" in o:
                t = [t for t in o["topics"] if t["title"].lower() == (title or "").lower()]
                o = _bt(t[0]["slug"]) if t else None
        except Exception:
            o = None
        time.sleep(.2)
        if not o or not o.get("course"):
            continue
        c = o["course"]
        terms = [t for t in (o.get("termStats") or {}).values() if t["gpa"] is not None]
        recent = [t for t in terms if t["termCode"] >= RECENT]
        # Half the whole record, half the last four years: courses drift (ECE 20001 swung 2.1-3.1 by
        # term), but a one-section course is noisy term to term and its bad years still count.
        mean = lambda k: (c[k] + sum(t[k] for t in recent) / len(recent)) / 2 if len(recent) >= 2 else c[k]
        out[course] = {"title": c["title"], "gpa": mean("gpa"), "dfw": mean("pctDfw"), "w": mean("pctWithdraw"),
                       "allDfw": c["pctDfw"], "pct": c["difficulty"], "peer": c["peerGroup"], "recent": len(recent) >= 2,
                       "credits": (o.get("catalog") or {}).get("creditsMin"),
                       "prereq": (o.get("catalog") or {}).get("prereqTree"),
                       "inst": o.get("instructors") or []}
    return out


_bt_cache = {}


def _course(course):
    """(pass rate, prerequisite tree, sections since Fall 2024) for a course, or None when boiler.tools
    has no grades or catalog entry for it."""
    if course not in _bt_cache:
        try:
            o = _bt(course.lower().replace(" ", "-"))
        except Exception:
            o = None
        time.sleep(.15)
        ok = o and o.get("course") and o["course"].get("pctDfw") is not None and o.get("catalog")
        live = ok and sum(t["sectionsCount"] for t in (o.get("termStats") or {}).values() if t["termCode"] >= 202510)
        _bt_cache[course] = (1 - o["course"]["pctDfw"] / 100, o["catalog"].get("prereqTree"), live) if ok else None
    return _bt_cache[course]


_req = {}


def required(course, depth=0):
    """Every course passed before `course` on the mainstream route, as a set: ancestors shared by two
    branches (MA 26600 under both halves of ECE 30100) must filter students once, not twice.
    ponytail: depth capped at 8, one fetch per course."""
    if course in _req or depth > 8:
        return _req.get(course, set())
    _req[course] = set()                                  # cycle guard
    c = _course(course)
    _req[course] = (chain(c[1], depth + 1, entry=course.split()[1][0] == "1") if c else None) or set()
    return _req[course]


def chain(tree, depth=0, entry=False):
    """The courses a prerequisite tree makes you pass first. AND takes them all; OR follows the
    mainstream route - the option with the most sections taught lately, not a side door like a
    retired code (ECE 20100) or another major's version (BME 30500). A concurrent prerequisite is
    not passed yet, but everything it requires is (ECE 27000 takes ECE 20001 alongside, so not
    before its calculus). A placement test is the mainstream way into a 100-level course and only
    there; above that AP credit is the exception, not the route. None when nothing is known."""
    if not tree:
        return None
    k = tree.get("kind")
    if k == "test":
        return set() if entry else None
    if k == "course":
        if tree.get("level") != "Undergraduate":
            return None
        name = f'{tree["subject"]} {tree["number"]}'
        if not _course(name):
            return None                                   # retired or unknown code: not a route
        return required(name, depth) | (set() if tree.get("concurrent") else {name})
    items = tree.get("items", [])
    if k == "or":
        if entry and any(t.get("kind") == "test" for t in items):
            return set()
        live = [(_course(f'{t["subject"]} {t["number"]}') or (0, 0, 0))[2] if t.get("kind") == "course" else -1 for t in items]
        order = sorted(range(len(items)), key=lambda i: -live[i])
        return next((x for x in (chain(items[i], depth) for i in order) if x is not None), None)
    parts = [x for x in (chain(t, depth, entry) for t in items) if x is not None]
    return set().union(*parts) if parts else None


# Failures land on the same students: whoever fails MA 16100 is likelier to fail PHYS 17200 too, so
# multiplying pass rates counts one struggling student as several. Grades across courses correlate
# about 0.5; each student gets one shared ability and each course a threshold matching its DFW.
# RHO = 0 is the plain product, 1 is "only the hardest prerequisite filters anyone".
# ponytail: retakes are not modelled - DFW counts enrollments and the public data has no student
# IDs - so H in general() stays below 1 to leave room for those who retake and pass.
RHO = 0.5


def joint(passes, rho=RHO):
    """P(a student passes every course) given each course's pass rate and correlation rho."""
    N, r = NormalDist(), math.sqrt(rho)
    cut = [N.inv_cdf(1 - min(max(p, 1e-6), 1 - 1e-6)) for p in passes]   # fail below the cut
    if not cut:
        return 1.0
    # ponytail: midpoint rule over the shared ability, 1201 steps; exact to ~1e-4, plenty here
    xs = [-6 + i * .01 for i in range(1201)]
    return sum(N.pdf(x) * .01 * math.prod(1 - N.cdf((c - r * x) / math.sqrt(1 - rho)) for c in cut) for x in xs)


def reach(tree, entry=False):
    """Share of students starting from scratch who pass everything the course requires first,
    from each prerequisite's DFW rate on boiler.tools, with failures correlated across courses."""
    return joint([_course(c)[0] for c in (chain(tree, entry=entry) or ())])


def instructor_record(bt, who_teaches):
    """Shift the course GPA by the instructor's grading effect: their sections against other
    instructors' sections of the same course in the same term, already shrunk by boiler.tools.
    A co-taught or sole-instructor course has no effect - there is nothing to compare against - so
    its numbers stay the course's (ECE 33700 once read 15% DFW by crediting Swabey with a shared record).
    Returns (gpa, dfw, instructor or None)."""
    for who in who_teaches:
        first, last = who.split(" ", 1)
        for i in bt["inst"]:
            l, f = (x.strip() for x in (i["instructorName"].split(",", 1) + [""])[:2])
            if l.lower() == last.lower() and f.lower().startswith(first.lower()) and i["effect"] is not None \
                    and (i["effectN"] or 0) >= 3:
                return round(bt["gpa"] + i["effect"], 2), round(bt["dfw"], 1), who
    return round(bt["gpa"], 2), round(bt["dfw"], 1), None


def course_gpa(bc, who_teaches):
    """Their own instructor's GPA if that pairing has history, else the course average."""
    gpa = bc["gpa"]
    for who in who_teaches:
        if who in gpa and gpa[who]:
            return round(sum(t[-1] for t in gpa[who].values()) / len(gpa[who]), 2), who
    terms = [t[-1] for by in gpa.values() for t in by.values()]
    return (round(sum(terms) / len(terms), 2), None) if terms else (None, None)


clamp = lambda x, lo=0, hi=10: max(lo, min(hi, x))
LEVEL = {1: 3.0, 2: 5.0, 3: 7.0, 4: 8.0, 5: 9.0}          # stands in for MATERIAL on unlisted courses

# How hard the material itself is to understand and be tested on, 0-10, independent of how it is
# graded: abstraction, how much math it leans on, how new the mental model is, and whether exams
# are timed problem-solving or recall. A curve can hide a hard subject and a heavy workload can
# sink an easy one; grades and DFW catch the second, this catches the first.
# ponytail: hand-assessed per course; a course missing here falls back to its level.
MATERIAL = {
    "ACCT 21200": (4.5, "debits, credits and accrual timing across four statements: procedural, but a new vocabulary and multi-step exam problems"),
    "ANTH 25400": (2.0, "reading-based look at pseudoarchaeology; intuitive concepts, assessed through reading and writing"),
    "BAND 11800": (1.0, "performance ensemble entered by audition; the skill is already there"),
    "BIOL 58601": (7.5, "graduate ecology: population and community models, species-interaction dynamics and primary literature"),
    "BIOL 58602": (5.0, "field and lab experiment design plus the statistics to analyse it, paired with the lecture"),
    "CGT 11600": (4.5, "spatial visualisation, projection and constraint-based CAD; the DFW is weekly lab volume more than ideas"),
    "CGT 36500": (2.5, "self-directed team game project, graded on progress; little new theory"),
    "CHM 11510": (6.5, "stoichiometry, gas laws, thermochemistry, the quantum atom and bonding on fast timed common exams"),
    "CHM 11520": (3.0, "procedural lab work and reports tied to the lecture"),
    "CNIT 24200": (5.5, "directory services, authentication and enterprise Linux/Windows admin: many moving parts in labs that break"),
    "CNIT 27000": (4.5, "security models, risk and controls, crypto basics: broad and memory-heavy, not deep"),
    "EAPS 10600": (1.0, "natural hazards through movies, asynchronous online"),
    "ECE 20001": (7.0, "first real circuit analysis: nodal/mesh, Thevenin, op-amps, RC/RL transients and phasors on timed common exams"),
    "ECE 20007": (3.5, "measurement lab that follows the lecture; procedures more than theory"),
    "ECE 20869": (7.0, "first proof course: logic, induction, recurrences, counting and finite-state machines, all abstract"),
    "ECE 20875": (4.5, "Python plus introductory statistics and ML; concepts are intro-level, the work is projects"),
    "ECE 26400": (6.5, "pointers, memory management, recursion and dynamic structures in C, graded by strict autograders"),
    "ECE 27000": (6.0, "Boolean algebra, K-maps, sequential state machines and Verilog: a new mental model, but well structured"),
    "ECE 29401": (1.0, "orientation seminar"),
    "ECE 30100": (8.5, "convolution and Fourier, Laplace and z-transforms in continuous and discrete time: the most mathematical ECE core course"),
    "ECE 33700": (7.5, "synthesisable SystemVerilog, timing closure and a semester-long team ASIC built to industry flow; 12% withdraw"),
    "ECE 36200": (7.0, "assembly, interrupts and microcontroller peripherals, debugged on real hardware against the clock"),
    "ECE 36800": (7.0, "trees, graphs, hashing and complexity, implemented in C against hidden test cases"),
    "ECON 25100": (4.5, "graphical models, elasticity and optimisation; the math is light, the reasoning is new"),
    "ENGR 10301": (1.0, "first-year engineering seminar"),
    "ENGR 13100": (2.5, "team design projects and engineering habits; workload, not difficult concepts"),
    "MA 26100": (6.0, "3D visualisation, partial derivatives, multiple integrals and vector calculus on common exams"),
    "MA 26600": (6.0, "a toolkit of solution methods (linear, Laplace, series, systems) to keep straight under time"),
    "ME 20000": (7.5, "entropy, property tables and control volumes: conceptually slippery, long multi-step problems"),
    "ME 27000": (7.0, "free-body diagrams, equilibrium, trusses and internal loads; every exam problem is set up from scratch"),
    "MSE 23000": (6.0, "bonding, crystal lattices, defects, X-ray diffraction and phase diagrams: spatial and quantitative"),
    "MSE 25000": (5.5, "applied statics, dynamics and mechanics with computational tools"),
    "MSE 39000": (1.0, "pass/fail seminar talks"),
    "MSE 42000": (5.5, "polymer chemistry and physics: chain structure, morphology and properties, leaning on organic chemistry"),
    "PHYS 23300": (5.0, "mechanics, diffusion, fluids and thermodynamics for life sciences; conceptual with light calculus"),
    "PHYS 27200": (7.0, "fields, Gauss's law, potential and induction: invisible abstractions with vector calculus"),
    "SCI 39500": (1.5, "mentorship program credit"),
    "SCLA 10200": (2.5, "reading, writing and discussion of world literature"),
    "SOC 10000": (2.0, "survey of sociological concepts; recall-based"),
    "VIP 27920": (2.5, "research team participation, graded on contribution"),
    "WGSS 28000": (2.0, "introductory survey; reading and discussion"),
}


def score(gpa, rmp):
    """0-10. Grades carry it; the professor's own difficulty and the course level nudge it."""
    g = 5.0 if gpa is None else clamp((3.9 - gpa) / 1.5 * 10)   # 3.9 GPA course -> 0, 2.4 -> 10
    if rmp:
        n = rmp["numRatings"]
        p = 5.0 + ((rmp["avgDifficulty"] - 1) / 4 * 10 - 5.0) * n / (n + 5)   # thin samples pull to average
    else:
        p = g                                                                 # no ratings: grades speak for both
    return g, p


# Every grade statistic is measured on whoever reached the course. 35% of ECE 33700 starters were
# filtered out by its prerequisites before anyone took it; a 24% DFW among the survivors is harder,
# for a general student, than 24% in a course anyone can walk into. Students the chain filtered out
# are taken to fail at half the rate the course's own outcome implies on top. ponytail: one factor,
# H, not a model of who switches majors; raise it toward 1 to treat every filtered student as a fail.
H = 0.5


def general(o, s):
    """Outcome score among survivors -> for a general student, given chain survival s."""
    return o + H * (1 - s) * (10 - o)


def dfw_score(dfw, w):
    """0-10 from D/F/W share, withdrawals counted a second time at half weight: GPA never sees
    the students who left. 3% -> 0, 28% -> 10."""
    return None if dfw is None else clamp((dfw + .5 * (w or 0) - 3) / 25 * 10)


# The semester is the work summed, not averaged: an easy seminar adds a little, never subtracts.
# Each course is worth credits x (score/10)^2 "full-strength credits" - convex, because an 8 eats
# far more than twice the evenings a 4 does. K sets where the curve bends: 18 credits of
# straight 8s reads about 8.5, 15 credits of 3s about 2.0.
K = 6.0


def weight(cr, hrs):
    """Credits undercount labs: ECE 33700 is 2 credits and 3.7 hours a week in the room. A 50-minute
    lecture is one credit, so hours x 1.2 is the credit-hours actually sat; meet halfway."""
    return max(cr, (cr + hrs * 1.2) / 2)


def work(cr, s):
    return cr * (s / 10) ** 2


def semester(courses):
    """0-10 from the summed work of (weighted credits, score) pairs."""
    w = sum(work(c, s) for c, s in courses)
    return clamp(10 * (1 - math.exp(-w / K))), w


def main():
    sched = json.load(open("schedule.json", encoding="utf-8"))
    taking = collections.defaultdict(list)                   # (person, course) -> instructors, lecture ones first
    sections, titles = {}, {}
    for who, p in sched.items():
        for b in p["blocks"]:
            sections.setdefault((who, b["course"]), b["section"].split("-")[-1])
            titles.setdefault(b["course"], b.get("title"))
            t = taking[(who, b["course"])]
            for n in instructors(b.get("instructor")):
                if n not in t: t.insert(0, n) if not re.search(r"Lab|Recit", b["type"]) else t.append(n)
        for u in p.get("untimed", []):
            taking.setdefault((who, u["course"]), [])
            titles.setdefault(u["course"], u.get("title"))

    bc = boilerclasses({c.split()[0] for _, c in taking})
    bt = boilertools(titles)
    syl = syllabus.fetch({(c, s) for (_, c), s in sections.items()})
    rmp = ratemyprofessors({n for v in taking.values() for n in v})

    people = {}
    for (who, course), profs in sorted(taking.items()):
        meta = bc.get(course, {"title": titles.get(course) or course, "credits": None, "gpa": {}})
        b = bt.get(course)
        if b and b["gpa"] is not None:
            gpa, dfw, gsrc = instructor_record(b, profs)
            src = "boiler.tools"
        else:                                                 # BoilerClasses still covers what boiler.tools lacks
            gpa, gsrc = course_gpa(meta, profs)
            dfw, src = b and b["dfw"], ("BoilerClasses" if gpa is not None else None)
        lvl = LEVEL[int(course.split()[1][0])]
        m, why = MATERIAL.get(course, (lvl, None))
        g = m if gpa is None else score(gpa, None)[0]         # no grades: the material is all there is to go on
        f = dfw_score(dfw, b and b["w"])
        o = g if f is None else .6 * g + .4 * f               # grade outcome: GPA and who did not make it through
        s = reach(b["prereq"], entry=course.split()[1][0] == "1") if b else 1.0
        o = general(o, s)
        prof = next((p for p in profs if rmp.get(p)), None)
        r = rmp.get(prof)
        p = general(score(None, r)[1], s) if r else o         # raters are survivors too; no ratings: outcomes speak
        doc = syl.get(course, {})
        rig, flags = syllabus.rigor(doc["text"]) if doc.get("text") else (None, [])
        # The syllabus is a nudge, not a pillar: it says how the course is run, not how hard it grades.
        d = clamp(round(.45 * o + .2 * p + .35 * m + (0 if rig is None else (rig - 5) * .2), 1))
        cr = meta["credits"] or (b and b["credits"]) or 1
        people.setdefault(who, {"courses": []})["courses"].append({
            "course": course, "title": meta["title"], "credits": cr, "score": d,
            "gpa": gpa, "gpaOf": gsrc, "gpaSrc": src, "dfw": dfw, "withdraw": b and round(b["w"], 1),
            "dfwAll": b and round(b["allDfw"], 1), "reach": round(s, 2),
            "peerPct": b and b["pct"], "peer": b and b["peer"], "recent": bool(b and b["recent"]),
            "prof": prof, "rating": r and r["avgRating"],
            "profDiff": r and r["avgDifficulty"], "ratings": r["numRatings"] if r else 0,
            "dept": r and r["department"], "material": m, "materialWhy": why,
            "syllabus": rig, "syllabusOf": doc.get("section"), "syllabusUrl": doc.get("url"),
            "desc": syllabus.describe(doc["text"]) if doc.get("text") else None, "flags": [{"why": n, "w": w} for n, w in flags],
            "parts": {"grades": round(o, 1), "prof": round(p, 1), "material": m}})

    for who, p in people.items():
        hrs = sum(b["end"] - b["start"] for b in sched[who]["blocks"]) / 60
        for c in p["courses"]:
            h = sum(b["end"] - b["start"] for b in sched[who]["blocks"] if b["course"] == c["course"]) / 60
            c["weight"] = round(weight(c["credits"], h), 1)
            c["work"] = round(work(c["weight"], c["score"]), 2)
        sc, w = semester([(c["weight"], c["score"]) for c in p["courses"]])
        p["credits"] = sum(c["credits"] for c in p["courses"])
        p["hours"], p["work"], p["score"] = round(hrs, 1), round(w, 1), round(sc, 1)
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
    # adding any course, however easy, never lowers a semester
    base = [(4, 7.0), (3, 6.0), (3, 5.0)]
    assert all(semester(base + [(cr, s)])[0] >= semester(base)[0] for cr in (1, 3) for s in (0.5, 2, 9))
    assert general(6, 1.0) == 6 and general(6, 0.5) == 7 and round(weight(2, 3.7), 1) == 3.2 and weight(3, 2.5) == 3
    assert dfw_score(3, 0) == 0 and dfw_score(28, 0) == 10
    bt = {"gpa": 2.6, "dfw": 20.0, "inst": [{"instructorName": "Koh, Cheng-Kok", "effect": -.1, "effectN": 9},
                                            {"instructorName": "Swabey, Matthew A.", "effect": None, "effectN": 0}]}
    assert instructor_record(bt, ["Cheng-Kok Koh"]) == (2.5, 20.0, "Cheng-Kok Koh")
    assert instructor_record(bt, ["Jongwook Koh"])[2] is None     # same surname is not the same person
    assert instructor_record(bt, ["Matthew Swabey"])[2] is None   # co-taught: nothing to compare against
    assert chain({"kind": "or", "items": [{"kind": "test"}]}, entry=True) == set() and chain(None) is None
    assert chain({"kind": "or", "items": [{"kind": "test"}]}) is None             # AP above 100-level is no route
    assert abs(joint([.9, .9], 0) - .81) < 1e-3 and abs(joint([.8]) - .8) < 1e-3 and joint([]) == 1
    assert .729 < joint([.9] * 3) < .9           # correlated: milder than the product, never above the hardest
    scored = [c for p in people.values() for c in p["courses"] if c["syllabus"] is not None]
    assert len(scored) > 20 and all(0 <= c["syllabus"] <= 10 for c in scored), len(scored)


if __name__ == "__main__":
    ppl = main()
    _test(ppl)
    for w, p in sorted(ppl.items(), key=lambda x: -x[1]["score"]):
        print(f"{w:7} {p['score']:4.1f}/10  {p['credits']:2}cr {p['hours']:4.1f}h  " +
              " ".join(f"{c['course'].replace(' ','')}:{c['score']}" for c in p["courses"]))
