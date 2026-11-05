// Usage: -postScript SpriteRefs.java <sitesOut> <constsOut> <spriteCount> <sinkVA> [<sinkVA>...]
// Static sprite usage scan of the YYC code (game code = addresses below game_end, the runtime sits above it).
//
// sitesOut: one row per call/jump from game code into a sprite-taking native (draw_sprite & co.):
//   sink <TAB> callVA <TAB> funcVA <TAB> reg <TAB> value
//   reg = the argument register that carries the sprite id (ECX/EDX/R8/R9 are all reported, the reader picks per sink);
//   value = integer constant (MOV r32,imm / XOR r,r found in the straight-line code before the call), `dyn` (computed:
//   the sprite comes from a variable) or `unk` (a jump target was reached first, so the value is not unique).
// constsOut: sprite-id-valued doubles in game code, `spriteId <TAB> count <TAB> first sites...`. A sprite assigned to a
//   variable (`sprite_index = X`, `char_sprite = X`, array cells) is stored as a double RValue, so its id shows up as
//   `MOV r64,imm64` (the double's bits) or as a read of an 8-byte double in .rdata. Small ids collide with ordinary numbers,
//   so this is a candidate list, not proof.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.nio.file.Files;
import java.util.*;

public class SpriteRefs extends GhidraScript {
    private static final long GAME_END = Symbols.addr("game_end");
    private static final String[] ARG_REGS = { "RCX", "RDX", "R8", "R9" };
    private static final Set<String> NO_WRITE = Set.of("CMP", "TEST", "BT", "PUSH", "JMP", "CALL", "NOP", "UCOMISD", "COMISD", "UCOMISS", "COMISS");

    private static String base(Register reg) {
        return reg == null ? null : reg.getBaseRegister().getName();
    }

    /** True when something other than the previous instruction can jump to `ins` (a merge point). */
    private boolean isMerge(Instruction ins) {
        for (Reference ref : getReferencesTo(ins.getAddress())) {
            RefType type = ref.getReferenceType();
            if (type.isJump() || type.isConditional() && type.isFlow()) return true;
        }
        return false;
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        int spriteCount = Integer.parseInt(args[2]);
        StringBuilder sites = new StringBuilder();

        for (int i = 3; i < args.length; i++) {
            for (Reference ref : getReferencesTo(toAddr(args[i]))) {
                RefType type = ref.getReferenceType();
                if (!type.isCall() && !type.isJump()) continue;
                Address from = ref.getFromAddress();
                if (from.getOffset() >= GAME_END) continue;
                Function fn = getFunctionContaining(from);
                Instruction call = getInstructionAt(from);
                if (call == null) continue;
                Map<String, String> found = new LinkedHashMap<>();
                Set<String> open = new HashSet<>(Arrays.asList(ARG_REGS));
                Instruction cur = call.getPrevious();
                boolean merged = false;
                for (int k = 0; k < 40 && cur != null && !open.isEmpty(); k++, cur = cur.getPrevious()) {
                    String mn = cur.getMnemonicString();
                    if (mn.equals("CALL") || mn.equals("RET")) break;
                    if (!NO_WRITE.contains(mn) && cur.getNumOperands() > 0) {
                        String dest = base(cur.getRegister(0));
                        if (dest != null && open.contains(dest)) {
                            Scalar imm = cur.getNumOperands() > 1 ? cur.getScalar(1) : null;
                            if (mn.equals("MOV") && imm != null && cur.getNumOperands() == 2 && cur.getRegister(1) == null
                                    && cur.getOpObjects(1).length == 1)
                                found.put(dest, Long.toString(imm.getUnsignedValue()));
                            else if (mn.equals("XOR") && base(cur.getRegister(1)) != null && dest.equals(base(cur.getRegister(1))))
                                found.put(dest, "0");
                            else found.put(dest, "dyn");
                            open.remove(dest);
                        }
                    }
                    if (!open.isEmpty() && isMerge(cur)) { merged = true; break; }
                }
                StringBuilder row = new StringBuilder();
                for (String reg : ARG_REGS) {
                    String value = found.get(reg);
                    if (value == null) value = merged ? "unk" : "none";
                    row.append(args[i]).append('\t').append(from).append('\t').append(fn == null ? "-" : fn.getEntryPoint().toString())
                       .append('\t').append(reg).append('\t').append(value).append('\n');
                }
                sites.append(row);
            }
        }
        Files.writeString(new File(args[0]).toPath(), sites.toString());

        // pass 2: sprite-id-valued doubles
        long[] counts = new long[spriteCount];
        List<List<String>> first = new ArrayList<>();
        for (int i = 0; i < spriteCount; i++) first.add(new ArrayList<>());
        MemoryBlock text = currentProgram.getMemory().getBlock(".text");
        AddressSet gameCode = new AddressSet(text.getStart(), toAddr(GAME_END - 1));
        InstructionIterator it = currentProgram.getListing().getInstructions(gameCode, true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Instruction ins = it.next();
            long bits;
            if (ins.getMnemonicString().equals("MOV") && ins.getNumOperands() == 2 && ins.getRegister(0) != null
                    && ins.getRegister(0).getBitLength() == 64 && ins.getScalar(1) != null) {
                bits = ins.getScalar(1).getUnsignedValue();
            } else if (ins.getMnemonicString().equals("MOVSD") && ins.getNumOperands() == 2 && ins.getRegister(0) != null) {
                Address pool = null;
                for (Reference ref : ins.getReferencesFrom())
                    if (ref.isMemoryReference() && ref.getReferenceType() == RefType.READ) pool = ref.getToAddress();
                if (pool == null) continue;
                try { bits = currentProgram.getMemory().getLong(pool); } catch (Exception e) { continue; }
            } else continue;
            double value = Double.longBitsToDouble(bits);
            if (value < 0 || value >= spriteCount || value != Math.rint(value)) continue;
            int id = (int) value;
            counts[id]++;
            if (first.get(id).size() < 6) first.get(id).add(ins.getAddress().toString());
        }
        StringBuilder consts = new StringBuilder();
        for (int id = 0; id < spriteCount; id++)
            consts.append(id).append('\t').append(counts[id]).append('\t').append(String.join(" ", first.get(id))).append('\n');
        Files.writeString(new File(args[1]).toPath(), consts.toString());
    }
}
