[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $rules = [ordered]@{
        private_key = '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'
        openai_key = 'sk-[A-Za-z0-9_-]{20,}'
        github_token = '(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})'
        aws_key = 'AKIA[0-9A-Z]{16}'
        google_key = 'AIza[0-9A-Za-z_-]{30,}'
        slack_token = 'xox[baprs]-[0-9A-Za-z-]{10,}'
        private_email = '(?i)\b[A-Z0-9._%+-]+@(?!users\.noreply\.github\.com\b|example\.(?:com|org|net)\b)[A-Z0-9.-]+\.[A-Z]{2,}\b'
        user_profile_path = '(?i)\bC:\\Users\\(?!Public\\|Default\\|<user>\\)[^\\\s"'']+\\'
        local_workspace_path = '(?i)\b[A-Z]:\\(?:Claude[_\\]|\u4e34\u65f6\u6587\u4ef6\u5b58\u653e\\)'
        real_mac = '(?i)\b(?!00:00:00:00:00:00\b)(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b'
    }

    $findings = [System.Collections.Generic.List[object]]::new()
    foreach ($file in (git ls-files)) {
        $fullPath = Join-Path $repoRoot $file
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) { continue }
        $bytes = [IO.File]::ReadAllBytes($fullPath)
        if ($bytes -contains 0) { continue }
        $text = [Text.Encoding]::UTF8.GetString($bytes)
        foreach ($rule in $rules.GetEnumerator()) {
            foreach ($match in [regex]::Matches($text, $rule.Value)) {
                $line = 1 + ([regex]::Matches($text.Substring(0, $match.Index), "`n")).Count
                $findings.Add([pscustomobject]@{ Rule = $rule.Key; File = $file; Line = $line })
            }
        }
    }

    if ($findings.Count -gt 0) {
        $findings | Sort-Object Rule, File, Line -Unique | Format-Table -AutoSize
        throw "Security audit failed: $($findings.Count) potential sensitive value(s)."
    }
    Write-Host "Security audit passed: tracked text files contain no configured sensitive patterns."
} finally {
    Pop-Location
}
