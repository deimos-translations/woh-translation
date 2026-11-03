// Usage: -postScript StringRefs.java <outDir> <str> [<str>...]
// For each exact NUL-delimited string: address, references, containing function; decompiles those functions into outDir.
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

public class StringRefs extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args[0]);
        out.mkdirs();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        Set<Address> done = new HashSet<>();
        StringBuilder report = new StringBuilder();

        for (int i = 1; i < args.length; i++) {
            byte[] pat = ("\0" + args[i] + "\0").getBytes("ISO-8859-1");
            byte[] mask = new byte[pat.length];
            java.util.Arrays.fill(mask, (byte) 0xff);
            Address from = currentProgram.getMinAddress();
            while (true) {
                Address hit = currentProgram.getMemory().findBytes(from, pat, mask, true, monitor);
                if (hit == null) break;
                Address str = hit.add(1);
                report.append("== \"").append(args[i]).append("\" @ ").append(str).append('\n');
                for (Reference ref : getReferencesTo(str)) {
                    Function fn = getFunctionContaining(ref.getFromAddress());
                    report.append("  ref ").append(ref.getFromAddress()).append(' ').append(ref.getReferenceType())
                          .append(" in ").append(fn == null ? "<none>" : fn.getName() + "@" + fn.getEntryPoint()).append('\n');
                    if (fn != null && done.add(fn.getEntryPoint())) {
                        DecompileResults res = dec.decompileFunction(fn, 120, monitor);
                        String code = res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed\n";
                        Files.writeString(new File(out, fn.getName() + "_" + fn.getEntryPoint() + ".c").toPath(), code);
                    }
                }
                from = hit.add(1);
            }
        }
        Files.writeString(new File(out, "report.txt").toPath(), report.toString());
    }
}
