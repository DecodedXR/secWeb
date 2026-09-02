"""Public Fall 2026 syllabi from Purdue's Simple Syllabus library, scored for rigor.

The library is public and unauthenticated: doc-library-search finds a section,
doc-html returns its syllabus. Text is cached in syllabi.json so difficulty.py
re-runs without refetching; delete that file to refresh.

Run standalone to refresh the cache and print what each syllabus scored.
"""
import json, re, html, os, time, urllib.request, urllib.parse

API = "https://purdue.simplesyllabus.com/api2/"
CACHE = "syllabi.json"
GET = lambda u: urllib.request.urlopen(
    urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode("utf-8", "replace")

# Every syllabus ends in the same university boilerplate; counting "exam" in the
# grade-appeal policy would score every course identically.
TAIL = re.compile(r"Per the Purdue University Academic Regulations|Academic Integrity|Nondiscrimination|"
                  r"Emergency Preparedness|Mental Health|Accessibility", re.I)


def plain(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def find(course, section):
    """The student's own section if it posted one, else any West Lafayette section."""
    subj, num = course.split()
    d = json.loads(GET(API + "doc-library-search?term_statuses%5B%5D=current&search=" + urllib.parse.quote(course)))
    ok = [i for i in d["items"] if re.match(rf"{re.escape(subj)} \(WL\) {num} ", i["title"])]
    exact = [i for i in ok if i["title"].split()[3] == section]
    return (exact or ok or [None])[0]


def fetch(courses):
    """courses: {(course, section)}. Returns {course: {...}} cached across runs."""
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    for course, section in sorted(courses):
        hit = cache.get(course)
        if hit and (hit.get("section") == section or not hit.get("miss")): continue
        item = find(course, section)
        time.sleep(.25)
        if not item:
            cache[course] = {"miss": True}
            continue
        cache[course] = {"code": item["code"], "section": item["title"].split()[3],
                         "asked": section, "text": plain(GET(API + "doc-html/" + item["code"]))}
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=1)
    return cache


# Each flag is a claim the syllabus makes about how much work it is, with what it moves the
# score by. Nothing here reads the course content: a syllabus that never says how it grades
# scores neutral rather than easy.
FLAGS = [
    (+0.6, "no rounding",      r"will not be rounded|no rounding|not round"),
    (+0.6, "no late work",     r"no late work|late work will not|will not be accepted|no credit"),
    (+0.6, "no make-ups",      r"no make-?up|there are no make-?up"),
    (+0.5, "strict A cutoff",  r"\bA\b[^.]{0,12}\b9[3-5](\.\d+)?\s*%"),
    (+0.4, "required text",    r"(?<!no )textbook is required|Required Text"),
    (-0.4, "no textbook",      r"[Nn]o [Tt]ext ?[Bb]ook [Ii]s [Rr]equired|No textbooks required"),
    (+0.5, "attendance graded", r"attendance (is )?(is )?(required|mandatory|graded)|attendance.{0,30}grade"),
    (-0.6, "pass/fail work",   r"pass/fail|graded on completion|credit/no credit"),
    (+0.5, "weekly writing",   r"weekly (paper|essay|report|quiz|assignment)"),
]
COUNTED = re.compile(r"(\d+|two|three|four|five)\s+(?:midterm|exam|test)s")
WORDS = {"two": 2, "three": 3, "four": 4, "five": 5}


def exams(body):
    """The final is counted separately, or "a final exam" reads as two sittings."""
    b = body.lower()
    final = "final exam" in b
    b = b.replace("final exam", "")
    n = max((WORDS.get(c, int(c) if c.isdigit() else 1) for c in COUNTED.findall(b)), default=0)
    if not n and re.search(r"midterm|\bexam\b|\btest\b", b): n = 1
    return min(n + final, 5)


def rigor(text):
    """0-10 with the flags that got it there, or None when the syllabus says nothing useful."""
    body = TAIL.split(text)[0]
    if len(body) < 700: return None, []          # a stub that defers to a course website
    hits, s = [], 5.0
    for w, name, pat in FLAGS:
        if re.search(pat, body, re.I):
            s += w; hits.append((name, w))
    n = exams(body)
    if n:
        s += min(n - 1, 3) * 0.5
        hits.append((f"{n} exam{'s' if n > 1 else ''}", min(n - 1, 3) * 0.5))
    elif len(re.findall(r"\d+\s*(?:%|points)", body)) >= 3:
        # Only when the syllabus actually enumerates its grade breakdown. One that defers to a
        # course website ("see Ground Rules for MA 26600") is silent about exams, not free of them.
        s -= 0.5; hits.append(("no exams", -0.5))
    return max(0.0, min(10.0, round(s, 1))), hits


def _test():
    assert plain("<b>a</b>  &amp; b") == "a & b"
    assert exams("tests (3 midterms), 2 timed coding") == 3
    assert exams("a final exam and weekly quizzes") == 1 and exams("no assessments listed") == 0
    assert rigor("short")[0] is None
    hard = "x" * 700 + " Grades will not be rounded. There are no make-up exams. 3 midterms and a final exam."
    assert rigor(hard)[0] > 6.5, rigor(hard)


if __name__ == "__main__":
    _test()
    sched = json.load(open("schedule.json", encoding="utf-8"))
    want = {(b["course"], b["section"].split("-")[-1]) for p in sched.values() for b in p["blocks"]}
    cache = fetch(want)
    for c, v in sorted(cache.items()):
        if v.get("miss"): print(f"{c:12} no syllabus posted"); continue
        s, hits = rigor(v["text"])
        print(f"{c:12} sec {v['section']:>3} {'stub' if s is None else f'{s:4.1f}'}  " +
              " ".join(f"{n}{w:+.1f}" for n, w in hits))
