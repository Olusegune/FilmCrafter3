param([string]$Voice, [string]$Text, [string]$Out, [int]$Rate = 0)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice($Voice)
$s.Rate = $Rate
$s.SetOutputToWaveFile($Out)
$s.Speak($Text)
$s.Dispose()
