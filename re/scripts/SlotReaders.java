// Usage: -postScript SlotReaders.java <outFile> <str> [<str>...]
// For each exact NUL-delimited literal, finds the startup initializer that wraps it (FUN_1420d8090(&slot, literal)),
// resolves the slot address, and lists every function that references the slot. Report only, no decompilation.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.nio.file.Files;
import java.util.TreeSet;

public class SlotReaders extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
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
                from = hit.add(1);
                for (Reference ref : getReferencesTo(str)) {
                    // slot = target of the LEA that precedes the literal's LEA (rcx before rdx)
                    Instruction ins = getInstructionAt(ref.getFromAddress());
                    Address slot = null;
                    for (int k = 0; k < 3 && ins != null && slot == null; k++) {
                        ins = ins.getPrevious();
                        if (ins != null && ins.getMnemonicString().equals("LEA")) {
                            for (Reference r : ins.getReferencesFrom()) slot = r.getToAddress();
                        }
                    }
                    report.append("\"").append(args[i]).append("\" @ ").append(str).append(" slot ").append(slot).append('\n');
                    if (slot == null) continue;
                    TreeSet<String> users = new TreeSet<>();
                    for (Reference r : getReferencesTo(slot)) {
                        Function fn = getFunctionContaining(r.getFromAddress());
                        users.add((fn == null ? "<none>" : fn.getName()) + " " + r.getReferenceType());
                    }
                    for (String u : users) report.append("    ").append(u).append('\n');
                }
            }
        }
        Files.writeString(new File(args[0]).toPath(), report.toString());
    }
}
