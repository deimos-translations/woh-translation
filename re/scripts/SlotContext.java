// Usage: -postScript SlotContext.java <outFile> <before> <after> <slotAddr> [<slotAddr>...]
// Prints disassembly around every READ reference to each slot. Calls show the callee name; LEAs show any string at the target.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.RefType;

import java.io.File;
import java.nio.file.Files;

public class SlotContext extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        int before = Integer.parseInt(args[1]);
        int after = Integer.parseInt(args[2]);
        StringBuilder out = new StringBuilder();
        for (int i = 3; i < args.length; i++) {
            Address slot = toAddr(args[i]);
            for (Reference r : getReferencesTo(slot)) {
                if (r.getReferenceType() != RefType.READ && !args[0].endsWith("_all.txt")) continue;
                Function fn = getFunctionContaining(r.getFromAddress());
                out.append("==== slot ").append(slot).append(" read at ").append(r.getFromAddress())
                   .append(" in ").append(fn == null ? "<none>" : fn.getName()).append('\n');
                Instruction ins = getInstructionContaining(r.getFromAddress());
                for (int k = 0; k < before && ins != null; k++) ins = ins.getPrevious();
                for (int k = 0; k < before + after && ins != null; k++, ins = ins.getNext()) {
                    out.append("  ").append(ins.getAddress()).append("  ").append(ins).append(note(ins)).append('\n');
                }
            }
        }
        Files.writeString(new File(args[0]).toPath(), out.toString());
    }

    private String note(Instruction ins) {
        for (Reference r : ins.getReferencesFrom()) {
            if (r.getReferenceType().isCall()) {
                Function callee = getFunctionAt(r.getToAddress());
                return "   ; call " + (callee == null ? r.getToAddress() : callee.getName());
            }
            Data d = getDataAt(r.getToAddress());
            if (d != null && d.hasStringValue()) return "   ; \"" + d.getValue() + "\"";
        }
        return "";
    }
}
