# DICOM Anonymizer & Sorter v3.0

**[English](#english) · [Español](#español)**

---

## English

Lightweight, cross-platform desktop app for **minimal and safe**
anonymization of DICOM images. It specifically protects the integrity of
complex 4D series (fMRI, DWI) by preserving UIDs, geometry, and temporal tags
intact, so medical viewers (Weasis, etc.) don't fragment the series.

### 🌐 Language

The interface is available in **Spanish** and **English**, selectable from
the **Language** menu in the top menu bar. Switching requires a restart
(confirmation is asked); the preference is saved to
`~/.dicom_anonymizer_lang.json` and remembered on the next launch. The
**Help** menu includes **About** and **Help** with usage instructions.

### 🚀 Features

* **Minimal, defensive anonymization:** by default only overwrites
  `PatientName` and `PatientID`. You can optionally enable ~30 additional
  fields (birth date, institution, physicians, study dates, etc.) from the
  **Optional fields** tab — useful to meet requirements of NIH-funded
  repositories (NDA, FITBIR, OpenNeuro). All off by default.
* **4D integrity protection:** UIDs, geometry, and ordering/temporal tags
  (SeriesInstanceUID, ImagePositionPatient, AcquisitionNumber, etc.) are
  never touched.
* **Multi-core parallel processing:** uses `ProcessPoolExecutor` to avoid
  the GIL bottleneck when parsing with pydicom.
* **Atomic writes:** saves to `.part` first and renames, avoiding truncated
  DICOM files.
* **Archive support:** accepts folders or `.zip`, `.7z`, `.tar`,
  `.tar.gz`/`.tgz`, `.tar.bz2`/`.tbz2`, `.tar.xz`/`.txz` files as input.
* **Batch mode:** processes several subjects in series, each with its own
  anonymization code.
* **Optional `dicomsorter`:** optional integration with the external
  `dicomsorter` tool (off by default since it can fragment 4D series). It's
  bundled inside the Linux AppImage — zero extra installation needed.

---

### 📋 Requirements

* Python 3.9 or newer (tested with 3.12).
* **Tkinter** (included in the standard Python install on Windows/macOS; on
  Linux it may require a system package — see below).

#### Installing Tkinter on Linux (if missing)

```bash
# Debian / Ubuntu / Pop!_OS
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter

# Arch
sudo pacman -S tk
```

---

### 📦 Installation

```bash
git clone https://github.com/pabloreyesg/dicom_anonymizer_batch.git
cd dicom_anonymizer_batch

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### ▶️ Usage

```bash
python anonymizerbatch.py
```

This opens the GUI with four tabs:

1. **Main** — anonymizes a folder or archive into an output directory.
2. **Batch** — processes several subjects in series (each with its own
   code, saved to `<root output>/<code>`).
3. **Optional fields** — checkboxes grouped by category (patient
   identification, institution/medical staff, equipment/study, dates) to
   clear additional DICOM fields beyond `PatientName`/`PatientID`. **Off by
   default**; enable them only if your study requires it (based on the
   DICOM PS3.15 Annex E basic confidentiality profile and the HIPAA Safe
   Harbor identifiers). They never touch UIDs, geometry, or temporal tags —
   those stay protected by `PROTECTED_KEYWORDS` without exception, even if
   accidentally selected. Applies to both Main and Batch mode.
4. **Log** — real-time console + a diagnostics button (checks
   `pydicom`/`py7zr` versions and the interpreter in use).

#### Optional `dicomsorter` support

The "Run dicomsorter" checkbox invokes the external `dicomsorter` command via
`PATH`. **It's incompatible with pydicom ≥ 3**: its code does
`from pydicom.dicomdir import DicomDir`, and that module was removed in
pydicom 3.0 (confirmed in the official release notes). `dicomsorter` declares
`pydicom>=2.3.0` with no upper bound, so `pip` installs it without
complaining in the same environment as `pydicom>=3` — but it fails at
runtime with `ModuleNotFoundError: No module named 'pydicom.dicomdir'`. That's
why it requires a **separate Python environment** with `pydicom 2.4.5` (the
latest 2.x release):

```bash
python3 -m venv venv-dicomsorter
venv-dicomsorter/bin/pip install -r requirements-dicomsorter.txt

# Expose the binary on PATH without mixing environments:
mkdir -p ~/.local/bin
ln -sf "$(pwd)/venv-dicomsorter/bin/dicomsorter" ~/.local/bin/dicomsorter

# Verify:
dicomsorter --version   # → dicomsorter 0.1.0a8
```

(`~/.local/bin` must be on your `$PATH`; on most distros it already is.)

If you don't need to reorganize files, leave the checkbox off (that's the
default, and it avoids fragmenting 4D series).

---

### 🐧 Building a self-contained AppImage (Linux)

The AppImage packages **two independent binaries** built with PyInstaller
(each with its own embedded Python and its own pydicom version, no
conflict): `DicomAnonymizer` (pydicom 3.x) and `dicomsorter` (pydicom 2.4.5).
The result is a single `.AppImage` file that requires no Python, pip, or any
system package on the target machine — not even for the "Run dicomsorter"
option.

#### Option A — Local build

```bash
# 1) Build DicomAnonymizer (environment with pydicom 3.x)
python3 -m venv venv
venv/bin/pip install -r requirements.txt pyinstaller
venv/bin/pyinstaller --onefile --name DicomAnonymizer \
  --distpath dist-main --workpath /tmp/build-main --specpath /tmp/build-main \
  anonymizerbatch.py

# 2) Build dicomsorter (isolated environment with pydicom 2.4.5)
python3 -m venv venv-dicomsorter
venv-dicomsorter/bin/pip install -r requirements-dicomsorter.txt pyinstaller
venv-dicomsorter/bin/pyinstaller --onefile --name dicomsorter \
  --distpath dist-dicomsorter --workpath /tmp/build-dicomsorter --specpath /tmp/build-dicomsorter \
  packaging/dicomsorter_entry.py

# 3) Assemble the AppDir
mkdir -p AppDir/usr/bin AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/256x256/apps
cp dist-main/DicomAnonymizer dist-dicomsorter/dicomsorter AppDir/usr/bin/
chmod +x AppDir/usr/bin/*
cp packaging/AppRun AppDir/AppRun && chmod +x AppDir/AppRun
cp packaging/dicomanonymizer.desktop AppDir/dicomanonymizer.desktop
cp packaging/dicomanonymizer.desktop AppDir/usr/share/applications/

# icon (requires ImageMagick: sudo apt install imagemagick)
convert -size 256x256 xc:"#1e3a5f" -fill white -gravity center \
  -pointsize 100 -font DejaVu-Sans-Bold -annotate +0-20 "Dx" \
  -fill "#4fc3f7" -pointsize 24 -annotate +0+60 "ANONYMIZER" \
  AppDir/dicomanonymizer.png
cp AppDir/dicomanonymizer.png AppDir/usr/share/icons/hicolor/256x256/apps/

# 4) Package
wget -q -O /tmp/appimagetool.AppImage \
  https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x /tmp/appimagetool.AppImage
ARCH=x86_64 /tmp/appimagetool.AppImage AppDir DicomAnonymizer-x86_64.AppImage
```

Result: `DicomAnonymizer-x86_64.AppImage`. To distribute it, the end user
just needs:

```bash
chmod +x DicomAnonymizer-x86_64.AppImage
./DicomAnonymizer-x86_64.AppImage
```

#### Option B — Automated build on GitHub Actions

This repo includes `.github/workflows/build-linux-appimage.yml`, which does
all of the above on an `ubuntu-22.04` runner whenever:

* a `v*` tag is pushed → it also attaches the AppImage to a GitHub Release, or
* it's triggered manually (`workflow_dispatch`):

```bash
gh workflow run build-linux-appimage.yml
gh run list --workflow=build-linux-appimage.yml --limit 1
gh run download <run-id> -n DicomAnonymizer-linux-appimage
```

---

### 🏗️ Building a self-contained `.exe` (Windows)

The `.exe` is built with [PyInstaller](https://pyinstaller.org/), which
packages Python + dependencies + the script into a single file.
**PyInstaller compiles for the OS it runs on** — to get a native Windows
`.exe` you need to run the build on Windows (a real machine, a VM, or CI).
There are two ways to do it:

#### Option A — Local build on a Windows machine

```powershell
git clone https://github.com/pabloreyesg/dicom_anonymizer_batch.git
cd dicom_anonymizer_batch

python -m venv venv
venv\Scripts\activate

pip install -r requirements-build.txt

pyinstaller --onefile --windowed --name DicomAnonymizer anonymizerbatch.py
```

The executable lands in `dist\DicomAnonymizer.exe`. It's self-contained: no
Python install needed on the target machine.

Useful flags:
* `--onefile` → a single `.exe` (starts a bit slower since it unpacks to a
  temp dir, but is easier to distribute).
* `--windowed` → no visible console (the app is a Tkinter GUI).
* `--icon=icon.ico` → optional, to give it a custom icon.

#### Option B — Automated build on GitHub Actions (no Windows needed)

This repo includes `.github/workflows/build-windows-exe.yml`, which compiles
the `.exe` on a `windows-latest` runner whenever:

* a `v*` tag is pushed (e.g. `v1.0.0`) → it also attaches the `.exe` to a
  GitHub Release automatically, or
* it's triggered manually from the repo's **Actions** tab
  (`workflow_dispatch`).

To trigger it manually:

```bash
gh workflow run build-windows-exe.yml
# wait for it to finish, then download the artifact:
gh run list --workflow=build-windows-exe.yml --limit 1
gh run download <run-id> -n DicomAnonymizer-windows-exe
```

Or just create and push a tag to publish a release with the `.exe` attached:

```bash
git tag v1.0.0
git push origin v1.0.0
```

---

### ⚠️ Security notes

* Archive extraction (`.zip`, `.7z`, `.tar.*`) validates paths to prevent
  *path traversal* (entries with `../` or absolute paths are rejected).
* The anonymizer **never** modifies UIDs, geometry, or temporal tags — see
  `PROTECTED_KEYWORDS` in `anonymizerbatch.py` for the full list.

---

### 📜 License

This project is released under the **MIT License** (see `LICENSE`).

It uses and/or bundles inside the compiled binaries (`.exe`/`.AppImage`)
third-party libraries under their own licenses (MIT, BSD-3-Clause,
Apache-2.0, LGPL-2.1, PSF, and GPL-2.0-or-later with a bootloader
exception) — full details, with the copyright notices each one requires,
are in [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).

---
---

## Español

Aplicación de escritorio ligera y multiplataforma para anonimización **mínima y
segura** de imágenes DICOM. Protege específicamente la integridad de series 4D
complejas (fMRI, DWI) preservando intactos UIDs, geometría y tags temporales,
para evitar que los visores médicos (Weasis, etc.) fragmenten las series.

### 🌐 Idioma

La interfaz está disponible en **español** e **inglés**, seleccionable desde el
menú **Idioma** en la barra superior. El cambio requiere reiniciar la app (se
pide confirmación); la preferencia se guarda en `~/.dicom_anonymizer_lang.json`
y se recuerda en el siguiente arranque. El menú **Ayuda** incluye **Acerca de**
y **Ayuda** con instrucciones de uso.

### 🚀 Características

* **Anonimización defensiva mínima:** por defecto solo sobreescribe `PatientName`
  y `PatientID`. Opcionalmente puedes activar ~30 campos adicionales (fecha de
  nacimiento, institución, médicos, fechas de estudio, etc.) desde la pestaña
  **Campos opcionales** — útil para cumplir requisitos de repositorios
  financiados por NIH (NDA, FITBIR, OpenNeuro). Todos desactivados por defecto.
* **Protección de integridad 4D:** UIDs, geometría y tags de orden/temporales
  (SeriesInstanceUID, ImagePositionPatient, AcquisitionNumber, etc.) nunca se tocan.
* **Procesamiento paralelo multinúcleo:** usa `ProcessPoolExecutor` para evitar
  el cuello de botella del GIL al parsear con pydicom.
* **Escritura atómica:** guarda primero en `.part` y renombra, evitando DICOM truncados.
* **Soporte de comprimidos:** acepta carpetas o archivos `.zip`, `.7z`, `.tar`,
  `.tar.gz`/`.tgz`, `.tar.bz2`/`.tbz2`, `.tar.xz`/`.txz` como entrada.
* **Modo lote:** procesa varios sujetos en serie, cada uno con su propio código
  de anonimización.
* **`dicomsorter` opcional:** integración opcional con la herramienta externa
  `dicomsorter` (desactivada por defecto porque puede fragmentar series 4D).
  En el AppImage de Linux viene embebido — cero instalación adicional.

---

### 📋 Requisitos

* Python 3.9 o superior (probado con 3.12).
* **Tkinter** (incluido en la instalación estándar de Python en Windows/macOS;
  en Linux puede requerir un paquete del sistema — ver abajo).

#### Instalar Tkinter en Linux (si falta)

```bash
# Debian / Ubuntu / Pop!_OS
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter

# Arch
sudo pacman -S tk
```

---

### 📦 Instalación

```bash
git clone https://github.com/pabloreyesg/dicom_anonymizer_batch.git
cd dicom_anonymizer_batch

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### ▶️ Uso

```bash
python anonymizerbatch.py
```

Se abre la interfaz gráfica con cuatro pestañas:

1. **Principal** — anonimiza una carpeta o un comprimido hacia un directorio de salida.
2. **Lote** — procesa varios sujetos en serie (cada uno con su propio código,
   guardado en `<salida raíz>/<código>`).
3. **Campos opcionales** — checkboxes agrupados por categoría (identificación
   del paciente, institución/personal médico, equipo/estudio, fechas) para
   vaciar campos DICOM adicionales más allá de `PatientName`/`PatientID`.
   Están **desactivados por defecto**; actívalos solo si tu estudio lo exige
   (basado en el perfil básico de confidencialidad de DICOM PS3.15 Anexo E y
   los identificadores HIPAA Safe Harbor). Nunca tocan UIDs, geometría ni tags
   temporales — esos siguen protegidos por `PROTECTED_KEYWORDS` sin excepción,
   incluso si aparecieran seleccionados. Aplica tanto al modo Principal como
   al modo Lote.
4. **Log** — consola en tiempo real + botón de diagnóstico (verifica versiones
   de `pydicom`/`py7zr` y el intérprete en uso).

#### Soporte opcional de `dicomsorter`

El checkbox "Ejecutar dicomsorter" invoca el comando externo `dicomsorter` vía
`PATH`. **Es incompatible con pydicom ≥ 3**: su código hace
`from pydicom.dicomdir import DicomDir`, y ese módulo fue eliminado en
pydicom 3.0 (confirmado en las release notes oficiales). `dicomsorter` declara
`pydicom>=2.3.0` sin límite superior, así que `pip` lo instala sin quejarse
en el mismo entorno que `pydicom>=3` — pero falla en tiempo de ejecución con
`ModuleNotFoundError: No module named 'pydicom.dicomdir'`. Por eso requiere
un **entorno Python separado** con `pydicom 2.4.5` (última release 2.x):

```bash
python3 -m venv venv-dicomsorter
venv-dicomsorter/bin/pip install -r requirements-dicomsorter.txt

# Exponer el binario en el PATH sin mezclar entornos:
mkdir -p ~/.local/bin
ln -sf "$(pwd)/venv-dicomsorter/bin/dicomsorter" ~/.local/bin/dicomsorter

# Verificar:
dicomsorter --version   # → dicomsorter 0.1.0a8
```

(`~/.local/bin` debe estar en tu `$PATH`; en la mayoría de distros ya lo está).

Si no necesitas reordenar archivos, deja el checkbox desactivado (es el valor
por defecto y evita fragmentar series 4D).

---

### 🐧 Generar un AppImage autocontenido (Linux)

El AppImage empaqueta **dos binarios independientes** generados con PyInstaller
(cada uno con su propio Python y su propia versión de pydicom embebida, sin
conflicto): `DicomAnonymizer` (pydicom 3.x) y `dicomsorter` (pydicom 2.4.5).
El resultado es un único archivo `.AppImage` que no requiere Python, pip ni
ningún paquete del sistema en la máquina destino — ni siquiera para usar la
opción "Ejecutar dicomsorter".

#### Opción A — Build local

```bash
# 1) Compilar DicomAnonymizer (entorno con pydicom 3.x)
python3 -m venv venv
venv/bin/pip install -r requirements.txt pyinstaller
venv/bin/pyinstaller --onefile --name DicomAnonymizer \
  --distpath dist-main --workpath /tmp/build-main --specpath /tmp/build-main \
  anonymizerbatch.py

# 2) Compilar dicomsorter (entorno aislado con pydicom 2.4.5)
python3 -m venv venv-dicomsorter
venv-dicomsorter/bin/pip install -r requirements-dicomsorter.txt pyinstaller
venv-dicomsorter/bin/pyinstaller --onefile --name dicomsorter \
  --distpath dist-dicomsorter --workpath /tmp/build-dicomsorter --specpath /tmp/build-dicomsorter \
  packaging/dicomsorter_entry.py

# 3) Armar el AppDir
mkdir -p AppDir/usr/bin AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/256x256/apps
cp dist-main/DicomAnonymizer dist-dicomsorter/dicomsorter AppDir/usr/bin/
chmod +x AppDir/usr/bin/*
cp packaging/AppRun AppDir/AppRun && chmod +x AppDir/AppRun
cp packaging/dicomanonymizer.desktop AppDir/dicomanonymizer.desktop
cp packaging/dicomanonymizer.desktop AppDir/usr/share/applications/

# icono (requiere ImageMagick: sudo apt install imagemagick)
convert -size 256x256 xc:"#1e3a5f" -fill white -gravity center \
  -pointsize 100 -font DejaVu-Sans-Bold -annotate +0-20 "Dx" \
  -fill "#4fc3f7" -pointsize 24 -annotate +0+60 "ANONYMIZER" \
  AppDir/dicomanonymizer.png
cp AppDir/dicomanonymizer.png AppDir/usr/share/icons/hicolor/256x256/apps/

# 4) Empaquetar
wget -q -O /tmp/appimagetool.AppImage \
  https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x /tmp/appimagetool.AppImage
ARCH=x86_64 /tmp/appimagetool.AppImage AppDir DicomAnonymizer-x86_64.AppImage
```

Resultado: `DicomAnonymizer-x86_64.AppImage`. Para distribuirlo, el usuario
final solo necesita:

```bash
chmod +x DicomAnonymizer-x86_64.AppImage
./DicomAnonymizer-x86_64.AppImage
```

#### Opción B — Build automático en GitHub Actions

Este repo incluye `.github/workflows/build-linux-appimage.yml`, que hace todo
lo anterior en un runner `ubuntu-22.04` cada vez que:

* se hace push de un tag `v*` → adjunta el AppImage a un GitHub Release, o
* se dispara manualmente (`workflow_dispatch`):

```bash
gh workflow run build-linux-appimage.yml
gh run list --workflow=build-linux-appimage.yml --limit 1
gh run download <run-id> -n DicomAnonymizer-linux-appimage
```

---

### 🏗️ Generar un ejecutable `.exe` autocontenido (Windows)

El `.exe` se construye con [PyInstaller](https://pyinstaller.org/), que empaqueta
Python + dependencias + el script en un solo archivo. **PyInstaller compila para
el sistema operativo en el que se ejecuta** — para obtener un `.exe` nativo de
Windows necesitas correr el build en Windows (máquina real, VM, o CI). Hay dos
formas de hacerlo:

#### Opción A — Build local en una máquina Windows

```powershell
git clone https://github.com/pabloreyesg/dicom_anonymizer_batch.git
cd dicom_anonymizer_batch

python -m venv venv
venv\Scripts\activate

pip install -r requirements-build.txt

pyinstaller --onefile --windowed --name DicomAnonymizer anonymizerbatch.py
```

El ejecutable queda en `dist\DicomAnonymizer.exe`. Es autocontenido: no requiere
Python instalado en la máquina destino.

Flags útiles:
* `--onefile` → un solo `.exe` (arranca un poco más lento porque se descomprime
  a un temporal, pero es más fácil de distribuir).
* `--windowed` → sin consola visible (la app es GUI con Tkinter).
* `--icon=icono.ico` → opcional, para darle ícono propio.

#### Opción B — Build automático en GitHub Actions (sin necesitar Windows)

Este repo incluye `.github/workflows/build-windows-exe.yml`, que compila el
`.exe` en un runner `windows-latest` cada vez que:

* se hace push de un tag `v*` (ej. `v1.0.0`) → además adjunta el `.exe` a un
  GitHub Release automáticamente, o
* se dispara manualmente desde la pestaña **Actions** del repo (`workflow_dispatch`).

Para generarlo manualmente:

```bash
gh workflow run build-windows-exe.yml
# espera a que termine y descarga el artefacto:
gh run list --workflow=build-windows-exe.yml --limit 1
gh run download <run-id> -n DicomAnonymizer-windows-exe
```

O simplemente crea un tag y súbelo para publicar un release con el `.exe` adjunto:

```bash
git tag v1.0.0
git push origin v1.0.0
```

---

### ⚠️ Notas de seguridad

* La extracción de comprimidos (`.zip`, `.7z`, `.tar.*`) valida rutas para
  evitar *path traversal* (entradas con `../` o rutas absolutas se rechazan).
* El anonimizador **nunca** modifica UIDs, geometría ni tags temporales —
  ver `PROTECTED_KEYWORDS` en `anonymizerbatch.py` para la lista completa.

---

### 📜 Licencia

Este proyecto se distribuye bajo la **licencia MIT** (ver `LICENSE`).

Usa y/o empaqueta dentro de los binarios compilados (`.exe`/`.AppImage`)
librerías de terceros bajo sus propias licencias (MIT, BSD-3-Clause,
Apache-2.0, LGPL-2.1, PSF y GPL-2.0-or-later con excepción de bootloader) —
el detalle completo, con los avisos de copyright exigidos por cada una, está
en [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).
