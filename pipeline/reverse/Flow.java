// args: out [debugSlotVA...] strings <file>   (the launcher splits `key=value` arguments, so the keyword and its file are two arguments)
// `strings <file>`: one hex slot VA per line, the startup slots that hold string literals. They are tracked as values tagged `s:<slot>`.
// Output, one row per compare call:  V <TAB> func <TAB> site <TAB> numeric
// numeric = 1 when one operand of the compare is a known number and no string literal is tracked in either (the language checks and the like), so classify_usage.py does not count it as a string compare.
// Intra-function symbolic value flow over the YYC runtime-value idioms, one forward pass per function in address order (last definition wins).
// Tracks registers (incl. XMM) and stack temps as {exact number, constant ids, variable slots, arith flag, unknown flag}.
// Variables whose slot VA is given after `out` are assumed to be 0 (false): a compare against one gives a known number.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.OperandType;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;
import java.io.File;
import java.nio.file.Files;
import java.util.*;

public class Flow extends GhidraScript {
    static final long GAME_END = Symbols.addr("game_end"), SLOT_LO = Symbols.addr("slot_lo"), SLOT_HI = Symbols.addr("slot_hi");
    static final Set<String> GETTERS = Symbols.set("getters");
    static final Set<String> ARITH = Symbols.set("arith");
    static final Set<String> FREE = Symbols.set("free");
    static final String COMPARE = Symbols.text("compare"); // (RValue* a, RValue* b, double eps, flag) -> -1 / 0 / 1, -2 if unordered
    static final double EPS = 1e-5; // decides only 0-vs-1 debug flag compares, so the runtime's own epsilon variable is not needed
    static final String INIT = Symbols.text("rvalue_init"), COPY = Symbols.text("rvalue_copy"), TO_REAL = Symbols.text("to_real"), TO_INT = Symbols.text("to_int"),
        ARRAY_ELEMENT = Symbols.text("array_element"), ARRAY_GET = Symbols.text("array_get");

    static class Val {
        Double num, flt; // exact number if known; flt = the same dword read as a float (32-bit immediates)
        boolean dbg;     // derived from one of the assumed-false debug variables: the result of comparing two such numbers is known
        TreeSet<Long> consts = new TreeSet<>(); TreeSet<String> vars = new TreeSet<>(); boolean arith, unk;
        Val copy() { Val v = new Val(); v.dbg = dbg; v.num = num; v.flt = flt; v.consts.addAll(consts); v.vars.addAll(vars); v.arith = arith; v.unk = unk; return v; }
        void merge(Val o) {
            consts.addAll(o.consts); vars.addAll(o.vars); arith |= o.arith; unk |= o.unk; dbg |= o.dbg;
            if (num != null && !num.equals(o.num)) num = null;
            if (flt != null && !flt.equals(o.flt)) flt = null;
        }
        static Val unknown() { Val v = new Val(); v.unk = true; return v; }
        static Val number(double d) {
            Val v = new Val(); v.num = d;
            if (d == Math.rint(d) && d >= 0 && d < 100000) v.consts.add((long) d);
            return v;
        }
        static Val var(String s) { Val v = new Val(); v.vars.add(s); return v; }
    }
    // register state: t = V value, S slot id, P pointer to cell, R reference to a variable, U unknown
    static class Rv {
        char t = 'U'; String id; Val v;
        static Rv val(Val v) { Rv r = new Rv(); r.t = 'V'; r.v = v; return r; }
        static Rv of(char t, String id) { Rv r = new Rv(); r.t = t; r.id = id; return r; }
    }

    Set<String> debugSlots = new HashSet<>();
    Set<String> stringSlots = new HashSet<>();                  // string-literal slots (hex VA)
    Map<String, Rv> regs; Map<String, Val> cells; StringBuilder sb = new StringBuilder(); String func;

    static String base(Register r) {
        if (r == null) return null;
        String n = r.getName();
        if (n.startsWith("XMM") || n.startsWith("YMM")) return "XMM" + n.substring(3);
        Register b = r.getBaseRegister();
        return b == null ? n : b.getName();
    }
    Rv reg(String n) { Rv r = regs.get(n); return r == null ? new Rv() : r; }
    Val asVal(Rv r) {
        if (r == null) return Val.unknown();
        switch (r.t) {
            case 'V': return r.v;
            case 'P': return cell(r.id);
            case 'R': {
                Val v = Val.var(r.id);
                if (debugSlots.contains(r.id)) { v.num = 0.0; v.dbg = true; }
                return v;
            }
            default: return Val.unknown();
        }
    }
    Val cell(String id) {
        if (id.startsWith("abs:")) {
            long va = Long.parseLong(id.substring(4), 16);
            if (va < SLOT_LO) { // pooled double
                try {
                    double d = Double.longBitsToDouble(currentProgram.getMemory().getLong(toAddr(va)));
                    if (Double.isNaN(d) || Double.isInfinite(d)) return Val.unknown();
                    return Val.number(d);
                } catch (Exception e) { return Val.unknown(); }
            }
            String hex = id.substring(4);
            if (stringSlots.contains(hex)) return Val.var("s:" + hex);
        }
        Val v = cells.get(id);
        return v == null ? Val.unknown() : v;
    }

    static TreeSet<String> tags(Val v) {
        TreeSet<String> out = new TreeSet<>();
        for (String s : v.vars) if (s.startsWith("s:")) out.add(s);
        return out;
    }
    void setCell(String id, Val v) { cells.put(id, v); } // a stack temp or static cell receives a value
    // memory operand decode: returns {baseRegName or null, offset or abs address}; null if not simple
    Object[] mem(Instruction in, int op) {
        Object[] o = in.getOpObjects(op);
        Register r = null; long off = 0; Address a = null; int regCount = 0;
        for (Object x : o) {
            if (x instanceof Register) { r = (Register) x; regCount++; }
            else if (x instanceof Scalar) off += ((Scalar) x).getSignedValue();
            else if (x instanceof Address) a = (Address) x;
        }
        if (regCount > 1) return null;
        if (r == null && a != null) return new Object[] { null, a.getOffset() };
        if (r == null) return null;
        return new Object[] { base(r), off };
    }
    Val load(Instruction in, int op) {
        Object[] m = mem(in, op);
        if (m == null) return Val.unknown();
        if (m[0] == null) {
            long va = (Long) m[1];
            if (va >= SLOT_LO && va < SLOT_HI) return Val.unknown();
            return cell("abs:" + Long.toHexString(va));
        }
        long off = (Long) m[1]; String b = (String) m[0];
        if (b.equals("RBP") || b.equals("RSP")) return cell(b + "+" + off);
        if (off == 0) return asVal(reg(b)); // loads the variable's value
        return Val.unknown();
    }
    Rv loadReg(Instruction in, int op) {
        Object[] m = mem(in, op);
        if (m != null && m[0] == null) {
            long va = (Long) m[1];
            if (va >= SLOT_LO && va < SLOT_HI) {
                String hex = Long.toHexString(va);
                if (!stringSlots.contains(hex)) return Rv.of('S', hex);
                return Rv.val(Val.var("s:" + hex)); // a MOV from a literal's slot copies the string value
            }
        }
        return Rv.val(load(in, op));
    }
    void store(Instruction in, int op, Val v) {
        Object[] m = mem(in, op);
        if (m == null) return;
        if (m[0] == null) {
            long va = (Long) m[1];
            if (va >= SLOT_LO && va < SLOT_HI) cells.put("abs:" + Long.toHexString(va), v);
            return;
        }
        long off = (Long) m[1]; String b = (String) m[0];
        if (b.equals("RBP") || b.equals("RSP")) { if (off % 8 == 0) setCell(b + "+" + off, v); return; }
        if (off == 0) { Rv p = reg(b); if (p.t == 'P') setCell(p.id, v); }
    }
    void kill(String... names) { for (String n : names) regs.put(n, new Rv()); }
    void killCallerSaved() {
        kill("RAX", "RCX", "RDX", "R8", "R9", "R10", "R11");
        for (int i = 0; i <= 5; i++) kill("XMM" + i);
    }
    boolean isReg(Instruction in, int op) { return OperandType.isRegister(in.getOperandType(op)); }
    boolean isImm(Instruction in, int op) { return OperandType.isScalar(in.getOperandType(op)); }
    int width(Instruction in, int op) {
        if (isReg(in, op)) return in.getRegister(op).getBitLength();
        String t = in.getDefaultOperandRepresentation(op);
        return t.startsWith("qword") ? 64 : t.startsWith("dword") ? 32 : t.startsWith("word") ? 16 : t.startsWith("byte") ? 8 : 64;
    }
    // immediate as a value: 64-bit destinations hold double bit patterns (RValue stores), narrower ones integers
    Val immVal(Scalar s, int bits) {
        long u = s.getUnsignedValue();
        if (bits == 64) {
            double d = Double.longBitsToDouble(u);
            if (u == 0) return Val.number(0);
            if (!Double.isNaN(d) && !Double.isInfinite(d) && Math.abs(d) >= 1e-9 && Math.abs(d) < 1e12) return Val.number(d);
            return Val.number((double) s.getSignedValue());
        }
        Val v = Val.number((double) s.getSignedValue());
        if (bits == 32) v.flt = (double) Float.intBitsToFloat((int) u);
        return v;
    }
    Rv srcOf(Instruction in, int op) {
        if (isReg(in, op)) return reg(base(in.getRegister(op)));
        if (isImm(in, op)) return Rv.val(immVal(in.getScalar(op), in.getRegister(0) != null ? in.getRegister(0).getBitLength() : 64));
        return loadReg(in, op);
    }

    // the runtime's compare of two known debug-derived numbers has a known result
    void compareCall(Rv rcx, Rv rdx) {
        Val a = asVal(rcx), b = asVal(rdx);
        killCallerSaved();
        if ((a.dbg || b.dbg) && a.num != null && b.num != null) {
            double d = a.num - b.num;
            Val r = Val.number(Math.abs(d) < EPS ? 0 : d < 0 ? -1 : 1);
            r.dbg = true;
            regs.put("RAX", Rv.val(r));
        }
    }

    void doCall(Instruction in) {
        String t = in.getOpObjects(0).length > 0 ? in.getOpObjects(0)[0].toString() : "";
        String rep = in.getDefaultOperandRepresentation(0).replace(" ", "");
        if (rep.endsWith("+0x8]") || rep.endsWith("+0x10]")) { // virtual variable accessor: RDX is the slot id
            Rv slot = reg("RDX");
            killCallerSaved();
            regs.put("RAX", slot.t == 'S' ? Rv.of('R', slot.id) : new Rv());
            return;
        }
        Rv rcx = reg("RCX"), rdx = reg("RDX"), r9 = reg("R9");
        if (t.equals(COMPARE)) {
            Val a = asVal(rcx), b = asVal(rdx);
            boolean numeric = tags(a).isEmpty() && tags(b).isEmpty() && (a.num != null || b.num != null); // compared with a known number: not a string compare
            sb.append("V\t").append(func).append('\t').append(in.getAddress()).append('\t').append(numeric ? 1 : 0).append('\n');
            compareCall(rcx, rdx); return;
        }
        if (GETTERS.contains(t)) {
            Rv slot = rdx; Rv out = r9;
            killCallerSaved();
            if (out.t == 'P' && slot.t == 'S') {
                Val v = Val.var(slot.id);
                if (debugSlots.contains(slot.id)) { v.num = 0.0; v.dbg = true; }
                setCell(out.id, v);
            }
            return;
        }
        if (t.equals(INIT) || t.equals(COPY)) {
            Val v = asVal(rdx); Rv dest = rcx;
            killCallerSaved();
            if (dest.t == 'P') setCell(dest.id, v);
            regs.put("RAX", dest); return;
        }
        if (t.equals(TO_REAL)) { Val v = asVal(rcx); killCallerSaved(); regs.put("XMM0", Rv.val(v)); return; }
        if (t.equals(TO_INT)) { Val v = asVal(rcx); killCallerSaved(); regs.put("RAX", Rv.val(v)); return; }
        if (t.equals(ARRAY_ELEMENT)) {
            Rv out = new Rv();
            if (rcx.t == 'R') out = rcx;
            else if (rcx.t == 'P') { Val c = cell(rcx.id); if (c.vars.size() == 1 && c.consts.isEmpty()) out = Rv.of('R', c.vars.first()); }
            killCallerSaved(); regs.put("RAX", out); return;
        }
        if (t.equals(ARRAY_GET)) { // `a[i]` read: (the array's data, i) -> the element
            Val arr = asVal(rcx);
            Rv out = arr.vars.size() == 1 && !arr.arith && !arr.vars.first().startsWith("s:") ? Rv.of('R', arr.vars.first()) : new Rv();
            killCallerSaved(); regs.put("RAX", out); return;
        }
        if (ARITH.contains(t)) {
            Val v = asVal(rcx).copy(); v.merge(asVal(rdx)); v.arith = true; v.num = null; v.flt = null; Rv dest = rcx;
            killCallerSaved();
            if (dest.t == 'P') setCell(dest.id, v);
            return;
        }
        if (!FREE.contains(t) && rcx.t == 'P' && rdx.t == 'P' && !tags(asVal(rdx)).isEmpty()) { // the string-aware copy helper: (dest temp, &literal)
            Val v = asVal(rdx); killCallerSaved(); setCell(rcx.id, v); return;
        }
        killCallerSaved();
    }

    static boolean isCondJump(String mn) {
        return mn.startsWith("J") && !mn.equals("JMP");
    }

    void step(Instruction in) {
        String mn = in.getMnemonicString();
        if (mn.equals("CALL")) { doCall(in); return; }
        int n = in.getNumOperands();
        if (isCondJump(mn)) return;
        if ((mn.equals("CMP") || mn.equals("TEST") || mn.equals("COMISD") || mn.equals("UCOMISD") || mn.equals("COMISS") || mn.equals("UCOMISS")) && n == 2) return; // flags only
        if (mn.equals("MOVSS") && n == 2 && isReg(in, 0) && !isReg(in, 1) && !isImm(in, 1)) { // float constant from the pool
            Object[] m = mem(in, 1);
            if (m != null && m[0] == null && (Long) m[1] < SLOT_LO) {
                try {
                    float f = Float.intBitsToFloat(currentProgram.getMemory().getInt(toAddr((Long) m[1])));
                    regs.put(base(in.getRegister(0)), Rv.val(Float.isNaN(f) ? Val.unknown() : Val.number(f)));
                    return;
                } catch (Exception e) { }
            }
        }
        if ((mn.equals("XORPS") || mn.equals("PXOR") || mn.equals("XORPD")) && n == 2 && isReg(in, 0) && isReg(in, 1) && base(in.getRegister(0)).equals(base(in.getRegister(1)))) {
            regs.put(base(in.getRegister(0)), Rv.val(Val.number(0))); return;
        }
        if (mn.equals("MOV") || mn.equals("MOVSXD") || mn.equals("MOVZX") || mn.equals("MOVSX") || mn.equals("MOVSD") || mn.equals("MOVSS")
            || mn.equals("MOVAPS") || mn.equals("MOVUPS") || mn.equals("MOVQ") || mn.equals("MOVD") || mn.equals("MOVAPD") || mn.equals("CVTSD2SS") || mn.equals("CVTSS2SD")
            || mn.equals("CVTTSD2SI") || mn.equals("CVTSD2SI") || mn.equals("CVTSI2SD") || mn.equals("CVTSI2SS") || mn.equals("CVTTSS2SI")) {
            if (n != 2) return;
            if (isReg(in, 0)) {
                String d = base(in.getRegister(0));
                Rv s = srcOf(in, 1);
                if (isImm(in, 1)) s = Rv.val(immVal(in.getScalar(1), in.getRegister(0).getBitLength()));
                regs.put(d, s.t == 'U' ? new Rv() : s);
            } else { // store
                Val v = isImm(in, 1) ? immVal(in.getScalar(1), width(in, 0)) : asVal(srcOf(in, 1));
                store(in, 0, v);
            }
            return;
        }
        if (mn.equals("LEA") && n == 2 && isReg(in, 0)) { // the operand of a RIP-relative LEA is a scalar, so take the slot from the reference
            for (var ref : in.getReferencesFrom()) {
                String hex = Long.toHexString(ref.getToAddress().getOffset());
                if (!ref.isMemoryReference() || !stringSlots.contains(hex)) continue;
                regs.put(base(in.getRegister(0)), Rv.of('P', "abs:" + hex));
                return;
            }
        }
        if (mn.equals("LEA") && n == 2 && isReg(in, 0)) {
            String d = base(in.getRegister(0)); Object[] m = mem(in, 1);
            Rv r = new Rv();
            if (m != null) {
                if (m[0] == null) r = Rv.of('P', "abs:" + Long.toHexString((Long) m[1]));
                else {
                    String b = (String) m[0]; long off = (Long) m[1];
                    if (b.equals("RBP") || b.equals("RSP")) r = Rv.of('P', b + "+" + off);
                    else if (off == 0 && (reg(b).t == 'P' || reg(b).t == 'R')) r = reg(b);
                }
            }
            regs.put(d, r); return;
        }
        if (mn.equals("XOR") && n == 2 && isReg(in, 0) && isReg(in, 1) && in.getRegister(0).getName().equals(in.getRegister(1).getName())) {
            regs.put(base(in.getRegister(0)), Rv.val(Val.number(0))); return;
        }
        if (mn.equals("NOP") || mn.equals("RET") || mn.equals("BT") || mn.equals("PUSH") || mn.equals("UD2") || mn.equals("INT3") || mn.equals("ENDBR64")
            || mn.equals("CDQE") || mn.equals("CDQ") || mn.equals("JMP")) return;
        if (n >= 1 && isReg(in, 0)) { // arithmetic and everything else: dst := f(dst, src)
            String d = base(in.getRegister(0)); Rv dv = reg(d);
            boolean arithOp = mn.startsWith("ADD") || mn.startsWith("SUB") || mn.startsWith("MUL") || mn.startsWith("IMUL") || mn.startsWith("DIV") || mn.startsWith("SHL")
                || mn.startsWith("SHR") || mn.startsWith("SAR") || mn.startsWith("AND") || mn.startsWith("OR") || mn.startsWith("XOR") || mn.startsWith("CVT") || mn.startsWith("MAX") || mn.startsWith("MIN") || mn.startsWith("SQRT") || mn.startsWith("NEG") || mn.startsWith("INC") || mn.startsWith("DEC");
            if (arithOp && dv.t == 'V') {
                Val v = dv.v.copy(); v.arith = true; v.num = null; v.flt = null;
                if (n >= 2) { Rv s = srcOf(in, 1); if (s.t == 'V') v.merge(s.v); else if (!isImm(in, 1)) v.unk = true; v.num = null; v.flt = null; }
                regs.put(d, Rv.val(v));
            } else regs.put(d, new Rv());
        }
    }

    @Override protected void run() throws Exception {
        String[] a = getScriptArgs();
        for (int i = 1; i < a.length; i++) {
            if (a[i].equals("strings")) stringSlots.addAll(Files.readAllLines(new File(a[++i]).toPath()));
            else debugSlots.add(a[i]);
        }
        stringSlots.removeIf(String::isEmpty);
        long textLo = currentProgram.getMemory().getBlock(".text").getStart().getOffset();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            long e = f.getEntryPoint().getOffset();
            if (e < textLo || e >= GAME_END) continue;
            if (monitor.isCancelled()) break;
            func = f.getEntryPoint().toString(); regs = new HashMap<>(); cells = new HashMap<>();
            InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
            while (it.hasNext()) step(it.next());
        }
        Files.writeString(new File(a[0]).toPath(), sb.toString());
    }
}
