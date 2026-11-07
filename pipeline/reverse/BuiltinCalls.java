// args: out [scriptFuncVA...]   (with function addresses: decode direct calls to those scripts instead; their args array is [rsp+0x20], slot col is the callee)
// Every game call shaped like the builtin-by-id helpers (self, other, &ret, argc=R9D, slot=[rsp+0x20], args=[rsp+0x28]) with the arguments decoded.
// `args` is an array of RValue* on the stack; each element is filled by `rvalue_init(dst, &pooled double)` (constant) or `rvalue_copy(dst, src)` (copy).
// cols: site, callee, func, slotVA, argc, args (`,`-joined: c:<double> | v (copied from a variable/temp) | ?)
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;
import java.io.File;
import java.nio.file.Files;
import java.util.*;
public class BuiltinCalls extends GhidraScript {
    static final long GAME_END = Symbols.addr("game_end");
    static final String INIT = Symbols.text("rvalue_init"), COPY = Symbols.text("rvalue_copy");
    // "REG+off" key of a memory operand, or null
    static String key(Instruction in, int op) {
        Object[] o = in.getOpObjects(op);
        if (o.length == 0 || !(o[0] instanceof Register)) return null;
        long off = 0;
        for (int i = 1; i < o.length; i++) if (o[i] instanceof Scalar) off += ((Scalar) o[i]).getSignedValue();
        return ((Register) o[0]).getName() + "+" + off;
    }
    static String keyAt(String key, int add) {
        int p = key.indexOf('+'); return key.substring(0, p) + "+" + (Long.parseLong(key.substring(p + 1)) + add);
    }
    String describe(Instruction store) throws Exception {
        // store = `MOV [slot],REG`; look at the instructions just before it for the CALL that filled REG's RValue
        String reg = store.getRegister(1).getName();
        Instruction c = store.getPrevious();
        for (int k = 0; k < 3 && c != null; k++, c = c.getPrevious()) {
            if (!c.getMnemonicString().equals("CALL") || c.getOpObjects(0).length == 0) continue;
            String callee = c.getOpObjects(0)[0].toString();
            Instruction r = c.getPrevious(); Long src = null;
            for (int j = 0; j < 8 && r != null; j++, r = r.getPrevious()) {
                if (r.getMnemonicString().equals("CALL")) break;
                if (r.getMnemonicString().equals("LEA") && r.getRegister(0) != null && r.getRegister(0).getName().equals("RDX")) {
                    for (var ref : r.getReferencesFrom()) if (ref.isMemoryReference()) src = ref.getToAddress().getOffset();
                    if (src == null) src = -1L;
                    break;
                }
                if (r.getMnemonicString().equals("MOV") && r.getRegister(0) != null && r.getRegister(0).getName().equals("RDX")) { src = -1L; break; }
            }
            if (callee.equals(INIT) && src != null && src > 0) {
                double d = Double.longBitsToDouble(currentProgram.getMemory().getLong(toAddr(src)));
                return "c:" + (d == Math.rint(d) ? String.valueOf((long) d) : String.valueOf(d));
            }
            if (callee.equals(COPY)) return "v";
            return "?";
        }
        return "?";
    }
    @Override protected void run() throws Exception {
        String[] a = getScriptArgs();
        StringBuilder sb = new StringBuilder();
        AddressSet gc = new AddressSet(currentProgram.getMemory().getBlock(".text").getStart(), toAddr(GAME_END - 1));
        InstructionIterator it = currentProgram.getListing().getInstructions(gc, true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Instruction call = it.next();
            if (!call.getMnemonicString().equals("CALL") || call.getOpObjects(0).length == 0) continue;
            boolean script = a.length > 1;
            if (script && !Arrays.asList(a).subList(1, a.length).contains(call.getOpObjects(0)[0].toString())) continue;
            String slot = "-", base = null; int argc = -1;
            String slotReg = null, baseReg = null; Instruction cur = call.getPrevious();
            Map<String, Instruction> regSrc = new HashMap<>();
            for (int k = 0; k < 16 && cur != null; k++, cur = cur.getPrevious()) {
                String mn = cur.getMnemonicString();
                if (mn.equals("CALL") || mn.equals("RET")) break;
                if (mn.equals("MOV") && cur.getNumOperands() == 2 && cur.getRegister(0) == null && cur.getRegister(1) != null) {
                    String kk = key(cur, 0);
                    if (!script && "RSP+32".equals(kk)) slotReg = cur.getRegister(1).getName();
                    if ((script ? "RSP+32" : "RSP+40").equals(kk)) baseReg = cur.getRegister(1).getName();
                }
                if (mn.equals("MOV") && cur.getRegister(0) != null && cur.getRegister(0).getName().startsWith("R9") && cur.getScalar(1) != null) argc = (int) cur.getScalar(1).getUnsignedValue();
            }
            cur = call.getPrevious();
            for (int k = 0; k < 30 && cur != null; k++, cur = cur.getPrevious()) {
                String mn = cur.getMnemonicString();
                if (mn.equals("RET")) break;
                if (slotReg != null && slot.equals("-") && mn.equals("MOV") && cur.getRegister(0) != null && cur.getRegister(0).getName().equals(slotReg)
                    && cur.getRegister(1) == null) for (var r : cur.getReferencesFrom()) if (r.isMemoryReference()) slot = r.getToAddress().toString();
                if (baseReg != null && base == null && mn.equals("LEA") && cur.getRegister(0) != null && cur.getRegister(0).getName().equals(baseReg)) base = key(cur, 1);
            }
            StringBuilder args = new StringBuilder();
            if ((!script && slot.equals("-")) || base == null) continue;
            if (argc >= 0) {
                for (int i = 0; i < argc; i++) {
                    String want = keyAt(base, 8 * i), got = "?";
                    Instruction s = call.getPrevious();
                    for (int k = 0; k < 160 && s != null; k++, s = s.getPrevious()) {
                        if (s.getMnemonicString().equals("RET")) break;
                        if (s.getMnemonicString().equals("MOV") && s.getNumOperands() == 2 && s.getRegister(0) == null && s.getRegister(1) != null
                            && want.equals(key(s, 0))) { got = describe(s); break; }
                    }
                    args.append(i == 0 ? "" : ",").append(got);
                }
            }
            sb.append(call.getAddress()).append('\t').append(currentProgram.getFunctionManager().getFunctionContaining(call.getAddress()) == null ? "-" :
                      currentProgram.getFunctionManager().getFunctionContaining(call.getAddress()).getEntryPoint()).append('\t')
              .append(slot).append('\t').append(argc).append('\t').append(args).append('\n');
        }
        Files.writeString(new File(a[0]).toPath(), sb.toString());
    }
}
