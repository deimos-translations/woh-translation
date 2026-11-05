// args: out [debugSlotVA...]
// Intra-function symbolic value flow over the YYC runtime-value idioms, one forward pass per function in address order (last definition wins).
// Tracks registers (incl. XMM) and stack temps as {exact number, constant ids, variable slots, arith flag, unknown flag}.
// Variables whose slot VA is given after `out` are assumed to be 0 (false): compares against them are evaluated, the conditional branches that
// follow are decided, and the blocks that become unreachable in the function are "dead" (this models `if (debug)` as `if (false)`).
// Every row ends with `dead` = 1 when its site is in such a dead block (the G/R rows: when every use in the function is dead).
// Rows:
//   W  func site destSlot consts vars arith unk dead      value written into variable destSlot (set helper, lvalue getter, array element)
//   D  func site sink consts vars arith unk dead x2 x3 s20  value of the sprite id operand (RDX) of a sprite native; x2/x3/s20 = the XMM2, XMM3 and
//                                                          [rsp+0x20] arguments (sub-image / x / y): k:<number> | v:<slot,..> | u ; s20 may be i:<int>|f:<float>
//   C  func callee site dead                              direct call to a game function (call graph)
//   G  func slot dead                                     the function READS this variable (virtual getter +8, or a get helper); writes are W
//   R  func slot dead                                     the function reads this variable slot id (script calls go through the script's name slot)
//   E  func from>to                                      a conditional branch decided by the debug-off assumption; `to` is the successor that never runs
//   K  func site                                          a CALL instruction in a dead block
//   N  func                                               function with a computed jump: no dead-block analysis done
//   X  func site callee slot                              other direct call that receives a variable slot id in RDX (unmodelled accessor)
// destSlot is a data-slot VA (variable id) or `abs:<va>` for a static table cell.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.OperandType;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.FlowType;
import java.io.File;
import java.nio.file.Files;
import java.util.*;

public class Flow extends GhidraScript {
    static final long GAME_END = Symbols.addr("game_end"), SLOT_LO = Symbols.addr("slot_lo"), SLOT_HI = Symbols.addr("slot_hi");
    static final Set<String> SINKS = Set.of(Symbols.text("draw_sprite"), Symbols.text("draw_sprite_ext"), Symbols.text("draw_sprite_part"));
    static final Set<String> SETTERS = Symbols.set("setters_flow");
    static final Set<String> OP_SETTERS = Symbols.set("op_setters"); // compound assignment: read-modify-write
    static final Set<String> GETTERS = Symbols.set("getters");
    static final Set<String> ARITH = Symbols.set("arith");
    static final String COMPARE = Symbols.text("compare"); // (RValue* a, RValue* b, double eps, flag) -> -1 / 0 / 1, -2 if unordered
    static final double EPS = 1e-5; // decides only 0-vs-1 debug flag compares, so the runtime's own epsilon variable is not needed
    static final String INIT = Symbols.text("rvalue_init"), COPY = Symbols.text("rvalue_copy"), TO_REAL = Symbols.text("to_real"), TO_INT = Symbols.text("to_int"),
        ARRAY_ELEMENT = Symbols.text("array_element");

    static class Val {
        Double num, flt; // exact number if known; flt = the same dword read as a float (32-bit immediates)
        boolean dbg;     // derived from one of the assumed-false debug variables: only such values are used to decide branches
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
    static class Row { String text; Address site; Row(String t, Address s) { text = t; site = s; } }

    Set<String> debugSlots = new HashSet<>();
    Map<String, List<Address>> slotUse = new TreeMap<>(), getUse = new TreeMap<>();
    List<Row> rows = new ArrayList<>(); List<Address> callSites = new ArrayList<>();
    Set<String> deadEdges = new HashSet<>();
    Map<String, Rv> regs; Map<String, Val> cells; StringBuilder sb = new StringBuilder(); String func;
    boolean flagsKnown; boolean zf, sf, of, cf;

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
            case 'R': { Val v = Val.var(r.id); if (debugSlots.contains(r.id)) { v.num = 0.0; v.dbg = true; } return v; }
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
        }
        Val v = cells.get(id);
        return v == null ? Val.unknown() : v;
    }
    String fmt(Val v) {
        StringBuilder s = new StringBuilder();
        s.append(joinL(v.consts)).append('\t').append(String.join(",", v.vars)).append('\t').append(v.arith ? 1 : 0).append('\t').append(v.unk ? 1 : 0);
        return s.toString();
    }
    static String joinL(Collection<Long> c) { StringBuilder s = new StringBuilder(); for (long x : c) { if (s.length() > 0) s.append(','); s.append(x); } return s.toString(); }
    static String num(double d) { return d == Math.rint(d) && Math.abs(d) < 1e15 ? String.valueOf((long) d) : String.valueOf(d); }
    static String kv(Val v) {
        if (v == null || v.unk && v.num == null && v.vars.isEmpty()) return "u";
        if (v.num != null && v.vars.isEmpty() && !v.arith) {
            String s = "k:" + num(v.num);
            return v.flt != null ? "i:" + num(v.num) + "|f:" + num(v.flt) : s;
        }
        if (!v.vars.isEmpty()) return "v:" + String.join(",", v.vars) + (v.arith ? "+" : "");
        return "u";
    }
    void row(String text, Address site) { rows.add(new Row(text, site)); }
    void emitW(Instruction at, String dest, Val v) { row("W\t" + func + "\t" + at.getAddress() + "\t" + dest + "\t" + fmt(v), at.getAddress()); }
    void emitD(Instruction at, String sink, Val v) {
        Val s20 = cells.get("RSP+32");
        row("D\t" + func + "\t" + at.getAddress() + "\t" + sink + "\t" + fmt(v) + "\t{dead}\t" + kv(asVal(reg("XMM2"))) + "\t" + kv(asVal(reg("XMM3"))) + "\t" + kv(s20), at.getAddress());
    }

    void assign(Instruction at, Rv p, Val v) {
        if (p == null) return;
        if (p.t == 'P') cells.put(p.id, v);
        else if (p.t == 'R') emitW(at, p.id, v);
    }
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
        if (off == 0) return asVal(reg(b));
        return Val.unknown();
    }
    Rv loadReg(Instruction in, int op) {
        Object[] m = mem(in, op);
        if (m != null && m[0] == null) {
            long va = (Long) m[1];
            if (va >= SLOT_LO && va < SLOT_HI) { slotUse.computeIfAbsent(Long.toHexString(va), k -> new ArrayList<>()).add(in.getAddress()); return Rv.of('S', Long.toHexString(va)); }
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
        if (b.equals("RBP") || b.equals("RSP")) { if (off % 8 == 0) cells.put(b + "+" + off, v); return; }
        if (off == 0) { Rv p = reg(b); if (p.t == 'R') emitW(in, p.id, v); else if (p.t == 'P') cells.put(p.id, v); }
    }
    void kill(String... names) { for (String n : names) regs.put(n, new Rv()); }
    void killCallerSaved() {
        kill("RAX", "RCX", "RDX", "R8", "R9", "R10", "R11");
        for (int i = 0; i <= 5; i++) kill("XMM" + i);
        flagsKnown = false;
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

    // ---- compare / branch evaluation ----
    boolean tainted(Rv a, Rv b) { return asVal(a).dbg || asVal(b).dbg; }
    boolean intOf(Rv r, long[] out) {
        Val v = asVal(r);
        if (v == null || v.num == null || v.num != Math.rint(v.num)) return false;
        out[0] = (long) (double) v.num; return true;
    }
    void setSub(long a, long b, int bits) {
        long mask = bits == 64 ? -1L : (1L << bits) - 1, sign = 1L << (bits - 1);
        long x = a & mask, y = b & mask, r = (x - y) & mask;
        zf = r == 0; sf = (r & sign) != 0; cf = Long.compareUnsigned(x, y) < 0;
        of = ((x ^ y) & (x ^ r) & sign) != 0; flagsKnown = true;
    }
    void setLogic(long a, long b, int bits) {
        long mask = bits == 64 ? -1L : (1L << bits) - 1, sign = 1L << (bits - 1);
        long r = (a & b) & mask;
        zf = r == 0; sf = (r & sign) != 0; cf = false; of = false; flagsKnown = true;
    }
    Boolean cond(String mn) {
        if (!flagsKnown) return null;
        switch (mn) {
            case "JZ": case "JE": return zf;
            case "JNZ": case "JNE": return !zf;
            case "JS": return sf;
            case "JNS": return !sf;
            case "JC": case "JB": case "JNAE": return cf;
            case "JNC": case "JAE": case "JNB": return !cf;
            case "JBE": case "JNA": return cf || zf;
            case "JA": case "JNBE": return !cf && !zf;
            case "JL": case "JNGE": return sf != of;
            case "JGE": case "JNL": return sf == of;
            case "JLE": case "JNG": return zf || sf != of;
            case "JG": case "JNLE": return !zf && sf == of;
            case "JO": return of;
            case "JNO": return !of;
            default: return null;
        }
    }
    void branch(Instruction in) {
        Boolean taken = cond(in.getMnemonicString());
        if (taken == null) return;
        Address ft = in.getFallThrough();
        Address[] fl = in.getFlows();
        if (ft == null || fl == null || fl.length != 1) return;
        deadEdges.add(in.getAddress() + ">" + (taken ? ft : fl[0]));
    }
    void compareCall(Instruction in, Rv rcx, Rv rdx) {
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
        callSites.add(in.getAddress());
        if (rep.endsWith("+0x8]") || rep.endsWith("+0x10]")) { // virtual variable accessor: RDX is the slot id
            Rv slot = reg("RDX");
            if (rep.endsWith("+0x8]") && slot.t == 'S') getUse.computeIfAbsent(slot.id, k -> new ArrayList<>()).add(in.getAddress());
            killCallerSaved();
            regs.put("RAX", slot.t == 'S' ? Rv.of('R', slot.id) : new Rv());
            return;
        }
        if (!t.isEmpty() && t.matches("[0-9a-f]+")) {
            try { if (Long.parseLong(t, 16) < GAME_END) row("C\t" + func + "\t" + t + "\t" + in.getAddress() + "\t{dead}", in.getAddress()); } catch (NumberFormatException e) { }
        }
        Rv rcx = reg("RCX"), rdx = reg("RDX"), r9 = reg("R9");
        if (rdx.t == 'S' && !SETTERS.contains(t) && !OP_SETTERS.contains(t) && !GETTERS.contains(t))
            sb.append("X\t").append(func).append('\t').append(in.getAddress()).append('\t').append(t).append('\t').append(rdx.id).append('\n');
        if (t.equals(COMPARE)) { compareCall(in, rcx, rdx); return; }
        if (SINKS.contains(t)) {
            Rv id = rdx;
            if (!(id.t == 'V' && id.v.vars.isEmpty() && !id.v.unk && !id.v.arith && !id.v.consts.isEmpty() && in.getPrevious() != null && litEdx(in))) emitD(in, t, asVal(id));
            killCallerSaved(); return;
        }
        if (SETTERS.contains(t)) {
            if (rdx.t == 'S') emitW(in, rdx.id, asVal(r9));
            killCallerSaved(); return;
        }
        if (OP_SETTERS.contains(t)) {
            if (rdx.t == 'S') { Val v = asVal(r9).copy(); v.arith = true; v.num = null; emitW(in, rdx.id, v); }
            killCallerSaved(); return;
        }
        if (GETTERS.contains(t)) {
            Rv slot = rdx; Rv out = r9;
            if (slot.t == 'S') getUse.computeIfAbsent(slot.id, k -> new ArrayList<>()).add(in.getAddress());
            killCallerSaved();
            if (out.t == 'P' && slot.t == 'S') {
                Val v = Val.var(slot.id);
                if (debugSlots.contains(slot.id)) { v.num = 0.0; v.dbg = true; }
                cells.put(out.id, v);
            }
            return;
        }
        if (t.equals(INIT) || t.equals(COPY)) {
            Val v = asVal(rdx); Rv dest = rcx;
            killCallerSaved();
            assign(in, dest, v); regs.put("RAX", dest); return;
        }
        if (t.equals(TO_REAL)) { Val v = asVal(rcx); killCallerSaved(); regs.put("XMM0", Rv.val(v)); return; }
        if (t.equals(TO_INT)) { Val v = asVal(rcx); killCallerSaved(); regs.put("RAX", Rv.val(v)); return; }
        if (t.equals(ARRAY_ELEMENT)) {
            Rv out = new Rv();
            if (rcx.t == 'R') out = rcx;
            else if (rcx.t == 'P') { Val c = cell(rcx.id); if (c.vars.size() == 1 && c.consts.isEmpty()) out = Rv.of('R', c.vars.first()); }
            killCallerSaved(); regs.put("RAX", out); return;
        }
        if (ARITH.contains(t)) {
            Val v = asVal(rcx).copy(); v.merge(asVal(rdx)); v.arith = true; v.num = null; v.flt = null; Rv dest = rcx;
            killCallerSaved(); assign(in, dest, v); return;
        }
        killCallerSaved();
    }
    // the sink's RDX operand was loaded by `MOV EDX,imm32` in the straight-line code just before (A tier, handled by SpriteRefs)
    boolean litEdx(Instruction call) {
        Instruction p = call.getPrevious();
        for (int k = 0; k < 14 && p != null; k++, p = p.getPrevious()) {
            if (p.getMnemonicString().equals("MOV") && p.getRegister(0) != null && p.getRegister(0).getName().equals("EDX"))
                return OperandType.isScalar(p.getOperandType(1));
            if (p.getMnemonicString().equals("CALL")) return false;
        }
        return false;
    }

    static boolean isCondJump(String mn) {
        return mn.startsWith("J") && !mn.equals("JMP");
    }

    void step(Instruction in) {
        String mn = in.getMnemonicString();
        if (mn.equals("CALL")) { doCall(in); return; }
        int n = in.getNumOperands();
        if (isCondJump(mn)) { branch(in); return; }
        if (mn.equals("CMP") && n == 2) {
            long[] a = new long[1], b = new long[1];
            Rv ra = srcOf(in, 0), rb = srcOf(in, 1);
            if (tainted(ra, rb) && intOf(ra, a) && intOf(rb, b)) setSub(a[0], b[0], width(in, 0)); else flagsKnown = false;
            return;
        }
        if (mn.equals("TEST") && n == 2) {
            long[] a = new long[1], b = new long[1];
            Rv ra = srcOf(in, 0), rb = srcOf(in, 1);
            if (tainted(ra, rb) && intOf(ra, a) && intOf(rb, b)) setLogic(a[0], b[0], width(in, 0)); else flagsKnown = false;
            return;
        }
        if ((mn.equals("COMISD") || mn.equals("UCOMISD") || mn.equals("COMISS") || mn.equals("UCOMISS")) && n == 2) {
            Val a = asVal(srcOf(in, 0)), b = asVal(srcOf(in, 1));
            if ((a.dbg || b.dbg) && a.num != null && b.num != null) {
                zf = a.num.equals(b.num); cf = a.num < b.num; sf = false; of = false; flagsKnown = true;
            } else flagsKnown = false;
            return;
        }
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
            regs.put(base(in.getRegister(0)), Rv.val(Val.number(0))); flagsKnown = false; return;
        }
        if (mn.equals("NOP") || mn.equals("RET") || mn.equals("BT") || mn.equals("PUSH") || mn.equals("UD2") || mn.equals("INT3") || mn.equals("ENDBR64")
            || mn.equals("CDQE") || mn.equals("CDQ") || mn.equals("JMP")) return;
        flagsKnown = false;
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

    // ---- dead blocks ----
    Set<Address> reachable(Function f, boolean cut, boolean[] computed) {
        Set<Address> seen = new HashSet<>(); ArrayDeque<Address> stack = new ArrayDeque<>();
        stack.push(f.getEntryPoint()); seen.add(f.getEntryPoint());
        while (!stack.isEmpty()) {
            Address a = stack.pop();
            Instruction in = getInstructionAt(a);
            if (in == null) continue;
            FlowType ft = in.getFlowType();
            List<Address> next = new ArrayList<>();
            if (ft.isJump()) {
                if (ft.isComputed()) computed[0] = true;
                for (Address t : in.getFlows()) next.add(t);
                if (ft.isConditional() && in.getFallThrough() != null) next.add(in.getFallThrough());
            } else if (!ft.isTerminal() && in.getFallThrough() != null) next.add(in.getFallThrough());
            for (Address t : next) {
                if (cut && deadEdges.contains(a + ">" + t)) continue;
                if (f.getBody().contains(t) && seen.add(t)) stack.push(t);
            }
        }
        return seen;
    }

    @Override protected void run() throws Exception {
        String[] a = getScriptArgs();
        for (int i = 1; i < a.length; i++) debugSlots.add(a[i]);
        long textLo = currentProgram.getMemory().getBlock(".text").getStart().getOffset();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            long e = f.getEntryPoint().getOffset();
            if (e < textLo || e >= GAME_END) continue;
            if (monitor.isCancelled()) break;
            func = f.getEntryPoint().toString(); regs = new HashMap<>(); cells = new HashMap<>();
            slotUse.clear(); getUse.clear(); rows.clear(); callSites.clear(); deadEdges.clear(); flagsKnown = false;
            InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
            while (it.hasNext()) step(it.next());
            Set<Address> dead = new HashSet<>();
            boolean[] computed = new boolean[1];
            if (!deadEdges.isEmpty()) {
                Set<Address> full = reachable(f, false, computed), cut = reachable(f, true, computed);
                if (computed[0]) sb.append("N\t").append(func).append('\n');
                else { dead.addAll(full); dead.removeAll(cut); }
            }
            for (String de : deadEdges) sb.append("E\t").append(func).append('\t').append(de).append('\n');
            for (Row r : rows) sb.append(r.text.replace("{dead}", dead.contains(r.site) ? "1" : "0")).append(r.text.contains("{dead}") ? "" : "\t" + (dead.contains(r.site) ? 1 : 0)).append('\n');
            for (Map.Entry<String, List<Address>> en : getUse.entrySet())
                sb.append("G\t").append(func).append('\t').append(en.getKey()).append('\t').append(allDead(en.getValue(), dead) ? 1 : 0).append('\n');
            for (Map.Entry<String, List<Address>> en : slotUse.entrySet())
                sb.append("R\t").append(func).append('\t').append(en.getKey()).append('\t').append(allDead(en.getValue(), dead) ? 1 : 0).append('\n');
            for (Address c : callSites) if (dead.contains(c)) sb.append("K\t").append(func).append('\t').append(c).append('\n');
        }
        Files.writeString(new File(a[0]).toPath(), sb.toString());
    }
    static boolean allDead(List<Address> uses, Set<Address> dead) {
        for (Address u : uses) if (!dead.contains(u)) return false;
        return true;
    }
}
