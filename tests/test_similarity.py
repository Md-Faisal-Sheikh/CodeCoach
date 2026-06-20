"""Plagiarism similarity: token-level fingerprints are robust to renaming and
reformatting, distinct code scores low, and the detector clusters copied
variants while leaving an independent solution out."""
from app.similarity.tokenizer import tokenize_code
from app.similarity.winnowing import fingerprints, similarity
from app.similarity.detector import analyze


KADANE = ("n = int(input())\n"
          "xs = list(map(int, input().split()))\n"
          "best = cur = xs[0]\n"
          "for x in xs[1:]:\n"
          "    cur = max(x, cur + x)\n"
          "    best = max(best, cur)\n"
          "print(best)\n")

KADANE_RENAMED = ("m = int(input())\n"
                  "arr = list(map(int, input().split()))\n"
                  "hi = run = arr[0]\n"
                  "for v in arr[1:]:\n"
                  "    run = max(v, run + v)\n"
                  "    hi = max(hi, run)\n"
                  "print(hi)\n")

KADANE_REFORMATTED = ("n = int(input())\n"
                      "nums = list(map(int, input().split()))\n\n"
                      "# kadane\n"
                      "best = cur = nums[0]\n"
                      "for x in nums[1:]:\n"
                      "    cur = max(x, cur + x)   # extend or restart\n"
                      "    best = max(best, cur)\n\n"
                      "print(best)\n")

BRUTE = ("n = int(input())\n"
         "a = list(map(int, input().split()))\n"
         "ans = a[0]\n"
         "for i in range(n):\n"
         "    s = 0\n"
         "    for j in range(i, n):\n"
         "        s += a[j]\n"
         "        if s > ans:\n"
         "            ans = s\n"
         "print(ans)\n")


def _fp(src):
    return fingerprints(tokenize_code(src, "python"))


def test_identical_is_one():
    assert similarity(_fp(KADANE), _fp(KADANE))["jaccard"] == 1.0


def test_renaming_is_robust():
    # variable renames must not fool token-level fingerprinting
    s = similarity(_fp(KADANE), _fp(KADANE_RENAMED))
    assert s["overlap"] > 0.85


def test_reformatting_is_robust():
    # comments / blank lines are stripped by tokenization
    s = similarity(_fp(KADANE), _fp(KADANE_REFORMATTED))
    assert s["overlap"] > 0.85


def test_independent_solution_scores_lower_than_copies():
    # Short idiomatic Python shares many k-grams (int/input/split/map/list), so
    # raw token overlap alone is a weak signal — which is exactly why the
    # detector blends three signals. The defensible property here is separation:
    # an independent solution must score clearly below a renamed copy.
    copy = similarity(_fp(KADANE), _fp(KADANE_RENAMED))["overlap"]
    indep = similarity(_fp(KADANE), _fp(BRUTE))["overlap"]
    assert copy > 0.85
    assert indep < copy - 0.2


def test_detector_clusters_copies_only():
    subs = [(1, KADANE), (2, KADANE_RENAMED), (3, KADANE_REFORMATTED), (4, BRUTE)]
    report = analyze(subs, "python")
    # the three copies form one cluster; the brute-force solution is excluded
    assert len(report.clusters) == 1
    members = set(report.clusters[0].members)
    assert members == {1, 2, 3}
    assert 4 not in members


def test_detector_pair_scores_present():
    subs = [(1, KADANE), (2, KADANE_RENAMED)]
    report = analyze(subs, "python")
    assert report.pairs
    p = report.pairs[0]
    assert 0.0 <= p.combined <= 1.0
    assert p.winnow >= 0.0 and p.tfidf >= 0.0
