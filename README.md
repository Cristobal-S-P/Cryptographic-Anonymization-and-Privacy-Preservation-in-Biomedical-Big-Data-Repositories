# Anonimización criptográfica y preservación de privacidad en repositorios de Big Data biomédico (Concepto de Zero-Knowledge Simplificado)

Implementación académica en Python para VS Code. Fragmenta un CSV clínico con PII simulada en dos repositorios enlazados por un pseudónimo criptográfico.

## Qué implementa

- **Una sal aleatoria de 128 bits por paciente**, reutilizada para todas sus filas.
- **PBKDF2-HMAC-SHA256** como salt stretching (`310000` iteraciones).
- **Cifrado reversible de nombre y RUT** mediante Fernet con una clave maestra local.
- `D_id_protegido.csv`: contiene PII cifrada, sal y material criptográfico; no contiene PII en claro.
- `D_ana_analitico.csv`: contiene variables clínicas y pseudónimo; no contiene nombre, RUT, sal ni secreto.
- **Prueba Schnorr simplificada** para demostrar posesión de una credencial pseudónima sin enviar PII al repositorio analítico.
- Consulta binaria de pertenencia a una cohorte de riesgo.
- Entropía de Shannon de caracteres hexadecimales del pseudónimo y de variables categóricas analíticas.
- Validación de datos, manejo de excepciones, tipado, clases y pruebas automáticas.

> La prueba Schnorr incluida es una demostración académica. No es una implementación certificada de ZKP para sistemas clínicos reales.

## Estructura

```text
proyecto7_vscode/
├─ main.py
├─ requirements.txt
├─ README.md
├─ src/
│  ├─ config.py
│  ├─ crypto_utils.py
│  ├─ entropy.py
│  ├─ ingestion.py
│  ├─ models.py
│  ├─ pipeline.py
│  ├─ repositories.py
│  ├─ sample_data.py
│  └─ verifier.py
├─ data/
│  ├─ input/
│  └─ output/
└─ tests/
   └─ test_pipeline.py
```

## Cómo ejecutar en VS Code

### 1. Abrir la carpeta

`Archivo > Abrir carpeta > proyecto7_vscode`

### 2. Crear entorno virtual

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Ejecutar demo completa

```powershell
python main.py --generate-demo
```

Para generar exactamente **1000 registros sintéticos** (200 pacientes × 5 registros):

```powershell
python main.py --generate-demo --patients 200 --records-per-patient 5
```

Esto crea un dataset sintético y luego genera:

- `data/output/D_id_protegido.csv`
- `data/output/D_ana_analitico.csv`
- `data/output/entropia.csv`
- `keys/master.key`

La carpeta `keys/` está excluida de Git mediante `.gitignore`. En un sistema real, la clave maestra debería mantenerse fuera del proyecto y gestionarse mediante un KMS/HSM o mecanismo equivalente.

### 4. Ejecutar tests

```powershell
pytest -q
```

## CSV de entrada

Columnas requeridas:

```text
subject_id,record_id,nombre,rut,edad,sexo,systolic_bp,diastolic_bp,heart_rate
```

Para trabajar con MIMIC-III Demo se debe hacer una etapa previa de extracción/merge que convierta las tablas seleccionadas de MIMIC a este esquema y agregue PII ficticia. El `subject_id` de MIMIC es la clave que garantiza que el mismo paciente tenga **un único pseudónimo**, aunque tenga múltiples registros.

## Flujo criptográfico

1. Para cada `subject_id` nuevo se genera una sal con `os.urandom(16)`.
2. El RUT normalizado pasa por PBKDF2-HMAC-SHA256 junto con la sal.
3. Se construye un pseudónimo SHA-256 estable para ese paciente.
4. Nombre y RUT se cifran con la clave maestra y se guardan únicamente en `D_id`.
5. Variables clínicas se copian a `D_ana` junto con el pseudónimo.
6. Se genera un secreto Schnorr aleatorio y solo su clave pública queda accesible al repositorio analítico.
7. En la consulta, el médico demuestra conocimiento del secreto mediante `commitment/challenge/response`; el RUT y el nombre no son transmitidos al repositorio analítico.

## Cohorte de riesgo

La demo utiliza como criterio configurable:

```text
PAS >= 140 mmHg OR PAD >= 90 mmHg
```

Se denomina **cohorte de riesgo** y no diagnóstico de hipertensión. Los umbrales se pueden modificar en `src/config.py`.

## Entropía

`entropia.py` calcula:

- entropía por carácter hexadecimal del pseudónimo (máximo teórico: 4 bits/carácter),
- entropía de sexo,
- entropía de grupo etario,
- entropía de pertenencia a la cohorte.

La entropía se calcula a partir de `D_ana`, usando los pseudónimos únicos para la métrica hexadecimal y las filas analíticas para las variables categóricas. Se reporta como **métrica complementaria** y no como demostración suficiente de anonimato o imposibilidad de reidentificación.

## Seguridad

Este proyecto es docente. En producción se requerirían, entre otras cosas, HSM/KMS, rotación de claves, control de acceso, auditoría, TLS, gestión formal de secretos, parámetros criptográficos estandarizados y una ZKP implementada con librerías auditadas.

## Usar MIMIC-III Demo directamente

Descarga MIMIC-III Clinical Database Demo v1.4 desde PhysioNet y deja, como mínimo, estos archivos dentro de una misma carpeta:

```text
PATIENTS.csv
D_ITEMS.csv
CHARTEVENTS.csv
```

Luego ejecuta:

```powershell
python main.py --mimic-dir "ruta/a/mimiciii-demo"
```

El adaptador descubre los `ITEMID` a partir de `D_ITEMS.csv`, extrae frecuencia cardíaca y presión arterial desde `CHARTEVENTS.csv`, agrupa las mediciones por hora y añade **nombre/RUT ficticios** exclusivamente para demostrar el proceso de protección de PII. Los datos clínicos originales de MIMIC permanecen desidentificados.
