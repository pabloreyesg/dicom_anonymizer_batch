"""
DICOM Anonymizer (mínimo) + DICOMSorter opcional  ·  v3.0
==========================================================

Cambios clave frente a v2:
  - Anonimización REDUCIDA a lo estrictamente pedido: PatientName + PatientID.
    (Nada de descripciones de serie/estudio, fechas, institución ni private tags,
     porque justamente esas ediciones pueden confundir a dicomsorter y a los visores.)
  - Guarda de seguridad: NUNCA se tocan UIDs, geometría ni tags temporales/de orden
    (SeriesInstanceUID, ImagePositionPatient, AcquisitionNumber, TemporalPositionIdentifier,
     InstanceNumber, SeriesNumber, etc.). Eso mantiene intactas las series 4D (fMRI/DWI).
  - Se preserva el TransferSyntax / file_meta al guardar (compatible pydicom 2 y 3).
  - dicomsorter DESACTIVADO por defecto (es el sospechoso #1 de "romper" series).
  - Escritura atómica opcional para evitar archivos truncados si se cancela a media escritura.

Para diagnosticar el problema de series partidas en Weasis:
  1) Corre con dicomsorter DESACTIVADO y abre la salida tal cual.
     - Si las series se ven completas -> el culpable era dicomsorter.
     - Si igual se parten -> es la preferencia "Split series" de Weasis / estructura 4D,
       no este script.
"""

import os
import sys
import json
import queue
import logging
import tempfile
import threading
import contextlib
import subprocess
import multiprocessing
import concurrent.futures
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pydicom

# ─────────────────────────────────────────────
#  Logging: consola + cola para el panel de GUI
# ─────────────────────────────────────────────
log_queue = queue.Queue()


class QueueHandler(logging.Handler):
    """Envía registros de log a una cola para que la GUI los consuma."""
    def __init__(self, q):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(self.format(record))


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
queue_handler = QueueHandler(log_queue)
queue_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(queue_handler)

# ─────────────────────────────────────────────
#  Estado global de cancelación
# ─────────────────────────────────────────────
cancel_event = threading.Event()

# ═════════════════════════════════════════════
#  IDIOMA (es/en)
# ═════════════════════════════════════════════
LANG_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".dicom_anonymizer_lang.json")


def load_language():
    try:
        with open(LANG_CONFIG_PATH, "r", encoding="utf-8") as f:
            lang = json.load(f).get("language")
            if lang in ("es", "en"):
                return lang
    except Exception:
        pass
    return "es"


def save_language(lang):
    try:
        with open(LANG_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"language": lang}, f)
    except Exception as e:
        logging.warning("No se pudo guardar la preferencia de idioma: %s", e)


APP_LANGUAGE = load_language()

STRINGS = {
    "es": {
        "app_title": "DICOM Anonymizer (mínimo)  v3.0",
        "menu_language": "Idioma",
        "lang_name_es": "Español",
        "lang_name_en": "English",
        "menu_help": "Ayuda",
        "menu_about_item": "Acerca de",
        "menu_help_item": "Ayuda",
        "about_title": "Acerca de DICOM Anonymizer",
        "about_body": (
            "DICOM Anonymizer & Sorter  v3.0\n\n"
            "Anonimización mínima y segura de imágenes DICOM, con protección\n"
            "especial para series 4D (fMRI/DWI).\n\n"
            "Repositorio: github.com/pabloreyesg/dicom_anonymizer_batch"
        ),
        "help_title": "Ayuda",
        "help_body": (
            "Cómo usar DICOM Anonymizer:\n\n"
            "1. Pestaña Principal: selecciona una carpeta o archivo comprimido\n"
            "   de entrada, un directorio de salida y un código de anonimización\n"
            "   (reemplaza Nombre e ID del paciente). Pulsa Procesar.\n\n"
            "2. Pestaña Lote: añade varios sujetos (carpetas o comprimidos) para\n"
            "   procesarlos en serie, cada uno con su propio código.\n\n"
            "3. Pestaña Campos opcionales: activa campos DICOM adicionales a\n"
            "   vaciar (fecha de nacimiento, institución, médicos, etc.) si tu\n"
            "   estudio lo exige. Desactivados por defecto.\n\n"
            "4. Pestaña Log: consola en tiempo real y botón de diagnóstico.\n\n"
            "UIDs, geometría y tags temporales nunca se modifican, para no\n"
            "romper series 4D (fMRI/DWI)."
        ),
        "tab_main": "  Principal  ",
        "tab_batch": "  Lote  ",
        "tab_extra": "  Campos opcionales  ",
        "tab_log": "  Log  ",
        "input_label": "Entrada (carpeta o comprimido):",
        "btn_browse": "Examinar",
        "dlg_select_input": "Seleccionar entrada",
        "dlg_select_archive": "Seleccionar archivo comprimido",
        "filetype_archives": "Comprimidos",
        "filetype_all": "Todos",
        "btn_archive": "Archivo…",
        "output_label": "Directorio de salida:",
        "dlg_select_output": "Seleccionar salida",
        "btn_create": "Crear",
        "code_label": "Código de anonimización:",
        "code_hint": (
            "Este valor reemplaza Nombre e ID del paciente.\n"
            "Si lo dejas vacío se usa \"Anonymized\". El resto (UIDs, geometría,\n"
            "tags temporales) se preserva intacto."
        ),
        "workers_label": "Procesos paralelos:",
        "sorter_check": "Ejecutar dicomsorter después de anonimizar  (⚠ puede fragmentar series 4D)",
        "progress_default": "0 / ? archivos (0%)",
        "progress_fmt": "{done} / {total} archivos ({pct}%)",
        "status_waiting": "Esperando acción…",
        "btn_process": "▶  Procesar",
        "btn_cancel": "✖  Cancelar",
        "batch_intro": (
            "Procesa varios sujetos en serie. Cada uno se anonimiza con su código\n"
            "y se guarda en:  <salida raíz>/<código>"
        ),
        "batch_output_label": "Salida raíz:",
        "dlg_batch_output": "Salida raíz del lote",
        "col_folder": "Carpeta de entrada",
        "col_code": "Código (Nombre/ID)",
        "col_status": "Estado",
        "dlg_subject_folder": "Seleccionar carpeta del sujeto",
        "status_pending": "pendiente",
        "status_pending_zip": "pendiente (zip)",
        "dlg_subfolders": "Carpeta padre (cada subcarpeta = 1 sujeto)",
        "dlg_archives": "Seleccionar archivos comprimidos (Ctrl/Shift para varios)",
        "dlg_archives_folder": "Carpeta con comprimidos (cada archivo = 1 sujeto)",
        "btn_add_subject": "+ Sujeto",
        "btn_add_subfolders": "+ Subcarpetas",
        "btn_add_archives": "+ Comprimido(s)",
        "btn_add_archives_folder": "+ Carpeta de zips",
        "btn_remove": "Quitar",
        "btn_clear": "Limpiar",
        "edit_hint": "(doble clic en la columna Código para editarlo)",
        "batch_sorter_check": "Ejecutar dicomsorter en cada sujeto  (⚠ puede fragmentar series 4D)",
        "subj_label_default": "Sujeto 0 / 0",
        "subj_label_fmt": "Sujeto {i} / {total}",
        "btn_batch_process": "▶  Procesar lote",
        "msg_no_archives_title": "Sin comprimidos",
        "msg_no_archives_body": "No se encontraron archivos comprimidos en:\n{parent}",
        "extra_intro": (
            "Campos adicionales a vaciar durante la anonimización. Todos están\n"
            "DESACTIVADOS por defecto — selecciona solo los que exija tu estudio\n"
            "(p. ej. requisitos de un repositorio financiado por NIH). No afectan\n"
            "UIDs, geometría ni tags temporales; nunca se tocan esos."
        ),
        "btn_check_all": "Marcar todos",
        "btn_uncheck_all": "Desmarcar todos",
        "btn_diagnostic": "Diagnóstico",
        "btn_clear_log": "Limpiar log",
        "msg_error_title": "Error",
        "msg_completed_title": "Proceso completado",
        "msg_batch_completed_title": "Lote completado",
        "msg_empty_path_title": "Ruta vacía",
        "msg_empty_path_body": "Escribe primero una ruta en el campo.",
        "msg_dir_exists_title": "Directorio existente",
        "msg_dir_exists_body": "El directorio ya existe:\n{path}",
        "msg_dir_created_title": "Directorio creado",
        "msg_dir_created_body": "Directorio creado exitosamente:\n{path}",
        "msg_dir_create_fail": "No se pudo crear el directorio:\n{e}",
        "msg_invalid_input": (
            "La entrada debe ser una carpeta DICOM o un archivo comprimido "
            "(.zip, .tar.gz, .tgz, .tar, .tar.bz2, .tar.xz)."
        ),
        "msg_dir_not_exist_title": "Directorio no existe",
        "msg_output_not_exist_body": "El directorio de salida no existe:\n{output_dir}\n\n¿Crearlo ahora?",
        "msg_no_subjects_title": "Sin sujetos",
        "msg_no_subjects_body": "Añade al menos un sujeto a la lista.",
        "msg_select_output_root": "Selecciona un directorio de salida (raíz) para el lote.",
        "msg_invalid_subject_input": "Entrada no válida (ni carpeta ni comprimido):\n{input}",
        "msg_root_not_exist_body": "La carpeta de salida raíz no existe:\n{output_root}\n\n¿Crearla ahora?",
        "status_cancelled": "Proceso cancelado.",
        "status_completed_fmt": "Completado  ✔ {ok}  ✗ {errors}  ⊘ {skipped}",
        "status_error_fmt": "Error: {e}",
        "batch_cancelled": "Lote cancelado.",
        "batch_summary_fmt": "Lote finalizado – Sujetos: {total}   ✔ {ok}  ✗ {errors}  ⊘ {skipped}",
        "batch_processing_fmt": "[{idx}/{total}] {name} …",
        "tree_processing": "procesando…",
        "tree_cancelled": "cancelado",
        "tree_error_fmt": "ERROR: {e}",
        "status_extracting": "Descomprimiendo…",
        "status_anonymizing": "Anonimizando imágenes…",
        "status_running_sorter": "Ejecutando dicomsorter…",
        "restart_confirm_title": "Reiniciar aplicación",
        "restart_confirm_body": (
            "Para cambiar el idioma hay que reiniciar la aplicación.\n"
            "Se perderán las rutas y la lista de sujetos no guardados.\n\n"
            "¿Reiniciar ahora?"
        ),
    },
    "en": {
        "app_title": "DICOM Anonymizer (minimal)  v3.0",
        "menu_language": "Language",
        "lang_name_es": "Español",
        "lang_name_en": "English",
        "menu_help": "Help",
        "menu_about_item": "About",
        "menu_help_item": "Help",
        "about_title": "About DICOM Anonymizer",
        "about_body": (
            "DICOM Anonymizer & Sorter  v3.0\n\n"
            "Minimal, safe anonymization of DICOM images, with special\n"
            "protection for 4D series (fMRI/DWI).\n\n"
            "Repository: github.com/pabloreyesg/dicom_anonymizer_batch"
        ),
        "help_title": "Help",
        "help_body": (
            "How to use DICOM Anonymizer:\n\n"
            "1. Main tab: pick an input folder or archive, an output\n"
            "   directory, and an anonymization code (replaces the patient's\n"
            "   Name and ID). Click Process.\n\n"
            "2. Batch tab: add several subjects (folders or archives) to\n"
            "   process them in series, each with its own code.\n\n"
            "3. Optional fields tab: enable additional DICOM fields to clear\n"
            "   (birth date, institution, physicians, etc.) if your study\n"
            "   requires it. Off by default.\n\n"
            "4. Log tab: real-time console and a diagnostics button.\n\n"
            "UIDs, geometry and temporal tags are never modified, to avoid\n"
            "breaking 4D series (fMRI/DWI)."
        ),
        "tab_main": "  Main  ",
        "tab_batch": "  Batch  ",
        "tab_extra": "  Optional fields  ",
        "tab_log": "  Log  ",
        "input_label": "Input (folder or archive):",
        "btn_browse": "Browse",
        "dlg_select_input": "Select input",
        "dlg_select_archive": "Select archive file",
        "filetype_archives": "Archives",
        "filetype_all": "All",
        "btn_archive": "Archive…",
        "output_label": "Output directory:",
        "dlg_select_output": "Select output",
        "btn_create": "Create",
        "code_label": "Anonymization code:",
        "code_hint": (
            "This value replaces the patient's Name and ID.\n"
            "If left empty, \"Anonymized\" is used. Everything else (UIDs,\n"
            "geometry, temporal tags) is preserved intact."
        ),
        "workers_label": "Parallel processes:",
        "sorter_check": "Run dicomsorter after anonymizing  (⚠ may fragment 4D series)",
        "progress_default": "0 / ? files (0%)",
        "progress_fmt": "{done} / {total} files ({pct}%)",
        "status_waiting": "Waiting for action…",
        "btn_process": "▶  Process",
        "btn_cancel": "✖  Cancel",
        "batch_intro": (
            "Processes several subjects in series. Each is anonymized with\n"
            "its own code and saved to:  <root output>/<code>"
        ),
        "batch_output_label": "Root output:",
        "dlg_batch_output": "Batch root output",
        "col_folder": "Input folder",
        "col_code": "Code (Name/ID)",
        "col_status": "Status",
        "dlg_subject_folder": "Select subject folder",
        "status_pending": "pending",
        "status_pending_zip": "pending (zip)",
        "dlg_subfolders": "Parent folder (each subfolder = 1 subject)",
        "dlg_archives": "Select archive files (Ctrl/Shift for multiple)",
        "dlg_archives_folder": "Folder with archives (each file = 1 subject)",
        "btn_add_subject": "+ Subject",
        "btn_add_subfolders": "+ Subfolders",
        "btn_add_archives": "+ Archive(s)",
        "btn_add_archives_folder": "+ Folder of zips",
        "btn_remove": "Remove",
        "btn_clear": "Clear",
        "edit_hint": "(double-click the Code column to edit it)",
        "batch_sorter_check": "Run dicomsorter on each subject  (⚠ may fragment 4D series)",
        "subj_label_default": "Subject 0 / 0",
        "subj_label_fmt": "Subject {i} / {total}",
        "btn_batch_process": "▶  Process batch",
        "msg_no_archives_title": "No archives",
        "msg_no_archives_body": "No archive files were found in:\n{parent}",
        "extra_intro": (
            "Additional fields to clear during anonymization. All are\n"
            "OFF by default — enable only the ones your study requires\n"
            "(e.g. requirements from a NIH-funded repository). They never\n"
            "affect UIDs, geometry, or temporal tags; those stay protected."
        ),
        "btn_check_all": "Check all",
        "btn_uncheck_all": "Uncheck all",
        "btn_diagnostic": "Diagnostics",
        "btn_clear_log": "Clear log",
        "msg_error_title": "Error",
        "msg_completed_title": "Process completed",
        "msg_batch_completed_title": "Batch completed",
        "msg_empty_path_title": "Empty path",
        "msg_empty_path_body": "Type a path in the field first.",
        "msg_dir_exists_title": "Directory exists",
        "msg_dir_exists_body": "The directory already exists:\n{path}",
        "msg_dir_created_title": "Directory created",
        "msg_dir_created_body": "Directory created successfully:\n{path}",
        "msg_dir_create_fail": "Could not create the directory:\n{e}",
        "msg_invalid_input": (
            "The input must be a DICOM folder or an archive file "
            "(.zip, .tar.gz, .tgz, .tar, .tar.bz2, .tar.xz)."
        ),
        "msg_dir_not_exist_title": "Directory does not exist",
        "msg_output_not_exist_body": "The output directory does not exist:\n{output_dir}\n\nCreate it now?",
        "msg_no_subjects_title": "No subjects",
        "msg_no_subjects_body": "Add at least one subject to the list.",
        "msg_select_output_root": "Select a root output directory for the batch.",
        "msg_invalid_subject_input": "Invalid input (neither a folder nor an archive):\n{input}",
        "msg_root_not_exist_body": "The root output folder does not exist:\n{output_root}\n\nCreate it now?",
        "status_cancelled": "Process cancelled.",
        "status_completed_fmt": "Completed  ✔ {ok}  ✗ {errors}  ⊘ {skipped}",
        "status_error_fmt": "Error: {e}",
        "batch_cancelled": "Batch cancelled.",
        "batch_summary_fmt": "Batch finished – Subjects: {total}   ✔ {ok}  ✗ {errors}  ⊘ {skipped}",
        "batch_processing_fmt": "[{idx}/{total}] {name} …",
        "tree_processing": "processing…",
        "tree_cancelled": "cancelled",
        "tree_error_fmt": "ERROR: {e}",
        "status_extracting": "Extracting…",
        "status_anonymizing": "Anonymizing images…",
        "status_running_sorter": "Running dicomsorter…",
        "restart_confirm_title": "Restart application",
        "restart_confirm_body": (
            "Changing the language requires restarting the application.\n"
            "Unsaved paths and the subject list will be lost.\n\n"
            "Restart now?"
        ),
    },
}


def tr(key, **kwargs):
    """Devuelve el string traducido para el idioma activo (APP_LANGUAGE)."""
    text = STRINGS.get(APP_LANGUAGE, STRINGS["es"]).get(key, key)
    return text.format(**kwargs) if kwargs else text


# ═════════════════════════════════════════════
#  CONFIGURACIÓN DE ANONIMIZACIÓN
# ═════════════════════════════════════════════

# Keywords DICOM que se anonimizan. El valor de reemplazo (el "código") lo define
# el usuario en la GUI; si lo deja vacío, se usa DEFAULT_ANON_CODE.
ANON_KEYWORDS = ("PatientName", "PatientID")
DEFAULT_ANON_CODE = "Anonymized"

# LISTA NEGRA: tags que NUNCA deben modificarse. Preservarlos es lo que mantiene
# intactas las series (agrupación por UID y ordenamiento 4D en fMRI/DWI).
# Es solo una salvaguarda defensiva; el código de arriba ya no los toca.
PROTECTED_KEYWORDS = frozenset({
    "SOPInstanceUID", "SOPClassUID",
    "StudyInstanceUID", "SeriesInstanceUID", "FrameOfReferenceUID",
    "SeriesNumber", "InstanceNumber", "AcquisitionNumber",
    "TemporalPositionIdentifier", "TemporalPositionIndex",
    "NumberOfTemporalPositions", "StackID", "InStackPositionNumber",
    "DiffusionBValue", "DiffusionGradientOrientation",
    "ImagePositionPatient", "ImageOrientationPatient",
    "SliceLocation", "EchoNumbers", "EchoTime",
    "TriggerTime", "AcquisitionTime", "ContentTime",
})

# ═════════════════════════════════════════════
#  CAMPOS OPCIONALES DE ANONIMIZACIÓN (desactivados por defecto)
# ═════════════════════════════════════════════
# Basados en el perfil básico de confidencialidad de DICOM (PS3.15 Anexo E)
# y los identificadores HIPAA Safe Harbor — el conjunto que suelen exigir
# los repositorios financiados por NIH (NDA, FITBIR, OpenNeuro, etc.).
# Ninguno toca geometría/UIDs/tags temporales (ver PROTECTED_KEYWORDS).
# Se vacían (valor "") en vez de usar el código de anonimización, siguiendo
# la práctica estándar de DICOM para atributos "Replace -> zero-length".
#
# Cada entrada: (keyword DICOM, slug de categoría — ver CATEGORY_LABELS/FIELD_LABELS)
OPTIONAL_ANON_FIELDS = [
    ("PatientBirthDate", "patient"),
    ("PatientAge", "patient"),
    ("PatientAddress", "patient"),
    ("PatientTelephoneNumbers", "patient"),
    ("OtherPatientIDs", "patient"),
    ("OtherPatientNames", "patient"),
    ("PatientBirthName", "patient"),
    ("PatientMotherBirthName", "patient"),
    ("EthnicGroup", "patient"),
    ("Occupation", "patient"),
    ("AdditionalPatientHistory", "patient"),
    ("PatientComments", "patient"),
    ("InstitutionName", "institution"),
    ("InstitutionAddress", "institution"),
    ("InstitutionalDepartmentName", "institution"),
    ("ReferringPhysicianName", "institution"),
    ("ReferringPhysicianAddress", "institution"),
    ("ReferringPhysicianTelephoneNumbers", "institution"),
    ("PerformingPhysicianName", "institution"),
    ("OperatorsName", "institution"),
    ("PhysiciansOfRecord", "institution"),
    ("NameOfPhysiciansReadingStudy", "institution"),
    ("RequestingPhysician", "institution"),
    ("StationName", "equipment"),
    ("DeviceSerialNumber", "equipment"),
    ("StudyID", "equipment"),
    ("AccessionNumber", "equipment"),
    ("StudyDate", "dates"),
    ("SeriesDate", "dates"),
    ("AcquisitionDate", "dates"),
    ("ContentDate", "dates"),
]

CATEGORY_LABELS = {
    "es": {
        "patient": "Identificación del paciente",
        "institution": "Institución y personal médico",
        "equipment": "Equipo y estudio",
        "dates": "Fechas (identificador HIPAA)",
    },
    "en": {
        "patient": "Patient identification",
        "institution": "Institution and medical staff",
        "equipment": "Equipment and study",
        "dates": "Dates (HIPAA identifier)",
    },
}

FIELD_LABELS = {
    "es": {
        "PatientBirthDate": "Fecha de nacimiento",
        "PatientAge": "Edad del paciente",
        "PatientAddress": "Dirección del paciente",
        "PatientTelephoneNumbers": "Teléfono del paciente",
        "OtherPatientIDs": "Otros IDs del paciente",
        "OtherPatientNames": "Otros nombres del paciente",
        "PatientBirthName": "Apellido de nacimiento",
        "PatientMotherBirthName": "Apellido de soltera de la madre",
        "EthnicGroup": "Grupo étnico",
        "Occupation": "Ocupación",
        "AdditionalPatientHistory": "Historia clínica adicional",
        "PatientComments": "Comentarios del paciente",
        "InstitutionName": "Nombre de la institución",
        "InstitutionAddress": "Dirección de la institución",
        "InstitutionalDepartmentName": "Departamento institucional",
        "ReferringPhysicianName": "Médico que remite",
        "ReferringPhysicianAddress": "Dirección del médico que remite",
        "ReferringPhysicianTelephoneNumbers": "Teléfono del médico que remite",
        "PerformingPhysicianName": "Médico que realiza el estudio",
        "OperatorsName": "Nombre del operador/técnico",
        "PhysiciansOfRecord": "Médicos responsables",
        "NameOfPhysiciansReadingStudy": "Médico que interpreta el estudio",
        "RequestingPhysician": "Médico solicitante",
        "StationName": "Nombre de la estación/equipo",
        "DeviceSerialNumber": "Número de serie del equipo",
        "StudyID": "ID del estudio",
        "AccessionNumber": "Número de accesión",
        "StudyDate": "Fecha del estudio",
        "SeriesDate": "Fecha de la serie",
        "AcquisitionDate": "Fecha de adquisición",
        "ContentDate": "Fecha de contenido",
    },
    "en": {
        "PatientBirthDate": "Patient birth date",
        "PatientAge": "Patient age",
        "PatientAddress": "Patient address",
        "PatientTelephoneNumbers": "Patient phone number",
        "OtherPatientIDs": "Other patient IDs",
        "OtherPatientNames": "Other patient names",
        "PatientBirthName": "Patient birth name",
        "PatientMotherBirthName": "Mother's birth name",
        "EthnicGroup": "Ethnic group",
        "Occupation": "Occupation",
        "AdditionalPatientHistory": "Additional patient history",
        "PatientComments": "Patient comments",
        "InstitutionName": "Institution name",
        "InstitutionAddress": "Institution address",
        "InstitutionalDepartmentName": "Institutional department",
        "ReferringPhysicianName": "Referring physician",
        "ReferringPhysicianAddress": "Referring physician address",
        "ReferringPhysicianTelephoneNumbers": "Referring physician phone",
        "PerformingPhysicianName": "Performing physician",
        "OperatorsName": "Operator/technician name",
        "PhysiciansOfRecord": "Physicians of record",
        "NameOfPhysiciansReadingStudy": "Reading physician",
        "RequestingPhysician": "Requesting physician",
        "StationName": "Station/equipment name",
        "DeviceSerialNumber": "Device serial number",
        "StudyID": "Study ID",
        "AccessionNumber": "Accession number",
        "StudyDate": "Study date",
        "SeriesDate": "Series date",
        "AcquisitionDate": "Acquisition date",
        "ContentDate": "Content date",
    },
}


# ═════════════════════════════════════════════
#  LÓGICA DE PROCESAMIENTO
# ═════════════════════════════════════════════

def _save_dataset(ds, out_path):
    """
    Guarda preservando el file_meta / TransferSyntax original.
    Compatible con pydicom 2.x (write_like_original) y 3.x (enforce_file_format).
    Escribe primero a un archivo temporal y luego renombra (escritura atómica),
    para no dejar DICOM truncados si el proceso se cancela a media escritura.
    """
    tmp_path = out_path + ".part"
    try:
        ds.save_as(tmp_path, enforce_file_format=False)  # pydicom >= 3
    except TypeError:
        ds.save_as(tmp_path, write_like_original=True)   # pydicom < 3
    os.replace(tmp_path, out_path)


def _anon_worker(args):
    """
    Worker de PROCESO (picklable, sin objetos de GUI).
    Anonimiza un archivo: PatientName + PatientID = anon_code, más los
    campos opcionales seleccionados (extra_keywords), que se vacían ("").
    Devuelve ('ok'|'skipped'|'error', mensaje_o_None).
    Preserva UIDs, geometría y tags temporales.
    """
    file_path, input_dir, output_dir, anon_code, extra_keywords = args
    try:
        ds = pydicom.dcmread(file_path)  # force=False: si no es DICOM, excepción -> skipped
    except Exception as e:
        return ("skipped", f"{file_path}: {e}")

    for keyword in ANON_KEYWORDS:
        if keyword in PROTECTED_KEYWORDS:
            continue
        if keyword in ds:
            setattr(ds, keyword, anon_code)

    for keyword in extra_keywords:
        if keyword in PROTECTED_KEYWORDS:
            continue
        if keyword in ds:
            setattr(ds, keyword, "")

    relative_path = os.path.relpath(file_path, input_dir)
    output_file_path = os.path.join(output_dir, relative_path)
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

    try:
        _save_dataset(ds, output_file_path)
        return ("ok", None)
    except Exception as e:
        return ("error", f"{file_path}: {e}")


def anonymize_dicom_files(input_dir, output_dir, max_workers, anon_code, progress_callback,
                          extra_keywords=frozenset()):
    """
    Recorre input_dir recursivamente y anonimiza EN PARALELO usando procesos
    (ProcessPoolExecutor), que aprovecha todos los núcleos (a diferencia de los
    hilos, limitados por el GIL para el parseo de pydicom).
    El proceso padre agrega contadores y reporta progreso a medida que terminan.
    `extra_keywords`: campos opcionales adicionales a vaciar (ver OPTIONAL_ANON_FIELDS).
    """
    logging.info("Iniciando anonimización (procesos) en: %s", input_dir)
    file_paths = [
        os.path.join(root, f)
        for root, _, files in os.walk(input_dir)
        for f in files
    ]
    total = len(file_paths)
    logging.info("Archivos encontrados: %d", total)

    counters = {"done": 0, "ok": 0, "errors": 0, "skipped": 0}
    if total == 0:
        return counters, total

    tasks = [(fp, input_dir, output_dir, anon_code, extra_keywords) for fp in file_paths]
    # chunksize amortiza el coste de IPC cuando hay muchísimos archivos pequeños.
    chunksize = max(1, min(64, total // (max_workers * 4) or 1))

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        result_iter = executor.map(_anon_worker, tasks, chunksize=chunksize)
        try:
            for status, msg in result_iter:
                counters["done"] += 1
                if status == "ok":
                    counters["ok"] += 1
                elif status == "skipped":
                    counters["skipped"] += 1
                    if msg:
                        logging.debug("Omitido %s", msg)
                else:
                    counters["errors"] += 1
                    if msg:
                        logging.error("Error %s", msg)
                progress_callback(counters["done"], total)

                if cancel_event.is_set():
                    logging.warning("Cancelación solicitada: deteniendo envío de tareas.")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
        except Exception as e:
            logging.error("Fallo en el pool de procesos: %s", e)
            raise

    logging.info(
        "Anonimización completada – OK:%d  Errores:%d  Omitidos:%d",
        counters["ok"], counters["errors"], counters["skipped"],
    )
    return counters, total


ARCHIVE_EXTS = (".zip", ".7z", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")


def is_archive(path):
    """True si la ruta es un archivo comprimido soportado."""
    p = path.lower()
    return os.path.isfile(path) and p.endswith(ARCHIVE_EXTS)


def archive_basename(path):
    """Nombre base del comprimido sin su extensión (para usar como código por defecto)."""
    name = os.path.basename(path)
    low = name.lower()
    for ext in sorted(ARCHIVE_EXTS, key=len, reverse=True):
        if low.endswith(ext):
            return name[: -len(ext)]
    return os.path.splitext(name)[0]


def _is_within(base, target):
    """Evita path traversal: target debe quedar dentro de base."""
    base = os.path.realpath(base)
    target = os.path.realpath(target)
    return target == base or target.startswith(base + os.sep)


def extract_archive(archive_path, dest_dir):
    """
    Descomprime de forma segura (rechaza rutas absolutas o con '..').
    Soporta zip y tar (gz/bz2/xz).
    """
    import zipfile
    import tarfile

    low = archive_path.lower()

    if low.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zf:
            for member in zf.namelist():
                out = os.path.join(dest_dir, member)
                if not _is_within(dest_dir, out):
                    raise RuntimeError(f"Entrada insegura en ZIP: {member}")
            zf.extractall(dest_dir)
    elif low.endswith(".7z"):
        try:
            import py7zr
        except ImportError:
            import sys
            raise RuntimeError(
                "Falta la librería py7zr para archivos .7z.\n"
                f"Instálala en ESTE Python:\n    {sys.executable} -m pip install py7zr")
        try:
            # 1) Inspección de nombres (control de traversal) en una apertura.
            with py7zr.SevenZipFile(archive_path, "r") as zf:
                names = zf.getnames()
            for member in names:
                out = os.path.join(dest_dir, member)
                if not _is_within(dest_dir, out):
                    raise RuntimeError(f"Entrada insegura en 7z: {member}")
            # 2) Reapertura limpia para extraer (evita problemas de posición de stream
            #    entre versiones de py7zr).
            with py7zr.SevenZipFile(archive_path, "r") as zf:
                zf.extractall(path=dest_dir)
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"py7zr no pudo extraer '{os.path.basename(archive_path)}': {e}")
    else:
        with tarfile.open(archive_path) as tf:
            for member in tf.getmembers():
                out = os.path.join(dest_dir, member.name)
                if not _is_within(dest_dir, out):
                    raise RuntimeError(f"Entrada insegura en TAR: {member.name}")
            try:
                tf.extractall(dest_dir, filter="data")  # Python >= 3.12
            except TypeError:
                tf.extractall(dest_dir)


def _resolved_input_root(extract_dir):
    """
    Si el comprimido tenía una única carpeta raíz, usarla como entrada
    (rutas relativas más limpias). Si no, usar el propio directorio de extracción.
    """
    entries = [e for e in os.listdir(extract_dir) if not e.startswith(".")]
    if len(entries) == 1:
        only = os.path.join(extract_dir, entries[0])
        if os.path.isdir(only):
            return only
    return extract_dir


def run_dicomsorter(input_dir, output_dir, n_files):
    """
    Ejecuta dicomsorter. Timeout escalado al número de archivos (min 5 min).
    ⚠ dicomsorter reorganiza archivos y es el sospechoso #1 de "romper" series 4D.
    """
    timeout = max(300, n_files // 2)  # ~0.5 s por archivo, mínimo 5 min
    logging.info("Ejecutando dicomsorter (timeout %ds): %s → %s", timeout, input_dir, output_dir)
    try:
        result = subprocess.run(
            ["dicomsorter", input_dir, output_dir],
            capture_output=True, text=True, timeout=timeout,
        )
        logging.debug("dicomsorter stdout: %s", result.stdout)
        if result.returncode != 0:
            logging.error("dicomsorter stderr: %s", result.stderr)
            if "pydicom.dicomdir" in (result.stderr or ""):
                raise RuntimeError(
                    "dicomsorter es incompatible con pydicom 3.x "
                    "(pydicom.dicomdir se eliminó en 3.0).\n"
                    "Instala pydicom 2.x en el entorno de dicomsorter, por ejemplo:\n"
                    "    <python_de_dicomsorter> -m pip install \"pydicom<3\"")
            raise RuntimeError(result.stderr)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"dicomsorter superó el tiempo límite ({timeout}s).")
    except FileNotFoundError:
        raise RuntimeError("'dicomsorter' no está instalado o no está en el PATH.")


def anonymize_subject(source, output_dir, max_workers, anon_code, run_sorter,
                      progress_callback, status_callback=None, extra_keywords=frozenset()):
    """
    Núcleo reutilizable: anonimiza UN sujeto hacia output_dir.
    `source` puede ser una CARPETA o un ARCHIVO COMPRIMIDO (zip/tar.*).
    Si es comprimido, se descomprime a un temporal que se limpia al terminar.
    `extra_keywords`: campos opcionales adicionales a vaciar (ver OPTIONAL_ANON_FIELDS).
    Devuelve (counters, total). Lanza excepción si algo falla.
    """
    with contextlib.ExitStack() as stack:
        # Resolver la entrada: carpeta directa o comprimido -> extraer a temporal.
        if is_archive(source):
            if status_callback:
                status_callback(tr("status_extracting"))
            logging.info("Descomprimiendo sujeto: %s", source)
            extract_dir = stack.enter_context(
                tempfile.TemporaryDirectory(prefix="dicom_extract_"))
            extract_archive(source, extract_dir)
            input_dir = _resolved_input_root(extract_dir)
        else:
            input_dir = source

        logging.info("Sujeto: %s  →  %s   (código='%s')", input_dir, output_dir, anon_code)
        if status_callback:
            status_callback(tr("status_anonymizing"))

        if run_sorter:
            # Intermedio: anonimizar y luego dejar que dicomsorter escriba el destino.
            temp_dir = stack.enter_context(
                tempfile.TemporaryDirectory(prefix="dicom_anon_"))
            logging.debug("Directorio temporal: %s", temp_dir)
            counters, total = anonymize_dicom_files(
                input_dir, temp_dir, max_workers, anon_code, progress_callback,
                extra_keywords=extra_keywords
            )
            if cancel_event.is_set():
                return counters, total
            if status_callback:
                status_callback(tr("status_running_sorter"))
            run_dicomsorter(temp_dir, output_dir, total)
        else:
            # Escritura DIRECTA al destino: la mitad de I/O (sin copytree posterior).
            os.makedirs(output_dir, exist_ok=True)
            counters, total = anonymize_dicom_files(
                input_dir, output_dir, max_workers, anon_code, progress_callback,
                extra_keywords=extra_keywords
            )

    return counters, total


def process_images(input_dir, output_dir, max_workers, anon_code, run_sorter,
                   status_label, progress_bar, progress_label, cancel_button,
                   extra_keywords=frozenset()):
    """Orquesta la anonimización de UN sujeto (modo pestaña Principal)."""
    cancel_event.clear()

    def update_progress(done, total):
        pct = int(done / total * 100) if total else 0
        progress_bar.after(0, lambda: progress_bar.config(value=pct))
        progress_label.after(0, lambda: progress_label.config(
            text=tr("progress_fmt", done=done, total=total, pct=pct)
        ))

    try:
        counters, _ = anonymize_subject(
            input_dir, output_dir, max_workers, anon_code, run_sorter,
            update_progress, status_callback=lambda t: safe_update(status_label, t),
            extra_keywords=extra_keywords
        )

        if cancel_event.is_set():
            safe_update(status_label, tr("status_cancelled"))
            return

        summary = tr("status_completed_fmt", ok=counters['ok'], errors=counters['errors'], skipped=counters['skipped'])
        safe_update(status_label, summary)
        messagebox.showinfo(tr("msg_completed_title"), summary)

    except Exception as e:
        logging.error("Error en process_images: %s", e)
        safe_update(status_label, tr("status_error_fmt", e=e))
        messagebox.showerror(tr("msg_error_title"), str(e))

    finally:
        cancel_button.after(0, lambda: cancel_button.config(state="disabled"))


def sanitize_code(code):
    """Convierte un código en un nombre de carpeta seguro."""
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in code.strip())
    return safe or "sujeto"


def process_batch(subjects, output_root, max_workers, run_sorter,
                  status_label, subj_progress_bar, subj_progress_label,
                  file_progress_bar, file_progress_label, tree, cancel_button,
                  extra_keywords=frozenset()):
    """
    Procesa una lista de sujetos EN SERIE.
    subjects: lista de dicts {'input': ruta, 'code': str, 'iid': id_en_treeview}
    Cada sujeto se anonimiza a output_root/<code sanitizado>.
    """
    cancel_event.clear()
    total_subj = len(subjects)
    aggregate = {"ok": 0, "errors": 0, "skipped": 0}

    def set_row(iid, estado):
        tree.after(0, lambda: tree.set(iid, "estado", estado))

    for idx, subj in enumerate(subjects, start=1):
        if cancel_event.is_set():
            safe_update(status_label, tr("batch_cancelled"))
            break

        input_dir = subj["input"]
        code = subj["code"].strip() or DEFAULT_ANON_CODE
        iid = subj["iid"]
        out_dir = os.path.join(output_root, sanitize_code(code))

        safe_update(status_label, tr("batch_processing_fmt", idx=idx, total=total_subj,
                                     name=os.path.basename(input_dir)))
        subj_progress_bar.after(0, lambda i=idx: subj_progress_bar.config(
            value=int((i - 1) / total_subj * 100)))
        subj_progress_label.after(0, lambda i=idx: subj_progress_label.config(
            text=tr("subj_label_fmt", i=i, total=total_subj)))
        set_row(iid, tr("tree_processing"))

        def update_file_progress(done, total):
            pct = int(done / total * 100) if total else 0
            file_progress_bar.after(0, lambda: file_progress_bar.config(value=pct))
            file_progress_label.after(0, lambda d=done, t=total, p=pct: file_progress_label.config(
                text=tr("progress_fmt", done=d, total=t, pct=p)))

        try:
            counters, _ = anonymize_subject(
                input_dir, out_dir, max_workers, code, run_sorter, update_file_progress,
                extra_keywords=extra_keywords
            )
            for k in aggregate:
                aggregate[k] += counters[k]

            if cancel_event.is_set():
                set_row(iid, tr("tree_cancelled"))
                break
            set_row(iid, f"✔ {counters['ok']}  ✗ {counters['errors']}  ⊘ {counters['skipped']}")
            logging.info("Sujeto '%s' completado.", code)

        except Exception as e:
            logging.error("Error en sujeto '%s': %s", code, e)
            set_row(iid, tr("tree_error_fmt", e=e))
            aggregate["errors"] += 1
            # continúa con el siguiente sujeto en vez de abortar todo el lote

    subj_progress_bar.after(0, lambda: subj_progress_bar.config(value=100))
    summary = tr("batch_summary_fmt", total=total_subj, ok=aggregate['ok'],
                errors=aggregate['errors'], skipped=aggregate['skipped'])
    safe_update(status_label, summary)
    messagebox.showinfo(tr("msg_batch_completed_title"), summary)
    cancel_button.after(0, lambda: cancel_button.config(state="disabled"))


# ═════════════════════════════════════════════
#  UTILIDADES DE GUI
# ═════════════════════════════════════════════

def safe_update(widget, text):
    widget.after(0, lambda: widget.config(text=text))


def browse_or_create_directory(entry, title=None):
    directory = filedialog.askdirectory(title=title or tr("dlg_select_input"))
    if directory:
        entry.delete(0, tk.END)
        entry.insert(0, directory)


def create_directory_from_entry(entry):
    path = entry.get().strip()
    if not path:
        messagebox.showwarning(tr("msg_empty_path_title"), tr("msg_empty_path_body"))
        return
    if os.path.isdir(path):
        messagebox.showinfo(tr("msg_dir_exists_title"), tr("msg_dir_exists_body", path=path))
        return
    try:
        os.makedirs(path, exist_ok=True)
        messagebox.showinfo(tr("msg_dir_created_title"), tr("msg_dir_created_body", path=path))
        logging.info("Directorio creado: %s", path)
    except Exception as e:
        messagebox.showerror(tr("msg_error_title"), tr("msg_dir_create_fail", e=e))


def poll_log_queue(log_text, root):
    try:
        while True:
            msg = log_queue.get_nowait()
            log_text.config(state="normal")
            log_text.insert(tk.END, msg + "\n")
            log_text.see(tk.END)
            log_text.config(state="disabled")
    except queue.Empty:
        pass
    root.after(200, poll_log_queue, log_text, root)


# ═════════════════════════════════════════════
#  INTERFAZ PRINCIPAL
# ═════════════════════════════════════════════

def start_processing(input_entry, output_entry, code_entry, workers_var, sorter_var,
                     status_label, progress_bar, progress_label,
                     process_button, cancel_button, get_extra_keywords):
    input_dir = input_entry.get().strip()
    output_dir = output_entry.get().strip()
    anon_code = code_entry.get().strip() or DEFAULT_ANON_CODE

    if not (os.path.isdir(input_dir) or is_archive(input_dir)):
        messagebox.showerror(tr("msg_error_title"), tr("msg_invalid_input"))
        return

    if not os.path.isdir(output_dir):
        if messagebox.askyesno(tr("msg_dir_not_exist_title"),
                               tr("msg_output_not_exist_body", output_dir=output_dir)):
            try:
                os.makedirs(output_dir, exist_ok=True)
                logging.info("Directorio de salida creado: %s", output_dir)
            except Exception as e:
                messagebox.showerror(tr("msg_error_title"), tr("msg_dir_create_fail", e=e))
                return
        else:
            return

    max_workers = workers_var.get()
    run_sorter = sorter_var.get()
    extra_keywords = get_extra_keywords()

    progress_bar.config(value=0)
    progress_label.config(text=tr("progress_default"))

    def worker():
        try:
            process_images(
                input_dir, output_dir, max_workers, anon_code, run_sorter,
                status_label, progress_bar, progress_label, cancel_button,
                extra_keywords=extra_keywords
            )
        finally:
            process_button.after(0, lambda: process_button.config(state="normal"))

    process_button.config(state="disabled")
    cancel_button.config(state="normal")
    threading.Thread(target=worker, daemon=True).start()


def start_batch(subjects, output_root, workers_var, sorter_var, tree,
                status_label, subj_bar, subj_label, file_bar, file_label,
                run_button, cancel_button, get_extra_keywords):
    """Valida y lanza el procesamiento en serie de varios sujetos."""
    if not subjects:
        messagebox.showwarning(tr("msg_no_subjects_title"), tr("msg_no_subjects_body"))
        return
    if not output_root:
        messagebox.showerror(tr("msg_error_title"), tr("msg_select_output_root"))
        return

    for s in subjects:
        if not (os.path.isdir(s["input"]) or is_archive(s["input"])):
            messagebox.showerror(tr("msg_error_title"), tr("msg_invalid_subject_input", input=s['input']))
            return

    if not os.path.isdir(output_root):
        if messagebox.askyesno(tr("msg_dir_not_exist_title"),
                               tr("msg_root_not_exist_body", output_root=output_root)):
            os.makedirs(output_root, exist_ok=True)
        else:
            return

    max_workers = workers_var.get()
    run_sorter = sorter_var.get()
    extra_keywords = get_extra_keywords()

    subj_bar.config(value=0)
    file_bar.config(value=0)

    def worker():
        try:
            process_batch(
                subjects, output_root, max_workers, run_sorter,
                status_label, subj_bar, subj_label, file_bar, file_label,
                tree, cancel_button, extra_keywords=extra_keywords
            )
        finally:
            run_button.after(0, lambda: run_button.config(state="normal"))

    run_button.config(state="disabled")
    cancel_button.config(state="normal")
    threading.Thread(target=worker, daemon=True).start()


def restart_app():
    """Relanza el proceso completo (necesario para aplicar el nuevo idioma)."""
    save_language(APP_LANGUAGE)
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        logging.error("No se pudo reiniciar automáticamente: %s", e)


def main():
    global APP_LANGUAGE

    root = tk.Tk()
    root.title(tr("app_title"))
    root.resizable(True, True)

    # ── Barra de menú: Idioma + Ayuda ─────────────────────────────────
    menubar = tk.Menu(root)
    root.config(menu=menubar)

    lang_var = tk.StringVar(value=APP_LANGUAGE)

    def on_lang_change():
        global APP_LANGUAGE
        new_lang = lang_var.get()
        if new_lang == APP_LANGUAGE:
            return
        if messagebox.askyesno(tr("restart_confirm_title"), tr("restart_confirm_body")):
            APP_LANGUAGE = new_lang
            root.destroy()
            restart_app()
        else:
            lang_var.set(APP_LANGUAGE)

    lang_menu = tk.Menu(menubar, tearoff=0)
    lang_menu.add_radiobutton(label=tr("lang_name_es"), value="es", variable=lang_var,
                              command=on_lang_change)
    lang_menu.add_radiobutton(label=tr("lang_name_en"), value="en", variable=lang_var,
                              command=on_lang_change)
    menubar.add_cascade(label=tr("menu_language"), menu=lang_menu)

    def show_about():
        messagebox.showinfo(tr("about_title"), tr("about_body"))

    def show_help():
        messagebox.showinfo(tr("help_title"), tr("help_body"))

    help_menu = tk.Menu(menubar, tearoff=0)
    help_menu.add_command(label=tr("menu_about_item"), command=show_about)
    help_menu.add_command(label=tr("menu_help_item"), command=show_help)
    menubar.add_cascade(label=tr("menu_help"), menu=help_menu)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=8, pady=8)

    # Estado compartido de los campos opcionales (desactivados por defecto).
    # Lo usan tanto la pestaña Principal como la de Lote.
    extra_field_vars = {kw: tk.BooleanVar(value=False) for kw, _ in OPTIONAL_ANON_FIELDS}

    def get_selected_extra_keywords():
        return frozenset(kw for kw, var in extra_field_vars.items() if var.get())

    # ── Pestaña 1: Principal ──────────────────────────────────────────
    tab_main = ttk.Frame(notebook, padding=10)
    notebook.add(tab_main, text=tr("tab_main"))

    ttk.Label(tab_main, text=tr("input_label")).grid(row=0, column=0, sticky="w", pady=4)
    input_entry = ttk.Entry(tab_main, width=52)
    input_entry.grid(row=0, column=1, padx=4)
    in_btn_frame = ttk.Frame(tab_main)
    in_btn_frame.grid(row=0, column=2)
    ttk.Button(in_btn_frame, text=tr("btn_browse"),
               command=lambda: browse_or_create_directory(input_entry, tr("dlg_select_input"))).pack(side="left")

    def pick_archive():
        f = filedialog.askopenfilename(
            title=tr("dlg_select_archive"),
            filetypes=[(tr("filetype_archives"), "*.zip *.7z *.tar *.gz *.tgz *.bz2 *.tbz2 *.xz *.txz"),
                       (tr("filetype_all"), "*.*")])
        if f:
            input_entry.delete(0, tk.END)
            input_entry.insert(0, f)

    ttk.Button(in_btn_frame, text=tr("btn_archive"), command=pick_archive).pack(side="left", padx=(4, 0))

    ttk.Label(tab_main, text=tr("output_label")).grid(row=1, column=0, sticky="w", pady=4)
    output_entry = ttk.Entry(tab_main, width=52)
    output_entry.grid(row=1, column=1, padx=4)

    out_btn_frame = ttk.Frame(tab_main)
    out_btn_frame.grid(row=1, column=2, padx=0)
    ttk.Button(out_btn_frame, text=tr("btn_browse"),
               command=lambda: browse_or_create_directory(output_entry, tr("dlg_select_output"))).pack(side="left")
    ttk.Button(out_btn_frame, text=tr("btn_create"),
               command=lambda: create_directory_from_entry(output_entry)).pack(side="left", padx=(4, 0))

    ttk.Separator(tab_main, orient="horizontal").grid(row=2, column=0, columnspan=3, sticky="ew", pady=8)

    # Código de anonimización (nuevo Nombre e ID)
    ttk.Label(tab_main, text=tr("code_label")).grid(row=3, column=0, sticky="w", pady=4)
    code_entry = ttk.Entry(tab_main, width=30)
    code_entry.grid(row=3, column=1, sticky="w", padx=4)
    ttk.Label(
        tab_main,
        text=tr("code_hint"),
        foreground="#0a7", justify="left"
    ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 6))

    # Procesos paralelos
    ttk.Label(tab_main, text=tr("workers_label")).grid(row=5, column=0, sticky="w")
    default_workers = min(16, max(1, (os.cpu_count() or 4)))
    workers_var = tk.IntVar(value=default_workers)
    workers_scale = ttk.Scale(tab_main, from_=1, to=32, orient="horizontal",
                              variable=workers_var, length=180)
    workers_scale.grid(row=5, column=1, sticky="w", padx=4)
    workers_lbl = ttk.Label(tab_main, text=str(default_workers))
    workers_lbl.grid(row=5, column=2, sticky="w")
    workers_var.trace_add("write", lambda *_: workers_lbl.config(text=str(workers_var.get())))

    # dicomsorter — DESACTIVADO por defecto
    sorter_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        tab_main,
        text=tr("sorter_check"),
        variable=sorter_var
    ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 2))

    ttk.Separator(tab_main, orient="horizontal").grid(row=7, column=0, columnspan=3, sticky="ew", pady=8)

    progress_bar = ttk.Progressbar(tab_main, orient="horizontal", length=460, mode="determinate")
    progress_bar.grid(row=8, column=0, columnspan=3, pady=(0, 4))

    progress_label = ttk.Label(tab_main, text=tr("progress_default"))
    progress_label.grid(row=9, column=0, columnspan=3)

    status_label = ttk.Label(tab_main, text=tr("status_waiting"), foreground="gray")
    status_label.grid(row=10, column=0, columnspan=3, pady=(4, 0))

    btn_frame = ttk.Frame(tab_main)
    btn_frame.grid(row=11, column=0, columnspan=3, pady=10)

    process_button = ttk.Button(btn_frame, text=tr("btn_process"), width=18)
    cancel_button = ttk.Button(btn_frame, text=tr("btn_cancel"), width=14, state="disabled",
                               command=lambda: cancel_event.set())
    process_button.pack(side="left", padx=6)
    cancel_button.pack(side="left", padx=6)

    # ── Pestaña 2: Lote (varios sujetos en serie) ────────────────────
    tab_batch = ttk.Frame(notebook, padding=10)
    notebook.add(tab_batch, text=tr("tab_batch"))

    ttk.Label(tab_batch,
              text=tr("batch_intro"),
              justify="left").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

    # Salida raíz
    ttk.Label(tab_batch, text=tr("batch_output_label")).grid(row=1, column=0, sticky="w")
    batch_out_entry = ttk.Entry(tab_batch, width=48)
    batch_out_entry.grid(row=1, column=1, columnspan=2, sticky="w", padx=4)
    ttk.Button(tab_batch, text=tr("btn_browse"),
               command=lambda: browse_or_create_directory(batch_out_entry, tr("dlg_batch_output"))
               ).grid(row=1, column=3, sticky="w")

    # Tabla de sujetos
    columns = ("carpeta", "codigo", "estado")
    tree = ttk.Treeview(tab_batch, columns=columns, show="headings", height=10)
    tree.heading("carpeta", text=tr("col_folder"))
    tree.heading("codigo", text=tr("col_code"))
    tree.heading("estado", text=tr("col_status"))
    tree.column("carpeta", width=300)
    tree.column("codigo", width=140)
    tree.column("estado", width=180)
    tree.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=8)

    tree_scroll = ttk.Scrollbar(tab_batch, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=tree_scroll.set)
    tree_scroll.grid(row=2, column=4, sticky="ns", pady=8)

    tab_batch.rowconfigure(2, weight=1)
    tab_batch.columnconfigure(1, weight=1)

    # Lista interna de sujetos: {input, code, iid}
    subjects = []

    def _refresh_codes_from_tree():
        for s in subjects:
            s["code"] = tree.set(s["iid"], "codigo")

    def add_subject_folder():
        d = filedialog.askdirectory(title=tr("dlg_subject_folder"))
        if not d:
            return
        code = os.path.basename(d.rstrip("/\\")) or f"sujeto{len(subjects)+1}"
        iid = tree.insert("", tk.END, values=(d, code, tr("status_pending")))
        subjects.append({"input": d, "code": code, "iid": iid})

    def add_subfolders():
        parent = filedialog.askdirectory(title=tr("dlg_subfolders"))
        if not parent:
            return
        added = 0
        for name in sorted(os.listdir(parent)):
            full = os.path.join(parent, name)
            if os.path.isdir(full):
                iid = tree.insert("", tk.END, values=(full, name, tr("status_pending")))
                subjects.append({"input": full, "code": name, "iid": iid})
                added += 1
        logging.info("Añadidos %d sujetos desde %s", added, parent)

    def add_archives():
        files = filedialog.askopenfilenames(
            title=tr("dlg_archives"),
            filetypes=[(tr("filetype_archives"), "*.zip *.7z *.tar *.gz *.tgz *.bz2 *.tbz2 *.xz *.txz"),
                       (tr("filetype_all"), "*.*")])
        added = 0
        for f in files:
            if not is_archive(f):
                logging.warning("Omitido (no es comprimido soportado): %s", f)
                continue
            code = archive_basename(f)
            iid = tree.insert("", tk.END, values=(f, code, tr("status_pending_zip")))
            subjects.append({"input": f, "code": code, "iid": iid})
            added += 1
        if added:
            logging.info("Añadidos %d sujetos comprimidos", added)

    def add_archives_from_folder():
        parent = filedialog.askdirectory(
            title=tr("dlg_archives_folder"))
        if not parent:
            return
        added = 0
        for name in sorted(os.listdir(parent)):
            full = os.path.join(parent, name)
            if is_archive(full):
                code = archive_basename(full)
                iid = tree.insert("", tk.END, values=(full, code, tr("status_pending_zip")))
                subjects.append({"input": full, "code": code, "iid": iid})
                added += 1
        logging.info("Añadidos %d comprimidos desde %s", added, parent)
        if added == 0:
            messagebox.showinfo(tr("msg_no_archives_title"),
                                tr("msg_no_archives_body", parent=parent))

    def remove_selected():
        for iid in tree.selection():
            tree.delete(iid)
            subjects[:] = [s for s in subjects if s["iid"] != iid]

    def clear_all():
        for iid in tree.get_children():
            tree.delete(iid)
        subjects.clear()

    # Edición inline del código con doble clic
    def on_double_click(event):
        if tree.identify_region(event.x, event.y) != "cell":
            return
        col = tree.identify_column(event.x)
        if col != "#2":  # solo la columna 'codigo' es editable
            return
        iid = tree.identify_row(event.y)
        if not iid:
            return
        x, y, w, h = tree.bbox(iid, col)
        edit = ttk.Entry(tree)
        edit.insert(0, tree.set(iid, "codigo"))
        edit.select_range(0, tk.END)
        edit.focus()
        edit.place(x=x, y=y, width=w, height=h)

        def save(_=None):
            tree.set(iid, "codigo", edit.get().strip())
            _refresh_codes_from_tree()
            edit.destroy()

        edit.bind("<Return>", save)
        edit.bind("<FocusOut>", save)
        edit.bind("<Escape>", lambda e: edit.destroy())

    tree.bind("<Double-1>", on_double_click)

    batch_btns = ttk.Frame(tab_batch)
    batch_btns.grid(row=3, column=0, columnspan=4, sticky="w", pady=(0, 6))
    ttk.Button(batch_btns, text=tr("btn_add_subject"), command=add_subject_folder).pack(side="left", padx=(0, 6))
    ttk.Button(batch_btns, text=tr("btn_add_subfolders"), command=add_subfolders).pack(side="left", padx=(0, 6))
    ttk.Button(batch_btns, text=tr("btn_add_archives"), command=add_archives).pack(side="left", padx=(0, 6))
    ttk.Button(batch_btns, text=tr("btn_add_archives_folder"), command=add_archives_from_folder).pack(side="left", padx=(0, 6))
    ttk.Button(batch_btns, text=tr("btn_remove"), command=remove_selected).pack(side="left", padx=(0, 6))
    ttk.Button(batch_btns, text=tr("btn_clear"), command=clear_all).pack(side="left")

    ttk.Label(tab_batch, text=tr("edit_hint"),
              foreground="gray").grid(row=4, column=0, columnspan=4, sticky="w")

    # dicomsorter propio del lote (activado por defecto)
    batch_sorter_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        tab_batch,
        text=tr("batch_sorter_check"),
        variable=batch_sorter_var
    ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))

    # Progreso del lote
    batch_subj_label = ttk.Label(tab_batch, text=tr("subj_label_default"))
    batch_subj_label.grid(row=6, column=0, columnspan=4, sticky="w", pady=(8, 0))
    batch_subj_bar = ttk.Progressbar(tab_batch, orient="horizontal", length=520, mode="determinate")
    batch_subj_bar.grid(row=7, column=0, columnspan=4, sticky="w", pady=(0, 4))

    batch_file_label = ttk.Label(tab_batch, text=tr("progress_default"))
    batch_file_label.grid(row=8, column=0, columnspan=4, sticky="w")
    batch_file_bar = ttk.Progressbar(tab_batch, orient="horizontal", length=520, mode="determinate")
    batch_file_bar.grid(row=9, column=0, columnspan=4, sticky="w", pady=(0, 4))

    batch_status = ttk.Label(tab_batch, text=tr("status_waiting"), foreground="gray")
    batch_status.grid(row=10, column=0, columnspan=4, sticky="w", pady=(4, 0))

    batch_action = ttk.Frame(tab_batch)
    batch_action.grid(row=11, column=0, columnspan=4, pady=10, sticky="w")
    batch_run_btn = ttk.Button(batch_action, text=tr("btn_batch_process"), width=18)
    batch_cancel_btn = ttk.Button(batch_action, text=tr("btn_cancel"), width=14, state="disabled",
                                  command=lambda: cancel_event.set())
    batch_run_btn.pack(side="left", padx=6)
    batch_cancel_btn.pack(side="left", padx=6)

    batch_run_btn.config(
        command=lambda: (
            _refresh_codes_from_tree(),
            start_batch(
                subjects, batch_out_entry.get().strip(), workers_var, batch_sorter_var, tree,
                batch_status, batch_subj_bar, batch_subj_label,
                batch_file_bar, batch_file_label, batch_run_btn, batch_cancel_btn,
                get_selected_extra_keywords
            )
        )
    )

    # ── Pestaña 3: Campos opcionales (NIH / HIPAA Safe Harbor) ────────
    tab_extra = ttk.Frame(notebook, padding=10)
    notebook.add(tab_extra, text=tr("tab_extra"))

    ttk.Label(
        tab_extra,
        text=tr("extra_intro"),
        justify="left", foreground="#555"
    ).pack(anchor="w", pady=(0, 8))

    extra_btns = ttk.Frame(tab_extra)
    extra_btns.pack(anchor="w", pady=(0, 8))
    ttk.Button(extra_btns, text=tr("btn_check_all"),
               command=lambda: [v.set(True) for v in extra_field_vars.values()]
               ).pack(side="left", padx=(0, 6))
    ttk.Button(extra_btns, text=tr("btn_uncheck_all"),
               command=lambda: [v.set(False) for v in extra_field_vars.values()]
               ).pack(side="left")

    # Área con scroll (hay ~30 checkboxes agrupados por categoría)
    extra_canvas = tk.Canvas(tab_extra, borderwidth=0, highlightthickness=0)
    extra_scroll = ttk.Scrollbar(tab_extra, orient="vertical", command=extra_canvas.yview)
    extra_inner = ttk.Frame(extra_canvas)

    extra_inner.bind(
        "<Configure>",
        lambda e: extra_canvas.configure(scrollregion=extra_canvas.bbox("all"))
    )
    extra_canvas.create_window((0, 0), window=extra_inner, anchor="nw")
    extra_canvas.configure(yscrollcommand=extra_scroll.set)

    extra_canvas.pack(side="left", fill="both", expand=True)
    extra_scroll.pack(side="right", fill="y")

    def _on_extra_scroll(event):
        extra_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    extra_canvas.bind_all("<MouseWheel>", _on_extra_scroll)

    current_category = None
    for keyword, category_slug in OPTIONAL_ANON_FIELDS:
        if category_slug != current_category:
            current_category = category_slug
            category_label = CATEGORY_LABELS[APP_LANGUAGE][category_slug]
            ttk.Label(extra_inner, text=category_label, font=("", 9, "bold")
                      ).pack(anchor="w", pady=(10, 2))
        field_label = FIELD_LABELS[APP_LANGUAGE][keyword]
        ttk.Checkbutton(
            extra_inner, text=f"{field_label}  ({keyword})",
            variable=extra_field_vars[keyword]
        ).pack(anchor="w", padx=(12, 0))

    # ── Pestaña 4: Log en tiempo real ────────────────────────────────
    tab_log = ttk.Frame(notebook, padding=6)
    notebook.add(tab_log, text=tr("tab_log"))

    log_text = tk.Text(tab_log, state="disabled", wrap="word", height=22,
                       font=("Courier", 9), background="#1e1e1e", foreground="#d4d4d4",
                       insertbackground="white")
    scrollbar = ttk.Scrollbar(tab_log, command=log_text.yview)
    log_text.config(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    log_text.pack(fill="both", expand=True)

    def clear_log():
        log_text.config(state="normal")
        log_text.delete("1.0", tk.END)
        log_text.config(state="disabled")

    def diagnostico():
        import sys
        logging.info("Python en uso: %s", sys.executable)
        logging.info("Versión: %s", sys.version.split()[0])
        for lib in ("pydicom", "py7zr"):
            try:
                mod = __import__(lib)
                ver = getattr(mod, "__version__", "?")
                path = getattr(mod, "__file__", "?")
                logging.info("✔ %s %s  (%s)", lib, ver, path)
            except Exception as e:
                logging.error("✘ %s NO disponible: %s", lib, e)
        logging.info("Formatos de comprimido soportados: %s", ", ".join(ARCHIVE_EXTS))

    log_btns = ttk.Frame(tab_log)
    log_btns.pack(anchor="e", pady=(4, 0))
    ttk.Button(log_btns, text=tr("btn_diagnostic"), command=diagnostico).pack(side="left", padx=(0, 6))
    ttk.Button(log_btns, text=tr("btn_clear_log"), command=clear_log).pack(side="left")

    # Conectar botón Procesar
    process_button.config(
        command=lambda: start_processing(
            input_entry, output_entry, code_entry, workers_var, sorter_var,
            status_label, progress_bar, progress_label,
            process_button, cancel_button, get_selected_extra_keywords
        )
    )

    root.after(200, poll_log_queue, log_text, root)
    logging.info("DICOM Anonymizer v3.0 iniciado – %s", datetime.now().strftime("%Y-%m-%d %H:%M"))
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()  # necesario si se congela en un ejecutable
    try:
        multiprocessing.set_start_method("spawn")  # evita fork con GUI/hilos activos
    except RuntimeError:
        pass  # ya estaba fijado
    main()
