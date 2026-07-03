# DICOM Anonymizer & Sorter v3.0 (Linux AppImage Build)

A lightweight, high-performance cross-platform desktop application designed for secure, minimal anonymization of DICOM medical images[cite: 1]. It specifically protects the integrity of complex 4D datasets—such as fMRI and DWI sequences—by safely preserving all vital UIDs, geometry, and temporal tags to prevent series fragmentation in medical viewers[cite: 1].

---

## 🚀 Features

* **Minimal Defensive Anonymization:** Only overwrites the strictly requested tags (`PatientName` and `PatientID`)[cite: 1]. 
* **4D Integrity Protection:** Leaves UIDs, geometry, and acquisition/temporal sorting tags completely untouched to avoid breaking fMRI/DWI series groupings[cite: 1].
* **Multi-Core Parallel Processing:** Utilizes a process-based pool (`multiprocessing`) to bypass Python's GIL, maximizing your CPU cores during heavy DICOM parsing[cite: 1].
* **Atomic Writing:** Saves updated files using `.part` extensions before an atomic rename, preventing corrupted or truncated files if the process is cancelled mid-execution[cite: 1].
* **Self-Contained `dicomsorter`:** Seamlessly bundles the external file-sorting tool internally, requiring zero system-wide installation dependencies for the end user[cite: 1].

---

## 📦 Building the Portable Linux AppImage

Follow these steps to package `anonymizerbatch.py` and its dependencies (including `dicomsorter`) into a completely autonomous, single-file **AppImage**.

### 1. Install System Tools
Install the necessary system compilation utilities and fetch the official `appimagetool`:
```bash
sudo apt update && sudo apt install python3-pip python3-venv binutils wget -y

# Download and install appimagetool globally
wget [https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage](https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage)
chmod +x appimagetool-x86_64.AppImage
sudo mv appimagetool-x86_64.AppImage /usr/local/bin/appimagetool
