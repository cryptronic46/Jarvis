param([string]$SttModel="small",[switch]$SkipSttModelDownload)
$arg=@('-ExecutionPolicy','Bypass','-File',"$PSScriptRoot\setup_voice_reset.ps1",'-SttModel',$SttModel)
if($SkipSttModelDownload){$arg += '-SkipSttModelDownload'}
& powershell @arg
exit $LASTEXITCODE
