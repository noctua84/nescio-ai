"""Contract tests for the review / publish / merge-gate job split and the
in-job hardening of the reusable PR-review core.

`github-action/claude-review-core.yml` is GENERATED. These tests parse that
generated file. The security boundary is the job boundary: Claude runs only in
`review` (read-only token, no OIDC token, no persisted checkout credentials,
base-branch Claude configuration restored first), nothing write-scoped follows
Claude in that job, and `publish` (write token, never runs Claude) re-validates
the artifact it downloads.

Each contract group is a detector function that takes a parsed workflow and
returns a list of problems. The real core must produce none. Every detector is
also run against a mutated deep copy of the parsed YAML (never the tracked
file) and must fire, so no group passes vacuously.

Assertions already made by `tests/test_review_core_template.py` (allow-list,
step order, learning-step placement, the permission scopes) are not repeated
there; the detectors here are the broader, job-split form of those and are
what the negative self-checks exercise.
"""
import copy
import json
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "github-action" / "claude-review-core.yml"
SCRIPTS = ROOT / "github-action" / "scripts" / "claude-review"

CLAUDE_ACTION = "anthropics/claude-code-action"
RESOLVE = "Resolve PR context"
CHECKOUT = "Checkout PR head"
RESTORE = "Restore base-branch Claude configuration"
SNAPSHOT = "Snapshot review state"
SCRUB = "Prune staged files before upload"
UPLOAD = "Upload staged review"
DOWNLOAD = "Download staged review"
PUBLISH = "Publish review comments"
LEARN_CHECKOUT = "Check out base branch for review-learning PRs"
LEARN = "Open review-learning PRs"
GATE = "Submit formal review based on Claude's verdict"

SHA40 = re.compile(r"[0-9a-f]{40}")
PINNED_USES = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
# Long options must precede `-p`: bash reads `-p` as a short option cluster, and
# the first non-option word ends option parsing.
SCRUB_SHELL = "/bin/bash --noprofile --norc -p -e -o pipefail {0}"
ENV_BLANKS = ("BASH_ENV", "ENV", "LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH")
TOKEN_WORDS = ("GH_TOKEN", "GITHUB_TOKEN", "github.token", "secrets.")
SECRET_RE = ("(gh[opusr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
             "|sk-ant-[A-Za-z0-9_-]{20,})")
SECRET_SCRIPTS = ("publish-comments.sh", "open-learning-prs.sh", "scrub-staged.sh")
READ_ONLY = {"contents": "read", "pull-requests": "read", "issues": "read"}


# --- helpers -----------------------------------------------------------------

def load(text=None):
    return yaml.safe_load(CORE.read_text(encoding="utf-8") if text is None else text)


def _jobs(doc):
    return doc.get("jobs") or {}


def _steps(job):
    return (job or {}).get("steps") or []


def _find(doc, name):
    """[(job id, index, step)] for every step called `name`, across all jobs."""
    return [(jid, i, s) for jid, job in _jobs(doc).items()
            for i, s in enumerate(_steps(job)) if s.get("name") == name]


def _one(doc, name, job, problems):
    """The one step `name`, which must sit in `job`; None (and a problem) if not."""
    found = _find(doc, name)
    if len(found) != 1:
        problems.append(f"expected exactly one step {name!r}, found {len(found)}")
        return None
    jid, i, step = found[0]
    if jid != job:
        problems.append(f"step {name!r} must be in job {job!r}, is in {jid!r}")
        return None
    return i, step


def _claude_steps(doc):
    return [(jid, i, s) for jid, job in _jobs(doc).items()
            for i, s in enumerate(_steps(job))
            if str(s.get("uses", "")).startswith(CLAUDE_ACTION + "@")]


def _needs(job):
    needs = (job or {}).get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _has_token(step):
    # Comments are not in the parsed YAML, so this sees only keys and values.
    return any(w in json.dumps(step) for w in TOKEN_WORDS)


def _first_code_line(run):
    for line in str(run).splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            return line.strip()
    return None


def _expr(s):
    return "${{ " + s + " }}"


# --- detectors: each returns a list of problems -------------------------------

def permission_problems(doc):
    p = []
    if "permissions" in doc:
        p.append("workflow-level permissions are not expected")
    if not _jobs(doc):
        p.append("no jobs")
    for jid, job in _jobs(doc).items():
        perms = job.get("permissions")
        if not isinstance(perms, dict):
            p.append(f"job {jid!r} has no explicit permissions block")
        elif "id-token" in perms:
            p.append(f"job {jid!r} requests id-token")
    if (_jobs(doc).get("review") or {}).get("permissions") != READ_ONLY:
        p.append(f"review permissions must equal exactly {READ_ONLY}")
    return p


def claude_problems(doc):
    p = []
    claude = _claude_steps(doc)
    if len(claude) != 1:
        return [f"{CLAUDE_ACTION} must appear in exactly one step, found {len(claude)}"]
    jid, _, step = claude[0]
    if jid != "review":
        p.append(f"{CLAUDE_ACTION} must run in 'review', runs in {jid!r}")
    with_ = step.get("with") or {}
    if with_.get("github_token") != _expr("secrets.GITHUB_TOKEN"):
        p.append("claude step must pass github_token: secrets.GITHUB_TOKEN")
    if with_.get("classify_inline_comments") != "false":
        p.append('claude step must set classify_inline_comments to the string "false"')
    return p


def checkout_problems(doc):
    p = []
    got = _one(doc, CHECKOUT, "review", p)
    if got:
        with_ = got[1].get("with") or {}
        if with_.get("persist-credentials") is not False:
            p.append("review checkout must set persist-credentials to YAML false")
        if with_.get("fetch-depth") != 0:
            p.append("review checkout must set fetch-depth 0 (the restore step needs it)")
    return p


def restore_problems(doc):
    p = []
    got = _one(doc, RESTORE, "review", p)
    claude = _claude_steps(doc)
    if not got or len(claude) != 1 or claude[0][0] != "review":
        return p or ["cannot order the restore step: no single Claude step in review"]
    idx, step = got
    order = {}
    for name in (CHECKOUT, SNAPSHOT):
        found = _find(doc, name)
        if len(found) == 1 and found[0][0] == "review":
            order[name] = found[0][1]
        else:
            p.append(f"review job lacks a single {name!r} step to order against")
    if "run" not in step:
        p.append("restore must be a run: step")
    if CHECKOUT in order and not idx > order[CHECKOUT]:
        p.append("restore must come after the checkout")
    if not idx < claude[0][1]:
        p.append("restore must come before the Claude step")
    if SNAPSHOT in order and not idx < order[SNAPSHOT]:
        p.append("restore must come before the snapshot step")
    if "if" in step:
        p.append("restore must have no if: (it runs for every event)")
    if _has_token(step):
        p.append("restore must carry no token")
    if (step.get("env") or {}).get("BASE_REF") != _expr("steps.pr.outputs.base_ref"):
        p.append("restore BASE_REF must come from steps.pr.outputs.base_ref")
    return p


def after_claude_problems(doc):
    """Nothing write-scoped, and no token, may follow Claude in `review`."""
    p = []
    claude = _claude_steps(doc)
    if len(claude) != 1 or claude[0][0] != "review":
        return ["no single Claude step in review to look after"]
    tail = _steps(doc["jobs"]["review"])[claude[0][1] + 1:]
    names = [s.get("name") for s in tail]
    if names != [SCRUB, UPLOAD]:
        p.append(f"steps after Claude must be exactly {[SCRUB, UPLOAD]}, are {names}")
    for s in tail:
        if _has_token(s):
            p.append(f"step {s.get('name')!r} after Claude carries a token")
    scrub = next((s for s in tail if s.get("name") == SCRUB), {})
    upload = next((s for s in tail if s.get("name") == UPLOAD), {})
    if "run" not in scrub or scrub.get("id") != "scrub":
        p.append("scrub must be a run: step with id: scrub")
    if "!cancelled()" not in str(scrub.get("if", "")):
        p.append("scrub if: must contain !cancelled()")
    uif = str(upload.get("if", ""))
    if "!cancelled()" not in uif or "steps.scrub.outcome == 'success'" not in uif:
        p.append("upload if: must contain !cancelled() and steps.scrub.outcome == 'success'")
    return p


def hardening_problems(doc):
    p = []
    review = _jobs(doc).get("review")
    scrub = next((s for s in _steps(review) if s.get("name") == SCRUB), None)
    upload = next((s for s in _steps(review) if s.get("name") == UPLOAD), None)
    for label, step in (("scrub", scrub), ("upload", upload)):
        if step is None:
            p.append(f"no {label} step in review")
            continue
        env = step.get("env") or {}
        for var in ENV_BLANKS:
            if env.get(var) != "":
                p.append(f"{label} step must set {var} to the empty string")
    if scrub is not None:
        if scrub.get("shell") != SCRUB_SHELL:
            p.append(f"scrub shell must equal exactly {SCRUB_SHELL!r}")
        if _first_code_line(scrub.get("run", "")) != "export PATH=/usr/bin:/bin":
            p.append("first command of the scrub run block must be export PATH=/usr/bin:/bin")
    return p


def upload_problems(doc):
    p = []
    got = _one(doc, UPLOAD, "review", p)
    if got:
        step = got[1]
        with_ = step.get("with") or {}
        if not re.fullmatch(r"actions/upload-artifact@[0-9a-f]{40}", str(step.get("uses"))):
            p.append("upload must use actions/upload-artifact pinned to a 40-hex SHA")
        if with_.get("name") != "review-staged":
            p.append("upload artifact name must be review-staged")
        paths = [x.strip() for x in str(with_.get("path", "")).splitlines() if x.strip()]
        if paths != ["/tmp/review-outbox", "/tmp/review-learnings"]:
            p.append(f"upload paths must be outbox then learnings, are {paths}")
        if with_.get("retention-days") != 1:
            p.append("upload retention-days must be 1")
        if with_.get("if-no-files-found") != "ignore":
            p.append("upload if-no-files-found must be ignore")
        if with_.get("overwrite") is not True:
            p.append("upload overwrite must be true")
    return p


def outputs_problems(doc):
    p = []
    outs = (_jobs(doc).get("review") or {}).get("outputs") or {}
    for key in ("number", "base_ref", "head_sha"):
        if outs.get(key) != _expr(f"steps.pr.outputs.{key}"):
            p.append(f"review output {key} must map to steps.pr.outputs.{key}")
    return p


def publish_problems(doc):
    p = []
    job = _jobs(doc).get("publish")
    if job is None:
        return ["no publish job"]
    if "review" not in _needs(job):
        p.append("publish must need review")
    if "!cancelled()" not in str(job.get("if", "")):
        p.append("publish if: must contain !cancelled()")
    perms = job.get("permissions") or {}
    for scope in ("contents", "pull-requests", "issues"):
        if perms.get(scope) != "write":
            p.append(f"publish must hold {scope}: write")
    for s in _steps(job):
        uses = str(s.get("uses", ""))
        if uses.startswith(CLAUDE_ACTION):
            p.append("publish must never run claude-code-action")
        if uses and not re.fullmatch(
                r"actions/(checkout|download-artifact)@[0-9a-f]{40}", uses):
            p.append(f"publish may only use pinned checkout/download-artifact, uses {uses!r}")

    dl = _one(doc, DOWNLOAD, "publish", p)
    pub = _one(doc, PUBLISH, "publish", p)
    lco = _one(doc, LEARN_CHECKOUT, "publish", p)
    learn = _one(doc, LEARN, "publish", p)
    up = next((s for s in _steps((_jobs(doc).get("review")))
               if s.get("name") == UPLOAD), None)
    if dl:
        step = dl[1]
        if step.get("continue-on-error") is not True:
            p.append("download must be continue-on-error: true")
        name = (step.get("with") or {}).get("name")
        if up is None or name != (up.get("with") or {}).get("name"):
            p.append("download name must equal the upload name")
        path = str((step.get("with") or {}).get("path", ""))
        for label, found, var in (("publish", pub, "REVIEW_OUTBOX"),
                                  ("learning", learn, "REVIEW_LEARNINGS")):
            val = str(((found[1] if found else {}).get("env") or {}).get(var, ""))
            if not path or not val.startswith(path + "/"):
                p.append(f"download path must prefix {label} step's {var}")
    if pub:
        step = pub[1]
        if step.get("id") != "publish":
            p.append("publish step must have id: publish")
        env = step.get("env") or {}
        for var, key in (("PR_NUMBER", "number"), ("HEAD_SHA", "head_sha")):
            if env.get(var) != _expr(f"needs.review.outputs.{key}"):
                p.append(f"publish step {var} must come from needs.review.outputs.{key}")
    if (job.get("outputs") or {}).get("review_published") != _expr(
            "steps.publish.outputs.review_published"):
        p.append("publish output review_published must map to steps.publish.outputs")
    if learn:
        if (learn[1].get("env") or {}).get("BASE_REF") != _expr("needs.review.outputs.base_ref"):
            p.append("learning step BASE_REF must come from needs.review.outputs.base_ref")
        if (learn[1].get("env") or {}).get("PR_NUMBER") != _expr("needs.review.outputs.number"):
            p.append("learning step PR_NUMBER must come from needs.review.outputs.number")
    if lco:
        step = lco[1]
        if step.get("continue-on-error") is not True:
            p.append("learning checkout must be continue-on-error: true")
        if "!cancelled()" not in str(step.get("if", "")):
            p.append("learning checkout if: must contain !cancelled()")
        if (step.get("with") or {}).get("ref") != _expr("needs.review.outputs.base_ref"):
            p.append("learning checkout ref must come from needs.review.outputs.base_ref")
        if pub and learn and not pub[0] < lco[0] < learn[0]:
            p.append("learning checkout must sit after Publish and before the learning step")
    return p


def gate_problems(doc):
    p = []
    job = _jobs(doc).get("merge-gate")
    if job is None:
        return ["no merge-gate job"]
    for need in ("review", "publish"):
        if need not in _needs(job):
            p.append(f"merge-gate must need {need}")
    step = _one(doc, GATE, "merge-gate", p)
    if step and (step[1].get("env") or {}).get("REVIEW_PUBLISHED") != _expr(
            "needs.publish.outputs.review_published"):
        p.append("REVIEW_PUBLISHED must come from needs.publish.outputs.review_published")
    return p


def pin_problems(doc):
    p = []
    uses = [(jid, str(s["uses"])) for jid, job in _jobs(doc).items()
            for s in _steps(job) if "uses" in s]
    if not uses:
        p.append("no uses: steps found")
    for jid, u in uses:
        if not PINNED_USES.fullmatch(u):
            p.append(f"job {jid!r}: {u!r} is not pinned to a 40-hex SHA")
    return p


def secret_re_problems(texts):
    """`texts` maps script name -> source; each must define the literal once."""
    p = []
    for name in SECRET_SCRIPTS:
        found = re.findall(r"^\s*SECRET_RE='([^']*)'\s*$", texts.get(name, ""), re.M)
        if len(found) != 1:
            p.append(f"{name}: expected exactly one SECRET_RE='...' line, found {len(found)}")
        elif found[0] != SECRET_RE:
            p.append(f"{name}: SECRET_RE differs from the contract literal")
    return p


GROUPS = {
    "permissions": permission_problems,
    "claude": claude_problems,
    "checkout": checkout_problems,
    "restore": restore_problems,
    "after-claude": after_claude_problems,
    "hardening": hardening_problems,
    "upload": upload_problems,
    "outputs": outputs_problems,
    "publish": publish_problems,
    "gate": gate_problems,
    "pins": pin_problems,
}


# --- tests on the real generated core ------------------------------------------

class JobSplitContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load()

    def test_every_group_is_clean_on_the_generated_core(self):
        for group, detector in GROUPS.items():
            with self.subTest(group=group):
                self.assertEqual(detector(self.doc), [])

    def test_scrub_script_is_inlined_with_path_reset_first(self):
        # The generated core, not the script file, is what runs.
        scrub = next(s for s in self.doc["jobs"]["review"]["steps"] if s.get("name") == SCRUB)
        self.assertEqual(_first_code_line(scrub["run"]), "export PATH=/usr/bin:/bin")

    def test_secret_re_is_identical_in_all_three_scripts(self):
        texts = {n: (SCRIPTS / n).read_text(encoding="utf-8") for n in SECRET_SCRIPTS}
        self.assertEqual(secret_re_problems(texts), [])

    def test_secret_re_is_also_inlined_in_the_core(self):
        # The scrub step runs the inlined copy; the three must not drift apart.
        text = CORE.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(rf"SECRET_RE='{re.escape(SECRET_RE)}'", text)), 3)

    def test_secret_re_matches_the_credential_families(self):
        rx = re.compile(SECRET_RE)
        for fam in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"):
            with self.subTest(family=fam):
                self.assertTrue(rx.search(fam + "a" * 30))
        self.assertTrue(rx.search("github_pat_" + "a" * 30))
        self.assertTrue(rx.search("sk-ant-" + "a" * 20))
        self.assertIsNone(rx.search("ghp_" + "a" * 10))
        self.assertIsNone(rx.search("the words sk-ant and github_pat_ in prose"))


# --- negative self-checks -------------------------------------------------------

def _job_step(doc, job, name):
    return next(s for s in doc["jobs"][job]["steps"] if s["name"] == name)


def _move(doc, name, src, dst, index=None):
    steps = doc["jobs"][src]["steps"]
    step = steps.pop(next(i for i, s in enumerate(steps) if s["name"] == name))
    doc["jobs"][dst]["steps"].insert(
        len(doc["jobs"][dst]["steps"]) if index is None else index, step)


def _claude_index(doc):
    return next(i for i, s in enumerate(doc["jobs"]["review"]["steps"])
                if str(s.get("uses", "")).startswith(CLAUDE_ACTION))


def _m_id_token_review(d):
    d["jobs"]["review"]["permissions"]["id-token"] = "write"


def _m_id_token_workflow(d):
    d["permissions"] = {"id-token": "write"}


def _m_id_token_gate(d):
    d["jobs"]["merge-gate"]["permissions"]["id-token"] = "write"


def _m_review_write(d):
    d["jobs"]["review"]["permissions"]["contents"] = "write"


def _m_publish_into_review(d):
    _move(d, PUBLISH, "publish", "review")


def _m_token_after_claude(d):
    _job_step(d, "review", UPLOAD)["env"]["GH_TOKEN"] = _expr("secrets.GITHUB_TOKEN")


def _m_extra_step_after_claude(d):
    d["jobs"]["review"]["steps"].append({"name": "Extra", "run": "true"})


def _m_restore_after_claude(d):
    steps = d["jobs"]["review"]["steps"]
    restore = steps.pop(next(i for i, s in enumerate(steps) if s["name"] == RESTORE))
    steps.insert(_claude_index(d) + 1, restore)


def _m_restore_has_token(d):
    _job_step(d, "review", RESTORE)["env"]["GH_TOKEN"] = _expr("secrets.GITHUB_TOKEN")


def _m_restore_has_if(d):
    _job_step(d, "review", RESTORE)["if"] = "${{ github.event_name == 'push' }}"


def _m_restore_wrong_base(d):
    _job_step(d, "review", RESTORE)["env"]["BASE_REF"] = _expr("inputs.pr_number")


def _m_checkout_persists(d):
    _job_step(d, "review", CHECKOUT)["with"]["persist-credentials"] = True


def _m_checkout_shallow(d):
    _job_step(d, "review", CHECKOUT)["with"]["fetch-depth"] = 1


def _m_claude_no_token(d):
    del d["jobs"]["review"]["steps"][_claude_index(d)]["with"]["github_token"]


def _m_claude_classify(d):
    d["jobs"]["review"]["steps"][_claude_index(d)]["with"]["classify_inline_comments"] = "true"


def _m_second_claude(d):
    d["jobs"]["publish"]["steps"].append(
        {"name": "Again", "uses": "anthropics/claude-code-action@" + "a" * 40})


def _m_upload_drops_ld_audit(d):
    del _job_step(d, "review", UPLOAD)["env"]["LD_AUDIT"]


def _m_scrub_drops_bash_env(d):
    del _job_step(d, "review", SCRUB)["env"]["BASH_ENV"]


def _m_scrub_env_not_empty(d):
    _job_step(d, "review", SCRUB)["env"]["LD_PRELOAD"] = "/tmp/x.so"


def _m_shell_without_p(d):
    _job_step(d, "review", SCRUB)["shell"] = "/bin/bash --noprofile --norc -e -o pipefail {0}"


def _m_shell_p_first(d):
    _job_step(d, "review", SCRUB)["shell"] = "/bin/bash -p --noprofile --norc -e -o pipefail {0}"


def _m_shell_relative(d):
    _job_step(d, "review", SCRUB)["shell"] = "bash --noprofile --norc -p -e -o pipefail {0}"


def _m_path_not_first(d):
    step = _job_step(d, "review", SCRUB)
    step["run"] = step["run"].replace("export PATH=/usr/bin:/bin\n",
                                      "umask 077\nexport PATH=/usr/bin:/bin\n", 1)


def _m_upload_unpinned(d):
    _job_step(d, "review", UPLOAD)["uses"] = "actions/upload-artifact@v4"


def _m_upload_retention(d):
    _job_step(d, "review", UPLOAD)["with"]["retention-days"] = 7


def _m_download_name(d):
    _job_step(d, "publish", DOWNLOAD)["with"]["name"] = "something-else"


def _m_download_path(d):
    _job_step(d, "publish", DOWNLOAD)["with"]["path"] = "/tmp/elsewhere"


def _m_download_hard_fail(d):
    del _job_step(d, "publish", DOWNLOAD)["continue-on-error"]


def _m_publish_runs_claude(d):
    d["jobs"]["publish"]["steps"].append(
        {"name": "Review again", "uses": "anthropics/claude-code-action@" + "b" * 40})


def _m_publish_pr_from_input(d):
    _job_step(d, "publish", PUBLISH)["env"]["PR_NUMBER"] = _expr("inputs.pr_number")


def _m_publish_output_missing(d):
    del d["jobs"]["publish"]["outputs"]


def _m_publish_no_id(d):
    del _job_step(d, "publish", PUBLISH)["id"]


def _m_learn_checkout_before_publish(d):
    _move(d, LEARN_CHECKOUT, "publish", "publish", index=0)


def _m_learn_checkout_ref(d):
    _job_step(d, "publish", LEARN_CHECKOUT)["with"]["ref"] = _expr("github.sha")


def _m_gate_drops_publish(d):
    d["jobs"]["merge-gate"]["needs"] = ["review"]


def _m_gate_wrong_source(d):
    _job_step(d, "merge-gate", GATE)["env"]["REVIEW_PUBLISHED"] = _expr(
        "needs.review.outputs.review_published")


def _m_unpinned_checkout(d):
    _job_step(d, "review", CHECKOUT)["uses"] = "actions/checkout@v7"


def _m_outputs_wrong(d):
    d["jobs"]["review"]["outputs"]["head_sha"] = _expr("inputs.pr_number")


MUTATIONS = (
    ("permissions", "id-token on review", _m_id_token_review),
    ("permissions", "workflow-level id-token", _m_id_token_workflow),
    ("permissions", "id-token on merge-gate", _m_id_token_gate),
    ("permissions", "review gains contents: write", _m_review_write),
    ("after-claude", "publish step moved into review", _m_publish_into_review),
    ("after-claude", "token env on the upload step", _m_token_after_claude),
    ("after-claude", "extra step after Claude", _m_extra_step_after_claude),
    ("restore", "restore moved after Claude", _m_restore_after_claude),
    ("restore", "restore gains GH_TOKEN", _m_restore_has_token),
    ("restore", "restore gains an if:", _m_restore_has_if),
    ("restore", "restore BASE_REF from the wrong source", _m_restore_wrong_base),
    ("checkout", "checkout persists credentials", _m_checkout_persists),
    ("checkout", "checkout is shallow", _m_checkout_shallow),
    ("claude", "claude step loses github_token", _m_claude_no_token),
    ("claude", "classify_inline_comments enabled", _m_claude_classify),
    ("claude", "a second claude step", _m_second_claude),
    ("hardening", "upload drops LD_AUDIT", _m_upload_drops_ld_audit),
    ("hardening", "scrub drops BASH_ENV", _m_scrub_drops_bash_env),
    ("hardening", "scrub LD_PRELOAD not empty", _m_scrub_env_not_empty),
    ("hardening", "scrub shell without -p", _m_shell_without_p),
    ("hardening", "scrub shell with -p first", _m_shell_p_first),
    ("hardening", "scrub shell via PATH lookup", _m_shell_relative),
    ("hardening", "PATH export not first", _m_path_not_first),
    ("upload", "upload unpinned", _m_upload_unpinned),
    ("upload", "upload retention 7 days", _m_upload_retention),
    ("publish", "download name differs from upload", _m_download_name),
    ("publish", "download path is not the REVIEW_* prefix", _m_download_path),
    ("publish", "download not continue-on-error", _m_download_hard_fail),
    ("publish", "claude step added to publish", _m_publish_runs_claude),
    ("publish", "publish PR_NUMBER from inputs", _m_publish_pr_from_input),
    ("publish", "publish output removed", _m_publish_output_missing),
    ("publish", "publish step loses its id", _m_publish_no_id),
    ("publish", "learning checkout before Publish", _m_learn_checkout_before_publish),
    ("publish", "learning checkout ref from the wrong source", _m_learn_checkout_ref),
    ("gate", "merge-gate stops needing publish", _m_gate_drops_publish),
    ("gate", "REVIEW_PUBLISHED from the wrong job", _m_gate_wrong_source),
    ("pins", "checkout pinned to a tag", _m_unpinned_checkout),
    ("outputs", "review output head_sha remapped", _m_outputs_wrong),
)


class NegativeSelfCheckTest(unittest.TestCase):
    """Each detector must fire on a deliberately broken copy of the core."""

    @classmethod
    def setUpClass(cls):
        cls.doc = load()

    def test_each_mutation_trips_its_detector(self):
        for group, label, mutate in MUTATIONS:
            with self.subTest(mutation=label):
                broken = copy.deepcopy(self.doc)
                mutate(broken)
                self.assertNotEqual(broken, self.doc, "mutation changed nothing")
                self.assertTrue(GROUPS[group](broken), f"{group} did not fire")

    def test_mutations_do_not_touch_the_original(self):
        # Guard the guard: the deep copies must keep the loaded core clean.
        for group, detector in GROUPS.items():
            with self.subTest(group=group):
                self.assertEqual(detector(self.doc), [])

    def test_every_group_has_a_mutation(self):
        self.assertEqual({g for g, _, _ in MUTATIONS}, set(GROUPS))

    def test_no_group_passes_on_an_empty_workflow(self):
        for group, detector in GROUPS.items():
            with self.subTest(group=group):
                self.assertTrue(detector({"jobs": {}}), f"{group} passes vacuously")

    def test_secret_re_detector_fires_on_drift_and_absence(self):
        good = "SECRET_RE='" + SECRET_RE + "'\n"
        texts = {n: good for n in SECRET_SCRIPTS}
        self.assertEqual(secret_re_problems(texts), [])
        drifted = dict(texts, **{"scrub-staged.sh": good.replace("{30,}", "{10,}", 1)})
        self.assertTrue(secret_re_problems(drifted))
        missing = dict(texts, **{"open-learning-prs.sh": "echo none\n"})
        self.assertTrue(secret_re_problems(missing))
        doubled = dict(texts, **{"publish-comments.sh": good + good})
        self.assertTrue(secret_re_problems(doubled))


if __name__ == "__main__":
    unittest.main()
