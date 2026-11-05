// Usage: -postScript FindDrawHooks.java <outFile>
// Finds where the runtime registers the text-drawing and text-measuring built-ins, so patch.py can point them at hooks.
// Registration is `register(name=RCX, function=RDX, argc=R8D, flag=R9)`, the function loaded by `LEA RDX,[rip+disp32]`.
// Output rows: `name<TAB>stringArgIndex<TAB>leaAddr<TAB>len<TAB>bytes<TAB>functionAddr`.
// stringArgIndex: the position of the text argument in the call (draw_text(x, y, text, ...) = 2, string_width(text) = 0).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.nio.file.Files;

public class FindDrawHooks extends GhidraScript {
    private static final String[] NAMES = {
        "draw_text", "draw_text_ext", "draw_text_transformed", "draw_text_ext_transformed",
        "draw_text_color", "draw_text_colour", "draw_text_ext_color", "draw_text_ext_colour",
        "draw_text_transformed_color", "draw_text_transformed_colour",
        "draw_text_ext_transformed_color", "draw_text_ext_transformed_colour",
        "string_width", "string_height", "string_width_ext", "string_height_ext" };

    private static String hex(byte[] bytes) {
        StringBuilder sb = new StringBuilder();
        for (byte b : bytes) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    @Override
    protected void run() throws Exception {
        StringBuilder out = new StringBuilder();
        for (String name : NAMES) {
            byte[] pat = ("\0" + name + "\0").getBytes("ISO-8859-1");
            byte[] mask = new byte[pat.length];
            java.util.Arrays.fill(mask, (byte) 0xff);
            Address from = currentProgram.getMinAddress();
            int found = 0;
            while (true) {
                Address hit = currentProgram.getMemory().findBytes(from, pat, mask, true, monitor);
                if (hit == null) break;
                from = hit.add(1);
                for (Reference ref : getReferencesTo(hit.add(1))) {
                    Instruction leaRcx = getInstructionAt(ref.getFromAddress());
                    if (leaRcx == null || !leaRcx.getMnemonicString().equals("LEA")) continue;
                    Instruction cursor = leaRcx.getPrevious();
                    for (int k = 0; k < 4 && cursor != null && !cursor.getFlowType().isCall(); k++, cursor = cursor.getPrevious()) {
                        if (!cursor.getMnemonicString().equals("LEA") || cursor.getRegister(0) == null
                                || !cursor.getRegister(0).getName().equals("RDX")) continue;
                        Address function = cursor.getReferencesFrom()[0].getToAddress();
                        int argIndex = name.startsWith("draw_text") ? 2 : 0;
                        out.append(name).append('\t').append(argIndex).append('\t').append(cursor.getAddress()).append('\t')
                           .append(cursor.getLength()).append('\t').append(hex(cursor.getBytes())).append('\t')
                           .append(function).append('\n');
                        found++;
                        break;
                    }
                }
            }
            if (found != 1) throw new IllegalStateException(name + ": expected 1 registration, found " + found);
        }
        Files.writeString(new File(getScriptArgs()[0]).toPath(), out.toString());
    }
}
