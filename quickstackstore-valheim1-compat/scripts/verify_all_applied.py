import clr, sys, re

CECIL_DIR = r"E:\Games\Valheim Server\mods\BepInEx\core"
sys.path.append(CECIL_DIR)
clr.AddReference(CECIL_DIR + r"\Mono.Cecil.dll")
import Mono.Cecil as Cecil
import os
APPDATA = os.environ["APPDATA"]

QSS_DLL = r"E:\Games\Valheim Server\mods\BepInEx\plugins\Goldenrevolver-Quick_Stack_Store_Sort_Trash_Restock\QuickStackStore.dll"
LOG = APPDATA + r"\Thunderstore Mod Manager\DataFolder\Valheim\profiles\Valheim 1.0\BepInEx\LogOutput.log"

qss = Cecil.ModuleDefinition.ReadModule(QSS_DLL)

def walk(types):
    for t in types:
        yield t
        for nt in walk(t.NestedTypes):
            yield nt

HARMONY_METHOD_ATTRS = {"HarmonyPrefix", "HarmonyPostfix", "HarmonyTranspiler", "HarmonyFinalizer", "HarmonyReversePatch"}

declaring = {}
for t in walk(qss.Types):
    patches = []
    for m in t.Methods:
        names = {ca.AttributeType.Name for ca in m.CustomAttributes}
        if names & HARMONY_METHOD_ATTRS:
            patches.append(m.Name)
    if patches:
        declaring[t.FullName] = patches

print(f"QSS types that declare Harmony patches: {len(declaring)}\n")

with open(LOG, "r", encoding="utf-8", errors="replace") as f:
    log = f.read()

# last boot only: everything after the final "Installed resilient" marker
marker = log.rfind("Installed resilient")
if marker != -1:
    log = log[marker:]

applied = {}
for m in re.finditer(r"PatchClassProcessor\.Patch OK for ([\w.+`<>\[\]]+): returned (\d+|<null>)", log):
    applied[m.group(1)] = m.group(2)

problems = []
for type_name, patch_methods in sorted(declaring.items()):
    key = type_name.replace("/", "+")
    result = applied.get(key)
    status = "OK"
    if result is None:
        status = "NEVER PROCESSED"
        problems.append((key, patch_methods, status))
    elif result in ("0", "<null>"):
        status = f"APPLIED NOTHING (returned {result})"
        problems.append((key, patch_methods, status))
    print(f"  [{status:28}] {key}  <- {', '.join(patch_methods)}")

print(f"\n=== {len(problems)} PROBLEM(S) ===")
for key, methods, status in problems:
    print(f"  {status}: {key} ({', '.join(methods)})")
