// Usage: -postScript ExportStringRefs.java <targets.tsv> <outFile>
// targets.tsv: lines `<hex VA>\t<text>`. Writes `<VA>\t<from>\t<kind>\t<length>\t<bytes hex>` per reference to each VA.
// kind is `LEA` etc. for an instruction reference, `data` for a reference from non-code (pointer tables).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.nio.file.Files;

public class ExportStringRefs extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        StringBuilder out = new StringBuilder();
        for (String line : Files.readAllLines(new File(args[0]).toPath())) {
            String va = line.substring(0, line.indexOf('\t'));
            Address target = toAddr(va);
            for (Reference ref : getReferencesTo(target)) {
                Instruction ins = getInstructionAt(ref.getFromAddress());
                if (ins == null) {
                    out.append(va).append('\t').append(ref.getFromAddress()).append("\tdata\t0\t\n");
                    continue;
                }
                StringBuilder hex = new StringBuilder();
                for (byte b : ins.getBytes()) hex.append(String.format("%02x", b));
                out.append(va).append('\t').append(ins.getAddress()).append('\t').append(ins.getMnemonicString())
                   .append('\t').append(ins.getLength()).append('\t').append(hex).append('\n');
            }
        }
        Files.writeString(new File(args[1]).toPath(), out.toString());
    }
}
