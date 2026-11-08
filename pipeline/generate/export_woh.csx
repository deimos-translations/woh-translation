using System;
using System.IO;
using System.Linq;
using UndertaleModLib.Util;

// Output roots from WOH_OUT (manifest, glyph tables) and WOH_SPRITES (sprite frames, font atlases in font/); set by woh.py. The CLI cannot show dialogs.
string Root = Environment.GetEnvironmentVariable("WOH_OUT") ?? throw new InvalidOperationException("WOH_OUT is not set.");
string SpritesDir = Environment.GetEnvironmentVariable("WOH_SPRITES") ?? throw new InvalidOperationException("WOH_SPRITES is not set.");

EnsureDataLoaded();

TextureWorker worker = new TextureWorker();

// Sprites: <name>_<frame>.png, same naming as ExportAllSprites.csx (unpadded).
using (StreamWriter manifest = new(Path.Combine(Root, "sprites_manifest.tsv")))
{
    manifest.WriteLine("sprite\tframes\twidth\theight\tfile_count");
    foreach (UndertaleSprite spr in Data.Sprites)
    {
        if (spr is not { SSpriteType: UndertaleSprite.SpriteType.Normal, Textures.Count: > 0 })
        {
            continue;
        }

        int written = 0;
        for (int i = 0; i < spr.Textures.Count; i++)
        {
            if (spr.Textures[i]?.Texture is null)
            {
                continue;
            }
            worker.ExportAsPNG(spr.Textures[i].Texture, Path.Combine(SpritesDir, $"{spr.Name.Content}_{i}.png"), null, true);
            written++;
        }
        manifest.WriteLine($"{spr.Name.Content}\t{spr.Textures.Count}\t{spr.Width}\t{spr.Height}\t{written}");
    }
}

// Fonts: atlas PNG + glyph table (char, source rect, shift, offset) per font.
foreach (UndertaleFont font in Data.Fonts.Where(f => f is not null))
{
    worker.ExportAsPNG(font.Texture, Path.Combine(SpritesDir, "font", $"{font.Name.Content}.png"));
    using StreamWriter writer = new(Path.Combine(Root, "fonts", $"glyphs_{font.Name.Content}.csv"));
    writer.WriteLine($"{font.DisplayName.Content};{font.EmSize};{font.Bold};{font.Italic};{font.Charset};{font.AntiAliasing};{font.ScaleX};{font.ScaleY}");
    foreach (var g in font.Glyphs)
    {
        writer.WriteLine($"{g.Character};{g.SourceX};{g.SourceY};{g.SourceWidth};{g.SourceHeight};{g.Shift};{g.Offset}");
    }
}

worker.Dispose();
Console.WriteLine($"Done: {Data.Sprites.Count} sprites scanned, {Data.Fonts.Count} fonts.");
