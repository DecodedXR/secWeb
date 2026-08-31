"""Parse Purdue schedule CSVs into schedule.json for the site. Run: python build.py"""
import csv, json, glob, re, os

NAMES = {"BremerFall2026Schedule": "Bremer", "diana_events": "Diana", "Morgan": "Morgan",
         "Noah": "Noah", "Romir": "Romir", "Vlad": "Vlad"}
DAYMAP = [("Th", 3), ("Su", 6), ("M", 0), ("T", 1), ("W", 2), ("F", 4), ("S", 5)]

def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

def course_of(s):                       # some rows carry a wrapped, multi-line course name
    m = re.match(r"([A-Z]+)\s+(\d+)", norm(s))
    return f"{m.group(1)} {m.group(2)}" if m else norm(s)

def label_of(typ, name, course):        # "Course" says nothing; the name holds the real label
    extra = norm(norm(name).replace(course, " "))
    return typ if "Exam" in typ else (extra or "Session")

def parse_days(s):
    out, i = [], 0
    while i < len(s):
        for tok, d in DAYMAP:
            if s.startswith(tok, i):
                out.append(d); i += len(tok); break
        else:
            i += 1
    return out

def parse_time(t):  # "10:30a" -> minutes from midnight
    m = re.match(r"(\d+):(\d+)\s*([ap])", t.strip(), re.I)
    if not m: return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if ap == "p" and h != 12: h += 12
    if ap == "a" and h == 12: h = 0
    return h * 60 + mi

people = {}
for path in sorted(glob.glob("*.csv")):
    person = NAMES.get(os.path.splitext(os.path.basename(path))[0])
    if not person: continue
    seen, blocks, exams, eseen = set(), [], [], set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            typ, course = norm(r["Type"]), course_of(r["Name"])
            # Rows whose Section is "Offering" are one-off dated events (exams, breakout sessions).
            # Every genuinely recurring meeting carries a real section number, so this is what keeps
            # a single-date breakout out of the weekly grid.
            if norm(r["Section"]) == "Offering" or "Exam" in typ:
                k = (course, typ, r["First Date"], r["Published Start"])
                if k not in eseen and r["Published Start"]:
                    eseen.add(k)
                    exams.append({"course": course, "title": norm(r["Title"]), "type": label_of(typ, r["Name"], course),
                                  "date": r["First Date"], "start": parse_time(r["Published Start"]),
                                  "end": parse_time(r["Published End"] or r["Published Start"])})
                continue
            days, start, end = parse_days(r["Day Of Week"] or ""), parse_time(r["Published Start"] or ""), parse_time(r["Published End"] or "")
            if not days or start is None or end is None: continue
            for d in days:
                key = (course, typ, d, start, end, norm(r["Location"]))
                if key in seen: continue
                seen.add(key)
                blocks.append({"course": course, "title": norm(r["Title"]), "type": typ,
                               "section": norm(r["Section"]), "day": d, "start": start, "end": end,
                               "loc": norm(r["Location"]), "instructor": norm(r["Instructor / Organization"]),
                               "first": r["First Date"], "last": r["Last Date"]})
    people[person] = {"blocks": sorted(blocks, key=lambda b: (b["day"], b["start"])),
                      "exams": sorted(exams, key=lambda e: (e["date"], e["start"]))}

json.dump(people, open("schedule.json", "w"), indent=1)
print({k: (len(v["blocks"]), len(v["exams"])) for k, v in people.items()})

def _test():
    assert course_of("ECE 29401 Breakout Session\n  ECE 29401") == "ECE 29401"
    assert parse_days("TTh") == [1, 3] and parse_days("MWF") == [0, 2, 4]
    assert parse_time("12:30p") == 750 and parse_time("8:30a") == 510 and parse_time("12:05a") == 5
    assert all(b["end"] > b["start"] for p in people.values() for b in p["blocks"])
    assert all(p["blocks"] for p in people.values())
    assert label_of("Course", "ECE 29401 Breakout Session\n  ECE 29401", "ECE 29401") == "Breakout Session"
    # the Tuesday 10:30a ECE 29401 breakout is a one-off: only Vlad's weekly section actually meets then
    tue = {n: [b for b in p["blocks"] if b["day"] == 1 and b["course"] == "ECE 29401"] for n, p in people.items()}
    assert not any(tue[n] for n in ("Morgan", "Noah", "Romir")) and tue["Vlad"], tue
_test()
