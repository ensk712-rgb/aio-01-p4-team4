# 로컬(Windows PowerShell 5.1+) → 서버 aio-t4 동기화. macOS/Linux는 deploy/push.sh.
#   powershell -ExecutionPolicy Bypass -File deploy\push.ps1            # 파일만 올린다
#   powershell -ExecutionPolicy Bypass -File deploy\push.ps1 -Setup     # 올린 뒤 서버 setup.sh 까지 실행
#   -KitDataApi 로 과정 키트 data-api 폴더를 지정할 수 있다 (기본 ..\aio-01d4-stu\Last3Mon\77\data-api)
param(
  [switch]$Setup,
  [string]$SshHost = "aio-t4",
  [string]$KitDataApi = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ($KitDataApi -eq "") { $KitDataApi = Join-Path (Split-Path -Parent $Root) "aio-01d4-stu\Last3Mon\77\data-api" }
$Remote = "~/aio-01-p4-team4"
Set-Location $Root

function Run($cmd) { Write-Host "  > $cmd"; & cmd /c $cmd; if ($LASTEXITCODE -ne 0) { throw "실패: $cmd" } }

Write-Host "== 저장소 파일 -> ${SshHost}:$Remote"
Run "ssh $SshHost ""mkdir -p $Remote/tools/data-api $Remote/runs $Remote/knowledge"""
foreach ($dir in @("workflows","lib","data","knowledge","cases","requests","config","webapp","deploy")) {
  if (-not (Test-Path $dir)) { Write-Host "  (없음, 건너뜀) $dir"; continue }
  if ($dir -eq "knowledge") {
    Run "scp -q knowledge\*.md ${SshHost}:$Remote/knowledge/"
  } else {
    Run "scp -rq $dir ${SshHost}:$Remote/"
  }
}

Write-Host "== 과정 키트 데이터 API -> ${SshHost}:$Remote/tools/data-api"
if (-not (Test-Path (Join-Path $KitDataApi "server.py"))) { throw "키트를 찾지 못함: $KitDataApi (-KitDataApi 로 지정)" }
Run "scp -q ""$KitDataApi\server.py"" ${SshHost}:$Remote/tools/data-api/server.py"
Run "ssh $SshHost ""mkdir -p $Remote/tools/data-api/kit-data"""
Run "scp -rq ""$KitDataApi\data\*"" ${SshHost}:$Remote/tools/data-api/kit-data/"

if (Test-Path (Join-Path $Root ".env")) {
  Write-Host "== .env -> 서버 (git에는 올리지 않음)"
  Run "scp -q .env ${SshHost}:$Remote/.env"
} else {
  Write-Host "== 로컬 .env 없음. 서버 .env 는 그대로 둔다 (없으면 setup.sh 가 만든다)."
}

if ($Setup) {
  Write-Host "== 서버 setup.sh 실행"
  Run "ssh $SshHost ""bash -lc 'cd $Remote && bash deploy/server/setup.sh'"""
} else {
  Write-Host "다음: ssh $SshHost ""bash -lc 'cd $Remote && bash deploy/server/setup.sh'"""
}
