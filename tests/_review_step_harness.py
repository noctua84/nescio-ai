"""Shared harness for behaviour tests of the review core's shell steps.

A step's script (`github-action/scripts/claude-review/<name>.sh`, the source the
generator inlines into the shipped core) is executed directly with bash against
a fake `gh` on PATH. The fake logs every call
and serves canned JSON for GET calls, applying the `--jq` filter with the real
`jq` and printing strings raw like `gh` does. Tests assert on the logged WRITE
calls (method + endpoint + fields), never on log wording.

Pagination is emulated the way `gh` does it: a response can be configured as
several pages; `--paginate` walks all of them and applies `--jq` to EACH page
separately, while a call without `--paginate` sees page 1 only.

Used by the test_review_*_step.py / test_review_merge_gate.py behaviour tests. Skipped
unless `bash` and `jq` are on PATH.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "github-action" / "scripts" / "claude-review"

BASH = shutil.which("bash")
JQ = shutil.which("jq")

FAKE_GH = r"""#!/usr/bin/env bash
# Fake gh for the review-step tests. Only `gh api` is supported.
set -u
D="$FAKE_GH_DIR"
n=$(( $(cat "$D/count" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$D/count"
{ printf '%s' "$n"; for a in "$@"; do printf '\x1f%s' "$a"; done; printf '\n'; } >> "$D/calls.log"
if [ "${1:-}" != api ]; then echo "fake-gh: unsupported command ${1:-}" >&2; exit 2; fi
shift
method=GET; endpoint=""; jqf=""; paginate=0
while [ $# -gt 0 ]; do
  case "$1" in
    -X|--method) method="$2"; shift 2 ;;
    --jq|-q) jqf="$2"; shift 2 ;;
    --paginate) paginate=1; shift ;;
    -F|--field)
      case "$2" in body=@*) cp "${2#body=@}" "$D/bodies/$n.md" ;; esac
      shift 2 ;;
    -f|--raw-field)
      case "$2" in body=*) printf '%s' "${2#body=}" > "$D/bodies/$n.md" ;; esac
      shift 2 ;;
    -*) echo "fake-gh: unsupported flag $1" >&2; exit 2 ;;
    *) endpoint="$1"; shift ;;
  esac
done
echo "fake-gh: $method $endpoint" >&2
if grep -Fxq -- "$method $endpoint" "$D/fail.txt" 2>/dev/null; then
  echo "fake-gh: HTTP 403 for $method $endpoint" >&2
  exit 1
fi
if [ "$method" != GET ]; then echo '{}'; exit 0; fi
base="$D/responses/$(printf '%s' "$endpoint" | tr '/?&=' '____')"
pages=()
i=1
while [ -f "$base.$i.json" ]; do
  pages+=("$base.$i.json")
  [ "$paginate" -eq 1 ] || break
  i=$((i + 1))
done
[ "${#pages[@]}" -gt 0 ] || pages=("$D/empty.json")
for page in "${pages[@]}"; do
  if [ -n "$jqf" ]; then
    # gh applies --jq to each page on its own.
    jq -r "($jqf) | if type == \"string\" then . else tojson end" < "$page" || exit 1
  else
    cat "$page"
  fi
done
"""

# Native Windows jq writes in text mode: every "\n" it emits, including one
# inside a raw string, becomes "\r\n". The step runs on ubuntu-latest where jq
# writes LF. Removing exactly one CR before each LF restores the Linux bytes
# and keeps a CR that is part of the data (a CRLF comment body), which
# `tr -d '\r'` would also delete. Only installed when the local jq emits CRLF.
JQ_LF_SHIM = """#!/usr/bin/env bash
set -o pipefail
"{real}" "$@" | "{python}" -c "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().replace(b'\\\\r\\\\n', b'\\\\n'))"
"""


def posix(path):
    return str(path).replace("\\", "/")


def jq_writes_crlf():
    out = subprocess.run([JQ, "-n", "-r", '"a","b"'], capture_output=True).stdout
    return b"\r\n" in out


def comment(cid, login, body, **extra):
    return {"id": cid, "user": {"login": login}, "body": body, **extra}


def split_pages(data, pages):
    """Split a list into `pages` contiguous, non-empty chunks (fewer if short)."""
    if not isinstance(data, list) or pages <= 1 or len(data) < 2:
        return [data]
    pages = min(pages, len(data))
    size, extra = divmod(len(data), pages)
    out, start = [], 0
    for i in range(pages):
        end = start + size + (1 if i < extra else 0)
        out.append(data[start:end])
        start = end
    return out


def step_script(name):
    """Text of `scripts/claude-review/<name>.sh`, LF-normalised."""
    return (SCRIPTS / f"{name}.sh").read_bytes().decode("utf-8").replace("\r\n", "\n")


@unittest.skipUnless(BASH and JQ, "bash and jq are required on PATH")
class StepHarness(unittest.TestCase):
    """Runs one workflow step's script against the fake gh.

    Subclasses set SCRIPT (the file stem, e.g. "merge-gate"); `run_step(env)`
    executes it.
    """

    SCRIPT = None

    @classmethod
    def setUpClass(cls):
        cls.script_text = step_script(cls.SCRIPT)
        cls.crlf_jq = jq_writes_crlf()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.root = root
        self.runner_temp = root / "runner-temp"
        self.runner_temp.mkdir()
        self.fake = root / "fake-gh"
        (self.fake / "responses").mkdir(parents=True)
        (self.fake / "bodies").mkdir()
        (self.fake / "empty.json").write_text("[]", encoding="utf-8", newline="\n")
        self.bin = root / "bin"
        self.bin.mkdir()
        self._write_exec(self.bin / "gh", FAKE_GH)
        if self.crlf_jq:
            self._write_exec(self.bin / "jq", JQ_LF_SHIM.format(
                real=posix(JQ), python=posix(sys.executable)))
        self.script = root / "step.sh"
        self.script.write_text(self.script_text, encoding="utf-8", newline="\n")

    # -- fixtures ---------------------------------------------------------------

    @staticmethod
    def _write_exec(path, text):
        path.write_text(text, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def _response_base(self, endpoint):
        return self.fake / "responses" / endpoint.translate(str.maketrans("/?&=", "____"))

    def respond_pages(self, endpoint, pages):
        """Serve `pages` (a list of page payloads) for GET `endpoint`."""
        base = self._response_base(endpoint)
        for old in base.parent.glob(base.name + ".*.json"):
            old.unlink()
        for i, page in enumerate(pages, 1):
            Path(f"{base}.{i}.json").write_text(
                json.dumps(page), encoding="utf-8", newline="\n")

    def respond(self, endpoint, data, pages=1):
        """Serve `data` for GET `endpoint`, split into `pages` pages."""
        self.respond_pages(endpoint, split_pages(data, pages))

    def refuse(self, method, endpoint):
        with open(self.fake / "fail.txt", "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"{method} {endpoint}\n")

    def run_step(self, env_vars):
        env = dict(os.environ)
        env.update({
            "RUNNER_TEMP": posix(self.runner_temp),
            "GH_TOKEN": "fake-token",
            "FAKE_GH_DIR": posix(self.fake),
            "PATH": str(self.bin) + os.pathsep + env.get("PATH", ""),
        })
        env.update(env_vars)
        proc = subprocess.run(
            [BASH, posix(self.script)], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=180)
        self.output = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        return proc

    # -- call log ---------------------------------------------------------------

    def clear_calls(self):
        for name in ("calls.log", "count"):
            (self.fake / name).unlink(missing_ok=True)
        for body in (self.fake / "bodies").iterdir():
            body.unlink()

    def calls(self):
        log = self.fake / "calls.log"
        if not log.exists():
            return []
        result = []
        for line in log.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            n, *args = line.split("\x1f")
            assert args[:1] == ["api"], args
            method, endpoint, fields = "GET", None, {}
            i = 1
            while i < len(args):
                a = args[i]
                if a in ("-X", "--method"):
                    method = args[i + 1]; i += 2
                elif a in ("--jq", "-q"):
                    i += 2
                elif a == "--paginate":
                    i += 1
                elif a in ("-f", "-F", "--field", "--raw-field"):
                    k, _, v = args[i + 1].partition("=")
                    fields[k] = v; i += 2
                else:
                    endpoint = a; i += 1
            body = self.fake / "bodies" / f"{n}.md"
            result.append({
                "n": int(n), "method": method, "endpoint": endpoint,
                "fields": fields,
                "body": body.read_text(encoding="utf-8") if body.exists() else None,
            })
        return result

    def writes(self):
        return [c for c in self.calls() if c["method"] != "GET"]

    def write_keys(self):
        return [(c["method"], c["endpoint"]) for c in self.writes()]

    def assertExit(self, proc, code):
        self.assertEqual(proc.returncode, code, f"exit {proc.returncode}; output:\n{self.output}")
