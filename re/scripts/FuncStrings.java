// Usage: -postScript FuncStrings.java <outFile> <funcAddr> [<funcAddr>...]
// Lists every string literal referenced by each function body, in address order, with size and callee count.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.nio.file.Files;
import java.util.LinkedHashSet;

public class FuncStrings extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        StringBuilder out = new StringBuilder();
        for (int i = 1; i < args.length; i++) {
            Function fn = getFunctionContaining(toAddr(args[i]));
            if (fn == null) continue;
            out.append("==== ").append(fn.getName()).append(" body ").append(fn.getBody().getNumAddresses()).append(" bytes\n");
            LinkedHashSet<String> seen = new LinkedHashSet<>();
            for (Instruction ins : currentProgram.getListing().getInstructions(fn.getBody(), true)) {
                for (Reference r : ins.getReferencesFrom()) {
                    Data d = getDataAt(r.getToAddress());
                    if (d != null && d.hasStringValue()) seen.add(r.getToAddress() + " \"" + d.getValue() + "\"");
                }
            }
            for (String s : seen) out.append("  ").append(s).append('\n');
        }
        Files.writeString(new File(args[0]).toPath(), out.toString());
    }
}
