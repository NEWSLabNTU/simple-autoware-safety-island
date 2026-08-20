# Local Zephyr patches

Patches applied on top of the west-managed Zephyr checkout
(`$NROS_ZEPHYR_WORKSPACE/zephyr`, pinned at `v4.4.0`). `west update` resets that
tree, so re-apply from here after one:

    cd "$NROS_ZEPHYR_WORKSPACE/zephyr" && git apply <repo>/patches/zephyr/*.patch

## 0001 — gen_relocate_app: fix source-to-object matching

`zephyr_code_relocate()` resolves a source file to its object with

    filename.split("/")[-2] in obj_file.parent.name

i.e. it assumes the object tree always mirrors the source tree. Two common
layouts break that assumption:

  * sources GENERATED into the build root — the test compares the build
    directory name against `<target>.dir`;
  * targets whose objects CMake flattens — it compares the source's directory
    against `<target>.dir`.

On no match `get_obj_filename()` returned `None` and the caller skipped the file
with `continue`, so the generator wrote an EMPTY linker fragment, printed
nothing, and exited 0. The build then links successfully having relocated
nothing — the failure is invisible unless you check the DTCM/ITCM line of the
region report.

That is what blocked this project: the nano-ros entry translation unit is
generated into the build root, so its ~78 KiB of `.bss` (executor storage plus
the four per-node component buffers) could not be moved into the S32K344's
otherwise-idle 128 KiB DTCM.

The patch:

  * matches both `.o` and `.obj` (the collector gathers both, but the matcher
    hardcoded `.obj`, silently skipping every `.o` toolchain);
  * uses the longest trailing run of shared path components only to
    DISAMBIGUATE between several objects sharing a basename, instead of as a
    precondition — a unique match is now always accepted;
  * warns when a source resolves to no object, and when it resolves ambiguously,
    rather than failing silently.

Upstreamable to Zephyr as-is.
