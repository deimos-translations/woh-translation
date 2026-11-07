// Usage: -postScript StringUses.java <targets.tsv> <outPrefix>
// Safety research for translating the strings in targets.tsv. Writes two files:
//   <outPrefix>.interior.tsv  `va <TAB> offset <TAB> from`: a reference that lands inside one of the strings (not at its start),
//                             i.e. a shared tail; patching the string start would not move that reference.
//   <outPrefix>.uses.tsv      `va <TAB> slot <TAB> useAddr <TAB> function <TAB> scriptName <TAB> calls`: every code use of the
//                             startup slot that holds the string (excluding the startup initializer and the tiny destructor
//                             stubs), with the call targets that follow within 40 instructions.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

import java.io.BufferedWriter;
import java.io.File;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;

public class StringUses extends GhidraScript {
    private final Map<Address, String> scriptNames = new HashMap<>();

    private int cStringLength(Address addr) throws Exception {
        int n = 0;
        while (getByte(addr.add(n)) != 0) n++;
        return n;
    }

    /** The `LEA RCX,[slot]` that pairs with `LEA RDX,[literal]` at the initializer. */
    private Address slotOf(Address literal) {
        for (Reference ref : getReferencesTo(literal)) {
            Instruction lea = getInstructionAt(ref.getFromAddress());
            if (lea == null || !lea.getMnemonicString().equals("LEA")) continue;
            for (Instruction cand : new Instruction[] { lea.getPrevious(), lea.getNext() }) {
                if (cand == null || !cand.getMnemonicString().equals("LEA") || cand.getRegister(0) == null) continue;
                if (!cand.getRegister(0).getName().equals("RCX")) continue;
                for (Reference r : cand.getReferencesFrom()) return r.getToAddress();
            }
        }
        return null;
    }

    private String scriptName(Function fn) throws Exception {
        String cached = scriptNames.get(fn.getEntryPoint());
        if (cached != null) return cached;
        String found = "";
        for (Instruction ins : currentProgram.getListing().getInstructions(fn.getBody(), true)) {
            for (Reference ref : ins.getReferencesFrom()) {
                Data d = getDataAt(ref.getToAddress());
                if (d != null && d.hasStringValue()) {
                    String s = String.valueOf(d.getValue());
                    if (s.startsWith("gml_")) { found = s; break; }
                }
            }
            if (!found.isEmpty()) break;
        }
        scriptNames.put(fn.getEntryPoint(), found);
        return found;
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        try (BufferedWriter interior = Files.newBufferedWriter(new File(args[1] + ".interior.tsv").toPath());
             BufferedWriter uses = Files.newBufferedWriter(new File(args[1] + ".uses.tsv").toPath())) {
            for (String line : Files.readAllLines(new File(args[0]).toPath())) {
                Address literal = toAddr(line.substring(0, line.indexOf('\t')));
                int len = cStringLength(literal);
                for (int k = 1; k < len; k++)
                    for (Reference ref : getReferencesTo(literal.add(k)))
                        interior.write(literal + "\t" + k + "\t" + ref.getFromAddress() + "\n");

                Address slot = slotOf(literal);
                if (slot == null) { uses.write(literal + "\tNOSLOT\n"); continue; }
                for (Reference ref : getReferencesTo(slot)) {
                    Function fn = getFunctionContaining(ref.getFromAddress());
                    if (fn == null || fn.getBody().getNumAddresses() < 100) continue; // destructor stub
                    // the startup initializer reads no value: it is the function that also holds the literal's LEA
                    if (fn.getBody().contains(literal) || isInitializer(fn, literal)) continue;
                    StringBuilder calls = new StringBuilder();
                    Instruction ins = getInstructionAt(ref.getFromAddress());
                    for (int n = 0; n < 40 && ins != null; n++, ins = ins.getNext()) {
                        if (ins.getMnemonicString().equals("RET")) break;
                        if (!ins.getFlowType().isCall()) continue;
                        Address[] flows = ins.getFlows();
                        calls.append(flows.length > 0 ? flows[0].toString() : "indirect").append(',');
                    }
                    uses.write(literal + "\t" + slot + "\t" + ref.getFromAddress() + "\t" + fn.getEntryPoint() + "\t"
                               + scriptName(fn) + "\t" + calls + "\n");
                }
            }
        }
    }

    private boolean isInitializer(Function fn, Address literal) {
        for (Reference ref : getReferencesTo(literal))
            if (fn.getBody().contains(ref.getFromAddress())) return true;
        return false;
    }
}
