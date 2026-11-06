# Transcribe every WAV in pending\ with Windows' offline recognizer and add the results to transcripts.json (keyed by file name without extension).
Add-Type -AssemblyName System.Speech
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cachePath = Join-Path $here "transcripts.json"
$cache = @{}
if (Test-Path $cachePath) { (Get-Content $cachePath -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $cache[$_.Name] = $_.Value } }
Get-ChildItem (Join-Path $here "pending") -Filter *.wav -ErrorAction SilentlyContinue | ForEach-Object {
  $key = $_.BaseName
  if ($cache.ContainsKey($key)) { return }
  $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
  $rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
  $rec.SetInputToWaveFile($_.FullName)
  $out = @()
  for ($i = 0; $i -lt 60; $i++) {                       # a file is a few sentences: when the file ends the recognizer says so with null or an error, and either ends this
    try { $r = $rec.Recognize([TimeSpan]::FromSeconds(30)) } catch { break }
    if ($null -eq $r) { break }
    $out += $r.Text
  }
  $rec.Dispose()
  $cache[$key] = ($out -join " ").Trim()
  Write-Host ($key + ": " + $cache[$key])
}
$cache | ConvertTo-Json | Set-Content $cachePath -Encoding UTF8
