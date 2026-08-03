param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [Parameter(Mandatory = $true)]
    [string]$WorkRoot,
    [int]$FirstPage = 1,
    [Parameter(Mandatory = $true)]
    [int]$LastPage,
    [Parameter(Mandatory = $true)]
    [int]$WorkerIndex,
    [Parameter(Mandatory = $true)]
    [int]$WorkerCount
)

$ErrorActionPreference = "Continue"
$project = [IO.Path]::GetFullPath($ProjectRoot)
$work = [IO.Path]::GetFullPath($WorkRoot)
$rescore = Join-Path $project ".venv\Scripts\rescore.exe"
$log = Join-Path $work ("worker-{0:D2}.log" -f $WorkerIndex)

for ($page = $FirstPage + $WorkerIndex; $page -le $LastPage; $page += $WorkerCount) {
    $image = Join-Path $work ("pages\page-{0:D4}.png" -f $page)
    $output = Join-Path $work ("individual\page-{0:D4}" -f $page)
    $candidate = Get-ChildItem -LiteralPath $output -Recurse -Filter *.mxl -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($candidate) {
        Add-Content -LiteralPath $log -Value ("SKIP page={0} candidate={1}" -f $page, $candidate.FullName)
        continue
    }
    Add-Content -LiteralPath $log -Value ("START page={0} time={1}" -f $page, (Get-Date -Format o))
    & $rescore omr-image $image --output $output *>> $log
    Add-Content -LiteralPath $log -Value ("END page={0} exit={1} time={2}" -f $page, $LASTEXITCODE, (Get-Date -Format o))
}

Add-Content -LiteralPath $log -Value ("WORKER_DONE index={0} time={1}" -f $WorkerIndex, (Get-Date -Format o))
