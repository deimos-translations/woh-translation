// Usage: -postScript CodeSites.java <outFile> <instrVA> [<instrVA>...]
// For each instruction address (a reference to a string literal), prints a token stream of the surrounding instructions:
// index constants loaded into EDX (E=n), calls to the array helpers (idx/idxset), compare (cmp), assign (set).
// Lets one read which array cell (a,b) is compared with / assigned the literal without decompiling a huge function.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;

import java.io.File;
import java.nio.file.Files;

public class CodeSites extends GhidraScript {
    private static String tok(Instruction in) {
        String mn = in.getMnemonicString();
        String txt = in.toString();
        if (mn.equals("CALL")) {
            String t = txt.replace("CALL ", "").trim();
            if (t.endsWith("1420f3c40")) return "idx";
            if (t.endsWith("1420c3970")) return "idxset";
            if (t.endsWith("1420f0fd0")) return "CMP";
            if (t.endsWith("14000f590")) return "SET";
            return null;
        }
        if (mn.equals("MOV") && txt.startsWith("MOV EDX,0x")) return "E=" + Long.decode(txt.substring(8).trim());
        if (mn.equals("XOR") && txt.startsWith("XOR EDX,EDX")) return "E=0";
        if (mn.equals("MOV") && txt.startsWith("MOV R8D,0x")) return "R8=" + Long.decode(txt.substring(10).trim());
        return null;
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        StringBuilder out = new StringBuilder();
        for (int i = 1; i < args.length; i++) {
            Address a = toAddr(args[i]);
            Function f = getFunctionContaining(a);
            out.append("== ").append(args[i]).append(' ').append(f == null ? "-" : f.getEntryPoint().toString()).append('\n');
            Instruction in = getInstructionAt(a);
            if (in == null) { out.append("  no instruction\n"); continue; }
            Instruction cur = in;
            for (int k = 0; k < 45 && cur.getPrevious() != null; k++) cur = cur.getPrevious();
            StringBuilder before = new StringBuilder(), after = new StringBuilder();
            boolean past = false;
            for (int k = 0; k < 130 && cur != null; k++, cur = cur.getNext()) {
                if (cur.getAddress().equals(in.getAddress())) { past = true; continue; }
                String t = tok(cur);
                if (t != null) (past ? after : before).append(' ').append(t);
            }
            out.append("  before:").append(before).append('\n').append("  after: ").append(after).append('\n');
        }
        Files.write(new File(args[0]).toPath(), out.toString().getBytes("UTF-8"));
    }
}
