// Usage: -postScript DumpAsm.java <outFile> <funcAddr>
// Writes the full disassembly of the function containing funcAddr, with call targets and string literals annotated.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

import java.io.BufferedWriter;
import java.nio.file.Files;
import java.nio.file.Path;

public class DumpAsm extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        Function fn = getFunctionContaining(toAddr(args[1]));
        try (BufferedWriter out = Files.newBufferedWriter(Path.of(args[0]))) {
            for (Instruction ins : currentProgram.getListing().getInstructions(fn.getBody(), true)) {
                StringBuilder line = new StringBuilder().append(ins.getAddress()).append("  ").append(ins);
                for (Reference r : ins.getReferencesFrom()) {
                    if (r.getReferenceType().isCall()) {
                        Function callee = getFunctionAt(r.getToAddress());
                        line.append("   ; call ").append(callee == null ? r.getToAddress() : callee.getName());
                        continue;
                    }
                    Data d = getDataAt(r.getToAddress());
                    if (d != null && d.hasStringValue()) line.append("   ; \"").append(d.getValue()).append('"');
                }
                out.write(line.append('\n').toString());
            }
        }
    }
}
