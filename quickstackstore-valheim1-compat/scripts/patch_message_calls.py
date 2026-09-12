import clr
import sys

CECIL_DIR = r"E:\Games\Valheim Server\mods\BepInEx\core"
sys.path.append(CECIL_DIR)
clr.AddReference(CECIL_DIR + r"\Mono.Cecil.dll")
clr.AddReference(CECIL_DIR + r"\Mono.Cecil.Rocks.dll")

import Mono.Cecil as Cecil
import Mono.Cecil.Cil as Cil
import System
import os
TEMP = os.environ["TEMP"]

SRC_DLL = r"E:\Games\Valheim Server\mods\BepInEx\plugins\Goldenrevolver-Quick_Stack_Store_Sort_Trash_Restock\QuickStackStore.dll.original-1.4.13.bak"
OUT_DLL = TEMP + r"\QuickStackStore.messagefix.dll"

module = Cecil.ModuleDefinition.ReadModule(SRC_DLL)

def find_type(module, full_name):
    def walk(types):
        for t in types:
            yield t
            for nt in walk(t.NestedTypes):
                yield nt
    return next(t for t in walk(module.Types) if t.FullName == full_name)

targets = [
    ("QuickStackStore.QuickStackModule", "DoQuickStack"),
    ("QuickStackStore.QuickStackModule", "ReportQuickStackResult"),
    ("QuickStackStore.StackAllPatch", "ContainerStackAllPatch"),
    ("QuickStackStore.RestockModule", "DoRestock"),
    ("QuickStackStore.RestockModule", "ReportRestockResult"),
    ("QuickStackStore.InventoryGridButtonHandlingPatches", "HandleClickInternal"),
    ("QuickStackStore.TrashModule/TrashItemsPatches", "UpdateItemDrag_Postfix"),
]

new_message_ref = None
total_patched = 0

for type_name, method_name in targets:
    t = find_type(module, type_name)
    method = next(x for x in t.Methods if x.Name == method_name)
    il = method.Body.GetILProcessor()

    # Find all stale 4-arg Character::Message call instructions in this method
    stale_calls = [
        instr for instr in list(method.Body.Instructions)
        if instr.OpCode.Name in ("call", "callvirt")
        and getattr(instr.Operand, "Name", None) == "Message"
        and str(getattr(instr.Operand, "DeclaringType", "")) == "Character"
        and len(instr.Operand.Parameters) == 4
    ]

    if not stale_calls:
        print(f"WARNING: no stale Message call found in {type_name}.{method_name}")
        continue

    if new_message_ref is None:
        # Build the reference once, reusing the existing (proven-good) Character
        # TypeReference and parameter TypeReferences from the first stale call itself --
        # these already resolve fine (the call executes; it's the ARITY that's wrong),
        # so reusing them avoids any cross-assembly import ambiguity.
        old_op = stale_calls[0].Operand
        character_type_ref = old_op.DeclaringType
        message_type_param = old_op.Parameters[0].ParameterType
        string_param = old_op.Parameters[1].ParameterType
        int_param = old_op.Parameters[2].ParameterType
        sprite_param = old_op.Parameters[3].ParameterType
        bool_param = module.TypeSystem.Boolean

        new_message_ref = Cecil.MethodReference("Message", module.TypeSystem.Void, character_type_ref)
        new_message_ref.HasThis = True
        new_message_ref.Parameters.Add(Cecil.ParameterDefinition(message_type_param))
        new_message_ref.Parameters.Add(Cecil.ParameterDefinition(string_param))
        new_message_ref.Parameters.Add(Cecil.ParameterDefinition(int_param))
        new_message_ref.Parameters.Add(Cecil.ParameterDefinition(sprite_param))
        new_message_ref.Parameters.Add(Cecil.ParameterDefinition(bool_param))
        new_message_ref = module.ImportReference(new_message_ref)
        print("Built new Message(5-arg) reference:", new_message_ref.FullName)

    for instr in stale_calls:
        # insert "ldc.i4.0" (false, for the new trailing "log" parameter) right before
        # the call, then retarget the call itself to the 5-arg overload.
        ldc = Cil.Instruction.Create(Cil.OpCodes.Ldc_I4_0)
        il.InsertBefore(instr, ldc)
        instr.Operand = new_message_ref
        total_patched += 1

    print(f"Patched {len(stale_calls)} call(s) in {type_name}.{method_name}")

# --- Fix #2: ZRoutedRpc.Everybody, now an Int64 const with value 0, has no runtime
# storage; the compiled ldsfld instructions must be replaced with a literal push. ---
everybody_targets = [
    ("ServerSync.ConfigSync", "sendZPackage"),
    ("ServerSync.ConfigSync/<>c__DisplayClass34_0`1", "<AddConfigEntry>b__0"),
    ("ServerSync.ConfigSync/<>c__DisplayClass36_0", "<AddCustomValue>b__1"),
]

everybody_patched = 0
for type_name, method_name in everybody_targets:
    t = find_type(module, type_name)
    method = next(x for x in t.Methods if x.Name == method_name)
    stale = [i for i in method.Body.Instructions if i.OpCode.Name == "ldsfld" and getattr(i.Operand, "Name", None) == "Everybody"]
    if not stale:
        print(f"WARNING: no ldsfld Everybody found in {type_name}.{method_name}")
        continue
    for instr in stale:
        instr.OpCode = Cil.OpCodes.Ldc_I8
        instr.Operand = System.Int64(0)
        everybody_patched += 1
    print(f"Patched {len(stale)} ldsfld Everybody in {type_name}.{method_name}")

# --- Fix #3: Inventory.Changed() gained two bool parameters (success=false,
# cheatedStateChanged=false in the current game). Affects QuickStack, Restock,
# StoreTakeAll, Sort, and Trash modules -- essentially all of QSS's core features. ---
changed_new_ref = None
changed_patched = 0

changed_targets = [
    ("QuickStackStore.QuickStackModule", "QuickStackIntoThisContainer"),
    ("QuickStackStore.QuickStackModule", "QuickStackIntoMultipleContainers"),
    ("QuickStackStore.RestockModule", "RestockFromThisContainer"),
    ("QuickStackStore.RestockModule", "RestockFromMultipleContainers"),
    ("QuickStackStore.StoreTakeAllModule", "MoveAllItemsInOrder"),  # has 2 call sites, both handled by the list comprehension below
    ("QuickStackStore.SortModule", "SortInternal"),
    ("QuickStackStore.TrashModule", "QuickTrash"),
]

for type_name, method_name in changed_targets:
    t = find_type(module, type_name)
    method = next(x for x in t.Methods if x.Name == method_name)
    il = method.Body.GetILProcessor()

    stale_calls = [
        instr for instr in list(method.Body.Instructions)
        if instr.OpCode.Name in ("call", "callvirt")
        and getattr(instr.Operand, "Name", None) == "Changed"
        and str(getattr(instr.Operand, "DeclaringType", "")) == "Inventory"
        and len(instr.Operand.Parameters) == 0
    ]

    if not stale_calls:
        print(f"WARNING: no stale Changed() call found in {type_name}.{method_name}")
        continue

    if changed_new_ref is None:
        old_op = stale_calls[0].Operand
        inventory_type_ref = old_op.DeclaringType
        changed_new_ref = Cecil.MethodReference("Changed", module.TypeSystem.Void, inventory_type_ref)
        changed_new_ref.HasThis = True
        changed_new_ref.Parameters.Add(Cecil.ParameterDefinition(module.TypeSystem.Boolean))
        changed_new_ref.Parameters.Add(Cecil.ParameterDefinition(module.TypeSystem.Boolean))
        changed_new_ref = module.ImportReference(changed_new_ref)
        print("Built new Changed(2-arg) reference:", changed_new_ref.FullName)

    for instr in stale_calls:
        ldc1 = Cil.Instruction.Create(Cil.OpCodes.Ldc_I4_0)
        ldc2 = Cil.Instruction.Create(Cil.OpCodes.Ldc_I4_0)
        il.InsertBefore(instr, ldc1)
        il.InsertBefore(instr, ldc2)
        instr.Operand = changed_new_ref
        changed_patched += 1

    print(f"Patched {len(stale_calls)} Changed() call(s) in {type_name}.{method_name}")

# --- Fix #4: InventoryGui.m_splitPanel (a bare Transform) was replaced by
# m_splitDialog (a SplitDialog, which is itself a MonoBehaviour/Component). QSS only
# ever accessed ".gameObject" on the old field, and Component.gameObject is inherited
# identically by SplitDialog, so this is a pure field-reference retarget -- nothing
# else about the call site (Object.Instantiate, etc.) needs to change. ---
t = find_type(module, "QuickStackStore.TrashModule")
method = next(x for x in t.Methods if x.Name == "ShowBaseConfirmDialog")
stale_field_loads = [
    i for i in method.Body.Instructions
    if i.OpCode.Name == "ldfld" and getattr(i.Operand, "Name", None) == "m_splitPanel"
]
if not stale_field_loads:
    print("WARNING: no ldfld m_splitPanel found in TrashModule.ShowBaseConfirmDialog")
else:
    old_field = stale_field_loads[0].Operand
    inventory_gui_type_ref = old_field.DeclaringType
    split_dialog_type_ref = module.ImportReference(find_type(
        Cecil.ModuleDefinition.ReadModule(TEMP + r"\qss_refs\assembly_valheim.dll"),
        "SplitDialog"))
    new_field_ref = Cecil.FieldReference("m_splitDialog", split_dialog_type_ref, inventory_gui_type_ref)
    new_field_ref = module.ImportReference(new_field_ref)
    for instr in stale_field_loads:
        instr.Operand = new_field_ref
    print(f"Patched {len(stale_field_loads)} ldfld m_splitPanel -> m_splitDialog in TrashModule.ShowBaseConfirmDialog")

# --- Fix #5: the grid's click handlers were renamed and re-split. InventoryGrid.UpdateGui
# now subscribes OnRightDown (not OnRightClick) and both OnLeftDown and OnLeftClick:
#
#   OnLeftDown  - resolves the clicked slot, sets m_pressedItem and fires m_onSelected.
#                 This is the handler that actually picks the item up / starts the drag.
#   OnLeftClick - only double-tap-to-equip and touch selection.
#
# QSS's favoriting prefix targeted OnLeftClick, which now runs *after* the pickup has
# already begun. Its own ShouldIgnoreFavoritingClick() bails out whenever
# InventoryGui.m_dragGo is set, so the first click was always ignored (it started the
# drag) and only a second click favorited -- and the pickup leaked through either way.
# Moving the prefix to OnLeftDown makes it run before m_onSelected fires, so returning
# false both performs the favoriting on the first click and suppresses the pickup.
#
# OnRightClick doesn't exist at all any more; its replacement is OnRightDown, so that
# patch is retargeted rather than disabled -- which restores right-click slot favoriting.
# Harmony binds prefix parameters by name, and the vanilla parameter names still match
# (OnLeftDown(clickHandler), OnRightDown(element)), so only the attribute target changes.
t = find_type(module, "QuickStackStore.InventoryGridButtonHandlingPatches")

def retarget_harmony_patch(type_def, method_name, old_target, new_target):
    method = next(x for x in type_def.Methods if x.Name == method_name)
    for ca in method.CustomAttributes:
        if ca.AttributeType.Name != "HarmonyPatch":
            continue
        for idx, arg in enumerate(ca.ConstructorArguments):
            if str(arg.Type) == "System.String" and str(arg.Value) == old_target:
                ca.ConstructorArguments[idx] = Cecil.CustomAttributeArgument(arg.Type, new_target)
                print(f"Retargeted {method_name}: [HarmonyPatch(\"{old_target}\")] -> [HarmonyPatch(\"{new_target}\")]")
                return True
    print(f"WARNING: no [HarmonyPatch(\"{old_target}\")] found on {method_name}")
    return False

retarget_harmony_patch(t, "OnLeftClick", "OnLeftClick", "OnLeftDown")
retarget_harmony_patch(t, "OnRightClick", "OnRightClick", "OnRightDown")

# --- Fix #6: InventoryGrid.Element (a nested class) was replaced by the top-level
# InventoryElement (a MonoBehaviour) and InventoryGrid.UpdateGui was resignatured.
# BorderRenderer -- the class that draws the favorited-slot highlight -- still names the
# old nested type in its postfix parameter, its List<T>::get_Item calls and its
# ldfld m_queued. Mono can't resolve that nested TypeRef while reading BorderRenderer's
# method attributes, which threw BadImageFormatException ("Expected reference type but
# got type kind 17") out of PatchClassProcessor's CONSTRUCTOR -- outside Harmony's own
# try/catch -- aborting QuickStackStore's whole PatchAll() partway through.
#
# InventoryElement carries the same "m_queued" Image field the old type did, so the
# entire class only needs the TypeReference itself repointed. Every usage (parameter
# type, generic instance argument, field and method declaring types) shares that one
# TypeReference object, so mutating it in place retargets all of them at once.
game_module = Cecil.ModuleDefinition.ReadModule(TEMP + r"\qss_refs\assembly_valheim.dll")

element_refs = [r for r in module.GetTypeReferences() if r.FullName == "InventoryGrid/Element"]
print(f"\nFound {len(element_refs)} TypeReference(s) to InventoryGrid/Element")
inventory_grid_ref = next(r for r in module.GetTypeReferences() if r.FullName == "InventoryGrid")
for r in element_refs:
    r.DeclaringType = None
    r.Namespace = ""
    r.Name = "InventoryElement"
    r.Scope = inventory_grid_ref.Scope
    print(f"  retargeted -> {r.FullName} (scope {r.Scope})")

# --- Fix #7: ItemDrop.ItemData.GetTooltip's static overload gained parameters, so
# TooltipRenderer's [HarmonyPatch(nameof(GetTooltip), new[]{...})] argument-type array no
# longer matches any overload. Harmony resolved the target to null and threw
# "Patching exception in method null", which is why favorite/trash markers never appeared
# in item tooltips. Rewrite the declared array to the current overload's parameter list;
# QSS's postfix binds "item" and "crafting" by name, both of which still exist. ---
tooltip_type = find_type(module, "QuickStackStore.TooltipRenderer")
tooltip_method = next(m for m in tooltip_type.Methods if m.Name == "GetTooltip")

item_data_ref = next(r for r in module.GetTypeReferences() if r.FullName == "ItemDrop/ItemData")

new_param_types = [
    item_data_ref,
    module.TypeSystem.Int32,
    module.TypeSystem.Boolean,
    module.TypeSystem.Single,
    module.TypeSystem.Int32,
    module.TypeSystem.Boolean,
]

for ca in tooltip_method.CustomAttributes:
    if ca.AttributeType.Name != "HarmonyPatch":
        continue
    for idx, arg in enumerate(ca.ConstructorArguments):
        if str(arg.Type) != "System.Type[]":
            continue
        old_types = [str(x.Value) for x in arg.Value]
        element_type = arg.Type.GetElementType()
        new_args = System.Array[Cecil.CustomAttributeArgument](
            [Cecil.CustomAttributeArgument(element_type, t) for t in new_param_types]
        )
        ca.ConstructorArguments[idx] = Cecil.CustomAttributeArgument(arg.Type, new_args)
        print(f"\nTooltipRenderer.GetTooltip declared arg types:")
        print(f"  before: {old_types}")
        print(f"  after:  {[str(t) for t in new_param_types]}")

module.Write(OUT_DLL)
print(f"\nTotal Message() call sites patched: {total_patched}")
print(f"Total Everybody field loads patched: {everybody_patched}")
print(f"Total Changed() call sites patched: {changed_patched}")
print("Wrote patched DLL to", OUT_DLL)
