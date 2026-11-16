param(
    [string]$Region = 'us-east-1',
    [string]$Profile,
    [string]$AwsExecutable = 'aws',
    [string]$PythonExecutable = 'python',
    [string]$StackName = 'pyrogravity-demo'
)

$ErrorActionPreference = 'Stop'
$env:AWS_CLI_AUTO_PROMPT = 'off'
$awsOptions = @('--region', $Region, '--no-cli-pager')
if ($Profile) {
    $awsOptions += @('--profile', $Profile)
}

function Invoke-Aws {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$CommandArguments)
    $output = & $AwsExecutable @awsOptions @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falló AWS CLI: $($CommandArguments[0..1] -join ' ')."
    }
    return $output
}

function Get-StackOutputs([string]$Name) {
    $values = Invoke-Aws cloudformation describe-stacks --stack-name $Name --query 'Stacks[0].Outputs' --output json
    $result = @{}
    foreach ($entry in ($values | ConvertFrom-Json)) {
        $result[$entry.OutputKey] = $entry.OutputValue
    }
    return $result
}

$zipPath = Join-Path $PSScriptRoot '.build/lambda.zip'
$webPath = Join-Path $PSScriptRoot '../demo/web'
if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
    throw 'Genera infrastructure/aws/.build/lambda.zip con build.py antes de desplegar.'
}

$parameters = Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
$hash = $parameters.Hash.ToLowerInvariant()
$hashBase64 = [Convert]::ToBase64String([Convert]::FromHexString($hash))
$zipKey = "lambda/$hash.zip"
$artifactStack = "$StackName-artifacts"

Invoke-Aws cloudformation deploy --stack-name $artifactStack --template-file (Join-Path $PSScriptRoot 'artifacts.yaml') --tags Project=Pyrogravity Environment=demo --no-fail-on-empty-changeset
$artifactBucket = (Get-StackOutputs $artifactStack).ReleaseBucketName
Invoke-Aws s3 cp $zipPath "s3://$artifactBucket/$zipKey" --only-show-errors

Invoke-Aws cloudformation deploy --stack-name $StackName --template-file (Join-Path $PSScriptRoot 'demo.yaml') --capabilities CAPABILITY_IAM --tags Project=Pyrogravity Environment=demo --no-fail-on-empty-changeset --parameter-overrides "ArtifactBucket=$artifactBucket" "ArtifactKey=$zipKey" "ArtifactSha256=$hashBase64"
$site = Get-StackOutputs $StackName
$siteBucket = $site.SiteBucketName

Invoke-Aws s3 cp (Join-Path $webPath 'assets') "s3://$siteBucket/assets/" --recursive --cache-control 'public,max-age=300' --only-show-errors
Invoke-Aws s3 cp (Join-Path $webPath 'index.html') "s3://$siteBucket/index.html" --content-type 'text/html; charset=utf-8' --cache-control 'public,max-age=60' --only-show-errors
$invalidation = Invoke-Aws cloudfront create-invalidation --distribution-id $site.DistributionId --paths '/' '/index.html' '/assets/*' --query 'Invalidation.Id' --output text
$site | ConvertTo-Json -Compress
Invoke-Aws cloudfront wait invalidation-completed --distribution-id $site.DistributionId --id $invalidation
& $PythonExecutable (Join-Path $PSScriptRoot 'smoke.py') $site.SiteUrl
if ($LASTEXITCODE -ne 0) { throw 'Falló la verificación de la demo publicada.' }
