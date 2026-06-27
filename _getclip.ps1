Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$out = "C:\Users\ksang\eclipse-workspace\Aiccounting\_clip.png"
if (Test-Path $out) { Remove-Item $out -Force }
$img = [System.Windows.Forms.Clipboard]::GetImage()
if ($img) {
    $img.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Output "IMAGE saved -> $out"
} elseif ([System.Windows.Forms.Clipboard]::ContainsText()) {
    Write-Output "TEXT:"
    Write-Output ([System.Windows.Forms.Clipboard]::GetText())
} else {
    Write-Output "EMPTY (clipboard has no image or text)"
}
