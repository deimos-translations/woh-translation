using System;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using ImageMagick;
using UndertaleModLib.Util;

// Folders from WOH_IN and WOH_FONTS (set by replace_sprites.py; the CLI cannot show dialogs).
string inDir = Environment.GetEnvironmentVariable("WOH_IN") ?? throw new InvalidOperationException("WOH_IN is not set.");
string fontDir = Environment.GetEnvironmentVariable("WOH_FONTS") ?? throw new InvalidOperationException("WOH_FONTS is not set.");

EnsureDataLoaded();

// <sprite>_<frame>.png, same naming as export_woh.csx (unpadded frame index).
Regex frameName = new(@"^(.+?)_(\d+)$", RegexOptions.Compiled);

int replaced = 0;
foreach (string file in Directory.EnumerateFiles(inDir, "*.png").OrderBy(f => f, StringComparer.Ordinal))
{
    string stem = Path.GetFileNameWithoutExtension(file);
    Match match = frameName.Match(stem);
    if (!match.Success || !int.TryParse(match.Groups[2].Value, out int frame))
    {
        Console.WriteLine($"Skipping {stem}: not named <sprite>_<frame>.png.");
        continue;
    }

    UndertaleSprite sprite = Data.Sprites.ByName(match.Groups[1].Value);
    if (sprite is null || frame >= sprite.Textures.Count)
    {
        Console.WriteLine($"Skipping {stem}: no such sprite frame in data.win.");
        continue;
    }

    sprite.Textures[frame] = new UndertaleSprite.TextureEntry { Texture = AddPage(file, sprite.Textures[frame]?.Texture, true) };
    replaced++;
}

Console.WriteLine($"Replaced {replaced} sprite frames.");

// Fonts: <font>.png, an edited copy of the atlas. The glyph table is kept, so a missing font or a different size is an error, not a skip.
int fonts = 0;
foreach (string file in Directory.EnumerateFiles(fontDir, "*.png").OrderBy(f => f, StringComparer.Ordinal))
{
    string name = Path.GetFileNameWithoutExtension(file);
    UndertaleFont font = Data.Fonts.ByName(name) ?? throw new InvalidOperationException($"No font {name} in data.win.");
    UndertaleTexturePageItem old = font.Texture;
    font.Texture = AddPage(file, old, false);
    fonts++;
}

Console.WriteLine($"Replaced {fonts} fonts.");

// A new page per image: the old atlas is shared with other assets, so it stays untouched.
// Frames are exported padded (export_woh.csx: ExportAsPNG padded), so the PNG is the whole bounding box with the padding already in it:
// it must be the bounding box and is placed at the origin. Fonts are exported unpadded: the image must be the old source size and keeps the old placement (the glyph table).
UndertaleTexturePageItem AddPage(string file, UndertaleTexturePageItem old, bool padded)
{
    using MagickImage image = TextureWorker.ReadBGRAImageFromFile(file);
    ushort width = (ushort)image.Width;
    ushort height = (ushort)image.Height;
    if (old is not null)
    {
        ushort expectedWidth = padded ? old.BoundingWidth : old.SourceWidth;
        ushort expectedHeight = padded ? old.BoundingHeight : old.SourceHeight;
        if (width != expectedWidth || height != expectedHeight)
        {
            throw new InvalidOperationException($"{Path.GetFileName(file)} is {width}x{height}, the texture it replaces is {expectedWidth}x{expectedHeight}.");
        }
    }

    UndertaleEmbeddedTexture page = new();
    page.Name = new UndertaleString($"Texture {Data.EmbeddedTextures.Count}");
    page.TextureData.Image = GMImage.FromMagickImage(image).ConvertToPng();
    Data.EmbeddedTextures.Add(page);

    UndertaleTexturePageItem item = new();
    item.Name = new UndertaleString($"PageItem {Data.TexturePageItems.Count}");
    item.SourceX = 0;
    item.SourceY = 0;
    item.SourceWidth = width;
    item.SourceHeight = height;
    item.TargetX = old is null || padded ? (ushort)0 : old.TargetX;
    item.TargetY = old is null || padded ? (ushort)0 : old.TargetY;
    item.TargetWidth = width;
    item.TargetHeight = height;
    item.BoundingWidth = old is null ? width : old.BoundingWidth;
    item.BoundingHeight = old is null ? height : old.BoundingHeight;
    item.TexturePage = page;
    Data.TexturePageItems.Add(item);
    return item;
}
