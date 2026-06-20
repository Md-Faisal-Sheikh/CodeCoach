"""End-to-end API tests via FastAPI TestClient. Exercises auth, the submit→
grade path, student/instructor visibility rules, the hint + baseline flow,
rating, human grading, similarity, and the research summary contract.

AI is forced offline (conftest), so hint source is 'heuristic' — the platform's
documented LLM-unavailable fallback. These assert the API contract, not model
quality."""
from app.constants import ROLE_STUDENT, ROLE_INSTRUCTOR
from tests.conftest import make_user, make_problem, make_submission, auth

KADANE = ("n = int(input())\nxs = list(map(int, input().split()))\n"
          "best = cur = xs[0]\nfor x in xs[1:]:\n"
          "    cur = max(x, cur + x)\n    best = max(best, cur)\nprint(best)\n")
KADANE_RN = ("m = int(input())\narr = list(map(int, input().split()))\n"
             "hi = run = arr[0]\nfor v in arr[1:]:\n"
             "    run = max(v, run + v)\n    hi = max(hi, run)\nprint(hi)\n")
KADANE_RF = ("n = int(input())\nnums = list(map(int, input().split()))\n\n"
             "# kadane's algorithm\nbest = cur = nums[0]\nfor x in nums[1:]:\n"
             "    cur = max(x, cur + x)   # extend or restart\n"
             "    best = max(best, cur)\n\nprint(best)\n")
BRUTE = ("n = int(input())\na = list(map(int, input().split()))\n"
         "ans = a[0]\nfor i in range(n):\n    s = 0\n    for j in range(i, n):\n"
         "        s += a[j]\n        if s > ans:\n            ans = s\nprint(ans)\n")
CORRECT = "a,b=map(int,input().split())\nprint(a+b)\n"
WRONG = "a,b=map(int,input().split())\nprint(a*b)\n"


# ---- HTML pages (regression: these are not exercised by the JSON API tests) ----
def test_html_pages_render(client):
    for path in ("/", "/student", "/instructor"):
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
        assert "text/html" in r.headers.get("content-type", "")
        assert "<html" in r.text.lower()


# ---- system / auth ----
def test_system_endpoint(client):
    r = client.get("/api/system")
    assert r.status_code == 200
    body = r.json()
    assert "sandbox" in body and "languages" in body and "ai" in body
    assert body["sandbox"]["resource_limits"] is True


def test_whoami_requires_valid_token(client, session):
    u = make_user(session, "ada", ROLE_STUDENT, token="stu-1")
    assert client.get("/api/whoami", headers=auth("stu-1")).status_code == 200
    assert client.get("/api/whoami", headers=auth("nope")).status_code == 401
    assert client.get("/api/whoami").status_code == 401


# ---- problem visibility ----
def test_student_cannot_see_hidden_tests_or_reference(client, session):
    make_user(session, "ada", ROLE_STUDENT, token="stu-1")
    make_user(session, "grace", ROLE_INSTRUCTOR, token="ins-1")
    prob = make_problem(session)   # has 1 hidden test + reference solution

    s = client.get(f"/api/problems/{prob.id}", headers=auth("stu-1")).json()
    assert s["reference_solution"] == ""
    assert all(not t["hidden"] for t in s["tests"])

    i = client.get(f"/api/problems/{prob.id}", headers=auth("ins-1")).json()
    assert i["reference_solution"] != ""
    assert any(t["hidden"] for t in i["tests"])


# ---- submit + grade ----
def test_submit_correct_is_ok(client, session):
    make_user(session, "ada", ROLE_STUDENT, token="stu-1")
    prob = make_problem(session)
    r = client.post("/api/submissions",
                    json={"problem_id": prob.id, "source_code": CORRECT},
                    headers=auth("stu-1"))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "OK"
    assert body["passed_count"] == body["total_count"] == 3
    # hidden-test I/O is blanked for students
    hidden = [o for o in body["outcomes"] if o["hidden"]]
    assert hidden and all(o["stdout_excerpt"] == "" for o in hidden)


def test_submit_wrong_is_wa(client, session):
    make_user(session, "ada", ROLE_STUDENT, token="stu-1")
    prob = make_problem(session)
    body = client.post("/api/submissions",
                       json={"problem_id": prob.id, "source_code": WRONG},
                       headers=auth("stu-1")).json()
    assert body["status"] == "WA"
    assert body["passed_count"] < 3


# ---- hints + baseline ----
def test_hint_and_baseline_flow(client, session):
    make_user(session, "ada", ROLE_STUDENT, token="stu-1")
    prob = make_problem(session)
    # submit through the API so ownership is attributed to the caller
    sub = client.post("/api/submissions",
                      json={"problem_id": prob.id, "source_code": WRONG},
                      headers=auth("stu-1")).json()
    sid = sub["id"]

    # progressive hint — offline => heuristic source, no leakage diagnostics for student
    h = client.post("/api/hints", json={"submission_id": sid, "level": 1},
                    headers=auth("stu-1"))
    assert h.status_code == 200
    hint = h.json()
    assert hint["content"].strip() != ""
    assert hint["source"] in ("heuristic", "llm")
    assert "leakage_score" not in hint          # students never see this

    # baseline control condition — raw error text
    b = client.post("/api/hints/baseline", json={"submission_id": sid},
                    headers=auth("stu-1"))
    assert b.status_code == 200
    assert b.json()["source"] == "baseline"


def test_instructor_sees_leakage_diagnostics(client, session):
    make_user(session, "ada", ROLE_STUDENT, token="stu-1")
    make_user(session, "grace", ROLE_INSTRUCTOR, token="ins-1")
    prob = make_problem(session)
    sub = client.post("/api/submissions",
                      json={"problem_id": prob.id, "source_code": WRONG},
                      headers=auth("stu-1")).json()
    h = client.post("/api/hints", json={"submission_id": sub["id"], "level": 2},
                    headers=auth("ins-1")).json()
    assert "leakage_score" in h and "leaked" in h
    assert isinstance(h["leakage_detail"], dict)


def test_hint_refused_when_already_passing(client, session):
    make_user(session, "ada", ROLE_STUDENT, token="stu-1")
    prob = make_problem(session)
    sub = client.post("/api/submissions",
                      json={"problem_id": prob.id, "source_code": CORRECT},
                      headers=auth("stu-1")).json()
    r = client.post("/api/hints", json={"submission_id": sub["id"], "level": 1},
                    headers=auth("stu-1"))
    assert r.status_code == 400


# ---- rating + grading + research contract ----
def test_rate_grade_and_research_summary(client, session):
    make_user(session, "ada", ROLE_STUDENT, token="stu-1")
    make_user(session, "grace", ROLE_INSTRUCTOR, token="ins-1")
    prob = make_problem(session)
    sub = client.post("/api/submissions",
                      json={"problem_id": prob.id, "source_code": WRONG},
                      headers=auth("stu-1")).json()
    hint = client.post("/api/hints", json={"submission_id": sub["id"], "level": 1},
                       headers=auth("ins-1")).json()

    # instructor-only endpoints reject students
    assert client.post("/api/hints/rate",
                       json={"hint_id": hint["id"], "helpfulness": 4,
                             "correctness": 5, "reveals_solution": False},
                       headers=auth("stu-1")).status_code == 403

    r = client.post("/api/hints/rate",
                    json={"hint_id": hint["id"], "helpfulness": 4,
                          "correctness": 5, "reveals_solution": False},
                    headers=auth("ins-1"))
    assert r.status_code == 200

    g = client.post("/api/grades",
                    json={"submission_id": sub["id"], "score": 0.5, "label": "partial"},
                    headers=auth("ins-1"))
    assert g.status_code == 200

    summary = client.get("/api/research/summary", headers=auth("ins-1"))
    assert summary.status_code == 200
    s = summary.json()
    for key in ("n_rated_hints", "hint_quality_by_source",
                "grading_agreement", "leak_agreement", "llm_vs_baseline"):
        assert key in s
    assert s["n_rated_hints"] >= 1
    assert s["grading_agreement"]["n"] >= 1


# ---- similarity ----
def test_similarity_endpoint_finds_cluster(client, session):
    make_user(session, "grace", ROLE_INSTRUCTOR, token="ins-1")
    s1 = make_user(session, "u1", ROLE_STUDENT, token="t1")
    s2 = make_user(session, "u2", ROLE_STUDENT, token="t2")
    s3 = make_user(session, "u3", ROLE_STUDENT, token="t3")
    s4 = make_user(session, "u4", ROLE_STUDENT, token="t4")
    prob = make_problem(session, slug="maxsub",
                        reference="n=int(input())\nprint(0)\n")
    make_submission(session, prob, s1, KADANE)
    make_submission(session, prob, s2, KADANE_RN)
    make_submission(session, prob, s3, KADANE_RF)
    make_submission(session, prob, s4, BRUTE)

    r = client.post(f"/api/similarity/problem/{prob.id}", headers=auth("ins-1"))
    assert r.status_code == 200
    body = r.json()
    assert body["n_submissions"] == 4
    assert len(body["clusters"]) == 1
    members = set(body["clusters"][0]["member_users"])
    assert members == {s1.id, s2.id, s3.id}      # brute-force excluded

    # students may not run similarity
    assert client.post(f"/api/similarity/problem/{prob.id}",
                       headers=auth("t1")).status_code == 403
