# DICOM Anonymizer & Sorter v3.0

Aplicación de escritorio ligera y multiplataforma para anonimización **mínima y
segura** de imágenes DICOM. Protege específicamente la integridad de series 4D
complejas (fMRI, DWI) preservando intactos UIDs, geometría y tags temporales,
para evitar que los visores médicos (Weasis, etc.) fragmenten las series.

## 🚀 Características

* **Anonimización defensiva mínima:** solo sobreescribe `PatientName` y `PatientID`.
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

## 📋 Requisitos

* Python 3.9 o superior (probado con 3.12).
* **Tkinter** (incluido en la instalación estándar de Python en Windows/macOS;
  en Linux puede requerir un paquete del sistema — ver abajo).

### Instalar Tkinter en Linux (si falta)

```bash
# Debian / Ubuntu / Pop!_OS
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter

# Arch
sudo pacman -S tk
```

---

## 📦 Instalación

```bash
git clone https://github.com/pabloreyesg/dicom_anonymizer_batch.git
cd dicom_anonymizer_batch

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

## ▶️ Uso

```bash
python anonymizerbatch.py
```

Se abre la interfaz gráfica con tres pestañas:

1. **Principal** — anonimiza una carpeta o un comprimido hacia un directorio de salida.
2. **Lote** — procesa varios sujetos en serie (cada uno con su propio código,
   guardado en `<salida raíz>/<código>`).
3. **Log** — consola en tiempo real + botón de diagnóstico (verifica versiones
   de `pydicom`/`py7zr` y el intérprete en uso).

### Soporte opcional de `dicomsorter`

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

## 🐧 Generar un AppImage autocontenido (Linux)

El AppImage empaqueta **dos binarios independientes** generados con PyInstaller
(cada uno con su propio Python y su propia versión de pydicom embebida, sin
conflicto): `DicomAnonymizer` (pydicom 3.x) y `dicomsorter` (pydicom 2.4.5).
El resultado es un único archivo `.AppImage` que no requiere Python, pip ni
ningún paquete del sistema en la máquina destino — ni siquiera para usar la
opción "Ejecutar dicomsorter".

### Opción A — Build local

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

### Opción B — Build automático en GitHub Actions

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

## 🏗️ Generar un ejecutable `.exe` autocontenido (Windows)

El `.exe` se construye con [PyInstaller](https://pyinstaller.org/), que empaqueta
Python + dependencias + el script en un solo archivo. **PyInstaller compila para
el sistema operativo en el que se ejecuta** — para obtener un `.exe` nativo de
Windows necesitas correr el build en Windows (máquina real, VM, o CI). Hay dos
formas de hacerlo:

### Opción A — Build local en una máquina Windows

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

### Opción B — Build automático en GitHub Actions (sin necesitar Windows)

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

## ⚠️ Notas de seguridad

* La extracción de comprimidos (`.zip`, `.7z`, `.tar.*`) valida rutas para
  evitar *path traversal* (entradas con `../` o rutas absolutas se rechazan).
* El anonimizador **nunca** modifica UIDs, geometría ni tags temporales —
  ver `PROTECTED_KEYWORDS` en `anonymizerbatch.py` para la lista completa.
