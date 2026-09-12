# Changelog

## 1.0.0

First release.

Repairs **Quick Stack - Store - Sort - Trash - Restock 1.4.13** for Valheim 1.0, tested on
**1.0.12**. Before this patch the mod aborts partway through startup and most of it silently
never activates.

Restored:

- **Quick stack, restock, store-all, take-all, sort and trash** — all were doing nothing;
  `Character.Message` and `Inventory.Changed` had both gained parameters.
- **The sort and quick-stack buttons** in the inventory and container windows, which never
  appeared even though their hotkeys worked.
- **Favouriting with alt+left-click** — previously needed a *double* click and picked the item
  up at the same time. Slot clicks moved to an earlier handler in Valheim 1.0.
- **Favouriting slots with alt+right-click**, which did nothing at all; the handler it used was
  removed from the game.
- **The blue highlight on favourited slots and items.**
- **Favourite and trash markers in item tooltips.**
- **Editing server-synced settings**, which threw as soon as a value changed.
- **The trash confirmation dialog's amounts**, which showed numbers unrelated to what was
  being trashed.
- **Startup crash when EquipmentAndQuickSlots 3.x is installed** (upstream issue #35).

Notes:

- Applies only to the exact stock 1.4.13 binary. Any other build is left untouched and a note
  is written to the log, so a future upstream release will not be modified.
- Keeps a copy of the original DLL beside the patched one and restores it if anything goes
  wrong during patching.
- Install on the dedicated server and on every client.
