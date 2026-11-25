param(
  [string]$path,
  [string]$out,
  [int]$owner = 0
)

$ErrorActionPreference = "Stop"

function Emit([string[]]$lines) {
  $lines | Set-Content -LiteralPath $out -Encoding UTF8
}

if (-not $path -or -not (Test-Path -LiteralPath $path)) {
  Emit @("ERR`t找不到图片")
  exit 1
}

$src = @"
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class FundlifeTiles {
  public static string[] Run(string src, string dir, int owner) {
    Bitmap raw = null;
    Bitmap gray = null;
    try {
      raw = new Bitmap(src);
      int W = raw.Width;
      int H = raw.Height;
      if (W < 2 || H < 2) throw new InvalidOperationException("图片尺寸无效");
      gray = ToGray(raw);
      raw.Dispose();
      raw = null;
      AutoContrast(gray, 2);
      int scale = W < 1400 ? 3 : W < 2200 ? 2 : 1;
      int tileSrcH = 2500 / Math.Max(scale, 1);
      int overlap = 60;
      var lines = new List<string>();
      int y = 0;
      int idx = 0;
      while (y < H) {
        int bottom = Math.Min(H, y + tileSrcH + overlap);
        var rect = new Rectangle(0, y, W, bottom - y);
        using (var part = gray.Clone(rect, PixelFormat.Format24bppRgb)) {
          Bitmap sized = part;
          Bitmap scaled = null;
          if (scale != 1) {
            scaled = Scale(part, scale);
            sized = scaled;
          }
          string file = Path.Combine(dir, "fundlife_tile_" + owner + "_" + idx + ".png");
          sized.Save(file, ImageFormat.Png);
          if (scaled != null) scaled.Dispose();
          lines.Add(file + "\t" + y + "\t" + scale);
        }
        idx++;
        y += tileSrcH;
      }
      return lines.ToArray();
    } finally {
      if (raw != null) raw.Dispose();
      if (gray != null) gray.Dispose();
    }
  }

  static Bitmap ToGray(Bitmap src) {
    var bmp = new Bitmap(src.Width, src.Height, PixelFormat.Format24bppRgb);
    using (var g = Graphics.FromImage(bmp))
    using (var ia = new ImageAttributes()) {
      var cm = new ColorMatrix(new float[][] {
        new float[] {0.299f, 0.299f, 0.299f, 0, 0},
        new float[] {0.587f, 0.587f, 0.587f, 0, 0},
        new float[] {0.114f, 0.114f, 0.114f, 0, 0},
        new float[] {0, 0, 0, 1, 0},
        new float[] {0, 0, 0, 0, 1}
      });
      ia.SetColorMatrix(cm);
      g.DrawImage(src, new Rectangle(0, 0, src.Width, src.Height),
        0, 0, src.Width, src.Height, GraphicsUnit.Pixel, ia);
    }
    return bmp;
  }

  static void AutoContrast(Bitmap bmp, int cutoffPercent) {
    var rect = new Rectangle(0, 0, bmp.Width, bmp.Height);
    var data = bmp.LockBits(rect, ImageLockMode.ReadWrite, PixelFormat.Format24bppRgb);
    try {
      int stride = data.Stride;
      int bytes = Math.Abs(stride) * bmp.Height;
      byte[] buf = new byte[bytes];
      Marshal.Copy(data.Scan0, buf, 0, bytes);
      int[] hist = new int[256];
      int count = bmp.Width * bmp.Height;
      for (int y = 0; y < bmp.Height; y++) {
        int row = y * stride;
        for (int x = 0; x < bmp.Width; x++) hist[buf[row + x * 3]]++;
      }
      int ignore = count * cutoffPercent / 100;
      int lo = 0, hi = 255, seen = 0;
      for (int i = 0; i < 256; i++) { seen += hist[i]; if (seen > ignore) { lo = i; break; } }
      seen = 0;
      for (int i = 255; i >= 0; i--) { seen += hist[i]; if (seen > ignore) { hi = i; break; } }
      if (hi <= lo) return;
      double stretch = 255.0 / (hi - lo);
      for (int y = 0; y < bmp.Height; y++) {
        int row = y * stride;
        for (int x = 0; x < bmp.Width; x++) {
          int i = row + x * 3;
          int v = (int)Math.Round((buf[i] - lo) * stretch);
          if (v < 0) v = 0; else if (v > 255) v = 255;
          buf[i] = buf[i + 1] = buf[i + 2] = (byte)v;
        }
      }
      Marshal.Copy(buf, 0, data.Scan0, bytes);
    } finally {
      bmp.UnlockBits(data);
    }
  }

  static Bitmap Scale(Bitmap src, int scale) {
    int w = src.Width * scale;
    int h = src.Height * scale;
    var dst = new Bitmap(w, h, PixelFormat.Format24bppRgb);
    using (var g = Graphics.FromImage(dst)) {
      g.InterpolationMode = InterpolationMode.HighQualityBicubic;
      g.PixelOffsetMode = PixelOffsetMode.HighQuality;
      g.DrawImage(src, new Rectangle(0, 0, w, h));
    }
    return dst;
  }
}
"@

try {
  Add-Type -TypeDefinition $src -ReferencedAssemblies System.Drawing
  $dir = [System.IO.Path]::GetTempPath()
  $lines = [FundlifeTiles]::Run($path, $dir, $owner)
  if (-not $lines -or $lines.Length -eq 0) {
    Emit @("ERR`t没有生成切片")
    exit 1
  }
  Emit $lines
} catch {
  $msg = $_.Exception.InnerException
  if (-not $msg) { $msg = $_.Exception }
  $text = [string]$msg.Message
  if ($text -match "Out of memory|参数无效|external component") {
    $text = "打不开这张图，请换 PNG 或 JPG 截图"
  }
  Emit @("ERR`t$text")
  exit 1
}
