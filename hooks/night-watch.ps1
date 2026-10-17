# night-watch.ps1 -- PermissionRequest hook (TRIAL version, 2026-09-29; conditional push 2026-09-30; night branch 2026-10-03)
# While night mode is on (marker file exists) it answers the permission prompt IMMEDIATELY with a reasoned "deny" and writes to the ledger;
# the agent does not wait and keeps working toward the goal. The ONLY exception is push (K6A-G, user decision 2026-10-03):
#   the command is exactly 'git [-C <hub>] push origin gece/<name>' (name = ^[a-z0-9][a-z0-9-]{0,40}$, lowercase)
#   + hub repo + origin push URL is the hub's + push/network settings at defaults + branch.gece/<name>.pushRemote empty/origin
#   + local refs/heads/gece/<name> EXISTS + refs/tags/gece/<name> ABSENT + the .github tree is IDENTICAL between the branch and remote main (ls-remote) (G9)
#   + push.followTags off + no push.pushOption (G10) -> "allow". The proof file (.gate-local-ok) is not consulted:
#   the arbiter is GitHub's CI, the user does the merge. A push to MAIN is denied in every form (K6-A; the local gate proof doesn't allow it).
#   Every push decision (allow and deny) is written to the ledger with category 'push-izin' + 'neden' (reason).
#   Merge / force / delete / tag / writing gh do not pass this path (deny, unchanged).
# C3 (05.10): read-only gh commands (Test-GhReadOnly allowlist) also get allow at night; category 'gh-okuma'.
# A6 (05.10): key = a real file, under USERPROFILE or HOME (Get-GeceKeyDir). A4/A7: below.
# When night mode is off or the mode is not bypass, nothing is printed -> the prompt reaches the user normally.
# If an error occurs while the key is on, deny is printed too (NO fail-open; see the catch blocks below).
# If an error occurs while the key is absent, nothing is printed (the prompt reaches the user normally).
# GECE_BEKCI_MERKEZ: hub root path (default <HOME>\merkez; the selftest redirects it to a temp repo).
# GECE_BEKCI_REPO: GitHub name of the hub repo (<OWNER>/<REPO>; demo default ornek-kullanici/merkez).
# GECE_BEKCI_LSREMOTE_URL: remote URL for ls-remote (selftest only; if unset, the 'origin' name; git uses the fetch address, verified with MerkezUrlRe in the G9 block).
# ASCII-only (PS 5.1).

# A6 (05.10, Y7 #4/#5): key = ONLY a real file (a directory / broken link is not a key; same meaning as pre-push '[ -f ]').
# Both USERPROFILE and HOME are checked (USERPROFILE set but keyless + HOME with a key -> key EXISTS). If HOME is in Git Bash
# form (/c/...) it is converted to a Windows path. Returns: the .claude directory holding the key (the ledger goes there), else ''.
function Get-GeceKeyDir {
    foreach ($h in @([string]$env:USERPROFILE, [string]$env:HOME)) {
        if (-not $h) { continue }
        try {
            $dm = [regex]::Match($h, '^/([A-Za-z])(/.*)?$')
            if ($dm.Success) { $h = $dm.Groups[1].Value + ':' + $(if ($dm.Groups[2].Value) { $dm.Groups[2].Value } else { '/' }) }
            $d = Join-Path $h '.claude'
            if (Test-Path -LiteralPath (Join-Path $d 'gece-modu.on') -PathType Leaf) { return $d }
        } catch { }
    }
    return ''
}
$MerkezRoot = [string]$env:GECE_BEKCI_MERKEZ
if (-not $MerkezRoot) { $MerkezRoot = Join-Path $env:USERPROFILE 'merkez' }
$MerkezRepo = [string]$env:GECE_BEKCI_REPO
if (-not $MerkezRepo) { $MerkezRepo = 'ornek-kullanici/merkez' }
$MerkezUrlRe = '^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)' + [regex]::Escape($MerkezRepo) + '(\.git)?/?$'
$ProofMaxAgeSec = 7200
$ProofFutureSkewSec = 300

# T84 (Turkish-I): under the tr-TR culture PowerShell -match/-imatch does NOT match case-insensitively on the letters I/i
# ('remove-item' -match 'Remove-Item' -> False). ALL case-insensitive matches in this script are made culture-independent
# with these two helpers (setting the culture has no effect in the same session; measured).
$RxOpts = [Text.RegularExpressions.RegexOptions]'IgnoreCase, CultureInvariant'
function Test-Rx([string]$s, [string]$p) { return [regex]::IsMatch($s, $p, $RxOpts) }

# Runs git in a child process (15 s limit; exceeding it = exception -> deny). Arguments contain no quotes (the callers' guarantee).
function Invoke-Git([string]$dir, [string[]]$gitArgs, [hashtable]$envVars = $null) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'git'
    $parts = @('-C', $dir) + $gitArgs | ForEach-Object { if (Test-Rx $_ '\s') { '"' + $_ + '"' } else { $_ } }
    $psi.Arguments = ($parts -join ' ')
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    if ($envVars) {
        foreach ($k in $envVars.Keys) {
            $psi.EnvironmentVariables[[string]$k] = [string]$envVars[$k]
        }
    }
    # replace objects can be written locally without a permission prompt; the watcher must read the real objects (envVars cannot override this).
    $psi.EnvironmentVariables['GIT_NO_REPLACE_OBJECTS'] = '1'
    $p =[System.Diagnostics.Process]::Start($psi)
    $o = $p.StandardOutput.ReadToEndAsync()
    $e = $p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit(15000)) { Stop-ProcessTree $p; throw "git timed out: $($gitArgs -join ' ')" }
    $p.WaitForExit()
    # A7: output is read with a time limit -- if git exited but a descendant holds the pipe, we do not wait forever (deny).
    if (-not ($o.Wait(5000) -and $e.Wait(5000))) { throw "git output could not be read (pipe left open): $($gitArgs -join ' ')" }
    return [pscustomobject]@{ Rc = $p.ExitCode; Out = ([string]$o.Result).Trim() }
}

# A7 (05.10, Y7 #13; Fable FACT 420 s block): 'git' = the cmd\git.exe wrapper; the real work is done by the child (mingw64/ucrt64 git.exe).
# Killing only the wrapper leaves the child ORPHANED; the child holds the pipe handles (including the hook's own stdout).
# The whole tree is killed with taskkill /T /F (absolute System32 path: isn't resolved from PATH); then the wrapper is also Kill()ed.
function Stop-ProcessTree([System.Diagnostics.Process]$proc) {
    try {
        $kpsi = New-Object System.Diagnostics.ProcessStartInfo
        $kpsi.FileName = Join-Path ([Environment]::SystemDirectory) 'taskkill.exe'
        $kpsi.Arguments = '/T /F /PID ' + $proc.Id
        $kpsi.UseShellExecute = $false
        $kpsi.RedirectStandardOutput = $true
        $kpsi.RedirectStandardError = $true
        $kpsi.CreateNoWindow = $true
        $k = [System.Diagnostics.Process]::Start($kpsi)
        $null = $k.StandardOutput.ReadToEndAsync(); $null = $k.StandardError.ReadToEndAsync()
        if (-not $k.WaitForExit(10000)) { try { $k.Kill() } catch { } }
    } catch { }
    try { $proc.Kill() } catch { }
}

function Get-NormPath([string]$p) { return $p.Replace('\', '/').TrimEnd('/').ToLowerInvariant() }

# $gece: allow is $true ONLY on the gece/<name> path (the main block's allow depends on this flag).
function New-Verdict([bool]$allow, [string]$neden, [bool]$gece = $false) { return [pscustomobject]@{ Allow = $allow; Neden = $neden; Gece = $gece } }

# N3: violation of a single network-setting line (empty = clean). Key in git's written form (section/key lowercase).
function Get-NetConfigViolation([string]$scope, [string]$key, [string]$val) {
    $k = $key.ToLowerInvariant(); $v = $val.Trim()
    if ($k -eq 'remote.origin.pushurl') { return "remote.origin.pushurl is set ($scope) -- push address only via url" }
    if (Test-Rx $k '^(remote\.origin\.proxy|core\.gitproxy|core\.sshcommand)$') { return "$k is set ($scope) -- traffic can be redirected" }
    if (Test-Rx $k '^http\.(.+\.)?proxy$') { return "$k is set ($scope) -- traffic goes through a proxy server" }
    if (Test-Rx $k '^url\..+\.(pushinsteadof|insteadof)$') { return "$k is set ($scope) -- address is rewritten" }
    if ((Test-Rx $k '^http\.(.+\.)?sslverify$') -and @('true', '1', 'yes', 'on') -notcontains $v.ToLowerInvariant()) { return "$k=$v ($scope) -- TLS verification disabled" }
    if ((Test-Rx $k '^http\.(.+\.)?(sslcainfo|sslcapath)$') -and $scope -ne 'system') { return "$k is set ($scope) -- custom CA (only system scope accepted)" }
    if (Test-Rx $k '^credential\.(.+\.)?helper$') {
        # N3-1 (GOREV-10): the gh helper ONLY with the measured full path (09-30: the global github.com/gist helper's value is this).
        # The old pattern accepted a 'gh' in any directory or resolved from PATH (a fake gh would obtain the user's credentials).
        $okHelper = ($v -eq '') -or (Test-Rx $v '^(manager|manager-core|wincred|osxkeychain)$') -or (Test-Rx $v '^cache(\s+--timeout=\d+)?$') -or
                    (Test-Rx $v '^!([''"])C:\\Program Files\\GitHub CLI\\gh\.exe\1\s+auth\s+git-credential$')
        if (-not $okHelper) { return "$k=$v ($scope) -- credential helper outside the allowlist" }
    }
    return ''
}

# --- Push decision: steps COMMON to the main and gece/<name> paths (K6A-G: a helper instead of a copy) ---

# Target directory (-C or cwd) -> hub repo -> origin's push URL. Returns: a verdict if there is a violation, else $null.
# $m: groups 1-3 = -C target (double quote / single quote / unquoted).
function Test-PushTarget($ev, $m) {
    # Target directory: -C (relative to the event's cwd if relative) or the event's cwd.
    $cwd = [string]$ev.cwd
    $target = $m.Groups[1].Value + $m.Groups[2].Value + $m.Groups[3].Value
    if ($target) {
        $dm = [regex]::Match($target, '^/([A-Za-z])(/.*)?$', $RxOpts)
        if ($dm.Success) { $target = $dm.Groups[1].Value + ':' + $(if ($dm.Groups[2].Value) { $dm.Groups[2].Value } else { '/' }) }
        if (-not [IO.Path]::IsPathRooted($target)) {
            if (-not $cwd) { return New-Verdict $false 'relative -C path but no cwd -- hub could not be verified' }
            $target = Join-Path $cwd $target
        }
    } else { $target = $cwd }
    if (-not $target) { return New-Verdict $false 'target directory unclear (no cwd, no -C) -- hub could not be verified' }
    if (-not (Test-Path -LiteralPath $target -PathType Container)) { return New-Verdict $false "target directory does not exist ($target) -- not the hub" }
    $tTop = Invoke-Git $target @('rev-parse', '--show-toplevel')
    $mTop = Invoke-Git $MerkezRoot @('rev-parse', '--show-toplevel')
    if ($mTop.Rc -ne 0) { return New-Verdict $false "hub repo could not be read ($MerkezRoot)" }
    if ($tTop.Rc -ne 0 -or (Get-NormPath $tTop.Out) -ne (Get-NormPath $mTop.Out)) {
        return New-Verdict $false "not the hub repo (target: $($tTop.Out); hub: $($mTop.Out))"
    }

    $urls = Invoke-Git $MerkezRoot @('remote', 'get-url', '--push', '--all', 'origin')
    $ulist = @(([string]$urls.Out) -split "`r?`n" | Where-Object { $_.Trim() -ne '' })
    if ($urls.Rc -ne 0 -or $ulist.Count -eq 0) { return New-Verdict $false 'origin push address could not be read' }
    foreach ($u in $ulist) { if (-not (Test-Rx $u.Trim() $MerkezUrlRe)) { return New-Verdict $false "origin push address is not the hub ($($u.Trim()))" } }
    return $null
}

# Push settings. $pushRemoteKey: branch-specific key (main: branch.main.pushRemote; night: branch.gece/<name>.pushRemote).
# $needTracking: main path only -- requires main's upstream to be origin/main (git's tracking). Returns: a verdict if there is a violation, else $null.
function Test-PushConfig([string]$pushRemoteKey, [bool]$needTracking) {
    $keys = @('push.default', 'remote.pushDefault', $pushRemoteKey)
    if ($needTracking) { $keys += @('branch.main.remote', 'branch.main.merge') }
    $keys += @('remote.origin.push', 'remote.origin.mirror', 'push.followTags', 'push.pushOption')
    $cfg = @{}
    $def = @{}
    foreach ($k in $keys) {
        # Boolean keys are normalized to git's own form (--type=bool): a bare key ([push] followTags, no '=') is git's TRUE
        # but a raw read gives an empty value; an invalid value gives rc=128 -> 'setting could not be read' deny.
        $gitCfg = @('config', '--get-all', $k)
        if ($k -ceq 'remote.origin.mirror' -or $k -ceq 'push.followTags') { $gitCfg = @('config', '--type=bool', '--get-all', $k) }
        $r = Invoke-Git $MerkezRoot $gitCfg
        if ($r.Rc -eq 0) { $cfg[$k] = [string]$r.Out; $def[$k] = $true } elseif ($r.Rc -eq 1) { $cfg[$k] = '' } else { return New-Verdict $false "setting could not be read ($k rc=$($r.Rc))" }
    }
    if (@('', 'simple', 'current', 'upstream') -notcontains $cfg['push.default'].ToLowerInvariant()) { return New-Verdict $false "setting: push.default=$($cfg['push.default']) (only simple/current/upstream)" }
    if (@('', 'origin') -cnotcontains $cfg['remote.pushDefault']) { return New-Verdict $false "setting: remote.pushDefault=$($cfg['remote.pushDefault'])" }
    if (@('', 'origin') -cnotcontains $cfg[$pushRemoteKey]) { return New-Verdict $false "setting: $pushRemoteKey=$($cfg[$pushRemoteKey])" }
    if ($cfg['remote.origin.push']) { return New-Verdict $false "setting: remote.origin.push is set ($($cfg['remote.origin.push']))" }
    if (@(([string]$cfg['remote.origin.mirror']) -split "`r?`n") -contains 'true') { return New-Verdict $false 'setting: remote.origin.mirror is on' }
    # G10: push settings that carry tags or extra data (push.followTags on / push.pushOption set) -> deny.
    if (@(([string]$cfg['push.followTags']) -split "`r?`n") -contains 'true') { return New-Verdict $false "setting: push.followTags=$($cfg['push.followTags']) (may carry tags)" }
    # G10b: being set means git's rc=0; an empty value or a bare key is also SET (git's rule).
    if ($def['push.pushOption']) { return New-Verdict $false "setting: push.pushOption is set ($($cfg['push.pushOption']))" }
    if ($needTracking -and ($cfg['branch.main.remote'] -cne 'origin' -or $cfg['branch.main.merge'] -cne 'refs/heads/main')) {
        return New-Verdict $false "setting: the branch main tracks is not origin/main (remote=$($cfg['branch.main.remote']) merge=$($cfg['branch.main.merge']))"
    }
    return $null
}

# N3 (Agent 2 OWASP, GOREV-4 2026-09-30): even if the URL is correct, a setting that redirects traffic (proxy/sshCommand/insteadOf),
# weakens TLS verification (sslVerify/sslCAInfo) or hands the credentials to another command (credential.helper) ->
# deny. All scopes (system/global/local, including include) are read. The allowlist was MEASURED on this machine (09-30):
# system credential.helper=manager, global github.com gh helper, system http.sslcainfo (Git's CA bundle).
function Test-PushNetConfig {
    $net = Invoke-Git $MerkezRoot @('config', '--show-scope', '--get-regexp', '^(http\..*|remote\.origin\.(pushurl|proxy)|core\.(sshcommand|gitproxy)|credential\..*|url\..*)$')
    if ($net.Rc -ne 0 -and $net.Rc -ne 1) { return New-Verdict $false "network settings could not be read (rc=$($net.Rc))" }
    foreach ($ln in (([string]$net.Out) -split "`r?`n")) {
        if (-not $ln.Trim()) { continue }
        $sc = ($ln -split "`t", 2)
        if ($sc.Count -lt 2) { return New-Verdict $false "network setting line could not be parsed ($ln)" }
        $kv = ($sc[1] -split ' ', 2)
        $bad = Get-NetConfigViolation $sc[0] $kv[0] $(if ($kv.Count -gt 1) { $kv[1] } else { '' })
        if ($bad) { return New-Verdict $false "network setting: $bad" }
    }
    return $null
}

# A4 (05.10, Y7 #2): N3 reads only git's config; the process ENVIRONMENT also redirects traffic (proxy / ssh command) or disables TLS
# verification. push and ls-remote run with this environment -> each one that is set (non-empty) is a deny. Windows environment names
# are case-insensitive (https_proxy is caught too). Needs no git read; called BEFORE ls-remote's invocation.
function Test-PushNetEnv {
    foreach ($nv in @('GIT_SSH_COMMAND', 'GIT_SSH', 'GIT_SSL_NO_VERIFY', 'GIT_SSL_CAINFO', 'GIT_SSL_CAPATH',
                      'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'GIT_PROXY_COMMAND')) {
        if ([Environment]::GetEnvironmentVariable($nv)) { return New-Verdict $false "network environment variable is set: $nv -- traffic can be redirected or TLS verification weakened" }
    }
    return $null
}

# K6A-G: the gece/<name> branch's push. Allow is produced ONLY here (Gece=$true). CI is the arbiter, the user does the merge.
# The name regex's matching is CASE-SENSITIVE (no IgnoreCase) and CultureInvariant: only a-z0-9-; tr-TR's dotless/dotted capital/small I letters (U+0131, U+0130) are rejected.
# The proof file (.gate-local-ok) is not consulted on this path (G4). Order: name -> git/network environment (G13, A4) -> hub -> origin ->
# local branch/tag -> origin fetch address -> N3 network settings (A4: ahead of ls-remote's network call) -> ls-remote/.github (G9) -> push settings.
# $m: groups 1-3 = -C target, group 4 = the 'gece/...' token (no spaces).
function Test-GecePush($ev, $m) {
    $ref = $m.Groups[4].Value
    if (-not [regex]::IsMatch($ref, '^gece/[a-z0-9][a-z0-9-]{0,40}\z', [Text.RegularExpressions.RegexOptions]::CultureInvariant)) {
        return New-Verdict $false "invalid night branch name ($ref) -- only gece/<name>, name = [a-z0-9][a-z0-9-]{0,40} (lowercase; no dot/underscore/slash/colon in the name)"
    }
    $ad = $ref.Substring(5)

    # G13: these variables shift git -C reads to another repo, and the real push goes there too (BEFORE the git reads).
    foreach ($gv in @('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR')) {
        if ([Environment]::GetEnvironmentVariable($gv)) { return New-Verdict $false "git environment variable is set: $gv" }
    }
    # A4: the network environment is also checked BEFORE the git reads (and ls-remote's run).
    $v = Test-PushNetEnv
    if ($v) { return $v }

    $v = Test-PushTarget $ev $m
    if ($v) { return $v }

    $hd = Invoke-Git $MerkezRoot @('show-ref', '--verify', '--quiet', "refs/heads/gece/$ad")
    if ($hd.Rc -ne 0) { return New-Verdict $false "local branch missing (refs/heads/gece/$ad rc=$($hd.Rc)) -- first create the local gece/$ad branch" }
    $tg = Invoke-Git $MerkezRoot @('show-ref', '--verify', '--quiet', "refs/tags/gece/$ad")
    if ($tg.Rc -ne 1) { return New-Verdict $false "tag conflict or could not be read (refs/tags/gece/$ad rc=$($tg.Rc)) -- git may push the tag" }

    # G9 (CRITICAL): a GitHub branch's push runs EVERY workflow file on the branch (the repo's secrets + a self-hosted runner exist);
    # a new/changed workflow on the branch breaks the K6-A lock from CI's side. The .github tree must be IDENTICAL between the branch and remote main (ls-remote).
    $om = Invoke-Git $MerkezRoot @('rev-parse', '--verify', '-q', 'refs/remotes/origin/main')
    if ($om.Rc -ne 0) { return New-Verdict $false 'origin/main missing locally -- .github comparison could not be made' }
    $localOmSha = [string]$om.Out

    # G9v3-6 (EXTRA): git ls-remote origin uses the fetch address (remote.origin.url). Hub URL verification (no network read).
    $fu = Invoke-Git $MerkezRoot @('remote', 'get-url', 'origin')
    $fetchUrl = [string]$fu.Out
    $fuLines = @($fetchUrl -split "`r?`n" | Where-Object { $_.Trim() -ne '' })
    if ($fu.Rc -ne 0 -or $fuLines.Count -ne 1 -or -not (Test-Rx $fetchUrl $MerkezUrlRe)) {
        return New-Verdict $false "origin fetch address is not the hub ($fetchUrl)"
    }

    # A4: N3's network settings BEFORE ls-remote (ls-remote's call goes onto the network; proxy/sshCommand/insteadOf/sslVerify affect it too).
    $v = Test-PushNetConfig
    if ($v) { return $v }

    $uzak = [string]$env:GECE_BEKCI_LSREMOTE_URL
    if (-not $uzak) { $uzak = 'origin' }
    $lsEnv = @{ 'GIT_TERMINAL_PROMPT' = '0'; 'GCM_INTERACTIVE' = 'never' }
    $ls = Invoke-Git $MerkezRoot @('ls-remote', $uzak, 'refs/heads/main') $lsEnv
    if ($ls.Rc -ne 0) { return New-Verdict $false "remote main could not be read (ls-remote rc=$($ls.Rc))" }
    if (-not $ls.Out) { return New-Verdict $false 'no main on the remote (ls-remote empty)' }
    $lsLines = @(([string]$ls.Out) -split "`r?`n" | Where-Object { $_.Trim() -ne '' })
    if ($lsLines.Count -ne 1) { return New-Verdict $false "remote main output is not a single line (ls-remote lines=$($lsLines.Count))" }
    $mSha = [regex]::Match($lsLines[0], '^([0-9a-f]{40})\trefs/heads/main\z', [Text.RegularExpressions.RegexOptions]::CultureInvariant)
    if (-not $mSha.Success) { return New-Verdict $false "remote main format invalid (ls-remote output: $($lsLines[0]))" }
    $remoteSha = $mSha.Groups[1].Value

    $cf = Invoke-Git $MerkezRoot @('cat-file', '-e', "$remoteSha^{commit}")
    if ($cf.Rc -ne 0) {
        $shortRemote = $remoteSha.Substring(0, 7)
        return New-Verdict $false "remote main $shortRemote missing locally -- run git fetch origin first"
    }

    if ($localOmSha -ne $remoteSha) {
        return New-Verdict $false "local origin/main differs from the remote main's tip (tampered or stale) -- git fetch origin"
    }

    # A5: the pathspec is case-insensitive; .GitHub/.GITHUB (a separate tree entry via update-index) also counts as .github.
    $gh = Invoke-Git $MerkezRoot @('diff', '--quiet', '--no-ext-diff', $remoteSha, "refs/heads/gece/$ad", '--', ':(icase).github')
    if ($gh.Rc -eq 1) { return New-Verdict $false "branch's .github tree differs from origin/main (gece/$ad) -- a workflow file could read secrets; push with .github unchanged" }
    if ($gh.Rc -ne 0) { return New-Verdict $false "branch .github comparison could not be read (gece/$ad rc=$($gh.Rc)) -- .github" }

    $v = Test-PushConfig "branch.gece/$ad.pushRemote" $false
    if ($v) { return $v }

    return New-Verdict $true "night branch push allowed (refs/heads/gece/$ad -> origin; CI is the arbiter, the user does the merge)" $true
}

# Conditional push decision. Returns: Allow + Neden + Gece. Allow occurs ONLY on the gece/<name> path; main is denied in every form (K6-A).
# Main order: form -> hub -> origin -> branch -> settings -> N3 -> fast-forward -> proof (result is still deny).
function Test-PushGate($ev, [string]$tool, [string]$cmd) {
    if ($tool -ne 'Bash' -and $tool -ne 'PowerShell') { return New-Verdict $false "tool $tool (only Bash/PowerShell)" }
    if (Test-Rx $cmd '[;&|<>`$(){}\r\n]') {
        return New-Verdict $false 'chaining/redirection/subshell character present (; & | < > ` $ ( ) { } line break) -- a single plain command is required'
    }
    $pfx = '^git(?:\s+-C\s+(?:"([^"]+)"|''([^'']+)''|([^\s"'']+)))?\s+push'
    $m = [regex]::Match($cmd.Trim(), $pfx + '(?:\s+origin(?:\s+main)?)?$')
    if (-not $m.Success) {
        $gm = [regex]::Match($cmd.Trim(), $pfx + '\s+origin\s+(gece/\S+)$')
        if ($gm.Success) { return Test-GecePush $ev $gm }
        return New-Verdict $false 'form outside the narrow path: only git [-C <hub>] push [origin [main]] (no force/delete/tag/refspec/other remote/flags)'
    }

    $v = Test-PushTarget $ev $m
    if ($v) { return $v }

    $br = Invoke-Git $MerkezRoot @('symbolic-ref', '-q', 'HEAD')
    if ($br.Rc -ne 0 -or $br.Out -cne 'refs/heads/main') { return New-Verdict $false "branch is not main ($($br.Out))" }

    $v = Test-PushConfig 'branch.main.pushRemote' $true
    if ($v) { return $v }
    $v = Test-PushNetConfig
    if ($v) { return $v }
    $v = Test-PushNetEnv
    if ($v) { return $v }

    $om = Invoke-Git $MerkezRoot @('rev-parse', '--verify', '-q', 'refs/remotes/origin/main')
    if ($om.Rc -ne 0) { return New-Verdict $false 'fast-forward could not be verified: origin/main missing locally' }
    $anc = Invoke-Git $MerkezRoot @('merge-base', '--is-ancestor', 'refs/remotes/origin/main', 'HEAD')
    if ($anc.Rc -ne 0) { return New-Verdict $false 'not a fast-forward: origin/main is not HEAD''s ancestor (no fetch was done; judged against the local origin/main''s state)' }

    $hd = Invoke-Git $MerkezRoot @('rev-parse', '--verify', 'HEAD')
    $head = [string]$hd.Out
    if ($hd.Rc -ne 0 -or -not (Test-Rx $head '^[0-9a-f]{40}$')) { return New-Verdict $false 'proof could not be checked: HEAD could not be read' }
    $short = $head.Substring(0, 7)
    $pf = Join-Path $MerkezRoot '.gate-local-ok'
    if (-not (Test-Path -LiteralPath $pf -PathType Leaf)) {
        return New-Verdict $false "no proof; main's push is forbidden while the night key is on (K6-A)"
    }
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $fams = @{}
    foreach ($ln in [IO.File]::ReadAllLines($pf)) {
        $pm = [regex]::Match($ln.Trim(), '^v1 sha=([0-9a-f]{40}) secim=(hepsi|bash|ps) parca=([0-9]{1,3})/([0-9]{1,3}) epoch=([0-9]{1,12}) zaman=\S+$')
        if (-not $pm.Success -or $pm.Groups[1].Value -ne $head) { continue }
        $k = [int]$pm.Groups[3].Value; $n = [int]$pm.Groups[4].Value; $ep = [long]$pm.Groups[5].Value
        if ($n -lt 1 -or $k -lt 1 -or $k -gt $n) { continue }
        if ($ep -gt ($now + $ProofFutureSkewSec) -or ($now - $ep) -gt $ProofMaxAgeSec) { continue }
        $fam = $pm.Groups[2].Value + '|' + $n
        if (-not $fams.ContainsKey($fam)) { $fams[$fam] = @{} }
        $fams[$fam][$k] = $true
    }
    $complete = @($fams.Keys | Where-Object { $fams[$_].Count -eq [int]($_.Split('|')[1]) } | Sort-Object)
    $sec = @($complete | ForEach-Object { $_.Split('|')[0] })
    $bashOk = ($sec -contains 'bash') -or ($sec -contains 'hepsi')
    $psOk = ($sec -contains 'ps') -or ($sec -contains 'hepsi')
    if (-not ($bashOk -and $psOk)) {
        return New-Verdict $false "proof missing/stale: no full coverage for HEAD $short within <= 2 h (bash=$bashOk ps=$psOk; complete families: $($complete -join ','))"
    }
    return New-Verdict $false "local gate proof doesn't permit main while the night key is on (K6-A)"
}

# C3 (05.10, FIKIR_KUTUSU_1005 C3; KURAL_KANCA_ENVANTER: 13/13 night 'dis-yazma' denials were read-only commands):
# so CI can be watched at night, ONLY these read-only gh forms get allow (Bash/PowerShell, a single plain command):
#   gh run list|view|watch, gh pr list|view|checks|diff, gh issue list|view  (arguments free; no chaining/redirection)
#   gh api <single endpoint>: no method or -X/--method GET; the only allowed flags are read-formatting ones
#   (--paginate --slurp -i/--include --silent --verbose -q/--jq -t/--template --cache --hostname). A field/input/header
#   flag (-f -F --field --raw-field --input -H --header) and every unknown flag -> not allowed. graphql -> not allowed.
# If not allowed, the command falls back to the old category table (deny). Pattern is case-insensitive + CultureInvariant (T84).
function Test-GhReadOnly([string]$tool, [string]$cmd) {
    if ($tool -ne 'Bash' -and $tool -ne 'PowerShell') { return $false }
    if (Test-Rx $cmd '[;&|<>`$(){}\r\n]') { return $false }
    $c = $cmd.Trim()
    if (Test-Rx $c '^gh\s+(run\s+(list|view|watch)|pr\s+(list|view|checks|diff)|issue\s+(list|view))(\s|$)') { return $true }
    if (-not (Test-Rx $c '^gh\s+api(\s|$)')) { return $false }
    $toks = @([regex]::Matches($c, '"[^"]*"|''[^'']*''|\S+') | ForEach-Object { $_.Value })
    $endpoints = 0
    $i = 2
    while ($i -lt $toks.Count) {
        $t = $toks[$i]
        $bare = $t.Trim('"', "'")
        if ($t.StartsWith('-')) {
            $fm = [regex]::Match($t, '^(--?[A-Za-z][A-Za-z-]*)(=(.*))?$', [Text.RegularExpressions.RegexOptions]::CultureInvariant)
            if (-not $fm.Success) { return $false }
            $flag = $fm.Groups[1].Value
            $hasEq = $fm.Groups[2].Success
            if (@('--paginate', '--slurp', '-i', '--include', '--silent', '--verbose') -ccontains $flag) {
                if ($hasEq) { return $false }
            } elseif (@('-q', '--jq', '-t', '--template', '--cache', '--hostname') -ccontains $flag) {
                if (-not $hasEq) { $i++; if ($i -ge $toks.Count) { return $false } }
            } elseif (@('-X', '--method') -ccontains $flag) {
                $val = $fm.Groups[3].Value
                if (-not $hasEq) { $i++; if ($i -ge $toks.Count) { return $false }; $val = $toks[$i] }
                if (-not (Test-Rx $val.Trim('"', "'") '^GET$')) { return $false }
            } else { return $false }
        } else {
            if (Test-Rx $bare '^graphql$') { return $false }
            $endpoints++
        }
        $i++
    }
    return ($endpoints -eq 1)
}

function Test-PlanIzni([string]$tool, [string]$cmd) {
    # Plan approval (decision #57, 2026-10-07): when the user says "approved" in a plan, the permissions the plan foresees
    # are written to the user's ~/.claude/plan-izinleri.txt. Lines: 'SON: yyyy-MM-ddTHH:mm:ss' (required; if past, the file is ignored)
    # + each other line is a -like pattern (the command; if no command, the tool name). A pattern cannot start with '*' and must be at least 6 characters.
    # Dangerous commands (force push, branch delete, --no-verify, night key) NEVER get permission even if a pattern matches.
    try {
        $f = Join-Path $env:USERPROFILE '.claude\plan-izinleri.txt'
        if (-not (Test-Path -LiteralPath $f)) { return $null }
        $lines = @(Get-Content -LiteralPath $f -Encoding UTF8 | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
        $son = $lines | Where-Object { $_ -like 'SON:*' } | Select-Object -First 1
        if (-not $son) { return $null }
        $t = [datetime]::ParseExact($son.Substring(4).Trim(), 'yyyy-MM-ddTHH:mm:ss', [Globalization.CultureInfo]::InvariantCulture)
        if ((Get-Date) -gt $t) { return $null }
        $hedef = if ($cmd) { $cmd.Trim() } else { $tool }
        if ([regex]::IsMatch($hedef, '(--force|\s-f(\s|$)|\s\+\S|--delete|\s-d\s|\s:\S|gece-modu|--no-verify)', 'IgnoreCase, CultureInvariant')) { return $null }
        # Prefix stripping: 'cd <path> && ', 'cd <path>; ', 'timeout N ', 'bash .../rwt.sh N ' -> so the real command can match the pattern.
        $soyulmus = $hedef
        for ($k = 0; $k -lt 4; $k++) {
            $soyulmus = [regex]::Replace($soyulmus, '^\s*cd\s+("[^"]*"|''[^'']*''|\S+)\s*(&&|;)\s*', '')
            $soyulmus = [regex]::Replace($soyulmus, '^\s*timeout\s+\d+\s+', '')
            $soyulmus = [regex]::Replace($soyulmus, '^\s*bash\s+\S*rwt\.sh\s+\d+\s+', '')
        }
        foreach ($p in ($lines | Where-Object { $_ -notlike 'SON:*' })) {
            # 'ARAC:<name>' = exact tool-name match for commandless tools (Edit/Write).
            if ($p -like 'ARAC:*') { if ((-not $cmd) -and ($tool -eq $p.Substring(5).Trim())) { return "plan permission: $p" }; continue }
            if ($p.Length -lt 6 -or $p.StartsWith('*')) { continue }
            if (($hedef -like $p) -or ($soyulmus -like $p)) { return "plan permission: $p" }
        }
    } catch { }
    return $null
}

try {
    $KeyDir = Get-GeceKeyDir
    if (-not $KeyDir) { exit 0 }
    $Ledger = Join-Path $KeyDir 'gece-defteri.jsonl'

    $reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [Text.Encoding]::UTF8)
    $raw = $reader.ReadToEnd()
    $ev = $raw | ConvertFrom-Json
    # Engage ONLY in bypass mode; in other modes the prompt is a conscious choice of the user (Fable A/B consensus 09-29).
    if ([string]$ev.permission_mode -ne 'bypassPermissions') { exit 0 }

    $tool = [string]$ev.tool_name
    $cmd = ''
    if ($ev.tool_input -and $ev.tool_input.command) { $cmd = [string]$ev.tool_input.command }

    $cat = 'diger'
    $karar = 'deny'
    $neden = ''
    $msg = 'GECE-BEKCI: the user is away, this permission prompt was denied. Skip this step, write it to the morning list (DEVAM.md) and continue toward the goal another way.'
    # CultureInvariant: under tr-TR's culture -match 'GIT' does not count as 'git' (I -> dotless i); in Windows' naming GIT.exe is still git's executable.
    $planNeden = Test-PlanIzni $tool $cmd
    if ($planNeden) {
        $cat = 'plan-izni'
        $karar = 'allow'
        $neden = $planNeden
    } elseif ([regex]::IsMatch($cmd, '\bgit\b.*\bpush\b', 'IgnoreCase, CultureInvariant')) {
        $cat = 'push-izin'
        try {
            $g = Test-PushGate $ev $tool $cmd
            $neden = $g.Neden
            # Allow passes ONLY from the gece/<name> path and only if the reason contains 'gece' (G6); everything else is deny.
            if ($g.Allow -eq $true -and $g.Gece -eq $true -and (Test-Rx $neden 'gece')) { $karar = 'allow' }
        } catch {
            $neden = "hook error (deny): $($_.Exception.Message)"
        }
        $msg = 'GECE-BEKCI: push denied -- ' + $neden + '. Push to a gece/<name> branch (git push origin gece/<name>; the local branch must exist, with .github unchanged); main''s merge is done by the user in the morning. Continue with a local commit; write the pending merge to the morning list.'
    } elseif (Test-GhReadOnly $tool $cmd) {
        $cat = 'gh-okuma'
        $karar = 'allow'
        $neden = 'read-only gh command (C3 allowlist)'
    } elseif (Test-Rx $cmd '\b(rm|rmdir|Remove-Item|del)\b') {
        $cat = 'silme'
        $msg = 'GECE-BEKCI: deletion of a critical path was denied. The target was probably resolved wrongly (relative path / empty variable). Use an absolute path (inside the scratchpad) or skip the deletion; carry on.'
    } elseif ($tool -eq 'AskUserQuestion') {
        $cat = 'soru'
        $msg = 'GECE-BEKCI: the user is away, no question can be asked. Decide yourself, write the rationale, carry on; state the decision in the morning report.'
    } elseif (Test-Rx $cmd '\bgh\b\s+(api|workflow\s+run|secret|variable|gist|pr\s+(create|comment|review|edit|close|merge)|issue|release|repo)\b') {
        # gh commands that write to an external service; the read-only ones in the C3 allowlist already got allow above as 'gh-okuma'.
        $cat = 'dis-yazma'
        $msg = 'GECE-BEKCI: writing to an external service (gh) is left for the morning. Write it to the morning list, carry on.'
    } elseif ((Test-Rx $tool 'Cron|RemoteTrigger|scheduled') -or (Test-Rx $cmd 'ScheduledTask|schtasks|New-Service')) {
        $cat = 'kalici-gorev'
        $msg = 'GECE-BEKCI: installing a persistent task/service is left for the morning. Write it to the morning list, carry on.'
    }

    $input_ozet = $cmd
    if (-not $input_ozet) { $input_ozet = ($ev.tool_input | ConvertTo-Json -Compress -Depth 4) }
    # B10 (OWASP 2026-09-30): a key-like string is masked in the ledger (stop-guard B5 pattern; BEFORE truncation).
    # W1C: wide secret set. CANON: scripts/tests/test_secret_mask_parity.py (identical in 5 places).
    $input_ozet = [regex]::Replace([string]$input_ozet, '(?:(?<=\\u00[0-9a-fA-F]{2})|(?<=\\[ntrbf])|(?<![A-Za-z0-9]))((?:nvapi-|sk-|AIza|ghp_|github_pat_|xox[abposr]-|AKIA|eyJ|Bearer\s+)|(?:[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD)|(?:[A-Z_]*_)?PASS(?:WD)?|[A-Z_]*_PWD)(?:[0-9_][A-Z0-9_]*)?(?:\\u0027|\\?[\x22\x27])?\s*[=:]\s*(?:\\u0027|\\?[\x22\x27])?)[^\s\x22\x27\\,}\]{\[]+', '$1***')
    if ($input_ozet.Length -gt 300) { $input_ozet = $input_ozet.Substring(0, 300) }

    $row = [ordered]@{
        ts         = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
        session_id = [string]$ev.session_id
        agent_id   = [string]$ev.agent_id
        mode       = [string]$ev.permission_mode
        tool       = $tool
        kategori   = $cat
        karar      = $karar
        girdi      = $input_ozet
    }
    if ($neden) { $row.neden = $neden }
    $line = ($row | ConvertTo-Json -Compress) + "`n"
    [IO.File]::AppendAllText($Ledger, $line, (New-Object Text.UTF8Encoding($false)))

    if ($karar -eq 'allow') { $decision = @{ behavior = 'allow' } } else { $decision = @{ behavior = 'deny'; message = $msg } }
    $out = @{
        hookSpecificOutput = @{
            hookEventName = 'PermissionRequest'
            decision      = $decision
        }
    }
    Write-Output ($out | ConvertTo-Json -Compress -Depth 5)
    exit 0
} catch {
    # If the key is on, an error is a deny too: fail-open opens the prompt and stops the work (Fable A/B consensus 09-29).
    $kd = ''
    try { $kd = Get-GeceKeyDir } catch { }
    if ($kd) {
        Write-Output '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"deny","message":"GECE-BEKCI: permission prompt denied (the hook could not read the input). Skip this step and continue toward the goal."}}}'
    }
    exit 0
}
