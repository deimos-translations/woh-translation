// args: out
// Instance-variable writes through the lvalue getter: `MOV EDX,[slot]; ... CALL [reg+0x10]` returns the variable's RValue*, which the code
// then fills in place (`MOV [RValue],imm64-double`, or the RValue copy helper with the RValue in RCX).
// cols: site, slot, kind (const|copy|op:<callee>|none), value (const double, or the source slot of a copy when seen)
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import java.io.File;
import java.nio.file.Files;
import java.util.*;
public class LvalStores extends GhidraScript {
    static final long GAME_END = Symbols.addr("game_end");
    static final Set<String> FREE = Symbols.set("free");
    static final String COPY = Symbols.text("rvalue_copy");
    @Override protected void run() throws Exception {
        String[] a = getScriptArgs();
        StringBuilder sb = new StringBuilder();
        AddressSet gc = new AddressSet(currentProgram.getMemory().getBlock(".text").getStart(), toAddr(GAME_END - 1));
        InstructionIterator it = currentProgram.getListing().getInstructions(gc, true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Instruction call = it.next();
            if (!call.getMnemonicString().equals("CALL") || call.getOpObjects(0).length == 0) continue;
            if (!call.getDefaultOperandRepresentation(0).replace(" ", "").endsWith("+0x10]")) continue;
            // slot: MOV EDX,[abs] within 5 insns before
            String slot = null;
            Instruction p = call.getPrevious();
            for (int k = 0; k < 5 && p != null && slot == null; k++, p = p.getPrevious())
                if (p.getMnemonicString().equals("MOV") && p.getRegister(0) != null && p.getRegister(0).getName().equals("EDX") && p.getRegister(1) == null)
                    for (var r : p.getReferencesFrom()) if (r.isMemoryReference()) slot = r.getToAddress().toString();
            if (slot == null) continue;
            // destination register of the returned pointer
            String dest = "RAX";
            Instruction n = call.getNext();
            if (n != null && n.getMnemonicString().equals("MOV") && n.getRegister(0) != null && n.getRegister(1) != null
                && n.getRegister(1).getName().equals("RAX") && n.getRegister(0).getBitLength() == 64) dest = n.getRegister(0).getName();
            String kind = "none", val = "";
            Instruction c = call.getNext();
            for (int k = 0; k < 30 && c != null; k++, c = c.getNext()) {
                String mn = c.getMnemonicString();
                if (mn.equals("RET")) break;
                if (mn.equals("CALL") && c.getDefaultOperandRepresentation(0).replace(" ", "").endsWith("+0x10]")) break;
                if (mn.equals("MOV") && c.getNumOperands() == 2 && c.getRegister(0) == null && c.getRegister(1) != null
                    && memIs(c, dest)) {
                    Instruction q = c.getPrevious();
                    for (int j = 0; j < 4 && q != null; j++, q = q.getPrevious())
                        if (q.getRegister(0) != null && q.getRegister(0).getName().equals(c.getRegister(1).getName())) {
                            if (q.getMnemonicString().equals("MOV") && q.getScalar(1) != null && q.getRegister(0).getBitLength() == 64) {
                                double d = Double.longBitsToDouble(q.getScalar(1).getUnsignedValue());
                                kind = "const"; val = d == Math.rint(d) ? String.valueOf((long) d) : String.valueOf(d);
                            }
                            break;
                        }
                    if (kind.equals("const")) break;
                }
                if (mn.equals("CALL") && c.getOpObjects(0).length > 0) {
                    // the callee takes the pointer as RCX if a `MOV RCX,dest` precedes within 3 insns
                    Instruction q = c.getPrevious(); boolean rcx = false;
                    for (int j = 0; j < 3 && q != null; j++, q = q.getPrevious())
                        if (q.getMnemonicString().equals("MOV") && q.getRegister(0) != null && q.getRegister(0).getName().equals("RCX")
                            && q.getRegister(1) != null && q.getRegister(1).getName().equals(dest)) rcx = true;
                    if (rcx) { String t = c.getOpObjects(0)[0].toString(); if (FREE.contains(t)) continue; kind = t.equals(COPY) ? "copy" : "op:" + t; break; }
                }
            }
            sb.append(call.getAddress()).append('\t').append(slot).append('\t').append(kind).append('\t').append(val).append('\n');
        }
        Files.writeString(new File(a[0]).toPath(), sb.toString());
    }
    static boolean memIs(Instruction in, String reg) {
        String s = in.getDefaultOperandRepresentation(0).replace(" ", "");
        return s.equals("qwordptr[" + reg + "]");
    }
}
