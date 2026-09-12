import clr
import sys

CECIL_DIR = r"E:\Games\Valheim Server\mods\BepInEx\core"
sys.path.append(CECIL_DIR)
clr.AddReference(CECIL_DIR + r"\Mono.Cecil.dll")
import Mono.Cecil as Cecil
import os
TEMP = os.environ["TEMP"]

QSS_DLL = TEMP + r"\QuickStackStore.messagefix.dll"

GAME_ASSEMBLIES = {
    "assembly_valheim": TEMP + r"\qss_refs\assembly_valheim.dll",
    "Assembly-CSharp": TEMP + r"\qss_refs\Assembly-CSharp.dll",
    "assembly_utils": TEMP + r"\qss_refs\assembly_utils.dll",
    "assembly_guiutils": TEMP + r"\qss_refs\assembly_guiutils.dll",
    "gui_framework": TEMP + r"\qss_refs\gui_framework.dll",
}

game_modules = {name: Cecil.ModuleDefinition.ReadModule(path) for name, path in GAME_ASSEMBLIES.items()}

type_lookup = {}
for mod_name, mod in game_modules.items():
    def walk(types):
        for t in types:
            yield t
            for nt in walk(t.NestedTypes):
                yield nt
    for t in walk(mod.Types):
        if t.FullName not in type_lookup:
            type_lookup[t.FullName] = (mod_name, t)

qss = Cecil.ModuleDefinition.ReadModule(QSS_DLL)

def walk_qss_types(types):
    for t in types:
        yield t
        for nt in walk_qss_types(t.NestedTypes):
            yield nt

# For each type, find [HarmonyPatch(typeof(X))] at the class level (sets the "current"
# target type for method-level [HarmonyPatch(nameof(Method))] attributes underneath it),
# then for each method, find [HarmonyPatch("MethodName")] or [HarmonyPatch(typeof(X), "Method")]
results = []

for t in walk_qss_types(qss.Types):
    class_level_type = None
    for ca in t.CustomAttributes:
        if ca.AttributeType.Name == "HarmonyPatch":
            args = ca.ConstructorArguments
            for a in args:
                if str(a.Type) == "System.Type":
                    class_level_type = str(a.Value)

    for meth in t.Methods:
        for ca in meth.CustomAttributes:
            if ca.AttributeType.Name != "HarmonyPatch":
                continue
            args = list(ca.ConstructorArguments)
            target_type = class_level_type
            target_name = None
            for a in args:
                if str(a.Type) == "System.Type":
                    target_type = str(a.Value)
                elif str(a.Type) == "System.String":
                    target_name = str(a.Value)
            if target_type is None or target_name is None:
                continue
            results.append((t.FullName, meth.Name, target_type, target_name))

print(f"Found {len(results)} attribute-based Harmony patch targets.\n")

problems = []
for qss_type, qss_method, target_type, target_name in results:
    if target_type not in type_lookup:
        problems.append((qss_type, qss_method, target_type, target_name, "TYPE NOT FOUND in loaded game assemblies"))
        continue
    mod_name, type_def = type_lookup[target_type]
    candidates = [m for m in type_def.Methods if m.Name == target_name]
    if not candidates:
        problems.append((qss_type, qss_method, target_type, target_name, "METHOD DOES NOT EXIST"))

print(f"=== {len(problems)} PROBLEMS ===\n")
for qss_type, qss_method, target_type, target_name, issue in problems:
    print(f"[{issue}] {target_type}::{target_name}  (patched by {qss_type}.{qss_method})")
