param(
    [string]$Destination = "G:\JARVIS"
)

$ErrorActionPreference = "Stop"
$ExpectedVersion = "0.27.8"

function Fail([string]$Message) {
    Write-Host "ERRO: $Message" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath $Destination)) {
    Fail "Destino nao existe: $Destination"
}

$ManifestPath = Join-Path $Destination "release_manifest.json"
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    Fail "release_manifest.json em falta."
}

try {
    $Manifest = (
        Get-Content -LiteralPath $ManifestPath -Raw |
        ConvertFrom-Json
    )
}
catch {
    Fail "release_manifest.json e invalido."
}

if ($Manifest.release -ne $ExpectedVersion) {
    Fail "Manifesto nao corresponde a versao $ExpectedVersion."
}

function Get-ControlledReleaseFiles(
    [string]$Root,
    [object]$Manifest
) {
    $RootFull = (
        [System.IO.Path]::GetFullPath($Root)
    ).TrimEnd('\')
    $RuntimeParts = @(
        "__pycache__",
        ".venv",
        "memory",
        "knowledge",
        ".cache",
        "logs",
        "voice_profiles",
        "models"
    )
    $Result = @()

    foreach ($TreeName in @($Manifest.scope.trees)) {
        $Base = Join-Path $RootFull $TreeName
        if (-not (Test-Path -LiteralPath $Base)) {
            Fail "Controlled tree missing: $TreeName"
        }

        Get-ChildItem -LiteralPath $Base -File -Recurse -Force |
        ForEach-Object {
            $Relative = $_.FullName.Substring(
                $RootFull.Length + 1
            ).Replace('\','/')
            $Parts = $Relative.Split('/')
            $Skip = $false

            foreach ($Part in $Parts) {
                if ($RuntimeParts -contains $Part) {
                    $Skip = $true
                    break
                }
            }

            if ($_.Extension -ieq ".pyc") {
                $Skip = $true
            }

            if (-not $Skip) {
                $Result += $Relative
            }
        }
    }

    foreach ($Name in @($Manifest.scope.top_level)) {
        $Path = Join-Path $RootFull $Name
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            Fail "Controlled top-level file missing: $Name"
        }
        $Result += $Name.Replace('\','/')
    }

    return @($Result | Sort-Object -Unique)
}

foreach ($Item in $Manifest.files) {
    $Path = Join-Path $Destination $Item.path
    if (-not (Test-Path -LiteralPath $Path)) {
        Fail "Ficheiro em falta: $($Item.path)"
    }

    $Hash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $Path
    ).Hash.ToLowerInvariant()

    if ($Hash -ne $Item.sha256.ToLowerInvariant()) {
        Fail "Hash invalido: $($Item.path)"
    }
}

$Known = @(
    $Manifest.files |
    ForEach-Object { $_.path.Replace('\','/') } |
    Sort-Object -Unique
)
$Controlled = @(
    Get-ControlledReleaseFiles `
        -Root $Destination `
        -Manifest $Manifest
)
$MissingFromManifest = @(
    $Controlled |
    Where-Object { $Known -notcontains $_ }
)
$ManifestOutsideScope = @(
    $Known |
    Where-Object { $Controlled -notcontains $_ }
)

if ($MissingFromManifest.Count -gt 0) {
    Fail (
        "Ficheiros controlados fora do manifesto: " +
        ($MissingFromManifest -join ", ")
    )
}
if ($ManifestOutsideScope.Count -gt 0) {
    Fail (
        "Entradas do manifesto fora do scope controlado: " +
        ($ManifestOutsideScope -join ", ")
    )
}

$UnexpectedPy = @()
foreach ($Tree in @("jarvis_core", "tests")) {
    $Base = Join-Path $Destination $Tree
    if (-not (Test-Path -LiteralPath $Base)) {
        continue
    }

    Get-ChildItem $Base -File -Recurse -Filter "*.py" |
    ForEach-Object {
        $Relative = $_.FullName.Substring(
            $Destination.TrimEnd('\').Length + 1
        ).Replace('\','/')

        if ($Known -notcontains $Relative) {
            $UnexpectedPy += $Relative
        }
    }
}

if ($UnexpectedPy.Count -gt 0) {
    Write-Host "AVISO: ficheiros Python fora do manifesto:" -ForegroundColor Yellow
    $UnexpectedPy | ForEach-Object { Write-Host "  $_" }
    exit 2
}

Write-Host "JARVIS Core ${ExpectedVersion}: OK" -ForegroundColor Green
Write-Host "Manifesto integral: OK"
Write-Host "Ficheiros controlados inesperados: 0"
Write-Host "Ficheiros Python inesperados: 0"
exit 0
