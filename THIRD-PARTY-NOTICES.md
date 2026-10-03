# Third-party notices

`DICOM Anonymizer & Sorter` (this repository) is licensed under the MIT
License (see `LICENSE`). It depends on, and the released `.exe`/`.AppImage`
binaries bundle, the third-party components listed below. Each remains under
its own license; this file exists to satisfy their attribution requirements.

## Directly used by `anonymizerbatch.py`

### pydicom — MIT License
Pure-Python library for reading/writing/modifying DICOM files; core of the
anonymization logic.
Copyright (c) 2008-2020 Darcy Mason and pydicom contributors.
https://github.com/pydicom/pydicom

### py7zr — GNU Lesser General Public License v2.1 (LGPL-2.1-or-later)
Used only when anonymizing `.7z` archives (optional, imported on demand).
Copyright (c) 2019-2024 Hiroshi Miura; Copyright (c) 2004-2015 Joachim Bauch;
based on the 7-Zip / LZMA SDK by Igor Pavlov.
https://github.com/miurahr/py7zr

py7zr is used unmodified, as a dynamically-imported Python library (not
statically compiled in), both when run from source and inside the PyInstaller
builds. Its full license text is reproduced below. Its source code is
publicly available at the URL above and on PyPI for the exact version pinned
in `requirements.txt`.

### Python standard library (incl. tkinter) — PSF License
`tkinter` wraps Tcl/Tk, which is distributed under its own permissive
BSD-style license (Tcl/Tk Copyright (c) 1987-2024 the Tcl core team and
contributors). Both the PSF License and the Tcl/Tk license permit
redistribution, including in compiled/frozen form.

## Bundled only inside the Linux AppImage (standalone `dicomsorter` binary)

The AppImage embeds a separately-compiled `dicomsorter` executable (built
against pydicom 2.4.5, its only supported version — see README for why) so
that the optional "run dicomsorter" feature works with zero extra
installation. It pulls in:

### dicomsorter — MIT License
Copyright (c) 2017-2023 Jonathan Suever.
https://github.com/dicomsort/dicomsorter

### fasteners — Apache License 2.0
https://github.com/harlowja/fasteners

### pathos — BSD-3-Clause
Copyright (c) 2004-2016 California Institute of Technology.
Copyright (c) 2016-2026 The Uncertainty Quantification Foundation.
https://github.com/uqfoundation/pathos

### tqdm — MPL-2.0 AND MIT (dual-licensed by file; see upstream LICENCE)
https://github.com/tqdm/tqdm

## Build tooling embedded in the compiled binaries

### PyInstaller — GPL-2.0-or-later, with an explicit Bootloader Exception
Used to freeze `anonymizerbatch.py` (and, for the AppImage, `dicomsorter`)
into standalone executables for the Windows `.exe` and the binaries inside
the Linux `.AppImage`.

> In addition to the permissions in the GNU General Public License, the
> authors give you unlimited permission to link or embed compiled bootloader
> and related files into combinations with other programs, and to distribute
> those combinations without any restriction coming from the use of those
> files.

This exception is what allows the resulting `.exe`/`.AppImage` to be
distributed under this project's own MIT license rather than the GPL. Only
the embedded bootloader/loader is covered by the exception; PyInstaller
itself (the build-time tool) remains GPL-2.0-or-later and is not redistributed
by this project — only used in CI to produce the binaries.
https://github.com/pyinstaller/pyinstaller

---

## Full text: py7zr (LGPL-2.1-or-later)

```
                  GNU LESSER GENERAL PUBLIC LICENSE
                       Version 2.1, February 1999

 Copyright (C) 1991, 1999 Free Software Foundation, Inc.
 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
 Everyone is permitted to copy and distribute verbatim copies
 of this license document, but changing it is not allowed.

[This is the first released version of the Lesser GPL.  It also counts
 as the successor of the GNU Library Public License, version 2, hence
 the version number 2.1.]

Full text: https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
```

## Full text: PyInstaller bootloader exception (GPL-2.0-or-later + exception)

Full text: https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt
