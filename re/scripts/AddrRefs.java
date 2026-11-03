// Usage: -postScript AddrRefs.java <outDir> <addr> [<addr>...]
// For each address (data slot or function): lists references and decompiles every function that references it
// (a function address itself is decompiled too).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.nio.file.Files;
import java.util.HashSet;
import java.util.Set;

public class AddrRefs extends GhidraScript {
    private DecompInterface dec;
    private File out;
    private final Set<Address> done = new HashSet<>();

    private void dump(Function fn) throws Exception {
        if (fn == null || !done.add(fn.getEntryPoint())) return;
        DecompileResults res = dec.decompileFunction(fn, 120, monitor);
        String code = res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed\n";
        Files.writeString(new File(out, fn.getName() + "_" + fn.getEntryPoint() + ".c").toPath(), code);
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        out = new File(args[0]);
        out.mkdirs();
        dec = new DecompInterface();
        dec.openProgram(currentProgram);
        StringBuilder report = new StringBuilder();
        for (int i = 1; i < args.length; i++) {
            Address addr = toAddr(args[i]);
            report.append("== ").append(addr).append('\n');
            dump(getFunctionAt(addr));
            for (Reference ref : getReferencesTo(addr)) {
                Function fn = getFunctionContaining(ref.getFromAddress());
                report.append("  ref ").append(ref.getFromAddress()).append(' ').append(ref.getReferenceType())
                      .append(" in ").append(fn == null ? "<none>" : fn.getName() + "@" + fn.getEntryPoint()).append('\n');
                dump(fn);
            }
        }
        Files.writeString(new File(out, "report.txt").toPath(), report.toString());
    }
}
