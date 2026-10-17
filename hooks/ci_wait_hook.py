"""Wait hook (decision 0610 #48, #49-1): no ending the turn while CI runs + timeout warning.

  post  (PostToolUse, matcher Bash|PowerShell): successful `git push` -> record in ~/.claude/agent-state/bekleme.json
        {session_id, repo (owner/name), dal, sha, zaman, islendi=false}.
  stop  (Stop): for this session's unprocessed records from the last 3 hours, `gh run list` (only that sha's runs).
        Run in progress -> block; finished and unprocessed -> block ONCE, then mark as processed.

Rules: no push record -> no network call; gh error / timeout -> allow + systemMessage (fail-open);
at most 8 consecutive blocks for the same run within the same turn (prompt_id); hook error -> silent exit 0.
Environment (for tests): BEKLEME_DURUM (state file), BEKLEME_GH (gh path).
"""

import json
import os
import re
import sys
import time

UC_SAAT = 3 * 3600
KAYIT_OMRU = 24 * 3600
KOSU_GORUNME_PAYI = 120  # time for GitHub to create the run after a push
BLOK_SINIRI = 8
VARSAYILAN_BEKLENEN = 600  # 10 min if there is no history
PAY = 60
GH_ZAMAN_ASIMI = 15
STOP_BUTCESI = 40
GIT_ZAMAN_ASIMI = 5
ALANLAR = "databaseId,status,conclusion,createdAt,updatedAt,workflowName,headSha"
AKTIF = {"queued", "in_progress", "waiting", "requested", "pending"}
RET_ISARETLERI = ("! [rejected]", "! [remote rejected]", "error: failed to push", "fatal:")


def simdi():
    return time.time()


# ---------------- state file ----------------


def durum_yolu():
    return os.environ.get("BEKLEME_DURUM") or os.path.join(os.path.expanduser("~"), ".claude", "agent-state", "bekleme.json")


def durum_oku():
    try:
        with open(durum_yolu(), encoding="utf-8") as f:
            veri = json.load(f)
        if isinstance(veri.get("kayitlar"), list):
            return veri
    except (OSError, ValueError, AttributeError):
        pass
    return {"kayitlar": []}


class _Kilit:
    """Short lock shared between sessions (O_EXCL file). If not acquired within 3 s, continue without it (fail-open)."""

    def __init__(self):
        self.yol = durum_yolu() + ".kilit"
        self.alindi = False

    def __enter__(self):
        os.makedirs(os.path.dirname(self.yol) or ".", exist_ok=True)
        son = time.monotonic() + 3
        while time.monotonic() < son:
            try:
                os.close(os.open(self.yol, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                self.alindi = True
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.yol) > 15:
                        os.remove(self.yol)
                        continue
                except OSError:
                    pass
                time.sleep(0.05)
        return self

    def __exit__(self, *_):
        if self.alindi:
            try:
                os.remove(self.yol)
            except OSError:
                pass


def _durum_yaz(veri):
    yol = durum_yolu()
    gecici = f"{yol}.{os.getpid()}.tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=1)
    os.replace(gecici, yol)


def _guncelle(degistir):
    """Under the lock: read -> change(records) -> prune old records -> write."""
    with _Kilit():
        veri = durum_oku()
        degistir(veri["kayitlar"])
        sinir = simdi() - KAYIT_OMRU
        veri["kayitlar"] = [k for k in veri["kayitlar"] if k.get("ts", 0) >= sinir]
        _durum_yaz(veri)


def yeni_kayit(session_id, repo, dal, sha, ts, remote_url="", dizin=""):
    return {
        "kimlik": f"{session_id}|{repo}|{dal}|{sha}",
        "session_id": session_id,
        "repo": repo,
        "dal": dal,
        "sha": sha,
        "ts": ts,
        "zaman": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
        "remote_url": remote_url,
        "dizin": dizin,
        "islendi": False,
        "bloklar": {},
        "beklenen": {},
    }


def kayitlari_ekle(yeniler):
    def ekle(kayitlar):
        var = {k.get("kimlik") for k in kayitlar}
        kayitlar.extend(k for k in yeniler if k["kimlik"] not in var)

    _guncelle(ekle)


# ---------------- parsing the push command ----------------


class PushIstegi:
    def __init__(self, dizin, remote, refspecler):
        self.dizin = dizin
        self.remote = remote
        self.refspecler = refspecler

    def __repr__(self):
        return f"PushIstegi({self.dizin!r}, {self.remote!r}, {self.refspecler!r})"


def yol_normal(yol):
    yol = str(yol).replace("\\", "/")
    m = re.match(r"^/([A-Za-z])(/.*)?$", yol)
    if m:
        yol = m.group(1).upper() + ":" + (m.group(2) or "/")
    if re.match(r"^[a-z]:", yol):
        yol = yol[0].upper() + yol[1:]
    return yol.rstrip("/") if len(yol) > 3 else yol


def _coz(taban, hedef):
    hedef = os.path.expanduser(hedef.strip())
    hedef = yol_normal(hedef)
    if re.match(r"^[A-Za-z]:", hedef) or hedef.startswith("/"):
        return hedef
    return yol_normal(os.path.join(taban, hedef))


def _parcalar(komut, arac):
    import shlex

    for satir in komut.splitlines():
        try:
            lex = shlex.shlex(satir, posix=True, punctuation_chars=";&|()")
            lex.whitespace_split = True
            if arac == "PowerShell":
                lex.escape = ""  # PowerShell's escape character is the backtick; backslash is a path separator
            simgeler = list(lex)
        except ValueError:
            simgeler = satir.split()
        parca = []
        for s in simgeler:
            if s and set(s) <= set(";&|()"):
                if parca:
                    yield parca
                parca = []
            else:
                parca.append(s)
        if parca:
            yield parca


SARMALAYICI = {"timeout", "time", "nice", "nohup", "env", "command", "builtin"}
CD = {"cd", "set-location", "sl", "pushd", "chdir"}
DEGERLI_SECENEK = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def _git_push_ayristir(simgeler, dizin):
    """['git', ...] -> (dizin, remote, refspecler) or None (not a push / dry run / delete)."""
    i = 1
    while i < len(simgeler):
        s = simgeler[i]
        if s == "-C" and i + 1 < len(simgeler):
            dizin = _coz(dizin, simgeler[i + 1])
            i += 2
        elif s in ("-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(simgeler):
            i += 2
        elif s.startswith("-"):
            i += 1
        else:
            break
    if i >= len(simgeler) or simgeler[i] != "push":
        return None
    konumlu = []
    j = i + 1
    while j < len(simgeler):
        s = simgeler[j]
        if s in DEGERLI_SECENEK:
            j += 2
            continue
        if s in ("--dry-run", "--delete", "--mirror", "--all", "--branches"):
            return None
        if re.match(r"^-[A-Za-z]+$", s) and ("n" in s or "d" in s):
            return None
        if not s.startswith("-"):
            konumlu.append(s)
        j += 1
    remote = konumlu[0] if konumlu else None
    refspecler = konumlu[1:]
    if any(r.lstrip("+").startswith(":") for r in refspecler):
        return None
    return dizin, remote, refspecler


def push_istekleri(komut, arac, cwd):
    dizin = yol_normal(cwd or os.getcwd())
    istekler = []
    for parca in _parcalar(komut or "", arac):
        while parca and (re.match(r"^\w+=", parca[0]) or parca[0].lower() in SARMALAYICI):
            parca = parca[1:]
            while parca and re.match(r"^(-\w+|\d+(\.\d+)?[smhd]?)$", parca[0]):  # timeout -k 5 60 ...
                parca = parca[1:]
        if not parca:
            continue
        ad = parca[0].lower()
        if ad in CD:
            hedef = [s for s in parca[1:] if not s.startswith("-")]
            if hedef:
                dizin = _coz(dizin, hedef[0])
            continue
        if ad not in ("git", "git.exe"):
            continue
        sonuc = _git_push_ayristir(parca, dizin)
        if sonuc:
            istekler.append(PushIstegi(*sonuc))
    return istekler


def repo_adi(url):
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", str(url or ""))
    return f"{m.group(1)}/{m.group(2)}" if m else None


# ---------------- PostToolUse ----------------


def git_calistir(dizin, *args):
    import subprocess

    try:
        out = subprocess.run(["git", "-C", dizin, *args], capture_output=True, timeout=GIT_ZAMAN_ASIMI, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8", "replace").strip() if out.returncode == 0 else None


def _metinler(deger):
    if isinstance(deger, str):
        yield deger
    elif isinstance(deger, dict):
        for v in deger.values():
            yield from _metinler(v)
    elif isinstance(deger, list):
        for v in deger:
            yield from _metinler(v)


def _remote_sec(dizin, dal):
    for anahtar in (f"branch.{dal}.pushRemote", "remote.pushDefault", f"branch.{dal}.remote"):
        if dal or "branch." not in anahtar:
            deger = git_calistir(dizin, "config", "--get", anahtar)
            if deger:
                return deger
    return "origin"


def _kayitlar(ist, session_id, reddedildi):
    dizin = ist.dizin
    dal_su_an = git_calistir(dizin, "symbolic-ref", "--short", "-q", "HEAD")
    remote = ist.remote or _remote_sec(dizin, dal_su_an)
    adli_remote = not re.search(r"[:/\\]", remote)
    url = git_calistir(dizin, "remote", "get-url", "--push", remote) if adli_remote else remote
    repo = repo_adi(url)
    if not repo:
        return []
    refspecler = ist.refspecler or ([dal_su_an] if dal_su_an else [])
    sonuc = []
    for spec in refspecler:
        spec = spec.lstrip("+")
        kaynak, _, hedef = spec.partition(":")
        hedef = hedef or kaynak
        if hedef == "HEAD":
            hedef = dal_su_an or ""
        hedef = re.sub(r"^refs/heads/", "", hedef)
        if not hedef or hedef.startswith("refs/"):
            continue
        sha = git_calistir(dizin, "rev-parse", "--verify", "-q", f"{kaynak}^{{commit}}")
        if not sha:
            continue
        if adli_remote:
            izleyen = git_calistir(dizin, "rev-parse", "--verify", "-q", f"refs/remotes/{remote}/{hedef}")
            if izleyen != sha:
                continue  # push did not land (tracking ref was not updated)
        elif reddedildi:
            continue
        sonuc.append(yeni_kayit(session_id, repo, hedef, sha, simdi(), url or "", dizin))
    return sonuc


def post_isle(olay):
    girdi = olay.get("tool_input") or {}
    komut = girdi.get("command") or ""
    if not re.search(r"\bgit\b", komut) or not re.search(r"\bpush\b", komut) or girdi.get("run_in_background"):
        return None
    yanit = olay.get("tool_response") or {}
    if isinstance(yanit, dict) and (yanit.get("interrupted") or yanit.get("exit_code") not in (None, 0)):
        return None
    reddedildi = any(i in m for m in _metinler(yanit) for i in RET_ISARETLERI)
    yeniler = []
    for ist in push_istekleri(komut, olay.get("tool_name", "Bash"), olay.get("cwd", "")):
        yeniler.extend(_kayitlar(ist, olay.get("session_id", ""), reddedildi))
    if not yeniler:
        return None
    kayitlari_ekle(yeniler)
    ozet = ", ".join(f"{k['repo']} {k['dal']} @ {k['sha'][:7]}" for k in yeniler)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"wait hook: push recorded ({ozet}). Do not end the turn before CI finishes.",
        }
    }


# ---------------- Stop ----------------


def gh_calistir(args, zaman_asimi):
    import shutil
    import subprocess

    gh = os.environ.get("BEKLEME_GH") or shutil.which("gh") or "gh"
    out = subprocess.run([gh, *args], capture_output=True, timeout=zaman_asimi, stdin=subprocess.DEVNULL)
    return out.returncode, out.stdout.decode("utf-8", "replace"), out.stderr.decode("utf-8", "replace")


def _epoch(iso):
    from datetime import datetime, timezone

    sade = re.sub(r"\.\d+", "", str(iso)).replace("+00:00", "Z")
    return datetime.strptime(sade, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def dk(saniye):
    return f"{max(saniye, 0) / 60:.1f}"


class GhHatasi(Exception):
    pass


def _gh_json(args):
    import subprocess

    try:
        rc, out, err = gh_calistir(args, GH_ZAMAN_ASIMI)
    except subprocess.TimeoutExpired:
        raise GhHatasi(f"gh did not respond within {GH_ZAMAN_ASIMI} s")
    except OSError as hata:
        raise GhHatasi(f"gh failed to run: {hata}")
    if rc != 0:
        raise GhHatasi((err or out).strip()[:200] or f"gh exit {rc}")
    try:
        return json.loads(out or "[]")
    except ValueError:
        raise GhHatasi("gh output is not JSON")


def beklenen_sure(repo, workflow):
    """Median duration of the same workflow's last 5 completed runs + 60 s; 10 min if there is no data."""
    try:
        gecmis = _gh_json(
            [
                "run",
                "list",
                "-R",
                repo,
                "--workflow",
                workflow,
                "--status",
                "completed",
                "-L",
                "5",
                "--json",
                "createdAt,updatedAt",
            ]
        )
        sureler = sorted(_epoch(r["updatedAt"]) - _epoch(r["createdAt"]) for r in gecmis)
    except (GhHatasi, KeyError, ValueError, TypeError):
        sureler = []
    if not sureler:
        return VARSAYILAN_BEKLENEN
    n = len(sureler)
    ortanca = sureler[n // 2] if n % 2 else (sureler[n // 2 - 1] + sureler[n // 2]) / 2
    return ortanca + PAY


def _blok_sayisi(kayit, anahtar, prompt_id):
    b = kayit.get("bloklar", {}).get(anahtar)
    return b["sayi"] if b and b.get("prompt_id") == prompt_id else 0


def _kayit_karari(k, prompt_id, an):
    """Single record -> (reason | None, message | None, change dict)."""
    repo, dal, sha = k["repo"], k["dal"], k["sha"]
    try:
        kosular = [
            r
            for r in _gh_json(["run", "list", "-R", repo, "--branch", dal, "--json", ALANLAR, "-L", "20"])
            if r.get("headSha") == sha
        ]
    except GhHatasi as hata:
        return (
            None,
            f"wait hook: could not read gh ({repo} {dal}: {hata}) — CI status NOT VERIFIED, turn end allowed.",
            {},
        )

    def blok(anahtar, neden, ek=None):
        sayi = _blok_sayisi(k, anahtar, prompt_id)
        if sayi >= BLOK_SINIRI:
            return (
                None,
                f"wait hook: {anahtar} reached the limit of {BLOK_SINIRI} consecutive blocks — turn end allowed; handle the CI result later.",
                {},
            )
        degisiklik = {"bloklar": {anahtar: {"prompt_id": prompt_id, "sayi": sayi + 1}}}
        degisiklik.update(ek or {})
        return neden, None, degisiklik

    if not kosular:
        yas = an - k["ts"]
        if yas < KOSU_GORUNME_PAYI:
            return blok(
                f"waiting {sha[:7]}",
                f"CI run not visible yet ({repo} {dal} @ {sha[:7]}, pushed {int(yas)} s ago). Do not end the turn: "
                f"find the run with `gh run list -R {repo} --branch {dal} -L 5`, wait with `gh run watch <id> --exit-status`, then handle the result.",
            )
        return None, None, {"islendi": True, "ci_yok": True}

    aktif = sorted((r for r in kosular if r.get("status") in AKTIF), key=lambda r: r.get("createdAt", ""))
    if aktif:
        r = aktif[0]
        rid, wf = r["databaseId"], r.get("workflowName", "")
        beklenen = k.get("beklenen", {}).get(wf) or beklenen_sure(repo, wf)
        gecen = an - _epoch(r["createdAt"])
        neden = (
            f"CI {rid} running (elapsed {dk(gecen)} min, expected {dk(beklenen)} min). "
            f"Do not end the turn: wait with `gh run watch {rid} --exit-status`, then handle the result."
        )
        if gecen > beklenen:
            neden = (
                f"TIME EXCEEDED — {neden} Send the user a PushNotification: "
                f"'CI {wf} ({repo} {dal}) exceeded the estimate by {dk(gecen - beklenen)} min: <reason>'"
            )
        return blok(f"CI {rid}", neden, {"beklenen": {wf: beklenen}})

    ozet = "; ".join(f"CI {r['databaseId']} finished: {r.get('conclusion') or 'unknown'}" for r in kosular)
    return f"{ozet}. Handle the result and report it.", None, {"islendi": True}


def stop_isle(olay):
    sid = olay.get("session_id", "")
    an = simdi()
    bekleyen = [
        k
        for k in durum_oku()["kayitlar"]
        if k.get("session_id") == sid and not k.get("islendi") and an - k.get("ts", 0) <= UC_SAAT
    ]
    if not bekleyen:
        return None  # no push -> no network call
    prompt_id = olay.get("prompt_id") or ""
    son = time.monotonic() + STOP_BUTCESI
    nedenler, mesajlar, degisiklikler = [], [], {}
    for k in bekleyen:
        if time.monotonic() > son:
            mesajlar.append(f"wait hook: time budget exhausted ({k['repo']} {k['dal']}) — CI status NOT VERIFIED.")
            continue
        neden, mesaj, degisiklik = _kayit_karari(k, prompt_id, an)
        if neden:
            nedenler.append(neden)
        if mesaj:
            mesajlar.append(mesaj)
        if degisiklik:
            degisiklikler[k["kimlik"]] = degisiklik

    if degisiklikler:

        def uygula(kayitlar):
            for k in kayitlar:
                d = degisiklikler.get(k.get("kimlik"))
                if not d:
                    continue
                for alan, deger in d.items():
                    if isinstance(deger, dict):
                        k.setdefault(alan, {}).update(deger)
                    else:
                        k[alan] = deger

        _guncelle(uygula)

    cikti = {}
    if nedenler:
        cikti["decision"] = "block"
        cikti["reason"] = "\n".join(nedenler)
    if mesajlar:
        cikti["systemMessage"] = " | ".join(mesajlar)
    return cikti or None


def main(argv):
    try:
        mod = argv[1] if len(argv) > 1 else ""
        olay = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        cikti = {"post": post_isle, "stop": stop_isle}[mod](olay)
        if cikti:
            sys.stdout.write(json.dumps(cikti, ensure_ascii=True))
    except Exception as hata:  # fail-open: a hook error must not lock the turn
        sys.stderr.write(f"ci_wait_hook: {hata!r}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
