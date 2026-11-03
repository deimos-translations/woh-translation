// Usage: -postScript RefsTo.java <outFile> <addr> [<addr>...]
// Every reference to each address with its type, the instruction text and the containing function. Report only.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.nio.file.Files;

public class RefsTo extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        StringBuilder out = new StringBuilder();
        for (int i = 1; i < args.length; i++) {
            Address addr = toAddr(args[i]);
            out.append("== ").append(addr).append('\n');
            for (Reference ref : getReferencesTo(addr)) {
                Function fn = getFunctionContaining(ref.getFromAddress());
                Instruction ins = getInstructionAt(ref.getFromAddress());
                out.append("  ").append(ref.getFromAddress()).append('\t').append(ref.getReferenceType()).append('\t')
                   .append(ins == null ? "<data>" : ins.toString()).append('\t')
                   .append(fn == null ? "<none>" : fn.getName()).append('\n');
            }
        }
        Files.writeString(new File(args[0]).toPath(), out.toString());
    }
}
