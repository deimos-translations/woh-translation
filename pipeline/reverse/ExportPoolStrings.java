// Usage: -postScript ExportPoolStrings.java <poolStartVA> <poolSizeBytes> <outFile>
// Every address in the game's string pool that code references, with the NUL-terminated UTF-8 text found there.
// This is code-reference driven, so it also finds copies that sit directly after binary data (no NUL in front) or in the
// middle of a longer literal, which a byte scan misses.
// Output: `<hex VA>\t<escaped text>\t<reference count>`; `\`, CR, LF and TAB are written as `\\`, `\r`, `\n`, `\t`.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.symbol.Reference;

import java.io.BufferedWriter;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

public class ExportPoolStrings extends GhidraScript {
    private static String escape(String text) {
        return text.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t");
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        Address start = toAddr(args[0]);
        long size = Long.parseLong(args[1]);
        try (BufferedWriter out = Files.newBufferedWriter(new File(args[2]).toPath())) {
            for (long offset = 0; offset < size; offset++) {
                Address addr = start.add(offset);
                int refs = 0;
                for (Reference ref : getReferencesTo(addr))
                    if (getInstructionAt(ref.getFromAddress()) != null) refs++;
                if (refs == 0) continue;
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                byte value;
                for (int n = 0; n < 4000 && (value = getByte(addr.add(n))) != 0; n++) bytes.write(value);
                out.write(addr + "\t" + escape(bytes.toString(StandardCharsets.UTF_8)) + "\t" + refs + "\n");
            }
        }
    }
}
