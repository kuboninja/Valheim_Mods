import clr
import sys

CECIL_DIR = r"E:\Games\Valheim Server\mods\BepInEx\core"
sys.path.append(CECIL_DIR)
clr.AddReference(CECIL_DIR + r"\Mono.Cecil.dll")
import Mono.Cecil as Cecil
import os
TEMP = os.environ["TEMP"]

paths = {
    "assembly_valheim": TEMP + r"\qss_refs\assembly_valheim.dll",
    "assembly_guiutils": TEMP + r"\qss_refs\assembly_guiutils.dll",
    "assembly_utils": TEMP + r"\qss_refs\assembly_utils.dll",
    "Assembly-CSharp": TEMP + r"\qss_refs\Assembly-CSharp.dll",
}

def walk(types):
    for t in types:
        yield t
        for nt in walk(t.NestedTypes):
            yield nt

for name, p in paths.items():
    mod = Cecil.ModuleDefinition.ReadModule(p)
    for t in walk(mod.Types):
        if t.FullName == "InventoryGrid":
            print(f"=== InventoryGrid found in {name} ===")
            print("nested types:")
            for nt in t.NestedTypes:
                print(f"   {nt.FullName}  IsValueType={nt.IsValueType} base={nt.BaseType}")
            print("UpdateGui overloads:")
            for m in t.Methods:
                if m.Name in ("UpdateGui", "UpdateGamepad", "OnLeftClick"):
                    ps = ", ".join(f"{x.ParameterType} {x.Name}" for x in m.Parameters)
                    print(f"   {m.ReturnType} {m.Name}({ps})")

qss = Cecil.ModuleDefinition.ReadModule(r"E:\Games\Valheim Server\mods\BepInEx\plugins\Goldenrevolver-Quick_Stack_Store_Sort_Trash_Restock\QuickStackStore.dll")
print("\n=== QSS TooltipRenderer HarmonyPatch attribute args (expanded) ===")
for t in walk(qss.Types):
    if t.Name != "TooltipRenderer":
        continue
    for m in t.Methods:
        print(f"  method {m.Name}({', '.join(f'{x.ParameterType} {x.Name}' for x in m.Parameters)})")
        for ca in m.CustomAttributes:
            if ca.AttributeType.Name != "HarmonyPatch":
                continue
            for a in ca.ConstructorArguments:
                val = a.Value
                try:
                    items = list(val)
                    print("    array arg:", [str(x.Value) for x in items])
                except TypeError:
                    print("    scalar arg:", val)
