// Usage: -postScript FindPatchSites.java <outFile>
// Writes patch_sites.tsv for the analysed build, so a game update needs no manual tracing.
//
// For each combat draw event (found by the name string it embeds):
//   * the startup slots whose literal is DOOM / STA / REA / ALL and that the event reads (logic keys, never patched);
//   * for each, the label slot 0x10 above it and the `LEA RDX,[literal]` that feeds it (patch.py repoints these);
//   * the `JNZ rel32` after `MOV RAX,7.0` that guards the language==7 block containing those reads.
// Output rows: `guard<TAB>addr<TAB>len<TAB>bytes<TAB>text` and
//              `slot<TAB>labelSlot<TAB>leaAddr<TAB>len<TAB>bytes<TAB>literalAddr<TAB>text`.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.nio.file.Files;
import java.util.LinkedHashMap;
import java.util.Map;

public class FindPatchSites extends GhidraScript {
    private static final String[] EVENTS = {
        "gml_Object_parent_newcombat_Draw_0", "gml_Object_nenm_xxx_custom_Draw_0", "gml_Object_nenm_xxx_custom_ext_Draw_0" };
    private static final String[] KEYS = { "DOOM", "STA", "REA", "ALL" };
    private static final long SEVEN = 0x401c000000000000L; // double 7.0, the language index of the label block

    private static String hex(byte[] bytes) {
        StringBuilder sb = new StringBuilder();
        for (byte b : bytes) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    private String cString(Address addr) throws Exception {
        java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
        byte value;
        while ((value = getByte(addr)) != 0) {
            bytes.write(value);
            addr = addr.add(1);
        }
        return bytes.toString(java.nio.charset.StandardCharsets.UTF_8);
    }

    /** The `LEA RDX,[literal]` next to the `LEA RCX,[slot]` of the startup initializer, or null. */
    private Instruction initializerLea(Address slot) {
        for (Reference ref : getReferencesTo(slot)) {
            Instruction lea = getInstructionAt(ref.getFromAddress());
            if (lea == null || !lea.getMnemonicString().equals("LEA")) continue;
            for (Instruction cand : new Instruction[] { lea.getNext(), lea.getPrevious() }) {
                if (cand != null && cand.getMnemonicString().equals("LEA") && cand.getRegister(0) != null
                        && cand.getRegister(0).getName().equals("RDX")) return cand;
            }
        }
        return null;
    }

    private Function eventFunction(String name) throws Exception {
        byte[] pat = ("\0" + name + "\0").getBytes("ISO-8859-1");
        byte[] mask = new byte[pat.length];
        java.util.Arrays.fill(mask, (byte) 0xff);
        Address hit = currentProgram.getMemory().findBytes(currentProgram.getMinAddress(), pat, mask, true, monitor);
        if (hit == null) throw new IllegalStateException("name string not found: " + name);
        for (Reference ref : getReferencesTo(hit.add(1))) {
            Function fn = getFunctionContaining(ref.getFromAddress());
            if (fn != null) return fn;
        }
        throw new IllegalStateException("no function references " + name);
    }

    @Override
    protected void run() throws Exception {
        StringBuilder out = new StringBuilder();
        for (String event : EVENTS) {
            Function fn = eventFunction(event);
            println(event + " -> " + fn.getName() + " (" + fn.getBody().getNumAddresses() + " bytes)");

            // slots the event reads whose startup literal is one of the damage-type keys
            Map<String, Address> slotOf = new LinkedHashMap<>();
            for (Instruction ins : currentProgram.getListing().getInstructions(fn.getBody(), true)) {
                for (Reference ref : ins.getReferencesFrom()) {
                    if (ref.getReferenceType() != RefType.READ || !ref.getToAddress().isMemoryAddress()) continue;
                    Instruction init = initializerLea(ref.getToAddress());
                    if (init == null) continue;
                    String literal = cString(init.getReferencesFrom()[0].getToAddress());
                    for (String key : KEYS) {
                        if (!literal.equals(key)) continue;
                        Address known = slotOf.putIfAbsent(key, ref.getToAddress());
                        if (known != null && !known.equals(ref.getToAddress()))
                            throw new IllegalStateException(event + ": two slots hold " + key);
                    }
                }
            }
            if (slotOf.size() != KEYS.length) throw new IllegalStateException(event + ": slots found " + slotOf.keySet());

            // reads of those slots, to decide which guard covers the block
            java.util.List<Address> reads = new java.util.ArrayList<>();
            for (Instruction ins : currentProgram.getListing().getInstructions(fn.getBody(), true))
                for (Reference ref : ins.getReferencesFrom())
                    if (ref.getReferenceType() == RefType.READ && slotOf.containsValue(ref.getToAddress()))
                        reads.add(ins.getAddress());

            int guards = 0;
            for (Instruction ins : currentProgram.getListing().getInstructions(fn.getBody(), true)) {
                if (!ins.getMnemonicString().equals("MOV") || ins.getNumOperands() != 2) continue;
                Object[] second = ins.getOpObjects(1);
                if (second.length != 1 || !(second[0] instanceof Scalar) || ((Scalar) second[0]).getValue() != SEVEN) continue;
                Instruction cursor = ins.getNext();
                for (int k = 0; k < 30 && cursor != null; k++, cursor = cursor.getNext()) {
                    if (!cursor.getMnemonicString().equals("JNZ") || cursor.getLength() != 6) continue;
                    Address target = cursor.getFlows()[0];
                    boolean covers = false;
                    for (Address read : reads)
                        if (read.compareTo(cursor.getAddress()) > 0 && read.compareTo(target) < 0) covers = true;
                    if (covers) {
                        out.append("guard\t").append(cursor.getAddress()).append('\t').append(cursor.getLength()).append('\t')
                           .append(hex(cursor.getBytes())).append('\t').append(cursor).append('\n');
                        guards++;
                    }
                    break;
                }
            }
            if (guards != 1) throw new IllegalStateException(event + ": expected 1 guard, found " + guards);

            for (String key : KEYS) {
                Address label = slotOf.get(key).add(0x10);
                Instruction lea = initializerLea(label);
                if (lea == null) throw new IllegalStateException(event + ": no initializer for label slot of " + key);
                Address literal = lea.getReferencesFrom()[0].getToAddress();
                out.append("slot\t").append(label).append('\t').append(lea.getAddress()).append('\t').append(lea.getLength())
                   .append('\t').append(hex(lea.getBytes())).append('\t').append(literal).append('\t').append(cString(literal)).append('\n');
            }
        }
        Files.writeString(new File(getScriptArgs()[0]).toPath(), out.toString());
    }
}
