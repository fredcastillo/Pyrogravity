param(
    [Parameter(Mandatory)] [string]$ReleaseDirectory,
    [Parameter(Mandatory)] [ValidatePattern('^[0-9a-f]{40}$')] [string]$ReleaseId,
    [Parameter(Mandatory)] [string]$TemplateUrl,
    [string]$StackName = 'pyrogravity-demo',
    [string]$Region = 'us-east-1',
    [string]$PythonExecutable = 'python'
)

$ErrorActionPreference = 'Stop'
$env:AWS_CLI_AUTO_PROMPT = 'off'
$awsOptions = @('--region', $Region, '--no-cli-pager', '--output', 'json')

function Invoke-Aws {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$CommandArguments)
    $output = & aws @awsOptions @CommandArguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $detail = $output -join [Environment]::NewLine
        throw "Falló AWS CLI ($($CommandArguments[0..1] -join ' ')): $detail"
    }
    return $output
}

function Get-Stack([string]$Name) {
    $result = Invoke-Aws cloudformation describe-stacks --stack-name $Name --query 'Stacks[0]' | ConvertFrom-Json
    $outputs = @{}
    $parameters = @{}
    foreach ($output in $result.Outputs) { $outputs[$output.OutputKey] = $output.OutputValue }
    foreach ($parameter in $result.Parameters) { $parameters[$parameter.ParameterKey] = $parameter.ParameterValue }
    return @{ Id = $result.StackId; Outputs = $outputs; Parameters = $parameters }
}

function Update-Backend([hashtable]$Parameters) {
    $overrides = @(
        "ParameterKey=ArtifactBucket,ParameterValue=$($Parameters.ArtifactBucket)"
        "ParameterKey=ArtifactKey,ParameterValue=$($Parameters.ArtifactKey)"
        "ParameterKey=ArtifactSha256,ParameterValue=$($Parameters.ArtifactSha256)"
    )
    $null = Invoke-Aws cloudformation update-stack --stack-name $stack.Id --template-url $TemplateUrl --capabilities CAPABILITY_IAM --parameters @overrides
    $null = Invoke-Aws cloudformation wait stack-update-complete --stack-name $stack.Id
}

function Clear-PageCache {
    $id = Invoke-Aws cloudfront create-invalidation --distribution-id $site.DistributionId --paths '/' '/index.html' --query 'Invalidation.Id' | ConvertFrom-Json
    $null = Invoke-Aws cloudfront wait invalidation-completed --distribution-id $site.DistributionId --id $id
}

$zip = Join-Path $ReleaseDirectory 'lambda.zip'
$siteFiles = Join-Path $ReleaseDirectory 'site'
$index = Join-Path $siteFiles 'index.html'
$assets = Join-Path $siteFiles 'assets'
if (!(Test-Path -LiteralPath $zip -PathType Leaf) -or !(Test-Path -LiteralPath $index -PathType Leaf) -or !(Test-Path -LiteralPath $assets -PathType Container)) {
    throw 'Faltan archivos en la compilación de la demo.'
}

$stack = Get-Stack $StackName
$site = $stack.Outputs
$artifactBucket = (Get-Stack "$StackName-artifacts").Outputs.ReleaseBucketName
$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
$package = @{
    ArtifactBucket = $artifactBucket
    ArtifactKey = "lambda/$zipHash.zip"
    ArtifactSha256 = [Convert]::ToBase64String([Convert]::FromHexString($zipHash))
}
$assetPrefix = "assets/releases/$ReleaseId"
$previousHtml = Join-Path $ReleaseDirectory 'previous.html'
$nextHtml = Join-Path $ReleaseDirectory 'release.html'
$previousPage = Invoke-Aws s3api get-object --bucket $site.SiteBucketName --key index.html $previousHtml | ConvertFrom-Json
$html = Get-Content -LiteralPath $index -Raw -Encoding utf8
[IO.File]::WriteAllText($nextHtml, $html.Replace('"/assets/', '"/' + $assetPrefix + '/'))

$sameBackend = $stack.Parameters.ArtifactKey -eq $package.ArtifactKey -and
    $stack.Parameters.ArtifactBucket -eq $package.ArtifactBucket -and
    $stack.Parameters.ArtifactSha256 -eq $package.ArtifactSha256
if ($sameBackend -and (Get-FileHash -LiteralPath $previousHtml).Hash -eq (Get-FileHash -LiteralPath $nextHtml).Hash) {
    & $PythonExecutable (Join-Path $PSScriptRoot 'smoke.py') $site.SiteUrl --release-id $ReleaseId
    if ($LASTEXITCODE -eq 0) {
        & $PythonExecutable (Join-Path $PSScriptRoot 'smoke_command_center.py') $site.SiteUrl
        if ($LASTEXITCODE -eq 0) {
            Write-Output "La versión $ReleaseId ya está publicada y verificada. No se modificó AWS."
            return
        }
    }
    Write-Warning 'El índice y el backend coinciden, pero falló la comprobación pública. Se intentará recuperar la publicación.'
}

$backendUpdated = $false
$newPage = $null
try {
    $null = Invoke-Aws s3 cp $assets "s3://$($site.SiteBucketName)/$assetPrefix/" --recursive --cache-control 'public,max-age=31536000,immutable' --only-show-errors
    if (!$sameBackend) {
        $null = Invoke-Aws s3api put-object --bucket $artifactBucket --key $package.ArtifactKey --body $zip --checksum-sha256 $package.ArtifactSha256
        Update-Backend $package
        $backendUpdated = $true
    }

    $newPage = Invoke-Aws s3api put-object --bucket $site.SiteBucketName --key index.html --body $nextHtml --if-match $previousPage.ETag --content-type 'text/html; charset=utf-8' --cache-control 'public,max-age=60' | ConvertFrom-Json
    Clear-PageCache
    & $PythonExecutable (Join-Path $PSScriptRoot 'smoke.py') $site.SiteUrl --release-id $ReleaseId
    if ($LASTEXITCODE -ne 0) { throw 'La versión publicada no pasó la verificación de la página.' }
    & $PythonExecutable (Join-Path $PSScriptRoot 'smoke_command_center.py') $site.SiteUrl
    if ($LASTEXITCODE -ne 0) { throw 'La versión publicada no pasó la verificación del Command Center.' }
    Write-Output "Publicado $ReleaseId en $($site.SiteUrl)"
} catch {
    if ($newPage) {
        try {
            $null = Invoke-Aws s3api put-object --bucket $site.SiteBucketName --key index.html --body $previousHtml --if-match $newPage.ETag --content-type 'text/html; charset=utf-8' --cache-control 'public,max-age=60'
            Clear-PageCache
        } catch { Write-Warning "No se pudo recuperar el índice anterior: $_" }
    }
    if ($backendUpdated) {
        try {
            $current = Get-Stack $StackName
            if ($current.Parameters.ArtifactKey -eq $package.ArtifactKey) {
                Update-Backend $stack.Parameters
            }
        } catch { Write-Warning "No se pudo recuperar la versión anterior de FastAPI: $_" }
    }
    throw
}
