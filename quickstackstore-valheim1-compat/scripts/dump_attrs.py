import clr
import sys

CECIL_DIR = r"E:\Games\Valheim Server\mods\BepInEx\core"
sys.path.append(CECIL_DIR)
clr.AddReference(CECIL_DIR + r"\Mono.Cecil.dll")
import Mono.Cecil as Cecil

QSS_DLL = r"E:\Games\Valheim Server\mods\BepInEx\plugins\Goldenrevolver-Quick_Stack_Store_Sort_Trash_Restock\QuickStackStore.dll"

qss = Cecil.ModuleDefinition.ReadModule(QSS_DLL)

def walk(types):
    for t in types:
        yield t
        for nt in walk(t.NestedTypes):
            yield nt

def fmt(ca):
    args = []
    for a in ca.ConstructorArguments:
        v = a.Value
        if hasattr(v, "Count") and not isinstance(v, str):
            try:
                v = "[" + ", ".join(str(x.Value) for x in v) + "]"
            except Exception:
                v = str(v)
        args.append(f"{a.Type}={v}")
    props = [f"{p.Name}={p.Argument.Value}" for p in ca.Properties]
    return f"{ca.AttributeType.Name}({', '.join(args)})" + (f" props[{', '.join(props)}]" if props else "")

TARGETS = [
    "QuickStackStore.InventoryGridButtonHandlingPatches",
    "QuickStackStore.ButtonRenderer",
]

for t in walk(qss.Types):
    if t.FullName not in TARGETS and "ButtonUIPatch" not in t.FullName and "FavoritingMode" not in t.FullName:
        continue
    print(f"### TYPE {t.FullName}")
    for ca in t.CustomAttributes:
        print("   CLASS-ATTR:", fmt(ca))
    for m in t.Methods:
        cas = [fmt(ca) for ca in m.CustomAttributes if "Harmony" in ca.AttributeType.Name]
        if cas:
            sig = ", ".join(f"{p.ParameterType} {p.Name}" for p in m.Parameters)
            print(f"   METHOD {m.Name}({sig})")
            for c in cas:
                print("      ", c)
    print()
