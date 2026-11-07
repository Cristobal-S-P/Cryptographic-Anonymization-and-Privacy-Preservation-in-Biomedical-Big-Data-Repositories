# Anonimización criptográfica y preservación de privacidad en repositorios de Big Data biomédico (Concepto de Zero-Knowledge Simplificado)

Implementación académica en Python para VS Code. Fragmenta un CSV clínico con PII simulada en dos repositorios enlazados por un pseudónimo criptográfico.

## Qué implementa

- **Una sal aleatoria de 128 bits por paciente**, reutilizada para todas sus filas.
- **PBKDF2-HMAC-SHA256** como salt stretching (`310000` iteraciones).
- **Cifrado reversible de nombre y RUT** mediante Fernet con una clave maestra local.
- `D_id_protegido.csv`: contiene PII cifrada, sal y material criptográfico; no contiene PII en claro.
- `D_ana_analitico.csv`: contiene variables clínicas y pseudónimo; no contiene nombre, RUT, sal ni secreto.
- **Prueba didáctica de posesión Schnorr** para verificar conocimiento de una clave asociada a un pseudónimo, sin enviar la clave ni PII.
- Consulta binaria de pertenencia a una cohorte de riesgo.
- Entropía de Shannon de caracteres hexadecimales del pseudónimo y de variables categóricas analíticas.
- Validación de datos, manejo de excepciones, tipado, clases y pruebas automáticas.

> La prueba Schnorr es un prototipo académico de conocimiento de clave. No constituye por sí misma una autorización clínica, una prueba de una condición médica ni una implementación certificada de ZKP.

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
│  ├─ generate_key.py
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
   ├─ test_key_management.py
   ├─ test_performance.py
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
python -m pip install -r requirements.txt
```

El entorno `.venv/` está excluido de Git. `requirements.txt` declara los rangos de versiones para pandas, cryptography, numpy y pytest.

### 3. Crear la clave maestra local

```powershell
python -m src.generate_key
```

Esto crea `keys/master.key` si todavía no existe y se niega a sobrescribir una clave existente. La carpeta `keys/` está excluida de Git. **No compartas ni subas la clave**: los datos cifrados con ella no podrán recuperarse si se pierde. La aplicación no genera claves automáticamente; si falta una clave válida, muestra el comando para crearla.

No reemplaces una clave cuando haya datos cifrados que deban seguir siendo legibles. Para rotarla hace falta descifrar con la clave anterior y volver a cifrar con la nueva; la utilidad de este proyecto no realiza esa migración.

### 4. Ejecutar demo completa

```powershell
python main.py --generate-demo
```

Para generar exactamente **1000 registros sintéticos** (200 pacientes × 5 registros):

```powershell
python main.py --generate-demo --patients 200 --records-per-patient 5
```

Esto crea o reemplaza el CSV sintético de entrada y genera localmente:

- `data/output/D_id_protegido.csv`
- `data/output/D_ana_analitico.csv`
- `data/output/entropia.csv`

`keys/master.key` se genera por separado con `python -m src.generate_key` y nunca se incluye en Git. La aplicación requiere una clave existente y válida; si falta, muestra el comando para generarla y no crea ni reemplaza claves automáticamente.

Los CSV generados están excluidos de Git; se conservan localmente para inspección. No se debe versionar el entorno virtual, la clave ni las salidas de ejecución.

### 5. Ejecutar tests

```powershell
python -m pytest -q -s
```

La prueba `tests/test_performance.py` imprime un informe de una ejecución real: tiempo mediano medido con `timeit` para `verify_proof` y `query_risk`, registros procesados, tamaños en bytes de los CSV de entrada/salida y conteo de perturbaciones rechazadas. El conjunto sintético usa 20 pacientes × 5 registros; `timeit` ejecuta 3 repeticiones de 10 llamadas por operación. Estos valores fijan un tamaño de carga para repetir la medición, no son metas de rendimiento. No se compara la latencia con un umbral porque depende del equipo y del entorno.

Para repetir solo el informe, desde la raíz del proyecto:

```powershell
python -m pytest -q -s tests/test_performance.py
```

La prueba usa el generador sintético con semilla fija; los valores de rendimiento se miden en cada ejecución y pueden variar. El informe también imprime las versiones, la plataforma y el procesador detectados. En la ejecución de desarrollo documentada aquí se usaron Windows 11 (AMD64; AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD), Python 3.14.4, pandas 3.0.2, cryptography 50.0.0 y pytest 9.1.1. Este entorno ejecutado no coincide con los límites de pandas y cryptography declarados en `requirements.txt`; para reproducir dentro de los rangos del proyecto, crear un entorno virtual e instalar esas dependencias antes de ejecutar el comando. Los resultados deben interpretarse junto con el entorno que imprime cada corrida.

El informe cuantifica cinco perturbaciones de la prueba (compromiso inválido, respuesta alterada, nonce de la prueba alterado, pseudónimo distinto y alcance de consulta distinto). Se conserva además la cobertura existente de rangos de Schnorr y reuso de nonce en `tests/test_pipeline.py`.

## CSV de entrada

Columnas requeridas:

```text
subject_id,record_id,nombre,rut,edad,sexo,systolic_bp,diastolic_bp,heart_rate
```

El cargador rechaza encabezados faltantes o duplicados, filas vacías, campos
obligatorios vacíos, tipos numéricos inválidos, `record_id` duplicados,
inconsistencias de nombre/RUT por paciente y RUT que no cumplen el dígito
verificador chileno. Los identificadores y datos ausentes no se corrigen ni se
imputan automáticamente. Los errores señalan el número de fila y campo sin
incluir los valores personales.

Como validación técnica inicial se usan estos límites amplios: edad 0–120 años,
PAS 50–260 mmHg, PAD 20–180 mmHg y frecuencia cardíaca 20–250 lpm; además,
PAS debe ser estrictamente mayor que PAD. Estos límites no son criterios
diagnósticos y no sustituyen la revisión clínica de valores extremos.

Para trabajar con MIMIC-III Demo se debe hacer una etapa previa de extracción/merge que convierta las tablas seleccionadas de MIMIC a este esquema y agregue PII ficticia. El `subject_id` de MIMIC es la clave que garantiza que el mismo paciente tenga **un único pseudónimo**, aunque tenga múltiples registros.

## Flujo criptográfico

1. Para cada `subject_id` nuevo se genera una sal con `os.urandom(16)`.
2. El RUT normalizado pasa por PBKDF2-HMAC-SHA256 junto con la sal.
3. Se construye un pseudónimo SHA-256 estable para ese paciente.
4. Nombre y RUT se cifran con la clave maestra y se guardan únicamente en `D_id`.
5. Variables clínicas se copian a `D_ana` junto con el pseudónimo.
6. Se genera un secreto Schnorr aleatorio en memoria; solo la clave pública queda en los repositorios. El secreto no se imprime, registra ni persiste.
7. El verificador genera un nonce aleatorio de sesión. La prueba `commitment/challenge/response` queda ligada al nonce, al pseudónimo y al alcance de la consulta solicitada; una instancia de `RiskVerifier` acepta cada nonce emitido como máximo una vez.

### Parámetros y alcance de Schnorr

Se usan exactamente los parámetros MODP publicados en el **grupo 2.3 de [RFC 5114](https://www.rfc-editor.org/rfc/rfc5114#section-2.3)**:

- `P`: módulo primo de 2048 bits.
- `Q`: orden primo de 256 bits del subgrupo.
- `G`: generador de ese subgrupo, de orden `Q` (`G^Q mod P = 1`, `G != 1`).

La prueba del proyecto fija los valores hexadecimales de `P`, `Q` y `G` según esa sección, y comprueba `Q | P−1`, `1 < G < P`, `G^Q mod P = 1` y `G != 1`. RFC 5114 identifica `P` y `Q` como primos y `G` como generador del subgrupo; el proyecto no vuelve a demostrar la primalidad de 2048/256 bits de forma independiente. La validez criptográfica que aquí se comprueba se limita a esos parámetros publicados y las relaciones de grupo indicadas, no a la seguridad del protocolo completo.

La implementación deriva `c` por Fiat–Shamir a partir de la transcripción (pseudónimo, clave pública, compromiso, nonce de sesión y alcance de consulta), no recibe un desafío interactivo aparte. Usa `Y = G^x mod P`, `T = G^r mod P`, `z = (r + c*x) mod Q` y verifica `G^z mod P == T * Y^c mod P`. Se rechazan secretos fuera de `1 <= x < Q`, respuestas fuera de `0 <= z < Q`, y claves públicas o compromisos fuera del subgrupo. Las claves públicas se serializan como hexadecimal en los CSV para conservar sus 2048 bits sin coerciones numéricas de pandas.

El nonce aleatorio de 256 bits es emitido por `RiskVerifier` y expira a los cinco minutos (configurable al construir la instancia). Se marca como consumido únicamente después de verificar correctamente la prueba. El registro, expiración y consumo se protegen con un lock durante toda la verificación para evitar que dos hilos acepten simultáneamente el mismo nonce; una prueba inválida no lo consume.

El control anti-replay sigue siendo exclusivamente en memoria y local a una instancia: no se comparte entre procesos ni instancias y se pierde al reiniciar. Nonces de otra instancia o de una ejecución anterior se rechazan porque no constan como emitidos en la instancia actual. No proporciona protección distribuida o persistente. La consulta `query_risk(pseudonym, proof, session_nonce)` valida la prueba y solo entonces lee el riesgo: si falta la prueba, es inválida, el nonce expiró, no fue emitido por esa instancia o ya fue consumido, o la prueba corresponde a otro pseudónimo u otra consulta, se rechaza sin leer ni devolver el dato clínico. La prueba demuestra conocimiento de una clave privada asociada a una clave pública; no demuestra la identidad civil del paciente, la veracidad de los datos clínicos ni una autorización clínica completa. El resultado representa únicamente la regla configurada sobre los registros disponibles, no un diagnóstico.

El probador (que conserva el secreto) y el verificador (que solo consulta la clave pública) son roles lógicos dentro del mismo proceso académico, no dominios independientes de confianza. La clave privada Schnorr se mantiene en `PatientCredential` en memoria y no se guarda en `D_ana`.

La salida de demostración no imprime el `subject_id` local ni el pseudónimo. Indica si la prueba de posesión fue válida y muestra el resultado solo cuando la consulta protegida pasa la validación.

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

La entropía se calcula a partir de `D_ana`, usando los pseudónimos únicos para la métrica hexadecimal y las filas analíticas para las variables categóricas. Se reporta en la salida de la demo y en `entropia.csv` como **métrica complementaria**; no demuestra anonimato ni imposibilidad de reidentificación.

## Limitaciones y seguridad

Este es un proyecto académico, no un servicio clínico listo para producción. La prueba Schnorr demuestra posesión de una clave; no constituye autorización clínica ni verifica la veracidad del dato. El control de nonces anti-replay vive en la memoria de una instancia de `RiskVerifier`: no se comparte entre instancias ni sobrevive reinicios. La entropía es una métrica complementaria, no una prueba de anonimato ni de imposibilidad de reidentificación. La seudonimización tampoco equivale a anonimización absoluta.

La aritmética Schnorr en Python no tiene endurecimiento contra canales laterales y no es una implementación criptográfica auditada. La clave maestra Fernet es local: perderla impide descifrar los datos existentes. En producción se necesitarían, entre otros controles, gestión de claves mediante KMS/HSM, copias de seguridad protegidas, control de acceso, auditoría, TLS, protección anti-replay persistente y una implementación criptográfica auditada. La separación de repositorios y el cifrado por sí solos no garantizan anonimato ni idoneidad clínica.

## Adaptador MIMIC-III Demo

El adaptador está implementado para aceptar `PATIENTS.csv`, `D_ITEMS.csv` y
`CHARTEVENTS.csv` de MIMIC-III Demo. Verifica existencia y columnas requeridas:
`SUBJECT_ID/GENDER/DOB`, `ITEMID/LABEL` y
`SUBJECT_ID/ITEMID/CHARTTIME/VALUENUM`, respectivamente.

La selección de mediciones es deliberadamente explícita y no depende de
coincidencias generales de palabras en las etiquetas:

| Variable interna | ITEMID aceptados | Clase de medición |
|---|---|---|
| Frecuencia cardíaca (`heart_rate`) | 211, 220045 (`Heart Rate`) | Frecuencia cardíaca |
| PAS (`systolic_bp`) | 455 (`NBP [Systolic]`), 220179 (`Non Invasive Blood Pressure systolic`) | Presión no invasiva |
| PAD (`diastolic_bp`) | 8441 (`NBP [Diastolic]`), 220180 (`Non Invasive Blood Pressure diastolic`) | Presión no invasiva |

Las etiquetas de los ITEMID admitidos deben coincidir con las variantes
esperadas; si un ITEMID conocido tiene una etiqueta distinta, la conversión se
detiene. No se aceptan ITEMID de presión arterial invasiva/arterial (por
ejemplo, 51, 442 o 220050), ni mediciones manuales, ni otros ITEMID encontrados
solo por contener “systolic”, “diastolic” o “heart rate”. Esto evita mezclar
modalidades de presión distintas. Se aceptan las variantes de presión no
invasiva de CareVue y MetaVision.

Las filas válidas de `CHARTEVENTS.csv` se asocian por `SUBJECT_ID` y se
agrupan por hora. Si hay varias mediciones del mismo tipo en una misma hora,
se usa la mediana; duplicados exactos de sujeto, ITEMID, hora y valor se
cuentan y eliminan antes de agregar. La combinación horaria es una aproximación
para construir el esquema tabular, no garantiza que FC, PAS y PAD pertenezcan
al mismo episodio clínico.

No se imputan mediciones, edad ni sexo. Se excluyen y contabilizan filas con
ITEMID no admitidos, identificadores o valores inválidos, `VALUENUM` ausente,
fecha/hora inválida o valores fuera de los límites técnicos del Prompt 2. Se
excluyen y reportan bins por hora incompletos, con PAS no mayor que PAD, sin
paciente en `PATIENTS.csv`, con fecha de nacimiento ausente/inválida, edad
calculada fuera de 0–120 o sexo ausente. La edad se deriva de `DOB` y la hora
del bin y se redondea al año más cercano; no se sustituye por una edad
predeterminada. Se descartan pacientes que no producen registros completos.

Después de `convert()`, `adapter.last_report` expone conteos de filas fuente,
exclusiones, bins incompletos, pacientes sin registros completos, truncamiento
por `max_rows` y filas de salida. Algunos conteos se refieren a etapas o
unidades distintas (filas de eventos, bins horarios o pacientes), por lo que no
deben sumarse como si fueran un total único. `adapter.record_trace` relaciona
cada `record_id` de salida con `subject_id`, bin horario y número de eventos
fuente válidos agregados. Estos reportes viven en memoria y no alteran las
columnas del CSV de salida.

El adaptador se probó con fixtures MIMIC sintéticos pequeños. No se ejecutó en
esta etapa contra archivos originales de MIMIC-III Demo; la aceptación de los
ITEMID y el comportamiento en esos archivos reales no se afirma como
verificado.

## Repositorios, privacidad y escala

`D_id_protegido.csv` contiene la correspondencia identificatoria protegida:
`subject_id`, pseudónimo, sal/hash, nombre/RUT cifrados y clave pública. El
secreto privado Schnorr no se persiste. `D_ana_analitico.csv` conserva los
datos clínicos y `record_id` junto con pseudónimo y clave pública, sin nombre
ni RUT en claro. La clave pública se repite por fila en D_ana para conservar el
esquema actual y permitir la verificación desde el repositorio analítico; el
repositorio también mantiene una búsqueda en memoria por pseudónimo. Retirarla
de las filas requeriría cambiar el contrato de salida y sus consumidores, por
lo que no se hizo.

D_id y D_ana se relacionan por pseudónimo. Este diseño es **pseudonimización,
no anonimización irreversible**: el pseudónimo vincula registros de un mismo
paciente y la clave pública añade otro identificador estable; además, quien
acceda a D_id puede recuperar la asociación civil mediante la clave Fernet.
Existe riesgo residual de reidentificación y deben protegerse ambos conjuntos
de datos.

`ClinicalRecord` permanece como dataclass disponible, pero no se utiliza en el
flujo actual, que pasa un DataFrame validado del cargador al pipeline. No se
integró para evitar introducir una segunda representación de los mismos
registros sin beneficio funcional demostrado.

`CHARTEVENTS.csv` se lee en bloques de 150.000 filas para reducir el tamaño de
cada lectura, pero las filas seleccionadas se acumulan en una lista y se
concatenan para deduplicar y calcular medianas exactas; el adaptador no tiene
memoria acotada respecto del total de mediciones aceptadas. El pipeline y los
repositorios también almacenan todos los registros en DataFrames/listas y
diccionarios en memoria. Esto es adecuado para una demo académica pequeña,
pero puede agotar memoria con el MIMIC completo o cargas grandes. No se
incorporó infraestructura distribuida ni persistencia incremental.

Descarga MIMIC-III Clinical Database Demo v1.4 desde PhysioNet y deja estos archivos dentro de una misma carpeta:

```text
PATIENTS.csv
D_ITEMS.csv
CHARTEVENTS.csv
```

Luego ejecuta:

```powershell
python main.py --mimic-dir "ruta/a/mimiciii-demo"
```

El adaptador añade **nombre/RUT ficticios** únicamente para hacer funcionar el esquema interno de protección de PII. Los datos clínicos originales permanecen desidentificados; estas pruebas sintéticas no implican que MIMIC-III Demo original haya sido procesado en esta etapa.
