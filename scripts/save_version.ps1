param(
  [string]$Message = "chore: save workspace version",
  [switch]$Push
)

$ErrorActionPreference = "Stop"

$git = "C:\Users\xueme\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
if (!(Test-Path $git)) {
  $git = "git"
}

& $git status --short
& $git add .

$pending = & $git diff --cached --name-only
if (!$pending) {
  Write-Host "No staged changes to commit."
  exit 0
}

& $git commit -m $Message

if ($Push) {
  & $git push
}
