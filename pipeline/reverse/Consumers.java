// args: out spriteCount minId
// For each `MOV r64,imm64` (sprite-id valued double) stored to a stack temp [reg+K], find the next CALL (within 40 insns, linear)
// that receives `LEA arg,[reg+K]` and report callee/arg register and the variable slot dword loaded just before that call.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;
import java.io.File;
import java.nio.file.Files;
import java.util.*;
public class Consumers extends GhidraScript {
    static final long GAME_END = Symbols.addr("game_end");
    static String memKey(Instruction in, int op) {
        // "[RBP + 0x4a8]" style: normalise via operand representation
        String s = in.getDefaultOperandRepresentation(op);
        int i = s.indexOf('['); int j = s.indexOf(']');
        return (i >= 0 && j > i) ? s.substring(i, j + 1) : null;
    }
    @Override protected void run() throws Exception {
        String[] a = getScriptArgs(); int count = Integer.parseInt(a[1]), minId = Integer.parseInt(a[2]);
        StringBuilder sb = new StringBuilder();
        AddressSet gc = new AddressSet(currentProgram.getMemory().getBlock(".text").getStart(), toAddr(GAME_END - 1));
        InstructionIterator it = currentProgram.getListing().getInstructions(gc, true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Instruction ins = it.next();
            if (!ins.getMnemonicString().equals("MOV") || ins.getNumOperands() != 2 || ins.getRegister(0) == null
                || ins.getRegister(0).getBitLength() != 64 || ins.getScalar(1) == null) continue;
            double v = Double.longBitsToDouble(ins.getScalar(1).getUnsignedValue());
            if (v < minId || v >= count || v != Math.rint(v)) continue;
            int id = (int) v;
            String reg = ins.getRegister(0).getName();
            // find the store of this register to memory within 3 insns
            Instruction st = ins.getNext(); String key = null;
            for (int k = 0; k < 3 && st != null; k++, st = st.getNext()) {
                if (st.getMnemonicString().equals("MOV") && st.getNumOperands() == 2 && st.getRegister(1) != null
                    && st.getRegister(1).getName().equals(reg) && st.getRegister(0) == null) { key = memKey(st, 0); break; }
            }
            String callee = "-", argreg = "-", slot = "-";
            if (key != null) {
                Instruction cur = st.getNext(); Instruction lastSlotLoad = null;
                for (int k = 0; k < 40 && cur != null; k++, cur = cur.getNext()) {
                    String mn = cur.getMnemonicString();
                    if (mn.equals("RET")) break;
                    if (mn.equals("MOV") && cur.getNumOperands() == 2 && cur.getRegister(0) != null
                        && cur.getRegister(0).getName().equals("EDX") && cur.getRegister(1) == null) lastSlotLoad = cur;
                    if (mn.equals("LEA") && cur.getRegister(0) != null && key.equals(memKey(cur, 1))) {
                        argreg = cur.getRegister(0).getName();
                        for (Instruction c2 = cur.getNext(); c2 != null; c2 = c2.getNext()) {
                            if (c2.getMnemonicString().equals("CALL")) { callee = c2.getAddress(0) != null ? c2.getOpObjects(0).length > 0 ? c2.getOpObjects(0)[0].toString() : "?" : "?"; break; }
                            if (c2.getMnemonicString().equals("RET") || c2.getMnemonicString().startsWith("J")) { callee = "jmp"; break; }
                        }
                        if (lastSlotLoad != null) for (var r : lastSlotLoad.getReferencesFrom()) slot = r.getToAddress().toString();
                        break;
                    }
                    if (mn.equals("CALL") && false) break;
                }
            } else { callee = "nostore"; }
            sb.append(id).append('\t').append(ins.getAddress()).append('\t').append(callee).append('\t').append(argreg).append('\t').append(slot).append('\n');
        }
        Files.writeString(new File(a[0]).toPath(), sb.toString());
    }
}
