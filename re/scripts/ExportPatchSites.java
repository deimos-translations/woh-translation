// Usage: -postScript ExportPatchSites.java <outFile> guard:<addr>... slot:<addr>...
// guard:<addr>  prints address, length and bytes of the instruction at addr.
// slot:<addr>   for a startup string slot, prints the `LEA RDX,[literal]` that feeds FUN_1420d8090 (address, bytes,
//               literal address, literal text).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.nio.file.Files;

public class ExportPatchSites extends GhidraScript {
    private static String hex(byte[] bytes) {
        StringBuilder sb = new StringBuilder();
        for (byte b : bytes) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        StringBuilder out = new StringBuilder();
        for (int i = 1; i < args.length; i++) {
            String kind = args[i].substring(0, args[i].indexOf(':'));
            Address addr = toAddr(args[i].substring(args[i].indexOf(':') + 1));
            if (kind.equals("guard")) {
                Instruction ins = getInstructionAt(addr);
                out.append("guard\t").append(addr).append('\t').append(ins.getLength()).append('\t')
                   .append(hex(ins.getBytes())).append('\t').append(ins).append('\n');
                continue;
            }
            for (Reference ref : getReferencesTo(addr)) {
                Instruction lea = getInstructionAt(ref.getFromAddress());
                if (lea == null || !lea.getMnemonicString().equals("LEA")) continue;
                // initializer shape: LEA RCX,[slot]; LEA RDX,[literal]; CALL FUN_1420d8090 (either order of the two LEAs)
                Instruction next = lea.getNext();
                Instruction prev = lea.getPrevious();
                for (Instruction cand : new Instruction[] { next, prev }) {
                    if (cand == null || !cand.getMnemonicString().equals("LEA")) continue;
                    if (!cand.getRegister(0).getName().equals("RDX")) continue;
                    for (Reference r : cand.getReferencesFrom()) {
                        Data d = getDataAt(r.getToAddress());
                        out.append("slot\t").append(addr).append('\t').append(cand.getAddress()).append('\t')
                           .append(cand.getLength()).append('\t').append(hex(cand.getBytes())).append('\t')
                           .append(r.getToAddress()).append('\t')
                           .append(d != null && d.hasStringValue() ? d.getValue() : "?").append('\n');
                    }
                }
            }
        }
        Files.writeString(new File(args[0]).toPath(), out.toString());
    }
}
