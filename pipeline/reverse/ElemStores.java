// args: out spriteCount minId
// For each id-valued double constant (`MOV r64,imm64`) stored through a register pointer (`MOV [reg],r64`, i.e. into an RValue handed out by an
// accessor), report the root variable: the nearest `MOV EDX,[data slot]; CALL [reg+0x8|0x10]` within 100 insns before, and whether an array-element
// accessor sits between that root and the store (so it is `var[..] = const`).
// cols: id, site, rootSlot, arrayDepth (count of array accessor calls between root and store), lastCallee
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import java.io.File;
import java.nio.file.Files;
import java.util.Set;
public class ElemStores extends GhidraScript {
    static final long GAME_END = Symbols.addr("game_end");
    static final Set<String> NOT_CONSUMERS = Symbols.set("free");
    static final String ARRAY_ELEMENT = Symbols.text("array_element");
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
            String reg = ins.getRegister(0).getName();
            Instruction st = ins.getNext(); boolean ok = false;
            for (int k = 0; k < 3 && st != null; k++, st = st.getNext())
                if (st.getMnemonicString().equals("MOV") && st.getRegister(1) != null && st.getRegister(1).getName().equals(reg) && st.getRegister(0) == null
                    && st.getDefaultOperandRepresentation(0).replace(" ", "").matches("qwordptr\\[[A-Z0-9]+\\]")) { ok = true; break; }
            if (!ok) continue;
            String root = "-"; int depth = 0; String lastCallee = "-";
            Instruction cur = ins.getPrevious();
            for (int k = 0; k < 100 && cur != null; k++, cur = cur.getPrevious()) {
                String mn = cur.getMnemonicString();
                if (mn.equals("RET")) break;
                if (mn.equals("CALL") && cur.getOpObjects(0).length > 0) {
                    String t = cur.getOpObjects(0)[0].toString();
                    if (lastCallee.equals("-") && !NOT_CONSUMERS.contains(t)) lastCallee = t;
                    if (t.equals(ARRAY_ELEMENT)) depth++;
                }
                String d = cur.getDefaultOperandRepresentation(0).replace(" ", "");
                if (mn.equals("CALL") && (d.endsWith("+0x10]") || d.endsWith("+0x8]"))) {
                    Instruction p = cur.getPrevious();
                    for (int j = 0; j < 5 && p != null; j++, p = p.getPrevious())
                        if (p.getMnemonicString().equals("MOV") && p.getRegister(0) != null && p.getRegister(0).getName().equals("EDX") && p.getRegister(1) == null) {
                            for (var r : p.getReferencesFrom()) if (r.isMemoryReference()) root = r.getToAddress().toString();
                            break;
                        }
                    if (!root.equals("-")) break;
                }
            }
            sb.append((int) v).append('\t').append(ins.getAddress()).append('\t').append(root).append('\t').append(depth).append('\t').append(lastCallee).append('\n');
        }
        Files.writeString(new File(a[0]).toPath(), sb.toString());
    }
}
