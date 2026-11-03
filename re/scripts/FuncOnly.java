// Usage: -postScript FuncOnly.java <outDir> <addr> [<addr>...]
// Decompiles the function containing each address into outDir. No reference walking.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;

import java.io.File;
import java.nio.file.Files;

public class FuncOnly extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args[0]);
        out.mkdirs();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        for (int i = 1; i < args.length; i++) {
            Function fn = getFunctionContaining(toAddr(args[i]));
            if (fn == null) continue;
            DecompileResults res = dec.decompileFunction(fn, 900, monitor);
            String code = res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed: " + res.getErrorMessage() + "\n";
            Files.writeString(new File(out, fn.getName() + "_" + fn.getEntryPoint() + ".c").toPath(), code);
        }
    }
}
