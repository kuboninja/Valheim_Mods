import clr
import sys

CECIL_DIR = r"E:\Games\Valheim Server\mods\BepInEx\core"
sys.path.append(CECIL_DIR)
clr.AddReference(CECIL_DIR + r"\Mono.Cecil.dll")
import Mono.Cecil as Cecil

qss = Cecil.ModuleDefinition.ReadModule(r"E:\Games\Valheim Server\mods\BepInEx\plugins\Goldenrevolver-Quick_Stack_Store_Sort_Trash_Restock\QuickStackStore.dll")

def walk(types):
    for t in types:
        yield t
        for nt in walk(t.NestedTypes):
            yield nt

INTEREST = ("UserConfig", "FavoritingMode", "BorderRenderer", "FavoriteConfig")

for t in walk(qss.Types):
    if t.Name not in INTEREST:
        continue
    print(f"########## {t.FullName} (base={t.BaseType})")
    for f in t.Fields:
        print(f"   FIELD {'static ' if f.IsStatic else ''}{f.FieldType} {f.Name}")
    for m in t.Methods:
        ps = ", ".join(f"{x.ParameterType} {x.Name}" for x in m.Parameters)
        print(f"   METH  {'static ' if m.IsStatic else ''}{m.ReturnType} {m.Name}({ps})")
    print()

print("########## BorderRenderer.UpdateGui IL ##########")
br = next(t for t in walk(qss.Types) if t.Name == "BorderRenderer")
for m in br.Methods:
    print(f"--- {m.Name} ---")
    if m.HasBody:
        for i in m.Body.Instructions:
            print("   ", i)
    print()

print("########## TooltipRenderer attribute types ##########")
tr = next(t for t in walk(qss.Types) if t.Name == "TooltipRenderer")
for m in tr.Methods:
    for ca in m.CustomAttributes:
        if ca.AttributeType.Name != "HarmonyPatch":
            continue
        for a in ca.ConstructorArguments:
            if str(a.Type) == "System.Type[]":
                print("   declared arg types:", [str(x.Value) for x in a.Value])
