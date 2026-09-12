import clr
import sys

CECIL_DIR = r"E:\Games\Valheim Server\mods\BepInEx\core"
sys.path.append(CECIL_DIR)
clr.AddReference(CECIL_DIR + r"\Mono.Cecil.dll")
import Mono.Cecil as Cecil
import os
TEMP = os.environ["TEMP"]

QSS_DLL = TEMP + r"\QuickStackStore.messagefix.dll"

# Game assemblies to check references against. Anything referencing types NOT in this
# set (BCL, UnityEngine.*, BepInEx, Harmony, its own bundled YamlDotNet/ServerSync) is
# skipped -- we only care about actual Valheim game API surface.
GAME_ASSEMBLIES = {
    "assembly_valheim": TEMP + r"\qss_refs\assembly_valheim.dll",
    "Assembly-CSharp": TEMP + r"\qss_refs\Assembly-CSharp.dll",
    "assembly_utils": TEMP + r"\qss_refs\assembly_utils.dll",
    "assembly_guiutils": TEMP + r"\qss_refs\assembly_guiutils.dll",
    "gui_framework": TEMP + r"\qss_refs\gui_framework.dll",
}

print("Loading game assemblies...")
game_modules = {name: Cecil.ModuleDefinition.ReadModule(path) for name, path in GAME_ASSEMBLIES.items()}

# Build a lookup: type full name -> (module_name, TypeDefinition), searching all loaded game modules
type_lookup = {}
for mod_name, mod in game_modules.items():
    def walk(types):
        for t in types:
            yield t
            for nt in walk(t.NestedTypes):
                yield nt
    for t in walk(mod.Types):
        # keep first occurrence (assembly_valheim checked first, most authoritative)
        if t.FullName not in type_lookup:
            type_lookup[t.FullName] = (mod_name, t)

print(f"Indexed {len(type_lookup)} game types across {len(game_modules)} assemblies.\n")

qss = Cecil.ModuleDefinition.ReadModule(QSS_DLL)

def walk_qss_types(types):
    for t in types:
        yield t
        for nt in walk_qss_types(t.NestedTypes):
            yield nt

def sig_matches(method_def, param_type_strs):
    if len(method_def.Parameters) != len(param_type_strs):
        return False
    for p, expected in zip(method_def.Parameters, param_type_strs):
        if str(p.ParameterType) != expected:
            return False
    return True

problems = []
checked = 0
skipped_types = set()

for t in walk_qss_types(qss.Types):
    for meth in t.Methods:
        if not meth.HasBody:
            continue
        for instr in meth.Body.Instructions:
            op = instr.Operand
            opname = instr.OpCode.Name

            if opname in ("call", "callvirt", "newobj"):
                if not hasattr(op, "DeclaringType"):
                    continue
                decl = op.DeclaringType
                decl_name = str(decl)
                if decl_name not in type_lookup:
                    continue
                mod_name, type_def = type_lookup[decl_name]
                checked += 1
                method_name = op.Name if opname != "newobj" else ".ctor"
                param_strs = [str(p.ParameterType) for p in op.Parameters]
                candidates = [m for m in type_def.Methods if m.Name == method_name]
                exact = [m for m in candidates if sig_matches(m, param_strs)]
                if not exact:
                    problems.append({
                        "kind": "method",
                        "qss_type": t.FullName,
                        "qss_method": meth.Name,
                        "target_type": decl_name,
                        "target_member": method_name,
                        "expected_params": param_strs,
                        "candidates": [(m.Name, [str(p.ParameterType) for p in m.Parameters]) for m in candidates],
                    })

            elif opname in ("ldfld", "stfld", "ldsfld", "stsfld", "ldflda", "ldsflda"):
                if not hasattr(op, "DeclaringType"):
                    continue
                decl = op.DeclaringType
                decl_name = str(decl)
                if decl_name not in type_lookup:
                    continue
                mod_name, type_def = type_lookup[decl_name]
                checked += 1
                field_name = op.Name
                match = next((f for f in type_def.Fields if f.Name == field_name), None)
                if match is None:
                    problems.append({
                        "kind": "field",
                        "qss_type": t.FullName,
                        "qss_method": meth.Name,
                        "target_type": decl_name,
                        "target_member": field_name,
                    })

print(f"Checked {checked} game-API references.\n")
print(f"=== {len(problems)} PROBLEMS FOUND ===\n")

# Deduplicate by (target_type, target_member, kind) since the same stale call often
# appears in multiple QSS methods
seen = {}
for p in problems:
    key = (p["kind"], p["target_type"], p["target_member"], tuple(p.get("expected_params", [])))
    seen.setdefault(key, []).append(f"{p['qss_type']}.{p['qss_method']}")

for (kind, target_type, target_member, expected_params), locations in seen.items():
    print(f"[{kind}] {target_type}::{target_member}({', '.join(expected_params)})")
    print(f"  referenced from: {', '.join(sorted(set(locations)))}")
    # show what candidates DO exist with that name, if any
    if target_type in type_lookup:
        _, type_def = type_lookup[target_type]
        if kind == "method":
            candidates = [m for m in type_def.Methods if m.Name == target_member]
            for c in candidates:
                print(f"    actual overload: ({', '.join(str(p.ParameterType) for p in c.Parameters)})")
            if not candidates:
                print(f"    ** no method named '{target_member}' exists on {target_type} at all **")
    print()
