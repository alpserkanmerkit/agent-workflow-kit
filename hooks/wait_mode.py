"""WAIT hook (decision 0610 #49-2; ~/.claude/CLAUDE.md §2).

  prompt  (UserPromptSubmit): if the message is ONLY an opening/greeting/wait, a session flag is set; any other message clears it.
  pre     (PreToolUse, matcher *): while the flag is set, every tool call is denied.

The list is deliberately narrow: a single task-bearing word ("basla" = start, "devam" = continue, "su dosyayi oku" = read that file) clears the flag.
On error nothing is printed (fail-open): the hook cannot lock tools by accident.
Flag directory: BEKLE_DIZIN or ~/.claude/agent-state/bekle/<session_id>.
"""

import json
import os
import sys

DENY_NEDENI = "WAIT mode: do not use tools until a task is given; reply in one line."
BAGLAM = "WAIT mode (hook): the message is only an opening/greeting/wait. Do not use tools; reply in one line."

# Turkish user-message phrases (product behavior), with Turkish letters folded to ASCII (same form as normallestir()):
# "session opening", "session opened", "hellos", "hello", "greetings", "hi", "wait", "are you ready", "get ready".
BEKLE_IFADELERI = (
    "oturum aciliyor",
    "oturum acildi",
    "selamlar",
    "selam",
    "merhabalar",
    "merhaba",
    "bekle",
    "hazir misin",
    "hazir ol",
)
ESKI_BAYRAK_SN = 2 * 24 * 3600


def bayrak_dizini():
    return os.environ.get("BEKLE_DIZIN") or os.path.join(os.path.expanduser("~"), ".claude", "agent-state", "bekle")


def bayrak_yolu(session_id):
    temiz = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    return os.path.join(bayrak_dizini(), temiz) if temiz else None


def normallestir(metin):
    import re
    import unicodedata

    ayrik = unicodedata.normalize("NFKD", metin)
    sade = "".join(c for c in ayrik if not unicodedata.combining(c)).lower().replace("ı", "i")
    return " ".join(re.sub(r"[^\w\s]", " ", sade).split())


def bekle_mi(mesaj):
    kalan = normallestir(mesaj or "")
    if not kalan:
        return False
    while kalan:
        for ifade in BEKLE_IFADELERI:
            if kalan == ifade or kalan.startswith(ifade + " "):
                kalan = kalan[len(ifade) :].strip()
                break
        else:
            return False
    return True


def _eski_bayraklari_temizle(dizin, simdi):
    for ad in os.listdir(dizin):
        yol = os.path.join(dizin, ad)
        try:
            if simdi - os.path.getmtime(yol) > ESKI_BAYRAK_SN:
                os.remove(yol)
        except OSError:
            pass


def prompt_isle(olay):
    yol = bayrak_yolu(olay.get("session_id", ""))
    if not yol:
        return None
    if not bekle_mi(olay.get("prompt", "")):
        if os.path.exists(yol):
            os.remove(yol)
        return None
    import time

    os.makedirs(os.path.dirname(yol), exist_ok=True)
    _eski_bayraklari_temizle(os.path.dirname(yol), time.time())
    with open(yol, "w", encoding="ascii") as f:
        f.write(str(int(time.time())))
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": BAGLAM}}


def pre_isle(olay):
    yol = bayrak_yolu(olay.get("session_id", ""))
    if not yol or not os.path.exists(yol):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_NEDENI,
        }
    }


def main(argv):
    try:
        mod = argv[1] if len(argv) > 1 else ""
        olay = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        cikti = {"prompt": prompt_isle, "pre": pre_isle}[mod](olay)
        if cikti:
            sys.stdout.write(json.dumps(cikti, ensure_ascii=True))
    except Exception as hata:  # fail-open: a hook error does not block tools
        sys.stderr.write(f"wait_mode: {hata!r}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
