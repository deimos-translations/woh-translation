// Build-specific addresses found by ResolveHelpers.java, for the other scripts. Reads the file named by the WOH_SYMBOLS environment variable,
// one `"name": ["hex", ...]` or `"name": "hex"` per line. A name missing from the file is an error: no script falls back to a stored address.
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class Symbols {
    private static final Map<String, Set<String>> VALUES = load();

    private static Map<String, Set<String>> load() {
        Map<String, Set<String>> values = new HashMap<>();
        Pattern row = Pattern.compile("\"(\\w+)\":\\s*(.+?),?\\s*$"), hex = Pattern.compile("\"([0-9a-f]+)\"");
        try {
            for (String line : Files.readAllLines(Path.of(System.getenv("WOH_SYMBOLS")))) {
                Matcher m = row.matcher(line);
                if (!m.find()) continue;
                Set<String> set = new HashSet<>();
                Matcher h = hex.matcher(m.group(2));
                while (h.find()) set.add(h.group(1));
                values.put(m.group(1), set);
            }
        } catch (java.io.IOException e) {
            throw new IllegalStateException("cannot read WOH_SYMBOLS", e);
        }
        return values;
    }

    public static Set<String> set(String name) {
        Set<String> value = VALUES.get(name);
        if (value == null) throw new IllegalStateException("no symbol " + name);
        return value;
    }

    public static String text(String name) {
        Set<String> value = set(name);
        if (value.size() != 1) throw new IllegalStateException("symbol " + name + " is not a single address");
        return value.iterator().next();
    }

    public static long addr(String name) {
        return Long.parseLong(text(name), 16);
    }
}
