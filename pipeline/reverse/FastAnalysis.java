// Pre-script: switch off auto-analyzers this project never uses, before headless analysis starts.
// Timings from the first full run (2058 s total): Decompiler Switch Analysis 449 s, Stack 434 s, Function ID 58 s,
// Variadic Function Signature Override 35 s. Our queries only need disassembly, functions and references.
import ghidra.app.script.GhidraScript;

public class FastAnalysis extends GhidraScript {
    @Override
    protected void run() throws Exception {
        for (String analyzer : new String[] {
                "Decompiler Switch Analysis", "Stack", "Function ID", "Variadic Function Signature Override" }) {
            setAnalysisOption(currentProgram, analyzer, "false");
            println("disabled analyzer: " + analyzer);
        }
    }
}
