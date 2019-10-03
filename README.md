GGC (Google Global Cache) Reverse Engineering
=============================================

Also known as `bandaid-xt`.

GGC ISO from https://dl.google.com/ggc/install/ggc-setup-latest.img

Unpack image (ISO then initramfs then squashfs).

`/export/hda3` has all deployment-specific stuff. Amongst a bunch of precompiled RAID and OOB tools you'll find some `.par` (Python ARchive) files.

    q3k@anathema ~/Security/Google/ggc/squash/squashfs-root/export/hda3 $ find . -iname *par
    ./bandaid/tools/csdt.par
    ./bandaid/tools/callhome.par

And also in `/opt`:

    ./opt/installer/setup.par

These are self-executing Python scripts. After the stub you'll find a .zip file, this can then be extracted.

`callhome.par` and `setup.par` will yield bytecode-compiled Python code which can be decompiled using a tool like `uncompyle6`.

Interestingly, `csdt.par` is not precompiled, and thus we can find some rare google3 commented artifacts, like `csdt/google3/__init__.py`.
