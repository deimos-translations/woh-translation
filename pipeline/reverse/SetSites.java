// args: out
// For every game call of a variable-set helper: the variable slot (last `MOV EDX,[data]` before the call),
// the RValue argument (`LEA R9,[reg+K]`), the double constants stored into that RValue in the 60 insns before it, and the calls/slots seen there.
// cols: site, callee, slotVA, key, consts, events
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import java.io.File;
import java.nio.file.Files;
import java.util.*;
public class SetSites extends GhidraScript {
    static final long GAME_END = Symbols.addr("game_end");
    static final Set<String> SETTERS = Symbols.set("setters");
    static final long SLOT_LO = Symbols.addr("slot_lo"), SLOT_HI = Symbols.addr("slot_hi");
    static String memKey(Instruction in, int op) {
        String s = in.getDefaultOperandRepresentation(op);
        int i = s.indexOf('['); int j = s.indexOf(']');
        return (i >= 0 && j > i) ? s.substring(i, j + 1) : null;
    }
    // double stored by `MOV r64,imm64` or loaded from a pooled double
    Double constOf(Instruction in) throws Exception {
        if (in.getMnemonicString().equals("MOV") && in.getRegister(0) != null && in.getRegister(0).getBitLength() == 64 && in.getScalar(1) != null)
            return Double.longBitsToDouble(in.getScalar(1).getUnsignedValue());
        if (in.getMnemonicString().startsWith("MOVS") && in.getRegister(0) != null && in.getRegister(0).getName().startsWith("XMM"))
            for (var r : in.getReferencesFrom())
                if (r.isMemoryReference()) try { return Double.longBitsToDouble(currentProgram.getMemory().getLong(r.getToAddress())); } catch (Exception e) { }
        return null;
    }
    @Override protected void run() throws Exception {
        String[] a = getScriptArgs();
        StringBuilder sb = new StringBuilder();
        AddressSet gc = new AddressSet(currentProgram.getMemory().getBlock(".text").getStart(), toAddr(GAME_END - 1));
        InstructionIterator it = currentProgram.getListing().getInstructions(gc, true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Instruction call = it.next();
            if (!call.getMnemonicString().equals("CALL") || call.getOpObjects(0).length == 0) continue;
            String callee = call.getOpObjects(0)[0].toString();
            if (!SETTERS.contains(callee)) continue;
            String slot = "-", key = "-"; Instruction leaIns = null;
            Instruction cur = call.getPrevious();
            for (int k = 0; k < 40 && cur != null; k++, cur = cur.getPrevious()) {
                String mn = cur.getMnemonicString();
                if (mn.equals("RET")) break;
                if (slot.equals("-") && mn.equals("MOV") && cur.getRegister(0) != null && cur.getRegister(0).getName().equals("EDX") && cur.getRegister(1) == null)
                    for (var r : cur.getReferencesFrom()) if (r.isMemoryReference()) slot = r.getToAddress().toString();
                if (leaIns == null && mn.equals("LEA") && cur.getRegister(0) != null && cur.getRegister(0).getName().equals("R9")) { leaIns = cur; key = memKey(cur, 1); }
            }
            StringBuilder consts = new StringBuilder(), ev = new StringBuilder();
            cur = call.getPrevious();
            for (int k = 0; k < 60 && cur != null; k++, cur = cur.getPrevious()) {
                String mn = cur.getMnemonicString();
                if (mn.equals("RET")) break;
                if (mn.equals("CALL")) {
                    var o = cur.getOpObjects(0);
                    ev.append(" C:").append(o.length > 0 ? o[0].toString() : "ind").append("@-").append(k);
                } else if (key != null && !key.equals("-") && mn.startsWith("MOV") && cur.getNumOperands() == 2 && cur.getRegister(0) == null
                           && key.equals(memKey(cur, 0)) && cur.getRegister(1) != null) {
                    // find the constant loaded into the stored register within 4 insns before
                    Instruction p = cur.getPrevious();
                    for (int q = 0; q < 4 && p != null; q++, p = p.getPrevious()) {
                        if (p.getRegister(0) != null && p.getRegister(0).getName().equals(cur.getRegister(1).getName())) {
                            Double d = constOf(p);
                            if (d != null) consts.append(d == Math.rint(d) ? String.valueOf((long) (double) d) : String.valueOf(d)).append(',');
                            break;
                        }
                    }
                } else if (mn.equals("MOV") && cur.getNumOperands() == 2 && cur.getRegister(0) != null && cur.getRegister(1) == null) {
                    for (var r : cur.getReferencesFrom())
                        if (r.isMemoryReference() && r.getToAddress().getOffset() >= SLOT_LO && r.getToAddress().getOffset() < SLOT_HI)
                            ev.append(" S:").append(r.getToAddress()).append("@-").append(k);
                }
            }
            sb.append(call.getAddress()).append('\t').append(callee).append('\t').append(slot).append('\t').append(key).append('\t')
              .append(consts).append('\t').append(ev).append('\n');
        }
        Files.writeString(new File(a[0]).toPath(), sb.toString());
    }
}
