// Usage: -postScript DecompBig.java <outDir> <timeoutSec> <addr> [<addr>...]
// Decompiles the function containing each address with a long timeout (for the huge load/save scripts).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;

import java.io.File;
import java.nio.file.Files;

public class DecompBig extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args[0]);
        out.mkdirs();
        int timeout = Integer.parseInt(args[1]);
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        for (int i = 2; i < args.length; i++) {
            Function fn = getFunctionContaining(toAddr(args[i]));
            if (fn == null) { println("no function at " + args[i]); continue; }
            DecompileResults res = dec.decompileFunction(fn, timeout, monitor);
            String code = res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed: " + res.getErrorMessage() + "\n";
            Files.writeString(new File(out, fn.getName() + "_" + fn.getEntryPoint() + ".c").toPath(), code);
        }
    }
}
