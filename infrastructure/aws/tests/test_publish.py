"""Exercise the real PowerShell publisher with an in-memory AWS service double."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PUBLISH = Path(__file__).resolve().parents[1] / "publish.ps1"
PRIVATE_OLD = "private-ai/" + "1" * 64 + ".zip"
PUBLIC_OLD = "lambda/" + "2" * 64 + ".zip"

HARNESS = r'''
param($Publisher, $Release, $Trace, $Mode)
$ErrorActionPreference = 'Stop'
$global:privateKey = 'private-ai/' + ('1' * 64) + '.zip'
$global:publicKey = 'lambda/' + ('2' * 64) + '.zip'
if ($Mode -eq 'private-current') {
    $global:privateKey = 'private-ai/' + (Get-FileHash (Join-Path $Release 'private-ai.zip') -Algorithm SHA256).Hash.ToLowerInvariant() + '.zip'
}
function global:aws {
    $a = @($args)[5..($args.Count-1)]
    Add-Content -LiteralPath $Trace -Value (ConvertTo-Json -InputObject $a -Compress)
    $global:LASTEXITCODE = 0
    if ($a[0] -eq 'cloudformation' -and $a[1] -eq 'describe-stacks') {
        $name = $a[3]
        if ($name -like '*artifacts*') {
            return (@{StackId='artifacts';StackStatus='UPDATE_COMPLETE';Parameters=@();Outputs=@(@{OutputKey='ReleaseBucketName';OutputValue='artifacts-bucket'})}|ConvertTo-Json -Depth 5)
        }
        $isPrivate = $name -like '*ai-private*'
        $key = if ($isPrivate) { $global:privateKey } else { $global:publicKey }
        $values = @{ArtifactBucket='artifacts-bucket';ArtifactKey=$key;ArtifactSha256='previous'}
        if ($isPrivate) { $values.BackendRoleName='backend';$values.IngestOperatorArn='operator' }
        else { $values.PrivateAiFunctionArn='arn:aws:lambda:us-east-1:123456789012:function:pyrogravity-ai-private';$values.BackendAiSecretArn='secret-reference' }
        $parameters = @($values.GetEnumerator() | ForEach-Object { @{ParameterKey=$_.Key;ParameterValue=$_.Value} })
        $outputs = if ($isPrivate) { @{FunctionArn='arn:aws:lambda:us-east-1:123456789012:function:pyrogravity-ai-private'} }
        else { @{SiteUrl='https://example.test';SiteBucketName='site-bucket';DistributionId='distribution'} }
        $outputRows = @($outputs.GetEnumerator() | ForEach-Object { @{OutputKey=$_.Key;OutputValue=$_.Value} })
        return (@{StackId=$name;StackStatus='UPDATE_COMPLETE';Parameters=$parameters;Outputs=$outputRows}|ConvertTo-Json -Depth 5)
    }
    if ($a[0] -eq 'cloudformation' -and $a[1] -eq 'update-stack') {
        $isPrivate = $a[3] -like '*ai-private*'
        if ($Mode -eq 'private-update-failure' -and $isPrivate) { $global:LASTEXITCODE=1; return 'Simulated CloudFormation rejection' }
        $key = ($a | Where-Object { $_ -like 'ParameterKey=ArtifactKey,ParameterValue=*' }) -replace '^ParameterKey=ArtifactKey,ParameterValue=',''
        if ($isPrivate) { $global:privateKey=$key } else { $global:publicKey=$key }
        return '{}'
    }
    if ($a[0] -eq 'lambda') {
        $hex = $global:privateKey.Replace('private-ai/','').Replace('.zip','')
        $hash = [Convert]::ToBase64String([Convert]::FromHexString($hex))
        if ($Mode -eq 'hash-mismatch') { $hash = 'unexpected' }
        return (@{CodeSha256=$hash;State='Active';LastUpdateStatus='Successful'}|ConvertTo-Json)
    }
    if ($a[0] -eq 's3api' -and $a[1] -eq 'get-object') {
        Set-Content -LiteralPath $a[-1] -Value '<html>previous</html>'
        return '{"ETag":"previous-etag"}'
    }
    if ($a[0] -eq 's3api' -and $a[1] -eq 'put-object') { return '{"ETag":"new-etag"}' }
    if ($a[0] -eq 'cloudfront' -and $a[1] -eq 'create-invalidation') { return '"invalidation"' }
    return '{}'
}
function global:Invoke-Smoke {
    $global:LASTEXITCODE = if ($Mode -eq 'smoke-failure') { 1 } else { 0 }
}
$options = @{ReleaseDirectory=$Release;ReleaseId=('a'*40);TemplateUrl='https://example.test/public.yaml';PythonExecutable='Invoke-Smoke'}
if ($Mode -ne 'legacy') { $options.PrivateStackName='pyrogravity-ai-private';$options.PrivateTemplateUrl='https://example.test/private.yaml' }
try { & $Publisher @options } catch { Write-Output $_.Exception.Message; exit 1 }
'''


class PublishTests(unittest.TestCase):
    def run_publish(self, mode):
        shell = shutil.which("pwsh")
        self.assertIsNotNone(shell, "PowerShell 7 is required to verify the production publisher")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            assets = release / "site" / "assets"
            assets.mkdir(parents=True)
            (release / "site" / "index.html").write_text('<script src="/assets/app.js"></script>')
            (assets / "app.js").write_text("// fixture")
            (release / "lambda.zip").write_bytes(b"verified-public-fixture")
            (release / "private-ai.zip").write_bytes(b"verified-private-fixture")
            harness = root / "harness.ps1"
            harness.write_text(HARNESS, encoding="utf-8")
            trace = root / "aws.jsonl"
            result = subprocess.run(
                [shell, "-NoProfile", "-File", str(harness), str(PUBLISH), str(release), str(trace), mode],
                capture_output=True, text=True, timeout=30,
            )
            calls = [json.loads(line) for line in trace.read_text(encoding="utf-8-sig").splitlines()]
            return result, calls

    @staticmethod
    def updates(calls):
        return [call for call in calls if call[:2] == ["cloudformation", "update-stack"]]

    def test_private_package_precedes_public_release(self):
        result, calls = self.run_publish("success")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updates = self.updates(calls)
        self.assertEqual([call[3] for call in updates], ["pyrogravity-ai-private", "pyrogravity-demo"])
        expected = hashlib.sha256(b"verified-private-fixture").hexdigest()
        self.assertIn(f"ParameterKey=ArtifactKey,ParameterValue=private-ai/{expected}.zip", updates[0])
        self.assertIn("ParameterKey=BackendRoleName,UsePreviousValue=true", updates[0])
        self.assertIn("ParameterKey=IngestOperatorArn,UsePreviousValue=true", updates[0])
        self.assertTrue(any(call[:2] == ["lambda", "get-function-configuration"] for call in calls))

    def test_private_update_failure_never_publishes_public_files(self):
        result, calls = self.run_publish("private-update-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.updates(calls)), 1)
        self.assertFalse(any("site-bucket" in call and call[1] in {"put-object", "cp"} for call in calls))

    def test_public_failure_rolls_back_both_packages(self):
        result, calls = self.run_publish("smoke-failure")
        self.assertNotEqual(result.returncode, 0)
        updates = self.updates(calls)
        self.assertEqual([call[3] for call in updates], ["pyrogravity-ai-private", "pyrogravity-demo", "pyrogravity-demo", "pyrogravity-ai-private"])
        self.assertIn(f"ParameterKey=ArtifactKey,ParameterValue={PUBLIC_OLD}", updates[2])
        self.assertIn(f"ParameterKey=ArtifactKey,ParameterValue={PRIVATE_OLD}", updates[3])

    def test_hash_mismatch_rolls_back_before_public_update(self):
        result, calls = self.run_publish("hash-mismatch")
        self.assertNotEqual(result.returncode, 0)
        updates = self.updates(calls)
        self.assertEqual([call[3] for call in updates], ["pyrogravity-ai-private", "pyrogravity-ai-private"])
        self.assertIn(f"ParameterKey=ArtifactKey,ParameterValue={PRIVATE_OLD}", updates[-1])

    def test_unchanged_private_package_is_not_republished(self):
        result, calls = self.run_publish("private-current")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call[3] for call in self.updates(calls)], ["pyrogravity-demo"])

    def test_configuration_without_private_stack_keeps_existing_deployment(self):
        result, calls = self.run_publish("legacy")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call[3] for call in self.updates(calls)], ["pyrogravity-demo"])
        self.assertFalse(any(call[0] == "lambda" for call in calls))


if __name__ == "__main__":
    unittest.main()
