# QuickStackStore — Valheim 1.0 Compatibility Patch

Lets **Quick Stack - Store - Sort - Trash - Restock 1.4.13** by Goldenrevolver run on
Valheim 1.0 (tested on 1.0.12), until upstream catches up with the game's changed API.

This is an independent compatibility patch, **not** an official Goldenrevolver release.

## It does not redistribute the mod

No part of QuickStackStore ships in this package. Thunderstore installs the official 1.4.13
package as a dependency, and a small BepInEx preloader patch repairs that installed copy
before the game loads it.

## What it fixes

Valheim 1.0 renamed or resignatured a number of things QuickStackStore relies on. Left alone,
the mod fails partway through startup and most of its features silently never register — the
sort button never appears, favoriting does nothing, and quick stacking is dead.

| Symptom | Cause |
| --- | --- |
| Mod does nothing at all; startup error in the log | A type Mono can no longer read aborts the mod's whole Harmony scan |
| Sort/quick-stack buttons missing from inventory | Same abort — the UI classes were never patched |
| Favourite slots show no highlight | `InventoryGrid.Element` became the top-level `InventoryElement` |
| Alt+click favouriting needed a double click, and picked the item up as well | Slot clicks moved from `OnLeftClick` to `OnLeftDown` |
| Alt+right-click slot favouriting did nothing | `OnRightClick` was replaced by `OnRightDown` |
| Quick stack / restock / sort / trash did nothing | `Character.Message` and `Inventory.Changed` both gained parameters |
| Editing a server-synced setting threw | `ZRoutedRpc.Everybody` became a constant with no runtime storage |
| Trash confirmation showed the wrong amounts | Its dialog is cloned from the split dialog, which is now a live component that overwrote the text |
| Favourite/trash markers missing from item tooltips | `ItemData.GetTooltip` gained a parameter |
| Crash on startup with EquipmentAndQuickSlots 3.x | The mod looks for a field that version removed (upstream issue #35) |

No gameplay behaviour, config, keybind, plugin identity or network protocol is changed. Every
fix restores something that already worked before the game update.

## Installing

Install with r2modman or Thunderstore Mod Manager; the dependencies pull in BepInEx and the
official QuickStackStore package automatically.

**Install it on the dedicated server and on every client**, exactly as you would QuickStackStore
itself.

## How it works, and what it touches

On startup the patch checks the installed `QuickStackStore.dll`:

- If it is **not** the exact stock 1.4.13 binary this was built and tested against, it is left
  completely untouched and a note is written to the log. A future upstream release will never
  be silently mangled — if QuickStackStore updates, remove this patch.
- Otherwise the fixes are applied and the DLL is rewritten in place. The stock file is kept
  beside it as `QuickStackStore.dll.qsscompat-original-1.4.13.bak`.

The rewrite is staged to a temporary file and verified as a loadable assembly before it
replaces anything, and re-checked afterwards; if anything is wrong the stock DLL is restored
and the game continues with QuickStackStore unpatched. It runs once — after that it recognises
its own output and does nothing.

Writing to disk is unavoidable here: a preloader can only patch the game's own assemblies in
memory, and plugin DLLs are loaded from disk afterwards.

## Removing it

Uninstall this package and reinstall the official QuickStackStore package for a clean
upstream DLL. Only the active profile copy is ever modified; Thunderstore's package cache is
untouched.

## Credits

Quick Stack - Store - Sort - Trash - Restock is by **Goldenrevolver**, MIT licensed. All credit
for the mod belongs to them. Please report gameplay bugs to this patch, not to Goldenrevolver,
while it is installed.

## Tested against

- Valheim **1.0.12** (network version 40), on a dedicated server and a client
- BepInExPack Valheim 5.4.2350
- Quick Stack - Store - Sort - Trash - Restock 1.4.13
- EquipmentAndQuickSlots 3.1.2 (the compatibility crash above)

The fixes target API changes introduced by the 1.0 release, so they should hold across 1.0.x
hotfixes. If a later patch changes these methods again, the patcher's hash guard means it
simply stops applying rather than breaking anything.
