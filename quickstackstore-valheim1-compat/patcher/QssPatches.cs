using System;
using System.Collections.Generic;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;

namespace QssValheim1Compat
{
    // Every IL repair applied to QuickStackStore 1.4.13 so it runs on Valheim 1.0.
    // Deliberately has no BepInEx dependency so it can be exercised offline against a copy
    // of the stock DLL and diffed against a known-good output.
    public static class QssPatches
    {
        public static void Apply(ModuleDefinition module, Action<string> log)
        {
            FixCharacterMessage(module, log);
            FixZRoutedRpcEverybody(module, log);
            FixInventoryChanged(module, log);
            FixSplitPanelField(module, log);
            FixClickHandlerTargets(module, log);
            FixInventoryGridElement(module, log);
            FixTooltipPatchSignature(module, log);
            FixHasRandyPlugin(module, log);
            FixTrashDialogSplitDialogClone(module, log);
        }

        // ---------- helpers ----------

        private static IEnumerable<TypeDefinition> AllTypes(ModuleDefinition module)
        {
            IEnumerable<TypeDefinition> Walk(TypeDefinition t)
            {
                yield return t;
                foreach (var n in t.NestedTypes)
                    foreach (var x in Walk(n))
                        yield return x;
            }

            // module.Types is top-level only; ILRepack-merged closures live in nested types.
            return module.Types.SelectMany(Walk);
        }

        private static TypeDefinition FindType(ModuleDefinition module, string fullName)
        {
            var t = AllTypes(module).FirstOrDefault(x => x.FullName == fullName);
            if (t == null) throw new InvalidOperationException($"type not found: {fullName}");
            return t;
        }

        private static MethodDefinition FindMethod(TypeDefinition type, string name)
        {
            var m = type.Methods.FirstOrDefault(x => x.Name == name);
            if (m == null) throw new InvalidOperationException($"method not found: {type.FullName}.{name}");
            return m;
        }

        private static bool IsCall(Instruction i) => i.OpCode == OpCodes.Call || i.OpCode == OpCodes.Callvirt;

        // ---------- fix 1: Character.Message gained a trailing "bool log" ----------

        private static readonly string[][] MessageTargets =
        {
            new[] { "QuickStackStore.QuickStackModule", "DoQuickStack" },
            new[] { "QuickStackStore.QuickStackModule", "ReportQuickStackResult" },
            new[] { "QuickStackStore.StackAllPatch", "ContainerStackAllPatch" },
            new[] { "QuickStackStore.RestockModule", "DoRestock" },
            new[] { "QuickStackStore.RestockModule", "ReportRestockResult" },
            new[] { "QuickStackStore.InventoryGridButtonHandlingPatches", "HandleClickInternal" },
            new[] { "QuickStackStore.TrashModule/TrashItemsPatches", "UpdateItemDrag_Postfix" },
        };

        private static void FixCharacterMessage(ModuleDefinition module, Action<string> log)
        {
            MethodReference replacement = null;
            var count = 0;

            foreach (var target in MessageTargets)
            {
                var method = FindMethod(FindType(module, target[0]), target[1]);
                var il = method.Body.GetILProcessor();

                var stale = method.Body.Instructions
                    .Where(i => IsCall(i) && i.Operand is MethodReference mr
                                && mr.Name == "Message"
                                && mr.DeclaringType.FullName == "Character"
                                && mr.Parameters.Count == 4)
                    .ToList();

                if (stale.Count == 0)
                    throw new InvalidOperationException($"no stale Character.Message call in {target[0]}.{target[1]}");

                if (replacement == null)
                {
                    // Reuse the existing (correctly scoped) parameter type references from the
                    // stale call itself; only the arity is wrong, not the types.
                    var old = (MethodReference)stale[0].Operand;
                    var built = new MethodReference("Message", module.TypeSystem.Void, old.DeclaringType) { HasThis = true };
                    foreach (var p in old.Parameters) built.Parameters.Add(new ParameterDefinition(p.ParameterType));
                    built.Parameters.Add(new ParameterDefinition(module.TypeSystem.Boolean));
                    replacement = module.ImportReference(built);
                }

                foreach (var ins in stale)
                {
                    il.InsertBefore(ins, Instruction.Create(OpCodes.Ldc_I4_0)); // log: false
                    ins.Operand = replacement;
                    count++;
                }
            }

            log($"Character.Message: retargeted {count} call site(s) to the 5-arg overload");
        }

        // ---------- fix 2: ZRoutedRpc.Everybody is now a const with no runtime storage ----------

        private static readonly string[][] EverybodyTargets =
        {
            new[] { "ServerSync.ConfigSync", "sendZPackage" },
            new[] { "ServerSync.ConfigSync/<>c__DisplayClass34_0`1", "<AddConfigEntry>b__0" },
            new[] { "ServerSync.ConfigSync/<>c__DisplayClass36_0", "<AddCustomValue>b__1" },
        };

        private static void FixZRoutedRpcEverybody(ModuleDefinition module, Action<string> log)
        {
            var count = 0;
            foreach (var target in EverybodyTargets)
            {
                var method = FindMethod(FindType(module, target[0]), target[1]);
                var stale = method.Body.Instructions
                    .Where(i => i.OpCode == OpCodes.Ldsfld && i.Operand is FieldReference f && f.Name == "Everybody")
                    .ToList();

                if (stale.Count == 0)
                    throw new InvalidOperationException($"no ldsfld Everybody in {target[0]}.{target[1]}");

                foreach (var ins in stale)
                {
                    ins.OpCode = OpCodes.Ldc_I8;
                    ins.Operand = 0L;
                    count++;
                }
            }

            log($"ZRoutedRpc.Everybody: replaced {count} field load(s) with the literal 0");
        }

        // ---------- fix 3: Inventory.Changed() gained (bool, bool) ----------

        private static readonly string[][] ChangedTargets =
        {
            new[] { "QuickStackStore.QuickStackModule", "QuickStackIntoThisContainer" },
            new[] { "QuickStackStore.QuickStackModule", "QuickStackIntoMultipleContainers" },
            new[] { "QuickStackStore.RestockModule", "RestockFromThisContainer" },
            new[] { "QuickStackStore.RestockModule", "RestockFromMultipleContainers" },
            new[] { "QuickStackStore.StoreTakeAllModule", "MoveAllItemsInOrder" },
            new[] { "QuickStackStore.SortModule", "SortInternal" },
            new[] { "QuickStackStore.TrashModule", "QuickTrash" },
        };

        private static void FixInventoryChanged(ModuleDefinition module, Action<string> log)
        {
            MethodReference replacement = null;
            var count = 0;

            foreach (var target in ChangedTargets)
            {
                var method = FindMethod(FindType(module, target[0]), target[1]);
                var il = method.Body.GetILProcessor();

                var stale = method.Body.Instructions
                    .Where(i => IsCall(i) && i.Operand is MethodReference mr
                                && mr.Name == "Changed"
                                && mr.DeclaringType.FullName == "Inventory"
                                && mr.Parameters.Count == 0)
                    .ToList();

                if (stale.Count == 0)
                    throw new InvalidOperationException($"no stale Inventory.Changed() call in {target[0]}.{target[1]}");

                if (replacement == null)
                {
                    var old = (MethodReference)stale[0].Operand;
                    var built = new MethodReference("Changed", module.TypeSystem.Void, old.DeclaringType) { HasThis = true };
                    built.Parameters.Add(new ParameterDefinition(module.TypeSystem.Boolean)); // success
                    built.Parameters.Add(new ParameterDefinition(module.TypeSystem.Boolean)); // cheatedStateChanged
                    replacement = module.ImportReference(built);
                }

                foreach (var ins in stale)
                {
                    il.InsertBefore(ins, Instruction.Create(OpCodes.Ldc_I4_0));
                    il.InsertBefore(ins, Instruction.Create(OpCodes.Ldc_I4_0));
                    ins.Operand = replacement;
                    count++;
                }
            }

            log($"Inventory.Changed: retargeted {count} call site(s) to the 2-arg overload");
        }

        // ---------- fix 4: InventoryGui.m_splitPanel (Transform) -> m_splitDialog (SplitDialog) ----------

        private static TypeReference SplitDialogRef(ModuleDefinition module)
        {
            var inventoryGui = module.GetTypeReferences().First(r => r.FullName == "InventoryGui");
            return module.ImportReference(new TypeReference("", "SplitDialog", module, inventoryGui.Scope));
        }

        private static void FixSplitPanelField(ModuleDefinition module, Action<string> log)
        {
            var method = FindMethod(FindType(module, "QuickStackStore.TrashModule"), "ShowBaseConfirmDialog");
            var stale = method.Body.Instructions
                .Where(i => i.OpCode == OpCodes.Ldfld && i.Operand is FieldReference f && f.Name == "m_splitPanel")
                .ToList();

            if (stale.Count == 0)
                throw new InvalidOperationException("no ldfld m_splitPanel in TrashModule.ShowBaseConfirmDialog");

            // QSS only ever reads .gameObject off this field, and SplitDialog is a Component,
            // so the access shape is unchanged -- only the field reference needs repointing.
            var splitDialog = SplitDialogRef(module);
            foreach (var ins in stale)
            {
                var old = (FieldReference)ins.Operand;
                ins.Operand = module.ImportReference(new FieldReference("m_splitDialog", splitDialog, old.DeclaringType));
            }

            log($"InventoryGui.m_splitPanel: retargeted {stale.Count} field load(s) to m_splitDialog");
        }

        // ---------- fix 5: grid click handlers were renamed and re-split ----------

        private static void FixClickHandlerTargets(ModuleDefinition module, Action<string> log)
        {
            var type = FindType(module, "QuickStackStore.InventoryGridButtonHandlingPatches");

            // OnLeftDown is what sets m_pressedItem and fires m_onSelected -- the pickup. Patching
            // OnLeftClick ran after the drag had already started, and QSS's own
            // ShouldIgnoreFavoritingClick bails whenever InventoryGui.m_dragGo is set, so the first
            // click was always swallowed. OnRightClick no longer exists at all; OnRightDown replaced it.
            RetargetHarmonyPatch(type, "OnLeftClick", "OnLeftClick", "OnLeftDown", log);
            RetargetHarmonyPatch(type, "OnRightClick", "OnRightClick", "OnRightDown", log);
        }

        private static void RetargetHarmonyPatch(TypeDefinition type, string patchMethod, string oldTarget, string newTarget, Action<string> log)
        {
            var method = FindMethod(type, patchMethod);
            foreach (var attr in method.CustomAttributes.Where(a => a.AttributeType.Name == "HarmonyPatch"))
            {
                for (var i = 0; i < attr.ConstructorArguments.Count; i++)
                {
                    var arg = attr.ConstructorArguments[i];
                    if (arg.Type.FullName != "System.String" || (string)arg.Value != oldTarget) continue;
                    attr.ConstructorArguments[i] = new CustomAttributeArgument(arg.Type, newTarget);
                    log($"{patchMethod}: [HarmonyPatch(\"{oldTarget}\")] -> [HarmonyPatch(\"{newTarget}\")]");
                    return;
                }
            }

            throw new InvalidOperationException($"no [HarmonyPatch(\"{oldTarget}\")] on {patchMethod}");
        }

        // ---------- fix 6: InventoryGrid.Element -> top-level InventoryElement ----------

        private static void FixInventoryGridElement(ModuleDefinition module, Action<string> log)
        {
            var elementRef = module.GetTypeReferences().FirstOrDefault(r => r.FullName == "InventoryGrid/Element");
            if (elementRef == null)
                throw new InvalidOperationException("no TypeReference to InventoryGrid/Element");

            // Mono cannot resolve this dead nested type while reading BorderRenderer's method
            // attributes, which throws BadImageFormatException out of PatchClassProcessor's
            // constructor -- outside Harmony's try/catch -- aborting the whole PatchAll().
            // InventoryElement carries the same m_queued Image field, and every usage (parameter,
            // generic argument, field and method declaring types) shares this one TypeReference,
            // so repointing it in place retargets all of them.
            var grid = module.GetTypeReferences().First(r => r.FullName == "InventoryGrid");
            elementRef.DeclaringType = null;
            elementRef.Namespace = "";
            elementRef.Name = "InventoryElement";
            elementRef.Scope = grid.Scope;

            log("InventoryGrid/Element: repointed to top-level InventoryElement");
        }

        // ---------- fix 7: ItemData.GetTooltip gained a trailing "bool appending" ----------

        private static void FixTooltipPatchSignature(ModuleDefinition module, Action<string> log)
        {
            var method = FindMethod(FindType(module, "QuickStackStore.TooltipRenderer"), "GetTooltip");
            var itemData = module.GetTypeReferences().First(r => r.FullName == "ItemDrop/ItemData");

            var current = new TypeReference[]
            {
                itemData,
                module.TypeSystem.Int32,     // qualityLevel
                module.TypeSystem.Boolean,   // crafting
                module.TypeSystem.Single,    // worldLevel
                module.TypeSystem.Int32,     // stackOverride
                module.TypeSystem.Boolean,   // appending  <- new
            };

            foreach (var attr in method.CustomAttributes.Where(a => a.AttributeType.Name == "HarmonyPatch"))
            {
                for (var i = 0; i < attr.ConstructorArguments.Count; i++)
                {
                    var arg = attr.ConstructorArguments[i];
                    if (arg.Type.FullName != "System.Type[]") continue;

                    var elementType = arg.Type.GetElementType();
                    var rebuilt = current.Select(t => new CustomAttributeArgument(elementType, t)).ToArray();
                    attr.ConstructorArguments[i] = new CustomAttributeArgument(arg.Type, rebuilt);
                    log("TooltipRenderer.GetTooltip: declared argument types updated to the 6-parameter overload");
                    return;
                }
            }

            throw new InvalidOperationException("no Type[] argument on TooltipRenderer.GetTooltip's [HarmonyPatch]");
        }

        // ---------- fix 8: HasRandyPlugin's unguarded .First() ----------

        private static void FixHasRandyPlugin(ModuleDefinition module, Action<string> log)
        {
            var method = FindMethod(FindType(module, "QuickStackStore.CompatibilitySupport"), "HasRandyPlugin");

            // Reuse a System.Exception reference already scoped to this module.
            var catchType = FindType(module, "QuickStackStore.QSSConfig").Methods
                .Where(m => m.HasBody)
                .SelectMany(m => m.Body.ExceptionHandlers)
                .Select(h => h.CatchType)
                .First(c => c != null && c.FullName == "System.Exception");

            // The method sets its result local to EnabledWithQuickSlots *before* this block, and
            // the code after it degrades correctly when RandyQuickSlotsEnabled stays null, so
            // catching and falling through returns exactly what the mod would have returned.
            var store = method.Body.Instructions.First(i =>
                i.OpCode == OpCodes.Stsfld && i.Operand is FieldReference f && f.Name == "RandyQuickSlotsEnabled");
            var tryLast = store.Next;      // trailing nop of the if-body
            var landing = tryLast.Next;    // nop the assembly-null-check already branches to
            var skip = method.Body.Instructions.First(i =>
                (i.OpCode == OpCodes.Brfalse || i.OpCode == OpCodes.Brfalse_S) && ReferenceEquals(i.Operand, landing));
            var tryStart = skip.Next;

            var il = method.Body.GetILProcessor();
            var leaveTry = Instruction.Create(OpCodes.Leave, landing);
            var handlerPop = Instruction.Create(OpCodes.Pop);
            var leaveHandler = Instruction.Create(OpCodes.Leave, landing);
            il.InsertAfter(tryLast, leaveTry);
            il.InsertAfter(leaveTry, handlerPop);
            il.InsertAfter(handlerPop, leaveHandler);

            method.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Catch)
            {
                TryStart = tryStart,
                TryEnd = handlerPop,        // exclusive
                HandlerStart = handlerPop,
                HandlerEnd = landing,       // exclusive
                CatchType = catchType,
            });

            log("HasRandyPlugin: reflection block wrapped in catch(Exception), falls through to EnabledWithQuickSlots");
        }

        // ---------- fix 9: the cloned SplitDialog overwrites the trash confirm amount ----------

        private static void FixTrashDialogSplitDialogClone(ModuleDefinition module, Action<string> log)
        {
            var method = FindMethod(FindType(module, "QuickStackStore.TrashModule"), "ShowBaseConfirmDialog");
            var body = method.Body;
            var il = body.GetILProcessor();

            var store = body.Instructions.First(i =>
                i.OpCode == OpCodes.Stsfld && i.Operand is FieldReference f && f.Name == "dialog");

            // Must be GameObject::get_transform -- the value pushed is a GameObject, and GameObject
            // does not derive from Component (both derive from Object), so the Component overload
            // would be type-unsafe IL. Both references already exist in this method.
            var getTransform = (MethodReference)body.Instructions
                .First(i => i.Operand is MethodReference m
                            && m.Name == "get_transform"
                            && m.DeclaringType.FullName == "UnityEngine.GameObject").Operand;

            var getComponent = (MethodReference)body.Instructions
                .First(i => i.Operand is MethodReference m && m.Name == "GetComponent").Operand;

            var setEnabled = (MethodReference)AllTypes(module)
                .SelectMany(t => t.Methods)
                .Where(m => m.HasBody)
                .SelectMany(m => m.Body.Instructions)
                .First(i => i.Operand is MethodReference m
                            && m.Name == "set_enabled"
                            && m.DeclaringType.FullName == "UnityEngine.Behaviour").Operand;

            var splitDialog = SplitDialogRef(module);
            var genericGetComponent = new GenericInstanceMethod(getComponent.GetElementMethod());
            genericGetComponent.GenericArguments.Add(splitDialog);

            var local = new VariableDefinition(splitDialog);
            body.Variables.Add(local);

            // enabled = false rather than Destroy: Destroy is deferred to end of frame, so OnEnable
            // would still fire on SetActive(true) and overwrite the text anyway. Unity does not call
            // OnEnable for a disabled Behaviour when its GameObject is activated.
            var skipTarget = store.Next;
            var sequence = new[]
            {
                Instruction.Create(OpCodes.Ldsfld, (FieldReference)store.Operand),
                Instruction.Create(OpCodes.Callvirt, getTransform),
                Instruction.Create(OpCodes.Call, genericGetComponent),
                Instruction.Create(OpCodes.Stloc, local),
                Instruction.Create(OpCodes.Ldloc, local),
                Instruction.Create(OpCodes.Brfalse, skipTarget),
                Instruction.Create(OpCodes.Ldloc, local),
                Instruction.Create(OpCodes.Ldc_I4_0),
                Instruction.Create(OpCodes.Callvirt, setEnabled),
            };

            var cursor = store;
            foreach (var ins in sequence)
            {
                il.InsertAfter(cursor, ins);
                cursor = ins;
            }

            log("TrashModule.ShowBaseConfirmDialog: cloned SplitDialog component disabled before SetActive");
        }
    }
}
